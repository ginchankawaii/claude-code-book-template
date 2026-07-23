"""PDCA monitor — is the LIVE run behaving like the BACKTEST said it would?

Compares the live FX run's realized stats against the validated expectation
envelope (H1 / SMA2400 / 5x / long-only — docs/RESEARCH.md, research_run8) and
flags four failure modes early:

  * DRAWDOWN BREACH   — live max drawdown exceeds the backtest's ~34% → the edge
                        may be breaking (or just a deep-but-normal DD; investigate).
  * OVERTRADING       — far more position changes than the ~20/year expected →
                        something is whipsawing (wrong bars, bug, regime).
  * EXECUTION DRIFT   — the strategy says LONG/FLAT but the live book disagrees →
                        EA/bridge problem or slippage.
  * INSUFFICIENT DATA — too few days to judge yet (most of the early life).

Pure functions here (no DB / no network) so they're unit-tested; the
scripts/run_monitor.py CLI feeds them data from the DB + the live bar feed.
"""
from __future__ import annotations

from datetime import datetime

# Backtest expectation for the shipped FX recipe (research_run8, 2015-2026).
EXP_CAGR_PCT = 12.4
EXP_MAXDD_PCT = 34.0
EXP_TRADES_PER_YEAR = 20.0
EXP_TIME_IN_MARKET = 0.55

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
                 staleness_days: float | None = None) -> dict:
    """Assemble the health report + per-check flags + an overall verdict."""
    st = equity_stats(equity_values)
    years = max(span_days, 0.0) / 365.25
    checks: list[dict] = []

    # --- data sufficiency ---
    enough_dd = span_days >= MIN_DAYS_FOR_DD
    enough_ret = span_days >= MIN_DAYS_FOR_RETURN

    # --- drawdown vs the ~34% envelope ---
    mdd = st["max_dd_pct"]
    if not enough_dd:
        checks.append({"name": "ドローダウン", "flag": YELLOW,
                       "msg": f"最大DD {mdd:.1f}%（観察{span_days:.0f}日・判定はもう少し先）"})
    elif mdd > EXP_MAXDD_PCT:
        checks.append({"name": "ドローダウン", "flag": RED,
                       "msg": f"最大DD {mdd:.1f}% が想定{EXP_MAXDD_PCT:.0f}%を超過。エッジ劣化の疑い → 要確認"})
    elif mdd > EXP_MAXDD_PCT * 0.75:
        checks.append({"name": "ドローダウン", "flag": YELLOW,
                       "msg": f"最大DD {mdd:.1f}%（想定{EXP_MAXDD_PCT:.0f}%内だが深い）"})
    else:
        checks.append({"name": "ドローダウン", "flag": GREEN,
                       "msg": f"最大DD {mdd:.1f}%（想定{EXP_MAXDD_PCT:.0f}%内）"})

    # --- trade frequency vs ~20/year ---
    n_changes = count_position_changes(actions)
    tpy = n_changes / years if years > 0 else 0.0
    if span_days < 30:
        checks.append({"name": "取引頻度", "flag": YELLOW,
                       "msg": f"建玉変化 {n_changes}回（観察期間が短く判定保留）"})
    elif tpy > EXP_TRADES_PER_YEAR * 3:
        checks.append({"name": "取引頻度", "flag": RED,
                       "msg": f"年率換算 {tpy:.0f}回/年 ≫ 想定{EXP_TRADES_PER_YEAR:.0f}回。過剰売買=ダマシ/不具合の疑い"})
    elif tpy > EXP_TRADES_PER_YEAR * 1.8:
        checks.append({"name": "取引頻度", "flag": YELLOW,
                       "msg": f"年率換算 {tpy:.0f}回/年（想定{EXP_TRADES_PER_YEAR:.0f}回よりやや多い）"})
    else:
        checks.append({"name": "取引頻度", "flag": GREEN,
                       "msg": f"年率換算 {tpy:.0f}回/年（想定{EXP_TRADES_PER_YEAR:.0f}回前後）"})

    # --- realized return vs ~12% CAGR (only once there's enough history) ---
    ann = annualize(st["return_pct"], years)
    if not enough_ret:
        checks.append({"name": "リターン", "flag": YELLOW,
                       "msg": f"累計 {st['return_pct']:+.1f}%（観察{span_days:.0f}日・年率判定は60日以降）"})
    elif ann < -10:
        checks.append({"name": "リターン", "flag": RED,
                       "msg": f"年率換算 {ann:+.1f}%（想定+{EXP_CAGR_PCT:.0f}%に対し持続的マイナス → 要確認）"})
    elif ann < EXP_CAGR_PCT * 0.3:
        checks.append({"name": "リターン", "flag": YELLOW,
                       "msg": f"年率換算 {ann:+.1f}%（想定+{EXP_CAGR_PCT:.0f}%を下回る・レンジ期かも）"})
    else:
        checks.append({"name": "リターン", "flag": GREEN,
                       "msg": f"年率換算 {ann:+.1f}%（想定+{EXP_CAGR_PCT:.0f}%圏）"})

    # --- staleness: has the system actually been updating? ---
    if staleness_days is not None and staleness_days > 1.5:
        checks.append({"name": "稼働鮮度", "flag": YELLOW,
                       "msg": f"最終更新が{staleness_days:.1f}日前（週末以外なら run_ai_bridge の稼働を確認）"})

    # --- execution drift: live book vs the system's LAST DECISION (NOT the raw
    #     trend — the live system has an Opus veto layer, so a legitimate FLAT
    #     decision must not be mis-flagged as drift). ---
    last_decision = actions[-1].upper() if actions else None
    if last_decision in ("LONG", "FLAT") and live_position:
        note = ""
        if trend_basis and trend_basis.upper() != last_decision:
            note = f"（トレンド基調={trend_basis.upper()}→Opus等で{last_decision}判断）"
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
               YELLOW: "🟡 観察（想定内 or データ不足。継続監視）",
               RED: "🔴 要対応（想定から逸脱。下のRED項目を確認）"}[worst]

    return {
        "verdict": verdict,
        "worst": worst,
        "span_days": span_days,
        "initial_balance": initial_balance,
        "current_equity": equity_values[-1] if equity_values else initial_balance,
        "stats": st,
        "ann_return_pct": ann if enough_ret else None,
        "trades_per_year": tpy if span_days >= 30 else None,
        "n_position_changes": n_changes,
        "checks": checks,
    }


def span_days_between(t0, t1) -> float:
    def _dt(x):
        return x if isinstance(x, datetime) else datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return max(0.0, (_dt(t1) - _dt(t0)).total_seconds() / 86400.0)
