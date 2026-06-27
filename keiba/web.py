"""当日予想 + 2026バックテストの Web ビューア(ブラウザ版)。

  python -m keiba.web --db /data/keiba.db --port 8000

構成:
  * モデルは「評価年(既定=データ最新年=2026)より前」で学習(アウトオブタイム)。
    → 今日のライブ予想も2026バックテストも、同じ blind なモデルで公正に評価。
  * ナビ: 日付 → 会場 → レース(過去の2026開催日も今日も同じ導線)。
  * 各レース: 勝率予想 + 買い方提案(根拠コメント・各券種の的中確率/妙味目安・単勝EV)
    + 確定済みなら着順を色分けして「予想 vs 結果」。
  * /summary: 2026通算の本命的中率・単勝回収率・月別推移など。
  * 今日(最新日)は一定間隔で自動更新。

⚠ 検証前モデルのペーパートレード。お金を賭ける根拠にはしないこと。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import os
import pickle
import threading
import time

import numpy as np
import pandas as pd
from flask import Flask, redirect, render_template_string, request, url_for

from . import win5
from .betadvice import advise_race
from .exotic_odds import load_exotic_odds_for_day
from .features import FEATURE_COLUMNS, build_features
from .ingest import IngestBackend, validate_runners
from .model import ModelConfig
from .predict import PredictConfig, fit_predictor, predict_range

app = Flask(__name__)

JYO = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
       "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
WD = "月火水木金土日"

STATE = {"db": None, "kind": "sqlite", "predictor": None, "pred": None,
         "updated": None, "issues": [], "building": False, "error": None,
         "objective": "binary", "ev": 1.15, "refresh_sec": 90, "cutoff": None,
         "today": None, "immutable": False, "odds_cache": {}, "win5_cache": {},
         "cache_dir": None}
_LOCK = threading.Lock()


def _cache_file() -> str | None:
    d = STATE.get("cache_dir")
    return os.path.join(d, "web_cache.pkl") if d else None


def _data_sig() -> str | None:
    """DB の変更署名(mtime+size)。読み込み前に安価に取れる。"""
    try:
        st = os.stat(STATE["db"])
        return f"{int(st.st_mtime)}-{st.st_size}"
    except (OSError, TypeError):
        return None


def _cfg_sig() -> str:
    """学習・特徴量の構成署名。これが変われば学習し直す。"""
    feat = hashlib.md5(",".join(FEATURE_COLUMNS).encode()).hexdigest()[:8]
    return f"{STATE['objective']}-{STATE['ev']}-{int(bool(STATE.get('immutable')))}-{feat}"


def _venue(race_id) -> str:
    return JYO.get(str(race_id).zfill(12)[4:6], "?")


def _racenum(race_id) -> int:
    try:
        return int(str(race_id).zfill(12)[10:12])
    except ValueError:
        return 0


def _date_label(ordinal) -> str:
    try:
        d = _dt.date.fromordinal(int(ordinal))
        return f"{d.month}/{d.day}({WD[d.weekday()]})"
    except Exception:
        return str(ordinal)


def rebuild(retrain: bool = False, use_cache: bool = False) -> None:
    """データ取込→学習→予測。--cache-dir 指定時はキャッシュで高速化する。

    * フルキャッシュ(use_cache=True・起動時): DB が前回と未変更なら pred ごと即
      ロードし、取込も学習も完全スキップ(起動が数秒)。
    * 学習キャッシュ(常時): cutoff/構成が同じなら学習済みモデルを再利用し fit を
      スキップ(更新時の再取込だけで済む)。
    """
    with _LOCK:
        if STATE["building"]:
            return
        STATE["building"] = True
    cf = _cache_file()
    full_key = f"{_data_sig()}|{_cfg_sig()}"
    try:
        # 1) フルキャッシュ: DB 未変更なら何もせず pred を復元(起動を数秒に)
        if use_cache and cf and _data_sig() and os.path.exists(cf):
            try:
                with open(cf, "rb") as fh:
                    C = pickle.load(fh)
                if C.get("full_key") == full_key and C.get("pred") is not None:
                    with _LOCK:
                        STATE.update(predictor=C["predictor"], pred=C["pred"],
                                     issues=C["issues"], cutoff=C["cutoff"],
                                     today=C["today"], odds_cache={}, win5_cache={},
                                     updated=C["updated"] + " (cache)", error=None)
                    return
            except Exception:
                pass   # キャッシュ破損等は無視してフル再構築へ

        runners, _ = IngestBackend(STATE["db"], kind=STATE["kind"],
                                   include_realtime=True,
                                   immutable=STATE.get("immutable", False)).load()
        issues = validate_runners(runners)
        feat = build_features(runners)
        # 評価年(最新年)の元旦を学習カットオフに(アウトオブタイム)
        max_ord = int(feat["race_date"].max())
        year = _dt.date.fromordinal(max_ord).year
        cutoff = _dt.date(year, 1, 1).toordinal()
        pred_key = f"{cutoff}|{_cfg_sig()}"
        # 2) 学習キャッシュ: cutoff/構成が同じならモデル再利用(fit をスキップ)
        predictor = STATE["predictor"]
        if not retrain and predictor is None and cf and os.path.exists(cf):
            try:
                with open(cf, "rb") as fh:
                    C = pickle.load(fh)
                if C.get("pred_key") == pred_key:
                    predictor = C["predictor"]
            except Exception:
                predictor = None
        if retrain or predictor is None:
            predictor = fit_predictor(
                feat, ModelConfig(objective=STATE["objective"]),
                PredictConfig(ev_threshold=STATE["ev"]), eval_date=cutoff)
        pred = predict_range(predictor, feat, cutoff, max_ord + 1)
        updated = _dt.datetime.now().strftime("%H:%M:%S")
        with _LOCK:
            STATE.update(predictor=predictor, pred=pred, issues=issues, cutoff=cutoff,
                         today=max_ord, odds_cache={}, win5_cache={},
                         updated=updated, error=None)
        if cf:   # キャッシュ保存(次回の高速起動用)
            try:
                with open(cf, "wb") as fh:
                    pickle.dump({"full_key": full_key, "pred_key": pred_key,
                                 "predictor": predictor, "pred": pred, "issues": issues,
                                 "cutoff": cutoff, "today": max_ord, "updated": updated}, fh)
            except Exception:
                pass
    except Exception as exc:  # pragma: no cover
        with _LOCK:
            STATE["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with _LOCK:
            STATE["building"] = False


# ---------------------------------------------------------------------------
# ビュー構築
# ---------------------------------------------------------------------------

def _nav_days(pred: pd.DataFrame):
    """日付→会場 のナビ構造。新しい日付が先頭。"""
    days = []
    for od, g in sorted(pred.groupby("race_date"), key=lambda kv: kv[0], reverse=True):
        venues = sorted({_venue(r) for r in g["race_id"].unique()})
        days.append({"ord": int(od), "label": _date_label(od), "venues": venues})
    return days


def _row_view(h) -> dict:
    fp = h["finish_pos"]
    return {
        "rank": int(h["rank"]),
        "post": "-" if h["post_position"] != h["post_position"] else str(int(h["post_position"])),
        "win": float(h["win_prob"]),
        "odds": "-" if h["odds"] != h["odds"] else f"{h['odds']:.1f}",
        "ev": "-" if h["ev"] != h["ev"] else f"{h['ev']:.2f}",
        "ev_hi": (h["ev"] == h["ev"]) and float(h["ev"]) >= 1.0,
        "bet": bool(h["bet"]),
        "fin": None if fp != fp else int(fp),
        "pick": int(h["rank"]) == 1,
    }


def _rid_int(rid):
    try:
        return int(rid)
    except (ValueError, TypeError):
        return None


def _day_odds(day_ord: int) -> dict:
    """表示中の日の連系オッズ(O2〜O6)を読み込み、race_id→券種→組番→倍率で返す。

    日付単位で遅延ロードしキャッシュ(2026全件を一度に読むと巨大になるため)。"""
    cache = STATE.setdefault("odds_cache", {})
    if day_ord in cache:
        return cache[day_ord]
    odds = {}
    if STATE.get("db"):
        try:
            d = _dt.date.fromordinal(int(day_ord))
            odds = load_exotic_odds_for_day(
                STATE["db"], d.year, d.month * 100 + d.day,
                kind=STATE["kind"], immutable=STATE.get("immutable", False))
        except Exception:
            odds = {}
    cache[day_ord] = odds
    return odds


def _intp(x):
    try:
        return None if x != x else int(x)
    except (ValueError, TypeError):
        return None


def _win5_designated(day_ord: int):
    """指定日のWIN5対象5レース(NL_WF)をキャッシュ付きで取得。無ければ None。"""
    cache = STATE.setdefault("win5_cache", {})
    if day_ord in cache:
        return cache[day_ord]
    info = None
    if STATE.get("db"):
        try:
            d = _dt.date.fromordinal(int(day_ord))
            info = win5.load_designated(STATE["db"], d.year, d.month * 100 + d.day,
                                        kind=STATE["kind"],
                                        immutable=STATE.get("immutable", False))
        except Exception:
            info = None
    cache[day_ord] = info
    return info


def _win5_view(pred: pd.DataFrame, day_ord: int) -> dict | None:
    info = _win5_designated(day_ord)
    if not info:
        return None
    legs_prob, legs = [], []
    for rid in info["races"]:
        g = pred[pred["race_id"].astype(str) == str(rid)].sort_values("rank")
        if g.empty:
            return {"day_label": _date_label(day_ord), "available": False,
                    "carryover": info["carryover"], "day_ord": day_ord}
        legs_prob.append(g["win_prob"].to_numpy(dtype=float))
        posts_full = [_intp(p) for p in g["post_position"].tolist()]
        finished = bool(g["race_finished"].iloc[0])
        win_post = None
        if finished:
            w = g[g["finish_pos"] == 1]
            win_post = _intp(w.iloc[0]["post_position"]) if len(w) else None
        legs.append({
            "label": f"{_venue(rid)} {_racenum(rid)}R", "finished": finished,
            "win_post": win_post, "posts_full": posts_full,
            "rows": [{"post": _intp(r.post_position), "win": float(r.win_prob),
                      "fin": _intp(r.finish_pos)} for r in g.head(8).itertuples()],
        })
    rec = win5.optimize(legs_prob, max_points=100)   # 推奨=¥10,000(100点)
    for i, sel in enumerate(rec["selections"]):
        s = set(sel)
        legs[i]["sel_posts"] = {legs[i]["posts_full"][j] for j in sel
                                if j < len(legs[i]["posts_full"])}
        for j, row in enumerate(legs[i]["rows"]):
            row["sel"] = j in s
    tiers = []
    for b in (1, 18, 48, 100, 200, 500):
        p = win5.optimize(legs_prob, max_points=b)
        tiers.append({"points": p["points"], "yen": p["cost_yen"], "hit": p["hit_prob"],
                      "fair": p["fair_odds"], "counts": p["counts"], "is_rec": b == 100})
    all_fin = all(l["finished"] for l in legs)
    won = None
    if all_fin:
        won = all(l["win_post"] is not None and l["win_post"] in l["sel_posts"] for l in legs)
    return {"day_label": _date_label(day_ord), "available": True, "day_ord": day_ord,
            "carryover": info["carryover"], "legs": legs, "rec": rec, "tiers": tiers,
            "all_finished": all_fin, "won": won}


def _best_bet(adv: dict) -> dict | None:
    """1レースのアドバイスから、実オッズで +EV の最良買い目を1つ選ぶ(配分の単位)。

    単勝の妙味馬と、実オッズで妙味(buy)の出た連系を候補にし、EV最大を返す。
    """
    cands = []
    for b in adv.get("tan_bets", []):
        if b.get("ev") and b.get("odds") and b["odds"] > 1:
            cands.append({"kind": "単勝", "sel": str(b["post"]),
                          "odds": float(b["odds"]), "ev": float(b["ev"])})
    for e in adv.get("exotic", []):
        if e.get("buy") and e.get("odds") and e.get("ev") and e["odds"] > 1:
            cands.append({"kind": e["kind"], "sel": e["sel"],
                          "odds": float(e["odds"]), "ev": float(e["ev"])})
    return max(cands, key=lambda c: c["ev"]) if cands else None


def _allocate(all_races: list, picks: set, budget: int, min_ev: float = 1.0,
              cap_pct: int = 100, max_bets: int = 0) -> dict:
    """選んだレースの最良買い目に、予算を分数ケリー(エッジ比例)で配分する。

    各買い目のケリー比率 f=(EV-1)/(オッズ-1) に比例させ、合計が予算になるよう
    正規化して ¥100 単位に丸める。リスク制御:
      min_ev : この EV 未満の買い目は除外
      cap_pct: 1点あたり予算の何%まで(集中しすぎ防止)
      max_bets: 点数の上限(EV上位のみ。0=無制限)
    """
    chosen = [(r, r["best_bet"]) for r in all_races
              if r.get("cbval") in picks and r.get("best_bet")
              and r["best_bet"]["ev"] >= min_ev]
    chosen.sort(key=lambda rb: -rb[1]["ev"])
    if max_bets and len(chosen) > max_bets:
        chosen = chosen[:max_bets]
    fs = [max(0.0, (b["ev"] - 1.0) / (b["odds"] - 1.0)) for _, b in chosen]
    tot = sum(fs)
    cap = (int(budget * cap_pct / 100) // 100) * 100 if cap_pct < 100 else budget
    rows, total = [], 0
    if budget > 0 and tot > 0:
        for (r, b), f in zip(chosen, fs):
            amt = min(int(round(budget * f / tot / 100.0)) * 100, cap)
            if amt <= 0:
                continue
            rows.append({"label": r["label"], "kind": b["kind"], "sel": b["sel"],
                         "odds": b["odds"], "ev": b["ev"], "amount": amt})
            total += amt
    rows.sort(key=lambda x: -x["amount"])
    copy = "\n".join(f"{r['label']} {r['kind']} {r['sel']} ¥{r['amount']:,}" for r in rows)
    return {"rows": rows, "total": total, "leftover": max(0, budget - total),
            "requested": bool(picks) and budget > 0,
            "n_picked": len(picks), "n_bet": len(rows), "copy": copy}


def _settle_best_bet(g: pd.DataFrame, bb: dict) -> tuple:
    """確定レースの推奨買い目(best_bet)を清算し (賭金=1.0, 払戻, 的中) を返す。

    払戻は表示したオッズ(実オッズ)。連系は着順から的中判定する(ペーパー成績用)。
    """
    fin = {}
    for r in g.itertuples():
        try:
            fin[int(r.finish_pos)] = int(r.post_position)   # 着順 -> 馬番
        except (ValueError, TypeError):
            continue
    w1, w2, w3 = fin.get(1), fin.get(2), fin.get(3)
    try:
        parts = [int(x) for x in bb["sel"].replace("→", "-").split("-")]
    except ValueError:
        return 1.0, 0.0, False
    k, hit = bb["kind"], False
    if k == "単勝":
        hit = bool(parts and parts[0] == w1)
    elif k == "馬連":
        hit = None not in (w1, w2) and set(parts) == {w1, w2}
    elif k == "ワイド":
        top3 = {w1, w2, w3} - {None}
        hit = len(parts) == 2 and all(p in top3 for p in parts)
    elif k == "馬単":
        hit = None not in (w1, w2) and parts == [w1, w2]
    elif k == "三連複":
        hit = None not in (w1, w2, w3) and set(parts) == {w1, w2, w3}
    elif k == "三連単":
        hit = None not in (w1, w2, w3) and parts == [w1, w2, w3]
    odds = bb.get("odds") or 0.0
    return 1.0, (float(odds) if hit else 0.0), bool(hit)


def _win5_rec(pred: pd.DataFrame, day_ord: int) -> dict | None:
    """WIN5対象日なら推奨プラン(金額・点数)を返す。配分パネルに統合表示する。"""
    if _win5_designated(day_ord) is None:
        return None
    try:
        v = _win5_view(pred, day_ord)
    except Exception:
        return None
    if not v or not v.get("available"):
        return None
    return {"cost": v["rec"]["cost_yen"], "points": v["rec"]["points"],
            "hit": v["rec"]["hit_prob"]}


def _day_view(pred: pd.DataFrame, day_ord: int, picks: set | None = None,
              budget: int = 10000, submitted: bool = False, sort: str = "num",
              min_ev: float = 1.0, cap_pct: int = 100, max_bets: int = 0) -> dict:
    sub = pred[pred["race_date"] == day_ord]
    day_odds = _day_odds(day_ord)
    picks = picks or set()
    venues = {}
    for rid, g in sub.groupby("race_id", sort=False):
        g = g.sort_values("rank")
        finished = bool(g["race_finished"].iloc[0])
        pick = g.iloc[0]
        status = "発走前"
        if finished:
            fp = pick["finish_pos"]
            pf = None if fp != fp else int(fp)
            status = "的中" if pf == 1 else ("複勝圏" if (pf is not None and pf <= 3) else "外")
        adv = advise_race(g, day_odds.get(_rid_int(rid)))
        bb = _best_bet(adv)
        cbval = str(rid)
        # 送信済みなら ☑ 状態を尊重。未送信(初回)は +EV のあるレースを既定 ☑。
        checked = (cbval in picks) if submitted else (bb is not None)
        race = {"race_id": rid, "cbval": cbval, "num": _racenum(rid),
                "label": f"{_venue(rid)} {_racenum(rid)}R", "finished": finished,
                "status": status, "checked": checked, "best_bet": bb,
                "rows": [_row_view(h) for _, h in g.head(8).iterrows()], "advice": adv}
        venues.setdefault(_venue(rid), []).append(race)
    for v in venues:
        if sort == "ev":   # おすすめ順: 妙味(+EV)レースを EV 高い順に上へ
            venues[v].sort(key=lambda r: (0 if r["best_bet"] else 1,
                                          -(r["best_bet"]["ev"] if r["best_bet"] else 0)))
        else:
            venues[v].sort(key=lambda r: r["num"])
    ordered = [{"venue": v, "races": venues[v]} for v in sorted(venues)]
    all_races = [r for v in ordered for r in v["races"]]
    eff_picks = picks if submitted else {r["cbval"] for r in all_races if r["best_bet"]}
    alloc = _allocate(all_races, eff_picks, budget, min_ev, cap_pct, max_bets)
    return {"day_ord": day_ord, "day_label": _date_label(day_ord), "venues": ordered,
            "is_today": day_ord == STATE["today"], "budget": budget, "alloc": alloc,
            "sort": sort, "min_ev": min_ev, "cap_pct": cap_pct, "max_bets": max_bets,
            "win5": _win5_designated(day_ord) is not None,
            "win5_rec": _win5_rec(pred, day_ord)}


def _summary_view(pred: pd.DataFrame) -> dict:
    fin = pred[pred["race_finished"]]
    out = {"n_races": int(pred["race_id"].nunique()),
           "n_finished": int(fin["race_id"].nunique()), "months": []}
    if fin.empty:
        return out
    picks = fin[fin["rank"] == 1].copy()
    picks["won"] = (picks["finish_pos"] == 1)
    picks["top3"] = picks["finish_pos"] <= 3
    picks["ret"] = np.where(picks["won"], picks["odds"].fillna(0.0), 0.0)
    n = len(picks)
    out["honmei_win"] = float(picks["won"].mean())
    out["honmei_top3"] = float(picks["top3"].mean())
    staked = picks["odds"].notna().sum()
    out["honmei_roi"] = float(picks.loc[picks["odds"].notna(), "ret"].sum() / staked) if staked else None
    # EVフィルタ買い目(単勝)の回収率
    out["ev_n"], out["ev_roi"], out["ev_hit"] = 0, None, None
    bets = fin[fin["bet"]]
    if len(bets):
        bret = (bets["finish_pos"] == 1).astype(float) * bets["odds"].fillna(0.0)
        out["ev_n"] = int(len(bets))
        out["ev_roi"] = float(bret.sum() / len(bets))
        out["ev_hit"] = float((bets["finish_pos"] == 1).mean())
    # ペーパー配分成績: 各確定レースの推奨買い目(best_bet)を flat ¥1 で清算した通算
    pn, ph, pret = 0, 0, 0.0
    for od, dg in fin.groupby("race_date"):
        dodds = _day_odds(int(od))
        for rid, g in dg.groupby("race_id", sort=False):
            g = g.sort_values("rank")
            bb = _best_bet(advise_race(g, dodds.get(_rid_int(rid))))
            if not bb:
                continue
            _, ret, hit = _settle_best_bet(g, bb)
            pn += 1; pret += ret; ph += 1 if hit else 0
    out["port"] = {"n": pn, "hit": ph / pn, "roi": pret / pn} if pn else None
    # 月別
    picks["month"] = picks["race_date"].map(lambda o: _dt.date.fromordinal(int(o)).month)
    for m, g in picks.groupby("month"):
        st = g["odds"].notna().sum()
        out["months"].append({
            "month": int(m), "n": int(len(g)),
            "win": float(g["won"].mean()),
            "roi": float(g.loc[g["odds"].notna(), "ret"].sum() / st) if st else None,
        })
    return out


# ---------------------------------------------------------------------------
# テンプレート
# ---------------------------------------------------------------------------

BASE_CSS = """
 :root{--bg:#0f1115;--card:#171a21;--line:#2a2f3a;--mut:#9aa4b2;--accent:#2a6df4}
 *{box-sizing:border-box} body{font-family:system-ui,'Segoe UI',sans-serif;margin:0;background:var(--bg);color:#e6e6e6}
 a{color:#7fb0ff;text-decoration:none} a:hover{text-decoration:underline}
 header{position:sticky;top:0;background:#141821;padding:10px 16px;border-bottom:1px solid var(--line);z-index:9}
 h1{font-size:16px;margin:0} .sub{font-size:12px;color:var(--mut)}
 .layout{display:flex;align-items:flex-start}
 .side{flex:0 0 190px;width:190px;position:sticky;top:53px;height:calc(100vh - 53px);
       overflow-y:auto;background:#12151c;border-right:1px solid var(--line);padding:8px 8px 40px}
 .side a{display:block;padding:6px 9px;border-radius:8px;font-size:12px;color:#cdd6e3;margin-bottom:2px;line-height:1.25}
 .side a:hover{background:#1b2029;text-decoration:none}
 .side a.on{background:var(--accent);color:#fff}
 .side a .v{display:block;color:var(--mut);font-size:10px;margin-top:1px}
 .side a.on .v{color:#dbe6ff}
 .main{flex:1;min-width:0;max-width:1180px;padding:12px 18px 56px}
 @media(max-width:760px){
   .layout{flex-direction:column}
   .side{position:static;width:auto;flex:none;height:auto;display:flex;gap:6px;
         overflow-x:auto;border-right:none;border-bottom:1px solid var(--line)}
   .side a{flex:0 0 auto;white-space:nowrap} .side a .v{display:none}
 }
 .warn{background:#3a2a12;color:#ffce8a;padding:8px 12px;border-radius:8px;font-size:12px;margin:8px 0}
 .vsec{margin-top:14px} .vsec h2{font-size:15px;margin:0 0 6px;color:#cdd6e3;border-left:3px solid var(--accent);padding-left:8px}
 .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
 .race{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
 .race h3{font-size:14px;margin:0 0 6px;display:flex;justify-content:space-between;align-items:center}
 .badge{font-size:11px;padding:2px 8px;border-radius:999px;font-weight:700}
 .b-pre{background:#222733;color:#9aa4b2} .b-win{background:#10391f;color:#5ee08a}
 .b-top3{background:#3a3413;color:#ffe08a} .b-miss{background:#3a1b1b;color:#ff9a9a}
 table{width:100%;border-collapse:collapse;font-size:13px} th,td{padding:3px 6px;text-align:right}
 th{color:#8a93a3;font-weight:600;border-bottom:1px solid var(--line)} td.l,th.l{text-align:left}
 tr.pick{box-shadow:inset 3px 0 0 var(--accent)} tr.bet{background:#13301c} .mk{color:#5ee08a;font-weight:700}
 .ev-hi{color:#5ee08a} .ev-lo{color:var(--mut)}
 .barwrap{display:inline-block;width:46px;height:7px;background:#222733;border-radius:4px;vertical-align:middle;margin-right:5px;overflow:hidden}
 .bar{height:100%;background:var(--accent)}
 .fin{display:inline-block;min-width:18px;text-align:center;border-radius:5px;font-weight:700;font-size:12px}
 .f1{background:#caa700;color:#1a1a1a} .f2{background:#9fb0c2;color:#1a1a1a} .f3{background:#b08552;color:#1a1a1a} .fx{color:var(--mut)}
 .adv{margin-top:6px;font-size:12px;background:#10141b;border:1px solid var(--line);border-radius:8px;padding:6px 8px;line-height:1.6}
 .adv .ty{color:#ffd479;font-weight:700} .adv .ex{color:var(--mut)} .adv .ex b{color:#cdd6e3}
 .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:10px 0}
 .sum{display:flex;gap:18px;flex-wrap:wrap;font-size:13px} .sum b{font-size:18px;color:#fff}
 a.btn{display:inline-block;background:var(--accent);color:#fff;padding:6px 12px;border-radius:8px;font-size:13px}
 .foot{color:var(--mut);font-size:11px;margin-top:18px;line-height:1.7}
 .daygrid{display:flex;gap:16px;align-items:flex-start}
 .daygrid .races{flex:1;min-width:0} .daygrid .slip{flex:0 0 244px;width:244px}
 .slipbox{position:sticky;top:60px}
 .bin{width:100%;padding:7px 9px;border-radius:8px;border:1px solid var(--line);background:#0f141c;color:#e6e6e6;font-size:15px}
 button.btn{border:none;cursor:pointer;font-family:inherit}
 input[type=checkbox]{accent-color:var(--accent);margin-right:5px;vertical-align:middle;width:15px;height:15px}
 @media(max-width:900px){.daygrid{flex-direction:column}.daygrid .slip{width:auto;flex:none}.slipbox{position:static}}
"""

LAYOUT = """
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{% if auto and refresh_sec %}<meta http-equiv="refresh" content="{{refresh_sec}}">{% endif %}
<title>keiba 予想</title><style>{{css}}</style></head><body>
<header>
  <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
    <div><h1>🐴 keiba 予想 <span class="sub">(ペーパートレード)</span></h1>
      <div class="sub">更新 {{updated or '—'}}{% if building %} ・<b style="color:#ffce8a">更新中…</b>{% endif %}
        ・<a href="{{url_for('summary')}}">2026通算成績</a></div></div>
    <a class="btn" href="{{url_for('refresh')}}">今すぐ更新</a>
  </div>
</header>
<div class="layout">
  <nav class="side">
    {% for d in days %}<a class="{{'on' if d.ord==cur_ord else ''}}" href="{{url_for('day', ordinal=d.ord)}}">{{d.label}}<span class="v">{{d.venues|join('・')}}</span></a>{% endfor %}
  </nav>
  <main class="main">
  {% if error %}<div class="warn">エラー: {{error}}</div>{% endif %}
  {% if issues %}<div class="warn">注意: {{issues|join(' / ')}}</div>{% endif %}
  {{ body|safe }}
  <div class="foot">⚠ 検証前モデルの紙上テスト。回収率が控除率を超える保証は無い。お金を賭ける根拠にはしないこと。<br>
    連系(馬連〜三連単)は的中確率を表示。実オッズ(O2〜O6/速報)がある券種は実EV(=的中率×払戻)を計算し、EV1.0以上を ◎ で妙味表示。無い券種はフェア倍率(◯倍以上で買い)。<br>
    取得層(別プロセス)で結果速報も回す: <code>jltsql realtime start --specs 0B12,0B15,0B30</code>(0B30で連系オッズも取得)。<br>
    realtime と同時に閲覧する場合は <code>--immutable</code> 付きで起動するか、DBを一度 WAL 化する。</div>
  </main>
</div></body></html>
"""

DAY_BODY = """
{% macro race_card(r) %}
  <div class="race">
    <h3><span><label style="cursor:pointer"><input type="checkbox" name="pick" value="{{r.cbval}}" {{'checked' if r.checked}}>{{r.label}}</label>
      {% if r.best_bet %}<span class="badge b-top3" style="margin-left:4px" title="実オッズで+EVの妙味買い目あり">妙味</span>{% endif %}</span>
      <span class="badge {{'b-win' if r.status=='的中' else 'b-top3' if r.status=='複勝圏' else 'b-miss' if r.status=='外' else 'b-pre'}}">{{r.status}}</span></h3>
    <table><tr><th>予</th><th class="l">馬番</th><th>勝率</th><th>オッズ</th><th>EV</th>{% if r.finished %}<th>着</th>{% endif %}</tr>
    {% for h in r.rows %}
      <tr class="{{'pick ' if h.pick else ''}}{{'bet' if h.bet else ''}}">
        <td>{{h.rank}}</td><td class="l">{{h.post}}{% if h.bet %} <span class="mk">◎</span>{% endif %}</td>
        <td><span class="barwrap"><span class="bar" style="width:{{(h.win*100)|round(0,'floor')}}%"></span></span>{{'%.1f'|format(h.win*100)}}%</td>
        <td>{{h.odds}}</td><td class="{{'ev-hi' if h.ev_hi else 'ev-lo'}}">{{h.ev}}</td>
        {% if r.finished %}<td>{% if h.fin %}<span class="fin {{'f1' if h.fin==1 else 'f2' if h.fin==2 else 'f3' if h.fin==3 else 'fx'}}">{{h.fin}}</span>{% else %}<span class="fx">-</span>{% endif %}</td>{% endif %}
      </tr>
    {% endfor %}
    </table>
    <div class="adv"><span class="ty">{{r.advice.type}}</span> {{r.advice.comment}}
      <div class="ex" style="margin-top:4px">
        {% for e in r.advice.exotic %}<b>{{e.kind}}</b> {{e.sel}} 的中{{'%.1f'|format(e.prob*100)}}%
          {% if e.odds %}<span class="{{'ev-hi' if e.buy else 'ev-lo'}}">{{'%.1f'|format(e.odds)}}倍 EV{{'%.2f'|format(e.ev)}}{% if e.buy %} ◎{% endif %}</span>{% else %}<span style="color:#7fb0ff">妙味{{'%.0f'|format(e.fair)}}倍↑</span>{% endif %}　{% endfor %}
      </div>
    </div>
  </div>
{% endmacro %}
<form method="get" action="{{url_for('day', ordinal=view.day_ord)}}" class="daygrid">
<input type="hidden" name="submitted" value="1">
<div class="races">
  <h2 style="margin:6px 0">{{view.day_label}} {% if view.is_today %}<span class="sub">(本日)</span>{% endif %}
    {% if view.win5 %}<a class="btn" style="font-size:12px;padding:4px 10px;margin-left:8px;background:#7a3df4" href="{{url_for('win5_page', ordinal=view.day_ord)}}">🎯 WIN5予想</a>{% endif %}
    <span class="sub" style="margin-left:10px;font-weight:400">表示:
      <a href="{{url_for('day',ordinal=view.day_ord,budget=view.budget)}}" style="{{'font-weight:700;color:#fff' if view.sort!='ev'}}">レース順</a> ·
      <a href="{{url_for('day',ordinal=view.day_ord,budget=view.budget,sort='ev')}}" style="{{'font-weight:700;color:#fff' if view.sort=='ev'}}">おすすめ順(EV高い順)</a></span></h2>
  {% for v in view.venues %}
    <div class="vsec"><h2>{{v.venue}}</h2><div class="cards">
      {% for r in v.races %}{{ race_card(r) }}{% endfor %}
    </div></div>
  {% endfor %}
</div>
<aside class="slip">
  <div class="panel slipbox">
    <input type="hidden" name="sort" value="{{view.sort}}">
    <div style="font-weight:700;margin-bottom:8px">💰 投資配分</div>
    <label class="sub">予算(円)</label>
    <input class="bin" type="number" name="budget" value="{{view.budget}}" min="100" step="1000" inputmode="numeric">
    <details style="margin-top:8px" {{'open' if view.min_ev>1.0 or view.cap_pct<100 or view.max_bets}}>
      <summary class="sub" style="cursor:pointer">リスク制御</summary>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px">
        <label class="sub">最低EV<input class="bin" type="number" name="min_ev" value="{{'%.2f'|format(view.min_ev)}}" min="1" max="100" step="0.05"></label>
        <label class="sub">1点上限%<input class="bin" type="number" name="cap_pct" value="{{view.cap_pct}}" min="1" max="100" step="5"></label>
        <label class="sub">最大点数<input class="bin" type="number" name="max_bets" value="{{view.max_bets}}" min="0" max="200" step="1"></label>
      </div>
      <div class="sub" style="margin-top:4px">最低EV未満は除外/1点に予算の上限%/点数の上限(0=無制限)</div>
    </details>
    <button class="btn" style="width:100%;margin-top:8px">この予算で配分</button>
    <div class="sub" style="margin-top:6px;line-height:1.5">レースを ☑ → 予算入力 → 配分。
      <b>妙味</b>(+EV)買い目に、エッジ比例(分数ケリー)で割り振る。</div>
    {% if view.win5_rec %}
      <div class="panel" style="margin:8px 0;padding:7px 9px;background:#1a1330;border-color:#3a2a5a">
        <a href="{{url_for('win5_page',ordinal=view.day_ord)}}" style="font-weight:700;color:#c9b3ff">🎯 WIN5</a>
        <span class="sub">推奨 ¥{{'{:,}'.format(view.win5_rec.cost)}}({{view.win5_rec.points}}点・的中{{'%.2f'|format(view.win5_rec.hit*100)}}%)</span>
        <div class="sub" style="margin-top:2px">※ WIN5は別枠予算(配分合計には含めない)</div>
      </div>
    {% endif %}
    {% if view.alloc.rows %}
      <table style="margin-top:10px"><tr><th class="l">レース</th><th class="l">買い目</th><th>金額</th></tr>
      {% for a in view.alloc.rows %}
        <tr><td class="l">{{a.label}}</td>
          <td class="l">{{a.kind}} {{a.sel}}<br><span class="sub">{{'%.1f'|format(a.odds)}}倍・EV{{'%.2f'|format(a.ev)}}</span></td>
          <td><b>¥{{'{:,}'.format(a.amount)}}</b></td></tr>
      {% endfor %}
      </table>
      <div class="sum" style="margin-top:8px;font-size:12px">
        <div>合計 <b>¥{{'{:,}'.format(view.alloc.total)}}</b></div>
        {% if view.alloc.leftover %}<div class="sub">余り ¥{{'{:,}'.format(view.alloc.leftover)}}</div>{% endif %}
      </div>
      <div class="sub" style="margin-top:6px">{{view.alloc.n_bet}}点 / 選択{{view.alloc.n_picked}}レース。¥100単位。</div>
      <label class="sub" style="display:block;margin-top:8px">買い目リスト(コピー用)</label>
      <textarea class="bin" rows="{{view.alloc.rows|length + 1}}" readonly onclick="this.select()"
        style="font-size:12px;resize:vertical">{{view.alloc.copy}}
合計 ¥{{'{:,}'.format(view.alloc.total)}}</textarea>
    {% elif view.alloc.requested %}
      <div class="sub" style="margin-top:10px">選んだレースに条件を満たす妙味(+EV)買い目がありません。☑/最低EVを調整、または実オッズ(O1〜O6)取得を確認。</div>
    {% else %}
      <div class="sub" style="margin-top:10px">妙味のあるレースを既定で ☑ 済み。予算を入れて「配分」。</div>
    {% endif %}
    <div class="sub" style="margin-top:8px;border-top:1px solid var(--line);padding-top:6px">
      ※ 紙上の目安。資金管理は自己責任。控除率の壁あり。</div>
  </div>
</aside>
</form>
"""

SUMMARY_BODY = """
<h2>2026 通算成績(アウトオブタイム・紙上)</h2>
{% if s.n_finished %}
<div class="panel sum">
  <div>対象 <b>{{s.n_finished}}</b> / {{s.n_races}} レース(確定)</div>
  <div>本命的中 <b>{{'%.1f'|format(s.honmei_win*100)}}%</b></div>
  <div>本命複勝圏 <b>{{'%.1f'|format(s.honmei_top3*100)}}%</b></div>
  {% if s.honmei_roi is not none %}<div>本命 単勝回収率 <b>{{'%.0f'|format(s.honmei_roi*100)}}%</b></div>{% endif %}
  {% if s.ev_roi is not none %}<div>EV買い目 回収率 <b>{{'%.0f'|format(s.ev_roi*100)}}%</b> <span class="sub">({{s.ev_n}}点/的中{{'%.0f'|format(s.ev_hit*100)}}%)</span></div>{% endif %}
</div>
{% if s.port %}
<div class="panel sum">
  <div>📋 ペーパー配分成績 <span class="sub">(各レース推奨買い目をflat¥1)</span></div>
  <div>点数 <b>{{s.port.n}}</b></div>
  <div>的中率 <b>{{'%.1f'|format(s.port.hit*100)}}%</b></div>
  <div>回収率 <b>{{'%.0f'|format(s.port.roi*100)}}%</b></div>
</div>
{% endif %}
<div class="panel">
  <div style="font-weight:700;margin-bottom:6px">月別(本命単勝)</div>
  <table style="max-width:520px"><tr><th class="l">月</th><th>レース</th><th>的中率</th><th>回収率</th></tr>
  {% for m in s.months %}<tr><td class="l">{{m.month}}月</td><td>{{m.n}}</td><td>{{'%.1f'|format(m.win*100)}}%</td><td>{% if m.roi is not none %}{{'%.0f'|format(m.roi*100)}}%{% else %}-{% endif %}</td></tr>{% endfor %}
  </table>
</div>
<div class="sub">※ 本命=モデル予想1位を単勝で1点買いし続けた紙上成績。回収率100%が損益分岐。控除率20%の壁を越えるのは構造的に難しい(リサーチ参照)。</div>
{% else %}
<div class="sub">確定済みの2026レースがまだありません(結果速報の取り込み後に集計されます)。</div>
{% endif %}
"""


WIN5_BODY = """
<h2 style="margin:6px 0">🎯 WIN5 — {{v.day_label}}
  {% if v.carryover %}<span class="badge" style="background:#5a1a1a;color:#ff9a9a">🔥 キャリーオーバー</span>{% endif %}
  {% if v.all_finished %}<span class="badge {{'b-win' if v.won else 'b-miss'}}">{{ '的中' if v.won else '不的中' }}</span>{% endif %}
</h2>
<div class="panel sum">
  <div>推奨 <b>¥{{'{:,}'.format(v.rec.cost_yen)}}</b> <span class="sub">({{v.rec.points}}点)</span></div>
  <div>的中率 <b>{{'%.2f'|format(v.rec.hit_prob*100)}}%</b></div>
  <div>フェア配当 <b>{{'{:,.0f}'.format(v.rec.fair_odds)}}倍↑</b></div>
  <div>頭数 <b>{{v.rec.counts|join('-')}}</b></div>
</div>
<div class="cards" style="grid-template-columns:repeat(auto-fill,minmax(205px,1fr))">
{% for leg in v.legs %}
  <div class="race">
    <h3><span>{{loop.index}}. {{leg.label}}</span>
      {% if leg.finished %}<span class="badge {{'b-win' if (leg.win_post in leg.sel_posts) else 'b-miss'}}">{{ '◎的中' if (leg.win_post in leg.sel_posts) else '×' }}</span>{% else %}<span class="badge b-pre">発走前</span>{% endif %}</h3>
    <table><tr><th class="l">馬番</th><th>勝率</th>{% if leg.finished %}<th>着</th>{% endif %}</tr>
    {% for h in leg.rows %}
      <tr class="{{'bet' if h.sel else ''}}">
        <td class="l">{{h.post}}{% if h.sel %} <span class="mk">◎</span>{% endif %}</td>
        <td>{{'%.1f'|format(h.win*100)}}%</td>
        {% if leg.finished %}<td>{% if h.fin %}<span class="fin {{'f1' if h.fin==1 else 'f2' if h.fin==2 else 'f3' if h.fin==3 else 'fx'}}">{{h.fin}}</span>{% else %}<span class="fx">-</span>{% endif %}</td>{% endif %}
      </tr>
    {% endfor %}
    </table>
  </div>
{% endfor %}
</div>
<div class="panel">
  <div style="font-weight:700;margin-bottom:6px">予算別プラン(点数=Π選択頭数)</div>
  <table style="max-width:600px"><tr><th class="l">金額</th><th>点数</th><th>頭数</th><th>的中率</th><th>フェア配当</th></tr>
  {% for t in v.tiers %}<tr class="{{'bet' if t.is_rec else ''}}"><td class="l">¥{{'{:,}'.format(t.yen)}}</td><td>{{t.points}}</td><td>{{t.counts|join('-')}}</td><td>{{'%.2f'|format(t.hit*100)}}%</td><td>{{'{:,.0f}'.format(t.fair)}}倍</td></tr>{% endfor %}
  </table>
</div>
<div class="sub">※ ◎=推奨選択。1頭堅いレースは固定、混戦は手広く自動配分(的中確率/コスト最大化)。
WIN5は控除率30%・配当はパリミュチュエル+繰越で大きく変動。フェア配当を超える配当なら理論上プラス。</div>
"""


def _render(body_html, cur_ord, auto=False):
    with _LOCK:
        pred = STATE["pred"]
        ctx = {k: STATE[k] for k in ("updated", "building", "error", "issues", "refresh_sec")}
    days = _nav_days(pred) if pred is not None and len(pred) else []
    return render_template_string(LAYOUT, css=BASE_CSS, body=body_html, days=days,
                                  cur_ord=cur_ord, auto=auto, url_for=url_for, **ctx)


@app.route("/")
def index():
    with _LOCK:
        today = STATE["today"]
    if today is None:
        return _render("<div class='sub'>準備中…</div>", None)
    return redirect(url_for("day", ordinal=today))


@app.route("/day/<int:ordinal>")
def day(ordinal: int):
    with _LOCK:
        pred = STATE["pred"]; today = STATE["today"]
    if pred is None or len(pred) == 0:
        return _render("<div class='sub'>準備中…</div>", ordinal)
    submitted = request.args.get("submitted") is not None
    budget = request.args.get("budget", type=int) or 10000
    budget = max(0, min(budget, 100_000_000))
    picks = set(request.args.getlist("pick"))
    sort = "ev" if request.args.get("sort") == "ev" else "num"
    min_ev = request.args.get("min_ev", type=float)
    min_ev = 1.0 if min_ev is None else max(1.0, min(min_ev, 100.0))
    cap_pct = request.args.get("cap_pct", type=int) or 100
    cap_pct = max(1, min(cap_pct, 100))
    max_bets = request.args.get("max_bets", type=int) or 0
    max_bets = max(0, min(max_bets, 200))
    view = _day_view(pred, ordinal, picks=picks, budget=budget, submitted=submitted,
                     sort=sort, min_ev=min_ev, cap_pct=cap_pct, max_bets=max_bets)
    body = render_template_string(DAY_BODY, view=view)
    # 配分フォーム送信時は自動更新(meta refresh)を切る(入力が消えないように)
    return _render(body, ordinal, auto=(ordinal == today and not submitted))


@app.route("/win5/<int:ordinal>")
def win5_page(ordinal: int):
    with _LOCK:
        pred = STATE["pred"]
    if pred is None or len(pred) == 0:
        return _render("<div class='sub'>準備中…</div>", ordinal)
    v = _win5_view(pred, ordinal)
    if v is None:
        body = ("<div class='sub'>この日はWIN5対象データ(NL_WF)が見つかりません。"
                "取得層で重勝式レコードを取り込むと表示されます。</div>")
    elif not v.get("available"):
        body = ("<div class='sub'>WIN5対象5レースは検出しましたが、まだ予測データに"
                "含まれていません(発走前の確定前など)。レース確定後に再表示されます。</div>")
    else:
        body = render_template_string(WIN5_BODY, v=v)
    return _render(body, ordinal)


@app.route("/summary")
def summary():
    with _LOCK:
        pred = STATE["pred"]
    s = _summary_view(pred) if pred is not None and len(pred) else {"n_finished": 0, "n_races": 0}
    body = render_template_string(SUMMARY_BODY, s=s)
    return _render(body, None)


@app.route("/refresh")
def refresh():
    rebuild(retrain=False)
    return redirect(url_for("index"))


def _auto_refresh_loop(interval: int):
    while True:
        time.sleep(interval)
        rebuild(retrain=False)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="keiba.web", description="当日予想+2026バックテストの Web ビューア")
    p.add_argument("--db", required=True)
    p.add_argument("--db-kind", choices=["sqlite", "duckdb"], default="sqlite")
    p.add_argument("--objective", choices=["binary", "lambdarank"], default="binary")
    p.add_argument("--ev", type=float, default=1.15)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--refresh", type=int, default=90)
    p.add_argument("--reingest", type=int, default=240)
    p.add_argument("--immutable", action="store_true",
                   help="realtime 取り込みが DB をロック中でも読めるよう immutable オープンする")
    p.add_argument("--cache-dir", default=None,
                   help="学習結果/予測のキャッシュ保存先。指定すると再起動が数分→数秒に")
    args = p.parse_args(argv)
    if args.cache_dir:
        os.makedirs(args.cache_dir, exist_ok=True)
    STATE.update(db=args.db, kind=args.db_kind, objective=args.objective,
                 ev=args.ev, refresh_sec=args.refresh, immutable=args.immutable,
                 cache_dir=args.cache_dir)
    print("準備中…(初回は学習で数分。キャッシュ有効かつDB未変更なら数秒)", flush=True)
    rebuild(use_cache=True)
    print(f"準備完了。ブラウザで http://localhost:{args.port} を開いてください。", flush=True)
    threading.Thread(target=_auto_refresh_loop, args=(args.reingest,), daemon=True).start()
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
