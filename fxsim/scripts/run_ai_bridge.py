"""Live trader on the MT5 file-bridge: validated trend edge + Opus overlay.

The DECISION is the OOS-validated long-or-flat trend filter (be long only while
price > its long SMA, else stand aside — docs/RESEARCH.md). Opus is consulted at
the KEY MOMENTS only (once a day and shortly after each high-impact USD/JPY
release) as a RISK-FIRST GATE: when the trend says long, Opus can confirm and
size the conviction, or VETO it (stand aside) — it never shorts and never opens
a long the trend filter doesn't already justify. With no API key the trend edge
runs on its own (Opus simply can't veto). Sizing = conviction x hard max-risk x
a conviction-scaled leverage cap (<=5x: full when price is well above the SMA,
eased toward the floor near it — app/sizing.py, docs/RESEARCH.md), scaled down
on drawdown.

  python -m scripts.run_ai_bridge --once --dry   # one decision, no order written
  python -m scripts.run_ai_bridge --once          # one decision now (writes signal)
  python -m scripts.run_ai_bridge                 # resident: daily + post-event

Default timeframe is H1 / SMA2400 (~100-day filter — the best OOS recipe,
docs/RESEARCH.md). The SteadyBridge EA must publish H1 bars (InpTimeframe=PERIOD_H1,
InpBars>=2405); see docs/AI_TRADER.md. To fall back to daily: `--granularity D --sma 90`.

Requires: SteadyBridge EA attached in MT5 (writes status/bars, executes signals).
ANTHROPIC_API_KEY in fxsim/.env enables the Opus veto; without it the trend edge
still trades. See docs/AI_TRADER.md.
"""
from __future__ import annotations

import argparse
import math
import time as _time
from datetime import datetime, timezone
from pathlib import Path

from app import bridge, db
from app.adaptive import AdaptiveConfig, AdaptiveController
from app.ai_trader import AITrader, size_lots
from app.config import Settings, pip_size
from app.events import get_calendar
from app.indicators import candles_to_df, enrich
from app.providers.csv import load_csv_file
from app.sizing import conviction_leverage


def _ongoing_run(start_balance: float, model: str, max_risk: float,
                 granularity: str = "H1") -> int:
    for r in db.list_runs():
        if not r.get("ended_at") and "steady-ai" in (r.get("params") or ""):
            return r["id"]
    return db.create_run(mode="live", instrument="USD_JPY", granularity=granularity,
                         initial_balance=start_balance,
                         params={"system": "steady-ai", "model": model, "max_risk": max_risk})


def build_context(instrument: str, candles, status: dict) -> dict:
    df = enrich(candles_to_df(candles))
    last = df.iloc[-1]
    closes = df["close"]
    sma150 = float(closes.iloc[-150:].mean())
    sma50 = float(closes.iloc[-50:].mean())
    price = float(last["close"])
    atr = float(last["atr"]) if not math.isnan(last["atr"]) else price * 0.005
    rsi = float(last["rsi"]) if not math.isnan(last["rsi"]) else 50.0
    mom20 = (price / float(closes.iloc[-21]) - 1) * 100 if len(closes) > 21 else 0.0
    mom60 = (price / float(closes.iloc[-61]) - 1) * 100 if len(closes) > 61 else 0.0
    return {
        "instrument": instrument,
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "technical": {
            "price": round(price, 3),
            "sma150": round(sma150, 3),
            "dist_from_sma150_pct": round((price / sma150 - 1) * 100, 2),
            "sma50": round(sma50, 3),
            "rsi14": round(rsi, 1),
            "atr": round(atr, 3),
            "momentum_20d_pct": round(mom20, 2),
            "momentum_60d_pct": round(mom60, 2),
            "trend": "up" if price > sma150 else "down",
        },
        "account": {
            "balance": status.get("balance"),
            "equity": status.get("equity"),
            "current_position_lots": status.get("position_lots", 0.0),
        },
    }


def decide_once(cfg: Settings, instrument: str, max_risk: float, max_lots: float,
                history_csv: str, trader: AITrader, dry: bool, trigger: str,
                granularity: str = "D", sma_n: int = 90) -> bool:
    status = bridge.read_status()
    if status is None or (status.get("equity") or 0) <= 0:
        print("[ai] waiting for EA status (balance/equity). Is SteadyBridge attached & synced?",
              flush=True)
        return False
    need = sma_n + 5
    candles = bridge.read_bars(instrument, granularity)
    if len(candles) < need and Path(history_csv).exists():
        candles = load_csv_file(Path(history_csv), instrument, granularity)
    if len(candles) < need:
        print(f"[ai] not enough {granularity} history ({len(candles)} bars, need {need})", flush=True)
        return False

    balance = status["balance"]; equity = status["equity"]
    ctx = build_context(instrument, candles, status)
    # VALIDATED EDGE: long only while price > long SMA, else stand aside.
    closes = enrich(candles_to_df(candles))["close"]
    price = float(closes.iloc[-1]); ma = float(closes.iloc[-sma_n:].mean())
    trend_up = price > ma
    trend_txt = f"price {price:.3f} {'>' if trend_up else '<'} SMA{sma_n} {ma:.3f}"

    factors: list = []; plan = ""
    if not trend_up:
        # Below the trend filter -> flat. No Opus call needed (edge stands aside).
        action, conviction, reason = "FLAT", 0.0, f"trend-down: {trend_txt} -> stand aside"
        print(f"[ai] ({trigger}) {reason}", flush=True)
    else:
        # Trend says long. Opus is a veto/sizing gate at the key moments.
        print(f"[ai] ({trigger}) trend-up ({trend_txt}); consulting Opus... "
              f"pos={status.get('position_lots')}", flush=True)
        decision = trader.decide(ctx)
        if not decision.ok:
            # No key / API error: the deterministic trend edge still says LONG.
            action, conviction, reason = "LONG", 0.6, f"trend-up; Opus unavailable ({decision.reason})"
        elif decision.action == "long":
            action, conviction, reason = "LONG", decision.conviction, decision.reason
            factors, plan = decision.factors, decision.plan
        else:
            # Opus veto (short or flat) -> stand aside. Never short.
            action, conviction, reason = "FLAT", 0.0, f"trend-up but Opus veto ({decision.action}): {decision.reason}"
            factors = decision.factors

    # drawdown brake on the hard cap (capital preservation)
    run_id = _ongoing_run(balance, trader.model, max_risk, granularity)
    db.record_equity(run_id, datetime.now(timezone.utc), balance, equity, price)
    eq_hist = [e["equity"] for e in db.load_equity(run_id)] or [equity]
    brake, _, _ = AdaptiveController(AdaptiveConfig(base_risk=1.0, min_risk=0.2)).evaluate(eq_hist, [])

    # Conviction-scaled leverage: within the same hard 5x cap, pull exposure down
    # toward the floor when price is near the SMA (whipsaw zone), full cap when the
    # trend is well established. Matches the backtest engine (docs/RESEARCH.md).
    atr_now = ctx["technical"]["atr"]
    eff_leverage = cfg.max_leverage
    if action == "LONG" and getattr(cfg, "dyn_leverage", False):
        eff_leverage = conviction_leverage(price, ma, atr_now, cfg.max_leverage,
                                           cfg.dyn_lev_atr_mult, cfg.dyn_lev_floor)
    pip = pip_size(instrument)
    lots = size_lots("long" if action == "LONG" else "flat", conviction, balance,
                     atr_now, pip, max_risk, max_lots, brake,
                     price=price, max_leverage=eff_leverage)
    if lots <= 0:
        action = "FLAT"
    direction = 1 if action == "LONG" else 0   # long-or-flat; never short
    risk_used = round(max_risk * conviction * brake, 4)

    now = datetime.now(timezone.utc)
    db.record_signal(run_id, now, instrument, "combined", direction,
                     conviction * direction, reason,
                     {"action": action, "conviction": conviction, "trend_up": trend_up,
                      "risk_used": risk_used, "brake": round(brake, 3),
                      "eff_leverage": round(eff_leverage, 2),
                      "target_lots": lots, "position_lots": status.get("position_lots", 0.0),
                      "factors": factors, "plan": plan, "trigger": trigger})
    print(f"[ai] decision: {action} {lots:.2f} lots | conviction {conviction:.2f} "
          f"risk {risk_used:.3f} (brake {brake:.2f}) lev {eff_leverage:.1f}x | {reason}", flush=True)
    for f in factors:
        print(f"      - {f}", flush=True)
    if plan:
        print(f"      ↳ 保有方針: {plan}", flush=True)
    if dry:
        print("[ai][DRY] signal NOT written", flush=True)
    else:
        bridge.write_signal(action, lots)
        print(f"[ai] wrote signal: {action} {lots:.2f}", flush=True)
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--max-risk", type=float, default=0.04)
    ap.add_argument("--max-lots", type=float, default=5.0)
    ap.add_argument("--granularity", default="H1", help="bars the EA publishes (H1 = best; D also ok)")
    ap.add_argument("--sma", type=int, default=2400, help="trend-filter SMA (H1 2400; daily 90)")
    ap.add_argument("--model", default=None, help="default claude-opus-4-8")
    ap.add_argument("--history", default="data/USD_JPY_H1.csv",
                    help="warmup/fallback history matching --granularity")
    ap.add_argument("--poll", type=int, default=600, help="resident poll seconds")
    ap.add_argument("--daily-gap-h", type=float, default=20.0, help="hours between daily decisions")
    ap.add_argument("--event-window-min", type=float, default=45.0,
                    help="decide within this many minutes after a high-impact release")
    ap.add_argument("--calendar-mode", default="file", help="file | anthropic (refresh schedule)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    cfg = Settings(strategy="ai", granularity=args.granularity)
    db.init_db()
    trader = AITrader(model=args.model)

    if args.once:
        decide_once(cfg, args.instrument, args.max_risk, args.max_lots, args.history,
                    trader, args.dry, trigger="manual",
                    granularity=args.granularity, sma_n=args.sma)
        return

    print(f"[ai] resident. model={trader.model} max_risk={args.max_risk} "
          f"daily_gap={args.daily_gap_h}h event_window={args.event_window_min}m", flush=True)
    last_decision = 0.0
    acted_events: set[str] = set()
    cal = get_calendar(args.calendar_mode, args.instrument)
    cal_day = datetime.now(timezone.utc).date()

    while True:
        try:
            now = datetime.now(timezone.utc)
            # refresh the event schedule once a day
            if now.date() != cal_day:
                cal = get_calendar(args.calendar_mode, args.instrument)
                cal_day = now.date(); acted_events.clear()

            trigger = None
            if (_time.time() - last_decision) >= args.daily_gap_h * 3600:
                trigger = "daily"
            else:
                for e in cal.for_instrument(args.instrument):
                    if not e.is_high:
                        continue
                    mins = -e.minutes_until(now)   # minutes SINCE release
                    key = f"{e.time.isoformat()}|{e.title}"
                    if 0 <= mins <= args.event_window_min and key not in acted_events:
                        trigger = f"event:{e.title}"; acted_events.add(key); break

            if trigger:
                if decide_once(cfg, args.instrument, args.max_risk, args.max_lots,
                               args.history, trader, args.dry, trigger,
                               granularity=args.granularity, sma_n=args.sma):
                    last_decision = _time.time()
        except Exception as exc:
            print(f"[ai] loop error: {exc}", flush=True)
        _time.sleep(args.poll)


if __name__ == "__main__":
    main()
