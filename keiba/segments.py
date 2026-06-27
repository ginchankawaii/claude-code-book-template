"""C1: エッジ探索 — バックテスト予測を条件で輪切りし、市場が崩れている
(回収率>100% が出る)ポケットを探す。

全体ではモデルは市場に勝てない(実測済み)。だが特定条件——人気帯・頭数など
——では市場が systematic に偏ることがある(古典例: 人気薄の買われすぎ=
favorite-longshot bias)。そこを見つけて「そこだけ賭ける」のがエッジ獲得の
現実的な入口。

⚠ 重要: 輪切りすれば必ずどこかで100%超が出る(ノイズ)。**本物は複数年・
out-of-sample で安定して残るものだけ**。件数 n が小さいバケットは信用しない。
ここが出すのは“候補”であって“結論”ではない。

入力 preds は backtest の result["preds"]:
  columns = [race_id, race_date, is_win, p_model, p_market, p_blend, final_odds]
ROI = Σ(is_win × オッズ) / 点数。100% が損益分岐(オッズは払戻倍率)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ODDS_BANDS = [(1.0, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0),
              (10.0, 20.0), (20.0, 50.0), (50.0, 1e12)]
FIELD_BINS = [(2, 10), (11, 13), (14, 16), (17, 99)]


def _roi(df: pd.DataFrame) -> dict:
    """flat ベット(各¥1)の (点数, 的中率, 回収率)。回収率=Σ(is_win×オッズ)/n。"""
    n = len(df)
    if n == 0:
        return {"n": 0, "hit": float("nan"), "roi": float("nan")}
    win = df["is_win"].to_numpy(dtype=float)
    odds = df["final_odds"].to_numpy(dtype=float)
    return {"n": int(n), "hit": float(win.mean()),
            "roi": float((win * odds).sum() / n)}


def _band_label(lo: float, hi: float) -> str:
    return f"{lo:g}-{hi:g}倍" if hi < 1e11 else f"{lo:g}倍+"


def favorite_longshot(preds: pd.DataFrame) -> list[dict]:
    """全出走を人気帯(確定オッズ)で輪切り、各帯を全部買ったROI。市場の偏り検出。"""
    o = pd.to_numeric(preds["final_odds"], errors="coerce")
    rows = []
    for lo, hi in ODDS_BANDS:
        seg = preds[(o >= lo) & (o < hi)]
        rows.append({"seg": _band_label(lo, hi), **_roi(seg)})
    return rows


def overlay_by_band(preds: pd.DataFrame, ev_threshold: float = 1.0) -> list[dict]:
    """モデルが妙味(p_blend×オッズ≥閾値)と見た馬だけを、人気帯別にROI集計。"""
    p = pd.to_numeric(preds["p_blend"], errors="coerce").to_numpy()
    o = pd.to_numeric(preds["final_odds"], errors="coerce").to_numpy()
    ov = preds[(p * o) >= ev_threshold]
    ob = pd.to_numeric(ov["final_odds"], errors="coerce")
    rows = []
    for lo, hi in ODDS_BANDS:
        seg = ov[(ob >= lo) & (ob < hi)]
        rows.append({"seg": _band_label(lo, hi), **_roi(seg)})
    return rows


def overlay_by_fieldsize(preds: pd.DataFrame, ev_threshold: float = 1.0) -> list[dict]:
    """モデル妙味馬を、出走頭数別にROI集計(少頭数/多頭数で偏りが出るか)。"""
    fs = preds.groupby("race_id")["is_win"].transform("size")
    p = pd.to_numeric(preds["p_blend"], errors="coerce").to_numpy()
    o = pd.to_numeric(preds["final_odds"], errors="coerce").to_numpy()
    ov = preds.assign(_fs=fs)[(p * o) >= ev_threshold]
    rows = []
    for lo, hi in FIELD_BINS:
        seg = ov[(ov["_fs"] >= lo) & (ov["_fs"] <= hi)]
        label = f"{lo}-{hi}頭" if hi < 99 else f"{lo}頭+"
        rows.append({"seg": label, **_roi(seg)})
    return rows


def drift_segments(preds: pd.DataFrame) -> list[dict] | None:
    """C2: オッズの動き(odds_drift=寄りつき→直近)別の的中率/回収率。

    drift>0 = 人気化(賢い金が入った)・drift<0 = 不人気化。蓄積した速報時系列が
    あるレースのみ非NaN。データが無ければ None(=まだ貯まっていない)。
    """
    if "odds_drift" not in preds.columns:
        return None
    d = pd.to_numeric(preds["odds_drift"], errors="coerce")
    if d.notna().sum() == 0:
        return None
    rows = []
    for label, mask in [("人気化(drift>0.1)", d > 0.1),
                        ("中立(|drift|≤0.1)", d.abs() <= 0.1),
                        ("不人気化(drift<-0.1)", d < -0.1)]:
        rows.append({"seg": label, **_roi(preds[mask & d.notna()])})
    return rows


def validate_oos(preds: pd.DataFrame, ev_threshold: float = 1.0,
                 min_n: int = 100) -> str:
    """C6: 前半(発見期)で回収率>100%だったセグメントが後半(検証期)でも残るか。

    輪切りで出た“候補”の大半はノイズで out-of-sample で消える。前半で見つけ、
    後半で残るかを照合して『本物候補』だけを残す自動チェック。
    """
    if preds is None or len(preds) == 0 or "race_date" not in preds.columns:
        return "OOS検証: データ不足"
    cut = preds["race_date"].median()
    a = preds[preds["race_date"] < cut]    # 発見期(前半)
    b = preds[preds["race_date"] >= cut]   # 検証期(後半)
    L = ["=" * 64, " C6 Out-of-Sample 検証(前半で発見 → 後半で残るか)", "=" * 64,
         f"  発見期 {len(a)}件 / 検証期 {len(b)}件 (race_date 中央値で分割)", ""]
    for title, fn in [("人気帯(全買い=市場の偏り)", favorite_longshot),
                      (f"モデル妙味×人気帯(EV≥{ev_threshold})",
                       lambda d: overlay_by_band(d, ev_threshold))]:
        ra = {r["seg"]: r for r in fn(a)}
        rb = {r["seg"]: r for r in fn(b)}
        L.append(f"--- {title} ---")
        L.append("  区分        発見ROI(n)      検証ROI(n)     判定")
        for seg, x in ra.items():
            y = rb.get(seg, {"n": 0, "roi": float("nan")})
            disc = x["n"] >= min_n and x["roi"] == x["roi"] and x["roi"] > 1.0
            val = y["n"] >= min_n and y["roi"] == y["roi"] and y["roi"] > 1.0
            verdict = "✅残った" if (disc and val) else ("⚠消えた" if disc else "—")
            xr = "  - " if x["roi"] != x["roi"] else f"{x['roi']*100:4.0f}%"
            yr = "  - " if y["roi"] != y["roi"] else f"{y['roi']*100:4.0f}%"
            L.append(f"  {seg:<10} {xr}({x['n']:>5})   {yr}({y['n']:>5})   {verdict}")
        L.append("")
    L += ["【読み方】✅残った = 発見期も検証期も回収率>100%(n十分)。**これだけが本物候補**。",
          " ⚠消えた = 発見期だけ良かった = ノイズ。 — = 発見期に候補ですらない。",
          "=" * 64]
    return "\n".join(L)


def _table(title: str, rows: list[dict], min_n: int) -> list[str]:
    L = [f"--- {title} ---", "  区分        点数    的中率   回収率"]
    for r in rows:
        flag = ""
        if r["n"] >= min_n and r["roi"] == r["roi"] and r["roi"] > 1.0:
            flag = "  ◎候補"   # 件数十分 & 100%超
        elif r["n"] < min_n and r["n"] > 0:
            flag = "  (n小)"
        hit = "  -  " if r["hit"] != r["hit"] else f"{r['hit']*100:5.1f}%"
        roi = "  -  " if r["roi"] != r["roi"] else f"{r['roi']*100:6.1f}%"
        L.append(f"  {r['seg']:<10}{r['n']:>6}  {hit}  {roi}{flag}")
    return L


def segment_report(preds: pd.DataFrame, ev_threshold: float = 1.0,
                   min_n: int = 100) -> str:
    """3つの輪切り(人気帯・モデル妙味×人気帯・モデル妙味×頭数)を整形して返す。"""
    if preds is None or len(preds) == 0:
        return "セグメント分析: 予測データが空です。"
    L = ["=" * 64, " C1 エッジ探索: 条件別の回収率(市場が崩れている所を探す)", "=" * 64]
    L += _table("人気帯別(全出走を均等買い=市場の偏り)", favorite_longshot(preds), min_n)
    L.append("")
    L += _table(f"モデル妙味馬×人気帯(EV≥{ev_threshold})", overlay_by_band(preds, ev_threshold), min_n)
    L.append("")
    L += _table(f"モデル妙味馬×頭数(EV≥{ev_threshold})", overlay_by_fieldsize(preds, ev_threshold), min_n)
    drift = drift_segments(preds)
    if drift is not None:
        L.append("")
        L += _table("オッズの動き別(C2: 賢い金)", drift, min_n)
    L += [
        "=" * 64,
        f"【読み方】◎候補 = 件数十分(n≥{min_n}) かつ 回収率>100%。",
        " ただし輪切りすれば偶然100%超は必ず出る。複数年/別期間でも残るか要再検証。",
        " n小のバケットは無視。これは“結論”でなく“次に深掘る候補”。",
        "=" * 64,
    ]
    return "\n".join(L)
