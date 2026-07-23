"""ライブ運用フォレンジック診断 — 記録された signals/equity から「何が起きたか」を復元する。

口座がマイナスのとき最初に見るべきレポート。ライブDB(app/db)とブリッジ status を
**読み取り専用**で解析し、以下を出力する:

  [1] クローズ済み意図サイクル(LONG→FLAT)ごとの実現損益の帰属
      — ストップ / AI拒否 / トレンド転換、どの出口でいくら失った(得た)か
  [2] AI(Opus/Sonnet)コンサル回数と概算APIコスト
  [3] バックテスト期待値(docs/RESEARCH.md のリファレンス)との比較
      — ストップアウト頻度・ポジションサイズ・ドローダウンの正常範囲判定
  [4] 異常検知 — ストップ無しLONG、equity記録の欠落、ブレーキ履歴、サイズ超過

使い方:
  docker compose run --rm app python -m scripts.diagnose_live
  python -m scripts.diagnose_live [--run-id N] [--db PATH]

DBへの書き込みは一切しない(sqlite を mode=ro で開く)。DBが無ければ何も作らず終了。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app import bridge
from app.config import settings

# --------------------------------------------------------------------------- #
# バックテスト・リファレンス (docs/RESEARCH.md Round-2 凸ランプ既定 15.5/24.6/0.89
# を再現する検証済みハーネスの実測値。2015-01..2026-06 H1, 219トレード)
# --------------------------------------------------------------------------- #
BACKTEST_REF = {
    "cagr_pct": 15.5,
    "max_dd_pct": 24.6,
    "sharpe": 0.89,
    "trades": 219,
    "years": 11.41,
    "trades_per_month": 1.60,        # 219 / (11.41*12)
    "stop_share": 0.352,             # ストップ退出 77/219
    "fade_share": 0.644,             # トレンド(シグナル消滅)退出 141/219
    "win_rate": 0.096,               # 勝ちトレード比率(小さく負けて大きく勝つ型)
    "avg_stop_loss_pct": -0.50,      # ストップ1回あたり平均損失(口座残高比%)
    "time_in_market": 0.567,
    # トレンド中に開始した42日間ウィンドウの損益分布(ロジック健全でも起きる範囲)
    "p42d_le_minus3_25": 0.165,      # P(42日リターン <= -3.25%)
    "p42d_p5_pct": -8.5,             # 5パーセンタイル
}

# APIコスト概算の前提 (モデル価格は 2026-06 時点の公表値, USD / 1M tokens)
PRICING_USD_PER_MTOK = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
}
DEFAULT_PRICING = (5.0, 25.0)        # 不明モデルは Opus 価格で保守的に
EST_INPUT_TOKENS = 8_000             # プロンプト+コンテキスト+検索結果の概算/回
EST_OUTPUT_TOKENS = 1_200            # JSON判断+根拠の概算/回
EST_WEB_SEARCHES = 4                 # max_web_uses=6 (app/ai_trader.py) の平均想定
WEB_SEARCH_USD_PER_1000 = 10.0

UNITS_PER_LOT = 100_000.0

# 消費される判断トリガー(= AIコンサルの可能性がある記録)
_DECISION_TRIGGERS = ("daily", "event", "gate-entry", "gate-exit", "gate-rearm", "manual")


# --------------------------------------------------------------------------- #
# 読み取り専用DBアクセス
# --------------------------------------------------------------------------- #
def _connect_ro(db_path: str) -> sqlite3.Connection:
    """書き込み不可能な接続。存在しないDBを勝手に作らない。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(str(ts))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _comp(sig: dict) -> dict:
    raw = sig.get("components")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def load_run_data(db_path: str, run_id: Optional[int] = None) -> dict:
    """steady-ai ランの signals(combined)/equity/adjustments を読み取り専用で取得。"""
    conn = _connect_ro(db_path)
    try:
        runs = _rows(conn, "SELECT * FROM runs WHERE instrument <> 'JP-STOCKS' "
                           "ORDER BY id ASC")
        runs = [r for r in runs if "steady-ai" in (r.get("params") or "")]
        if not runs:
            return {"runs": [], "run": None, "signals": [], "equity": [], "adjustments": []}
        if run_id is not None:
            run = next((r for r in runs if r["id"] == run_id), None)
            if run is None:
                raise ValueError(f"run {run_id} not found (steady-ai runs: "
                                 f"{[r['id'] for r in runs]})")
        else:
            ongoing = [r for r in runs if not r.get("ended_at")]
            run = (ongoing or runs)[-1]
        sigs = _rows(conn, "SELECT * FROM signals WHERE run_id=? AND source='combined' "
                           "ORDER BY time ASC", (run["id"],))
        eq = _rows(conn, "SELECT * FROM equity WHERE run_id=? ORDER BY time ASC",
                   (run["id"],))
        adj = _rows(conn, "SELECT * FROM adjustments WHERE run_id=? ORDER BY time ASC",
                    (run["id"],))
    finally:
        conn.close()
    for s in sigs:
        s["comp"] = _comp(s)
        s["dt"] = _parse_ts(s["time"])
    for e in eq:
        e["dt"] = _parse_ts(e["time"])
    return {"runs": runs, "run": run, "signals": sigs, "equity": eq, "adjustments": adj}


# --------------------------------------------------------------------------- #
# [1] 意図サイクルの復元と損益帰属
# --------------------------------------------------------------------------- #
def classify_exit(sig: dict) -> str:
    """FLAT化シグナルの出口ラベル: stop / ai-veto / trend / other。"""
    comp = sig.get("comp") or _comp(sig)
    reason = (sig.get("reason") or "")
    if comp.get("trigger") == "stop" or reason.startswith("stop-loss"):
        return "stop"
    if "veto" in reason:
        return "ai-veto"
    if "trend-down" in reason or comp.get("trend_up") is False:
        return "trend"
    return "other"


def build_cycles(signals: list[dict]) -> tuple[list[dict], list[dict]]:
    """combined シグナル列から (クローズ済み+進行中サイクル, 拒否されたエントリー) を復元。

    サイクル = intent が FLAT→LONG(エントリー)し LONG→FLAT(イグジット)するまで。
    exit_sig が None のサイクルは現在も保有中。
    """
    cycles: list[dict] = []
    vetoed_entries: list[dict] = []
    cur: Optional[dict] = None
    for s in signals:
        comp = s["comp"]
        if s["direction"] == 1:
            if cur is None:
                cur = {
                    "entry_sig": s,
                    "entry_time": s["dt"],
                    "lots": float(comp.get("target_lots") or 0.0),
                    "holds": [],
                    "stop_prices": [comp.get("stop_price")],
                    "brakes": [comp.get("brake")],
                }
            else:
                cur["holds"].append(s)
                cur["stop_prices"].append(comp.get("stop_price"))
                cur["brakes"].append(comp.get("brake"))
                pos = float(comp.get("position_lots") or 0.0)
                if pos > cur["lots"]:
                    cur["lots"] = pos
        else:
            if cur is not None:
                cur["exit_sig"] = s
                cur["exit_time"] = s["dt"]
                cur["trigger"] = classify_exit(s)
                pos = float(comp.get("position_lots") or 0.0)
                if pos > cur["lots"]:
                    cur["lots"] = pos
                cycles.append(cur)
                cur = None
            else:
                # FLAT中のFLAT判断: トレンド上なのに建てなかった＝AI拒否 or サイズ0
                if comp.get("trend_up") and classify_exit(s) == "ai-veto":
                    vetoed_entries.append(s)
    if cur is not None:
        cur["exit_sig"] = None
        cur["exit_time"] = None
        cur["trigger"] = "open"
        cycles.append(cur)
    return cycles, vetoed_entries


def attach_pnl(cycles: list[dict], equity: list[dict]) -> None:
    """サイクルごとの実現損益を equity の残高差分で帰属(不能なら価格差で概算)。

    残高はポジション決済時にのみ動くので、
      実現損益 ≈ (イグジット後の最初の残高) - (エントリー時点の残高)。
    ストップ退出は equity 記録を残さないため、次の判断の残高記録を使う。
    """
    def bal_at_or_before(dt: datetime) -> Optional[dict]:
        prev = None
        for e in equity:
            if e["dt"] <= dt:
                prev = e
            else:
                break
        return prev

    def first_after(dt: datetime) -> Optional[dict]:
        for e in equity:
            if e["dt"] > dt:
                return e
        return None

    for c in cycles:
        entry_row = bal_at_or_before(c["entry_time"])
        c["entry_price"] = entry_row.get("price") if entry_row else None
        c["entry_balance"] = entry_row.get("balance") if entry_row else None
        c["pnl"] = None
        c["pnl_method"] = None
        if c["exit_time"] is None:
            continue
        exit_comp = c["exit_sig"]["comp"]
        # ストップは stop_price、それ以外は直近 equity の価格を出口価格の目安に
        exit_row = bal_at_or_before(c["exit_time"])
        c["exit_price"] = exit_comp.get("stop_price") if c["trigger"] == "stop" else (
            exit_row.get("price") if exit_row else None)
        after = first_after(c["exit_time"])
        if after is not None and c["entry_balance"] is not None:
            c["pnl"] = float(after["balance"]) - float(c["entry_balance"])
            c["pnl_method"] = "balance"
        elif c["entry_price"] and c["exit_price"] and c["lots"]:
            c["pnl"] = c["lots"] * UNITS_PER_LOT * (float(c["exit_price"]) -
                                                    float(c["entry_price"]))
            c["pnl_method"] = "price"


def pnl_by_trigger(cycles: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for c in cycles:
        if c["exit_time"] is None or c["pnl"] is None:
            continue
        d = out.setdefault(c["trigger"], {"n": 0, "pnl": 0.0})
        d["n"] += 1
        d["pnl"] += c["pnl"]
    return out


# --------------------------------------------------------------------------- #
# [2] AIコンサル回数とコスト概算
# --------------------------------------------------------------------------- #
def count_consults(signals: list[dict]) -> dict:
    """記録された判断からAIコンサル回数を復元。

    トレンド下向きの判断はAIを呼ばない(無料)。トレンド上向きの判断のうち、
    reason に "Opus unavailable" が入るものはキー無し/エラー(課金なし)。
    それ以外の上向き判断が課金コンサル(承認 or 拒否)。ストップ退出はAI無関係。
    """
    n = {"paid": 0, "approved": 0, "veto": 0, "unavailable": 0,
         "free_trend_down": 0, "stop_records": 0}
    for s in signals:
        comp = s["comp"]
        trig = str(comp.get("trigger") or "")
        if trig == "stop":
            n["stop_records"] += 1
            continue
        if not any(trig.startswith(t) for t in _DECISION_TRIGGERS):
            continue
        reason = s.get("reason") or ""
        if comp.get("trend_up") is True:
            if "Opus unavailable" in reason or "unavailable" in reason:
                n["unavailable"] += 1
            else:
                n["paid"] += 1
                if s["direction"] == 1:
                    n["approved"] += 1
                else:
                    n["veto"] += 1
        else:
            n["free_trend_down"] += 1
    return n


def estimate_api_cost(n_paid: int, model: str) -> dict:
    key = (model or "").strip()
    pricing = PRICING_USD_PER_MTOK.get(key)
    if pricing is None:
        for k, v in PRICING_USD_PER_MTOK.items():
            if key.startswith(k):
                pricing = v
                break
    pricing = pricing or DEFAULT_PRICING
    in_usd = n_paid * EST_INPUT_TOKENS / 1e6 * pricing[0]
    out_usd = n_paid * EST_OUTPUT_TOKENS / 1e6 * pricing[1]
    ws_usd = n_paid * EST_WEB_SEARCHES / 1000.0 * WEB_SEARCH_USD_PER_1000
    return {
        "model": key or "(不明)",
        "pricing": pricing,
        "input_usd": in_usd,
        "output_usd": out_usd,
        "web_search_usd": ws_usd,
        "total_usd": in_usd + out_usd + ws_usd,
        "per_consult_usd": (in_usd + out_usd + ws_usd) / n_paid if n_paid else 0.0,
    }


# --------------------------------------------------------------------------- #
# [3] バックテスト期待値との比較
# --------------------------------------------------------------------------- #
def compare_with_backtest(cycles: list[dict], equity: list[dict]) -> dict:
    closed = [c for c in cycles if c["exit_time"] is not None]
    stops = [c for c in closed if c["trigger"] == "stop"]
    out: dict = {"n_closed": len(closed), "n_stops": len(stops)}
    if equity:
        span_days = max((equity[-1]["dt"] - equity[0]["dt"]).total_seconds() / 86400.0,
                        1.0)
        out["span_days"] = span_days
        out["trades_per_month"] = len(closed) / (span_days / 30.44)
        bal0 = float(equity[0]["balance"])
        eq_last = float(equity[-1]["equity"])
        out["balance0"] = bal0
        out["equity_last"] = eq_last
        out["return_pct"] = (eq_last / bal0 - 1.0) * 100.0 if bal0 > 0 else 0.0
        peak = 0.0
        max_dd = 0.0
        for e in equity:
            v = float(e["equity"])
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak)
        out["max_dd_pct"] = max_dd * 100.0
    out["stop_share"] = (len(stops) / len(closed)) if closed else None
    # ポジションサイズ: エントリー時の 5x キャップに対する使用率と超過チェック
    sizes = []
    for c in cycles:
        comp = c["entry_sig"]["comp"]
        lev = float(comp.get("eff_leverage") or 0.0)
        px = c.get("entry_price")
        bal = c.get("entry_balance")
        if lev > 0 and px and bal:
            cap = lev * float(bal) / (float(px) * UNITS_PER_LOT)
            sizes.append({"time": c["entry_time"], "lots": c["lots"], "cap": cap,
                          "util": c["lots"] / cap if cap > 0 else None})
    out["sizes"] = sizes
    return out


# --------------------------------------------------------------------------- #
# [4] 異常検知
# --------------------------------------------------------------------------- #
def _spans_weekend(a: datetime, b: datetime) -> bool:
    d = a.date()
    while d <= b.date():
        if d.weekday() >= 5:
            return True
        d += timedelta(days=1)
    return False


def find_anomalies(signals: list[dict], equity: list[dict], runs: list[dict],
                   cycles: list[dict]) -> list[str]:
    warns: list[str] = []
    # 1) ストップ無しLONG: 連続するLONG判断のどこにも stop_price が無い
    run_buf: list[dict] = []

    def _flush(open_ended: bool) -> None:
        if run_buf and not any(s["comp"].get("stop_price") for s in run_buf):
            tag = "(現在も保有中!)" if open_ended else ""
            warns.append(
                f"ストップ価格の無いLONG連続 {run_buf[0]['time']} .. "
                f"{run_buf[-1]['time']} ({len(run_buf)}件){tag} — "
                "保護ストップを復元できない状態だった")

    for s in signals:
        if s["direction"] == 1:
            run_buf.append(s)
        else:
            _flush(open_ended=False)
            run_buf = []
    _flush(open_ended=True)

    # 2) equity記録のギャップ (平日26h超 / 週末またぎ75h超)
    for a, b in zip(equity, equity[1:]):
        gap_h = (b["dt"] - a["dt"]).total_seconds() / 3600.0
        limit = 75.0 if _spans_weekend(a["dt"], b["dt"]) else 26.0
        if gap_h > limit:
            warns.append(f"equity記録ギャップ {gap_h:.0f}時間 "
                         f"({a['time']} → {b['time']}) — ループ停止/EA切断の疑い")

    # 3) 進行中 steady-ai ランが複数
    ongoing = [r["id"] for r in runs if not r.get("ended_at")]
    if len(ongoing) > 1:
        warns.append(f"進行中の steady-ai ランが複数: {ongoing} — "
                     "状態復元が別ランを読む恐れ")

    # 4) サイズがレバレッジ上限を超過
    for c in cycles:
        comp = c["entry_sig"]["comp"]
        lev = float(comp.get("eff_leverage") or 0.0)
        px, bal = c.get("entry_price"), c.get("entry_balance")
        if lev > 0 and px and bal:
            cap = lev * float(bal) / (float(px) * UNITS_PER_LOT)
            if c["lots"] > cap * 1.05 + 0.01:
                warns.append(f"サイズ超過 {c['entry_time']:%Y-%m-%d %H:%M} "
                             f"lots={c['lots']:.2f} > 上限{cap:.2f} "
                             f"(lev {lev:.1f}x, 残高 {bal:,.0f})")

    # 5) LONG判断なのに target_lots<=0
    for s in signals:
        comp = s["comp"]
        if s["direction"] == 1 and float(comp.get("target_lots") or 0.0) <= 0:
            warns.append(f"LONG判断なのに target_lots=0 ({s['time']})")
    return warns


def brake_history(signals: list[dict]) -> list[tuple[str, float]]:
    """ブレーキ値の変化点 (時刻, 値)。"""
    hist: list[tuple[str, float]] = []
    for s in signals:
        b = s["comp"].get("brake")
        if b is None:
            continue
        b = float(b)
        if not hist or abs(hist[-1][1] - b) > 1e-9:
            hist.append((s["time"], b))
    return hist


# --------------------------------------------------------------------------- #
# レポート出力
# --------------------------------------------------------------------------- #
def _fmt_dt(dt: Optional[datetime]) -> str:
    return dt.strftime("%m-%d %H:%M") if dt else "  (保有中)  "


_TRIGGER_JA = {"stop": "ストップ", "ai-veto": "AI拒否", "trend": "トレンド",
               "other": "その他", "open": "保有中"}


def render_report(data: dict, status: Optional[dict]) -> None:
    run = data["run"]
    if run is None:
        print("steady-ai のランがDBに見つかりません。診断対象なし。")
        return
    params = {}
    try:
        params = json.loads(run.get("params") or "{}")
    except ValueError:
        pass
    model = str(params.get("model") or "")
    signals, equity = data["signals"], data["equity"]
    cycles, vetoed = build_cycles(signals)
    attach_pnl(cycles, equity)
    by_trig = pnl_by_trigger(cycles)
    consults = count_consults(signals)
    cost = estimate_api_cost(consults["paid"], model)
    cmp_ = compare_with_backtest(cycles, equity)
    warns = find_anomalies(signals, equity, data["runs"], cycles)
    brakes = brake_history(signals)

    W = 78
    print("=" * W)
    print(f" ライブ診断レポート  run #{run['id']}  ({run['instrument']} "
          f"{run['granularity']}, model={model or '?'}, 開始 {run['started_at'][:16]})")
    print(f" 初期残高 {run['initial_balance']:,.0f} 円 | signals(combined) "
          f"{len(signals)}件 | equity記録 {len(equity)}件")
    if status:
        print(f" ブリッジ現況: 残高 {status.get('balance', 0):,.0f} / 評価 "
              f"{status.get('equity', 0):,.0f} / 建玉 {status.get('position_lots', 0):.2f} lots")
    else:
        print(" ブリッジ現況: status 読めず (EA未接続 or 共有フォルダ未マウント)")
    print("=" * W)

    # ---- [1] サイクル別損益 ----
    print("\n[1] 意図サイクル別 実現損益 (エントリー→イグジット)")
    if not cycles:
        print("  サイクルなし (エントリー記録がまだ無い)")
    else:
        print(f"  {'#':>2} {'エントリー':<12} {'価格':>8} {'lots':>5} "
              f"{'イグジット':<12} {'価格':>8} {'出口':<6} {'損益(円)':>12}")
        for i, c in enumerate(cycles, 1):
            ep = f"{c['entry_price']:.3f}" if c.get("entry_price") else "?"
            xp = f"{c['exit_price']:.3f}" if c.get("exit_price") else "-"
            pnl = ("      -" if c["pnl"] is None else
                   f"{c['pnl']:>+11,.0f}" + ("*" if c["pnl_method"] == "price" else " "))
            print(f"  {i:>2} {_fmt_dt(c['entry_time']):<12} {ep:>8} "
                  f"{c['lots']:>5.2f} {_fmt_dt(c['exit_time']):<12} {xp:>8} "
                  f"{_TRIGGER_JA.get(c['trigger'], c['trigger']):<6} {pnl}")
        print("  (* は価格差からの概算。無印は残高差分=手数料・スワップ込み実測)")
        total = sum(c["pnl"] for c in cycles if c["pnl"] is not None)
        print(f"\n  出口別合計:")
        for trig in ("stop", "ai-veto", "trend", "other"):
            if trig in by_trig:
                d = by_trig[trig]
                print(f"    {_TRIGGER_JA[trig]:<6}: {d['n']:>3}回  {d['pnl']:>+12,.0f} 円")
        print(f"    {'合計':<6}: {sum(d['n'] for d in by_trig.values()):>3}回  "
              f"{total:>+12,.0f} 円 (クローズ済みのみ)")
    if vetoed:
        print(f"\n  AI拒否でエントリーを見送った判断: {len(vetoed)}回")
        for s in vetoed[-5:]:
            print(f"    {s['time'][:16]}  {(s.get('reason') or '')[:56]}")

    # ---- [2] AIコンサル ----
    print("\n[2] AIコンサル回数とAPIコスト概算")
    print(f"  課金コンサル {consults['paid']}回 (承認 {consults['approved']} / "
          f"拒否 {consults['veto']}) | キー無し/エラー {consults['unavailable']}回 | "
          f"トレンド下=無料 {consults['free_trend_down']}回 | "
          f"ストップ記録 {consults['stop_records']}回")
    print(f"  概算コスト: ${cost['total_usd']:.2f} "
          f"(入力 ${cost['input_usd']:.2f} + 出力 ${cost['output_usd']:.2f} + "
          f"Web検索 ${cost['web_search_usd']:.2f}) ≒ ${cost['per_consult_usd']:.3f}/回")
    print(f"  前提: {cost['model']} ${cost['pricing'][0]:.0f}/${cost['pricing'][1]:.0f} "
          f"per MTok, {EST_INPUT_TOKENS:,}in/{EST_OUTPUT_TOKENS:,}out tok/回, "
          f"検索{EST_WEB_SEARCHES}回/コンサル(${WEB_SEARCH_USD_PER_1000:.0f}/1000回)")

    # ---- [3] バックテスト比較 ----
    ref = BACKTEST_REF
    print("\n[3] バックテスト期待値との比較 (リファレンス: "
          f"CAGR {ref['cagr_pct']}% / maxDD {ref['max_dd_pct']}% / "
          f"Sharpe {ref['sharpe']} / {ref['trades']}トレード/11.4年)")
    if "span_days" in cmp_:
        print(f"  {'指標':<24} {'ライブ':>12} {'バックテスト期待':>16}")
        print(f"  {'観測期間':<24} {cmp_['span_days']:>10.0f}日 {'-':>16}")
        print(f"  {'クローズ済みサイクル/月':<24} {cmp_['trades_per_month']:>12.2f} "
              f"{ref['trades_per_month']:>16.2f}")
        ss = cmp_["stop_share"]
        print(f"  {'ストップアウト比率':<24} "
              f"{(f'{ss:.0%}' if ss is not None else '-'):>12} "
              f"{ref['stop_share']:>16.0%}")
        print(f"  {'期間リターン':<24} {cmp_['return_pct']:>+11.2f}% "
              f"{'+1.9%/42日(平均)':>16}")
        print(f"  {'最大DD(equity記録上)':<24} {cmp_['max_dd_pct']:>11.2f}% "
              f"{ref['max_dd_pct']:>15.1f}%")
        # 判定コメント
        r = cmp_["return_pct"]
        if r >= 0:
            verdict = "プラス圏。バックテスト分布の正常範囲内。"
        elif cmp_["max_dd_pct"] <= abs(ref["p42d_p5_pct"]):
            verdict = (f"マイナスだが、トレンド中に始めた42日間の "
                       f"{ref['p42d_le_minus3_25']:.0%} は -3.25%以下になる分布"
                       f"(5%点 {ref['p42d_p5_pct']}%)。ロジック欠陥の証拠ではない。")
        else:
            verdict = (f"DDがバックテストの42日5%点({ref['p42d_p5_pct']}%)を超過。"
                       "執行乖離(約定・サイズ・停止)を優先調査。")
        print(f"  判定: {verdict}")
    if cmp_.get("sizes"):
        utils = [s["util"] for s in cmp_["sizes"] if s["util"] is not None]
        if utils:
            print(f"  サイズ: エントリー{len(utils)}回の対レバ上限使用率 "
                  f"平均 {sum(utils)/len(utils):.0%} "
                  f"(バックテストは時間の約95%で上限張り付きが正常)")

    # ---- [4] 異常検知 ----
    print("\n[4] 異常検知")
    if warns:
        for w in warns:
            print(f"  [警告] {w}")
    else:
        print("  異常なし (ストップ無しLONG・equity欠落・サイズ超過は検出されず)")
    if brakes:
        cur = brakes[-1][1]
        print(f"  ブレーキ履歴 (adaptive DD brake): 現在 x{cur:.2f}")
        for t, b in brakes[-6:]:
            print(f"    {t[:16]}  x{b:.2f}")
        if cur < 1.0:
            print("    → ドローダウン中のためリスクを自動縮小中 (仕様どおり)")
    print("\n" + "=" * W)
    print(" 注意: 本レポートは signals/equity 記録からの復元。EA側の実約定明細")
    print(" (スリッページ・スワップの内訳) はMT5の口座履歴と突き合わせること。")
    print("=" * W)


# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="ライブ運用フォレンジック診断 (read-only)")
    ap.add_argument("--db", default=None, help="DBパス (既定: FXSIM_DB or 設定値)")
    ap.add_argument("--run-id", type=int, default=None,
                    help="解析するラン (既定: 進行中の steady-ai ラン)")
    args = ap.parse_args(argv)
    db_path = args.db or os.getenv("FXSIM_DB") or settings.db_path
    if not Path(db_path).exists():
        print(f"DBが見つかりません: {db_path} (何も作成せず終了)")
        return 1
    try:
        data = load_run_data(db_path, run_id=args.run_id)
    except ValueError as exc:
        print(f"エラー: {exc}")
        return 1
    try:
        status = bridge.read_status()
    except Exception:
        status = None
    render_report(data, status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
