"""PDCA monitor — is the LIVE run behaving like the BACKTEST said it would?

Compares the live FX run's realized stats against production's own backtest
(H1 / SMA2400 / linear ramp to 5x / long-only — docs/RESEARCH.md Round-4/9),
judged over windows of the SAME length as the run (scripts/monitor_envelope.py),
and flags four failure modes early:

  * DRAWDOWN BREACH   — live max drawdown beyond the 36% alarm line (the
                        worst of the nine neighbouring SMA lengths is 35.4%,
                        their mean 29.5%, the live length's own path 26.7%) →
                        outside the tested envelope; not necessarily broken (a
                        1995-2014 proxy reached 51%).
  * OVERTRADING       — far more position changes than the backtest ever made
                        over the same span → whipsaw beyond history, or a bug.
  * EXECUTION DRIFT   — the strategy says LONG/FLAT but the live book disagrees →
                        EA/bridge problem or slippage.
  * INSUFFICIENT DATA — too few days to judge yet (most of the early life).

Pure functions here (no DB / no network) so they're unit-tested; the
scripts/run_monitor.py CLI feeds them data from the DB + the live bar feed.
"""
from __future__ import annotations

from .bridge import (BRAIN_SIGNAL_STALE_S, EA_BUILD_EXPECTED,
                     EA_STATUS_STALE_S, MAX_BAR_AGE_H)

import math
from datetime import datetime

# What the operator is shown as the expectation (H1 2015-01..2026-06, USD/JPY
# long-only, linear ramp 1.5 ATR, 5x cap, no swap; `python -m
# scripts.monitor_envelope` prints every number below). NOT SMA2400's own
# 15.3%/yr: the size a whole trend is held at is a draw on its entry bar (the
# 2021-22 trend: 5.0x at SMA2400, 1.0x at SMA2500), and 15.3% is the top of
# that draw — 5th of 81 neighbouring lengths (docs/RESEARCH.md Round-10). The
# reference is the nine lengths 2000..2800, each at the backtest close AND at
# the closed-bar live cadence the account trades at (five poll phases): about
# zero from 2015-01 to 2021-09. Before Round-9 these were the flat-5x recipe's
# numbers; before Round-10, the lucky path's; before Round-10B, the close
# cadence's alone (SMA2700 reaches 35.4% at the live cadence, 33.9% at the close).
BT_CAGR_PCT = 9.1                # nine lengths: mean of each length's mean
BT_CAGR_RANGE = (2.0, 15.3)      # lowest .. highest run (the highest = the live length's own path)
BT_MAXDD_MEAN_PCT = 29.5         # nine lengths: mean max drawdown (the live path's own: 26.7)
BT_MAXDD_PCT = 35.4              # the worst run of the nine at either cadence
BT_CHANGES_PER_YEAR = 40.8       # 2300-2500 (the count reference); entries + exits, a stop-out and its re-entry are two

# Drawdown alarm line: RED above it, YELLOW above 75% of it. It sits just above
# the neighbourhood's worst (BT_MAXDD_PCT); the daily-bar proxy of 1995-2014
# reached 51.5% under the same rules (Round-9), so RED here means "outside the
# tested envelope — review the size", not necessarily "broken".
EXP_MAXDD_PCT = 36.0

# Span-aware envelopes (`python -m scripts.monitor_envelope`; re-run it
# whenever production changes). A live run of N days is judged against windows
# of the SAME length. Both quantities are bursty — a whipsaw week near the SMA
# is normal — so the single annualised expectations used before Round-9 read
# normal behaviour 🔴 in 36-39% of 60-90-day windows. Each row covers the spans
# up to the next row and holds the EXTREME over every whole-day span in between
# (a step, never interpolated). The soft column (上位10% / 下位10%) is the
# percentile of the lengths POOLED, one weight per length; the hard column
# (過去最多 / 過去最悪) is the extreme of any run.
#   CHANGES: the live length and its immediate neighbours 2300-2500. SMA2400's
#     own 38 changes/yr is the fewest of the nine (41-51 for the others), so a
#     band from it alone read the whipsaw its neighbours really had as RED; all
#     nine would hide a doubled trade rate. The early warning (above the p90)
#     comes at a median ~170 days either way (Round-10B).
#   RETURN: all nine — the return depends on the leverage draw, and a band from
#     the lucky SMA2400 path alone would call the next ordinary draw
#     under-performance (Round-10). From day 150 on, a return below the RED
#     line implies a drawdown beyond the 36% line, so in practice a steady loss
#     is reported RED by the drawdown check and this one stays YELLOW; that is
#     the sensitivity traded for not calling an unlucky draw a fault (Round-10B:
#     a steady 3%/month bleed reads drawdown-RED on day ~440).
# Never the forming-bar brain before Round-9 (~85-100 changes/yr, 3-9%/yr
# replayed): including that defect made the monitor blind to it. A run that
# began before the fix is judged only from its first closed-bar decision.
ENVELOPE_CHANGES = (     # (from span_days, p90 count, max count)
    (30, 16, 47), (45, 19, 47), (60, 23, 56), (75, 27, 58), (90, 32, 64),
    (120, 39, 64), (150, 44, 67), (180, 52, 97), (240, 59, 106), (300, 70, 109),
    (365, 83, 126), (450, 94, 142), (545, 109, 153), (640, 122, 161),
    (730, 143, 176), (910, 174, 210), (1095, 199, 231), (1280, 222, 246),
    (1460, 222, 246),
)
ENVELOPE_RETURN = (      # (from span_days, p10 return %, worst return %), no swap;
    # worst = running minimum over spans: a longer window is never stricter
    (60, -5.8, -20.8), (75, -6.1, -20.8), (90, -6.6, -21.2), (120, -7.0, -27.1),
    (150, -7.5, -29.2), (180, -7.8, -29.2), (240, -8.1, -29.2), (300, -8.5, -29.2),
    (365, -9.2, -29.2), (450, -9.3, -31.8), (545, -9.5, -31.8), (640, -9.7, -31.8),
    (730, -10.0, -31.8), (910, -11.0, -31.8), (1095, -11.4, -32.7),
    (1280, -10.4, -32.9), (1460, -7.5, -32.9),
)
CHANGES_RED_MARGIN = 1.25        # RED only well beyond the backtest's busiest window
RETURN_RED_MARGIN_PP = 5.0       # ... or well below its worst (at least 5pp / 25%)

# How much live history before a metric is trustworthy.
MIN_DAYS_FOR_DD = 20
MIN_DAYS_FOR_RETURN = 60

GREEN, YELLOW, RED = "🟢", "🟡", "🔴"


def equity_stats(values: list[float]) -> dict:
    """Total return %, worst drawdown %, and current drawdown % (from all-time peak)."""
    if not values:
        return {"return_pct": 0.0, "max_dd_pct": 0.0, "cur_dd_pct": 0.0}
    start, cur = values[0], values[-1]
    peak, mdd = -1e18, 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100)
    cur_dd = (peak - cur) / peak * 100 if peak > 0 else 0.0
    return {
        "return_pct": (cur / start - 1) * 100 if start else 0.0,
        "max_dd_pct": mdd,
        "cur_dd_pct": cur_dd,
    }


def annualize(return_pct: float, years: float) -> float:
    if years <= 0:
        return 0.0
    growth = 1 + return_pct / 100.0
    if growth <= 0:
        return -100.0
    return (growth ** (1 / years) - 1) * 100


def envelope_at(table, span_days: float, beyond: str) -> tuple[float, float] | None:
    """(soft, hard) bound of `table` for a span: the row at or below it (each
    row already holds the extreme of its interval — never interpolate, which
    understated the worst between sparse rows). None below the first row or
    for a non-finite span (too little history to judge). From the last row on,
    'scale' grows both with the span (counts accumulate) and 'loosest' keeps
    the loosest row (returns: a long run is never judged more strictly than a
    short one)."""
    if not (math.isfinite(span_days) and span_days >= table[0][0]):
        return None
    w_last = table[-1][0]
    if span_days < w_last:
        row = [r for r in table if r[0] <= span_days][-1]
        return float(row[1]), float(row[2])
    if beyond == "scale":
        _, a, b = table[-1]
        return a * span_days / w_last, b * span_days / w_last
    return float(min(r[1] for r in table)), float(min(r[2] for r in table))


def _pending_msg(state) -> str:
    if state == "one-row":
        return "判定保留：確定足方式（2026-11修正）の判断を記録済み。次の記録から判定を始めます"
    return ("判定保留：このランには確定足方式（2026-11修正）の判断がまだありません。新しい脳なら"
            "20時間以内に記録されます（修正前の方式だけのランは判定対象外）")


def count_position_changes(actions: list[str]) -> int:
    """Number of LONG<->FLAT transitions in the decision log (a trade proxy)."""
    def is_long(a: str) -> bool:
        return str(a).upper() == "LONG"
    changes, prev = 0, None
    for a in actions:
        cur = is_long(a)
        if prev is not None and cur != prev:
            changes += 1
        prev = cur
    return changes


def build_report(*, initial_balance: float, equity_values: list[float],
                 span_days: float, actions: list[str],
                 live_position: str | None = None,
                 trend_basis: str | None = None,
                 staleness_days: float | None = None,
                 last_ai_binding: bool | None = None,
                 ea_build: str | None = None,
                 status_missing: bool = False,
                 ea_status_age_s: float | None = None,
                 bars_age_h: float | None = None,
                 bars_count: int | None = None,
                 bars_need: int | None = None,
                 bars_limit_h: float | None = None,
                 brain_signal_age_s: float | None = None,
                 signal_expired: bool | None = None,
                 last_decision_age_s: float | None = None,
                 blocked_on_lock: str | None = None,
                 daily_gap_h: float = 20.0,
                 kind: str = "fx",
                 segment: dict | None = None) -> dict:
    """Assemble the health report + per-check flags + an overall verdict.
    kind != "fx" (the stock system) has no backtest reference, so the
    envelope checks (取引頻度, リターン) are not judged for it.
    segment: the part of the run those two checks judge — {"equity_values",
    "span_days", "actions", "since"} — or {"pending": True} when the current
    (closed-bar) brain has not decided yet; None = the whole run. A run that
    began under the forming-bar brain is outside the envelopes by design."""
    st = equity_stats(equity_values)
    years = max(span_days, 0.0) / 365.25
    checks: list[dict] = []

    # --- data sufficiency ---
    enough_dd = span_days >= MIN_DAYS_FOR_DD
    enough_ret = span_days >= MIN_DAYS_FOR_RETURN

    # --- drawdown vs the 36% alarm line ---
    mdd = st["max_dd_pct"]
    if not enough_dd:
        checks.append({"name": "ドローダウン", "flag": YELLOW,
                       "msg": f"最大DD {mdd:.1f}%（観察{span_days:.0f}日・判定はもう少し先）"})
    elif mdd > EXP_MAXDD_PCT:
        bt = f"（バックテストの平均線9通りの最悪{BT_MAXDD_PCT:.1f}%を超える）" if kind == "fx" else ""
        checks.append({"name": "ドローダウン", "flag": RED,
                       "msg": f"最大DD {mdd:.1f}% が警告線{EXP_MAXDD_PCT:.0f}%を超過{bt}＝試験済みの範囲外"
                              f"（故障とは限らない）。ログを確認し、ルール通りならサイズの見直しを検討"
                              + ("（docs/RESEARCH.md Round-9）" if kind == "fx" else "")})
    elif mdd > EXP_MAXDD_PCT * 0.75:
        bt = f"。バックテストの平均線9通りの最悪は{BT_MAXDD_PCT:.1f}%" if kind == "fx" else ""
        checks.append({"name": "ドローダウン", "flag": YELLOW,
                       "msg": f"最大DD {mdd:.1f}%（警告線{EXP_MAXDD_PCT:.0f}%内だが深い{bt}）"})
    else:
        checks.append({"name": "ドローダウン", "flag": GREEN,
                       "msg": f"最大DD {mdd:.1f}%（警告線{EXP_MAXDD_PCT:.0f}%内）"})

    # --- trade frequency vs production's backtest over the SAME span ---
    n_changes = count_position_changes(actions)
    tpy = n_changes / years if years > 0 else 0.0
    seg = segment or {}
    pending = bool(seg.get("pending"))
    s_span = float(seg.get("span_days", span_days))
    s_changes = count_position_changes(seg.get("actions", actions))
    s_from = f"（{str(seg['since'])[:10]}以降）" if seg.get("since") else ""
    env = envelope_at(ENVELOPE_CHANGES, s_span, "scale") if kind == "fx" else None
    if kind != "fx":
        pass                                   # no stock backtest to compare with
    elif pending:
        checks.append({"name": "取引頻度", "flag": YELLOW, "msg": _pending_msg(seg["pending"])})
    elif env is None:
        checks.append({"name": "取引頻度", "flag": YELLOW,
                       "msg": f"建玉変化 {s_changes}回{s_from}（観察{s_span:.0f}日・判定は30日以降）"})
    else:
        p90, most = env
        ref = f"（同じ長さの期間の過去最多{most:.0f}回・上位10%{p90:.0f}回）"
        head = f"建玉変化 {s_changes}回／{s_span:.0f}日{s_from}"
        if s_changes > math.ceil(most * CHANGES_RED_MARGIN):
            checks.append({"name": "取引頻度", "flag": RED,
                           "msg": f"{head}：過去最多を大きく超過{ref} → "
                                  f"過剰売買（ダマシの連続 or 不具合）の疑い。`docker compose logs fx` で売買の理由を確認"})
        elif s_changes > most:
            checks.append({"name": "取引頻度", "flag": YELLOW,
                           "msg": f"{head}：過去に例のない水準{ref}。ログと執行一致を確認"})
        elif s_changes > p90:
            checks.append({"name": "取引頻度", "flag": YELLOW,
                           "msg": f"{head}（多め{ref}。平均線付近でダマシが続く時期はこうなる）"})
        else:
            checks.append({"name": "取引頻度", "flag": GREEN,
                           "msg": f"{head}（範囲内{ref}）"})

    # --- realized return vs production's backtest over the SAME span ---
    ann = annualize(st["return_pct"], years)
    ret = equity_stats(seg.get("equity_values", equity_values))["return_pct"]
    env = envelope_at(ENVELOPE_RETURN, s_span, "loosest") if kind == "fx" else None
    if kind != "fx":
        pass                                   # no stock backtest to compare with
    elif pending:
        checks.append({"name": "リターン", "flag": YELLOW, "msg": _pending_msg(seg["pending"])})
    elif env is None:
        checks.append({"name": "リターン", "flag": YELLOW,
                       "msg": f"累計 {ret:+.1f}%{s_from}（観察{s_span:.0f}日・判定は60日以降）"})
    else:
        p10, worst = env
        ref = f"（同じ長さの期間の過去最悪{worst:+.1f}%・下位10%{p10:+.1f}%、スワップ別）"
        head = f"累計 {ret:+.1f}%／{s_span:.0f}日{s_from}"
        if ret < worst - max(RETURN_RED_MARGIN_PP, 0.25 * abs(worst)):
            checks.append({"name": "リターン", "flag": RED,
                           "msg": f"{head}：過去最悪を大きく下回る{ref}＝試験済みの範囲外"
                                  f"（故障とは限らない）。ログと執行一致を確認（🟢でもスリッページ等の執行コストは否定できない）。"
                                  f"ルール通りならサイズ（レバ）の見直しを検討（docs/RESEARCH.md Round-8/9）"})
        elif ret < worst:
            checks.append({"name": "リターン", "flag": YELLOW,
                           "msg": f"{head}：過去に例のない水準{ref}。ログと執行一致を確認"})
        elif ret < p10:
            checks.append({"name": "リターン", "flag": YELLOW,
                           "msg": f"{head}（低め{ref}。横ばい・ダマシの時期によくある水準。"
                                  f"執行コストの問題かどうかはこの項目だけでは判別できない）"})
        else:
            checks.append({"name": "リターン", "flag": GREEN,
                           "msg": f"{head}（範囲内{ref}）"})

    # --- staleness: has the system actually been updating? A running brain
    #     records equity on every decision and decides at least every 20h, so
    #     >3 days is never normal — before round-6 this could only ever be
    #     YELLOW, and a brain dead for weeks reported "観察" (I10). ---
    stale_red_d = max(1.0, daily_gap_h * 1.5 / 24.0)     # 1.5 decision cycles
    if staleness_days is not None and staleness_days > stale_red_d:
        checks.append({"name": "稼働鮮度", "flag": RED,
                       "msg": f"最終更新が{staleness_days:.1f}日前：脳（fxコンテナ）が停止している疑い → "
                              f"`docker compose ps` / `docker compose logs fx` を確認し `docker compose up -d fx`"})
    elif staleness_days is not None and staleness_days > daily_gap_h / 24.0:
        checks.append({"name": "稼働鮮度", "flag": YELLOW,
                       "msg": f"最終更新が{staleness_days:.1f}日前（週末以外なら run_ai_bridge の稼働を確認）"})

    # --- brain liveness (round-7): judge the brain by its own heartbeat, the
    #     way the EA is judged by its status file. Before this the only brain
    #     signal was the age of the newest DB row, so the 67.7-hour outage —
    #     during which the brain wrote NOTHING — was rated 🟡「観察（想定内）」. ---
    brain_dead = False
    if blocked_on_lock:
        brain_dead = True
        checks.append({"name": "脳稼働", "flag": RED,
                       "msg": f"脳がロック待ちで止まっています（取引していません）: {blocked_on_lock} → "
                              f"`docker compose ps` で二重起動を確認し、無ければ "
                              f"Common\\Files の steady_brain.lock を削除して "
                              f"`docker compose restart fx`"})
    elif brain_signal_age_s is not None and brain_signal_age_s > BRAIN_SIGNAL_STALE_S:
        brain_dead = True
        checks.append({"name": "脳稼働", "flag": RED,
                       "msg": f"脳の心拍が{brain_signal_age_s / 60:.0f}分前で止まっています "
                              f"（>{BRAIN_SIGNAL_STALE_S / 60:.0f}分）→ `docker compose logs fx` を"
                              f"確認し `docker compose restart fx`"})
    elif brain_signal_age_s is not None:
        checks.append({"name": "脳稼働", "flag": GREEN,
                       "msg": f"心拍 {brain_signal_age_s:.0f}秒前"})
    elif blocked_on_lock is None and brain_signal_age_s is None:
        checks.append({"name": "脳稼働", "flag": YELLOW,
                       "msg": "シグナルファイルが読めず脳の生存を判定できません（共有フォルダを確認）"})

    # --- bridge liveness (round-6f): a status file the EA stopped writing,
    #     a missing file, or bars the brain refuses all made 執行一致 read
    #     🟢 from frozen data while the brain was blind. ---
    bridge_stale = False
    if status_missing:
        bridge_stale = True
        checks.append({"name": "EA稼働", "flag": RED,
                       "msg": "statusファイルが読めない：EA未接続 or 共有フォルダ未マウント → MT5で"
                              "SteadyBridgeが付いているか、`docker compose ps`、MT5_COMMON_FILES を確認"})
    elif ea_status_age_s is not None and ea_status_age_s > EA_STATUS_STALE_S:
        bridge_stale = True
        checks.append({"name": "EA稼働", "flag": RED,
                       "msg": f"EAのstatusが{ea_status_age_s / 60:.0f}分前で止まっている：EA停止の疑い → "
                              f"MT5/EA/アルゴ取引ONを確認（脳は盲目→心拍停止→EXPで決済に向かう状態。"
                              f"脳のログに CRITICAL clock があれば時計ズレ → `wsl --shutdown`）"})
    elif ea_status_age_s is not None and ea_status_age_s < -300.0:
        checks.append({"name": "時計", "flag": RED,
                       "msg": f"MT5の時計がコンテナより{-ea_status_age_s:.0f}秒進んでいる：WSL2の時計ズレ → "
                              f"`wsl --shutdown` してDocker Desktopを再起動"})
    if bars_count is not None and bars_need is not None and bars_count < bars_need:
        # The brain cannot decide on fewer bars than SMA+5 and goes blind
        # (heartbeat withheld, EA flattens at EXP). A missing or short feed
        # is a documented setup hazard (terminal history not downloaded,
        # InpBars too small) and was reported 🟢 (round-6g).
        bridge_stale = True
        checks.append({"name": "バー本数", "flag": RED,
                       "msg": f"バーが{bars_count}本（{bars_need}本必要）：脳はこのフィードで判断できず盲目→"
                              f"心拍停止→EAがEXPで決済する状態 → MT5でUSDJPYのH1チャートを開いてHomeで履歴を"
                              f"遡る／EAの InpBars≥2500 を確認（docs/AI_TRADER.md）"})
    elif bars_age_h is not None and bars_age_h > (bars_limit_h or MAX_BAR_AGE_H):
        # bars_limit_h: the brain's own limit for THIS feed (longer over a
        # Christmas / New Year closure — bridge.max_bar_age_h, Round-10)
        bridge_stale = True
        checks.append({"name": "バー鮮度", "flag": RED,
                       "msg": f"バーが{bars_age_h:.0f}時間前で止まっている（>{bars_limit_h or MAX_BAR_AGE_H:.0f}h）：脳はこの"
                              f"フィードを拒否して盲目→心拍停止→EAがEXPで決済する状態 → EAの配信を確認"})

    # --- EA build: every fix that lives in the EA exists only if the chart
    #     runs the build the brain's protocol assumes (round-6). ---
    if ea_build is not None and ea_build != EA_BUILD_EXPECTED:
        checks.append({"name": "EAビルド", "flag": RED,
                       "msg": f"EAは {ea_build or '不明（旧EA：build列なし）'}、必要なのは {EA_BUILD_EXPECTED} → "
                              f"mt5_ea/SteadyBridge.mq5 を再コンパイルして付け直す"})

    # --- execution drift: live book vs the system's LAST DECISION (NOT the raw
    #     trend — the live system has an Opus veto layer, so a legitimate FLAT
    #     decision must not be mis-flagged as drift). ---
    last_decision = actions[-1].upper() if actions else None
    stale_decision = (last_decision_age_s is not None
                      and last_decision_age_s > daily_gap_h * 3600)
    if (bridge_stale or brain_dead or stale_decision) and live_position:
        # A match computed from a frozen file, or against a decision the brain
        # made days ago, is not a match — and this 🟢 is the documented
        # criterion for going live and for increasing size (round-7).
        why = ("脳が停止" if brain_dead else
               "判断が古い" if stale_decision else "ブリッジ（status/バー）が古い")
        checks.append({"name": "執行一致", "flag": YELLOW,
                       "msg": f"判定不能：{why}ため、建玉の一致は凍結した状態との一致にすぎません"})
    elif bridge_stale and live_position:
        # A match against a frozen file is not a match (round-6f).
        checks.append({"name": "執行一致", "flag": YELLOW,
                       "msg": "判定不能：ブリッジ（status/バー）が古いため、建玉の一致は凍結ファイルとの一致"})
    elif last_decision in ("LONG", "FLAT") and live_position:
        note = ""
        if trend_basis and trend_basis.upper() != last_decision:
            # Attribute the gap to the AI only when the AI actually bound that
            # decision; in shadow authority it never does, and the reachable
            # causes are a dead brain, a blind feed or a gate cooldown (round-6).
            if last_ai_binding:
                note = f"（トレンド基調={trend_basis.upper()}→Opus拒否で{last_decision}判断）"
            else:
                note = (f"（トレンド基調={trend_basis.upper()}≠判断{last_decision}：AIの拘束なし → "
                        f"判断が古い／脳停止／盲目／ゲート冷却中の疑い。稼働鮮度と `docker compose logs fx` を確認）")
        if last_decision == live_position.upper():
            checks.append({"name": "執行一致", "flag": GREEN,
                           "msg": f"システム判断={last_decision}=建玉（一致）{note}"})
        else:
            checks.append({"name": "執行一致", "flag": RED,
                           "msg": f"システムは{last_decision}を指示も建玉={live_position}"
                                  f"（執行ズレ→EAのアルゴ取引ON/エラーを確認）"})

    order = {GREEN: 0, YELLOW: 1, RED: 2}
    worst = max((c["flag"] for c in checks), key=lambda f: order[f], default=GREEN)
    verdict = {GREEN: "🟢 健全（バックテスト通りの挙動）",
               YELLOW: "🟡 観察（データ不足、または過去の端に近い項目あり。🟡の項目を確認し継続監視）",
               RED: "🔴 要対応（想定から逸脱。下のRED項目を確認）"}[worst]

    return {
        "verdict": verdict,
        "worst": worst,
        "span_days": span_days,
        "initial_balance": initial_balance,
        "current_equity": equity_values[-1] if equity_values else initial_balance,
        "stats": st,
        "ann_return_pct": ann if enough_ret else None,
        "trades_per_year": tpy if span_days >= 365 else None,   # short spans annualise wildly
        "n_position_changes": n_changes,
        "checks": checks,
    }


def span_days_between(t0, t1) -> float:
    def _dt(x):
        return x if isinstance(x, datetime) else datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return max(0.0, (_dt(t1) - _dt(t0)).total_seconds() / 86400.0)
