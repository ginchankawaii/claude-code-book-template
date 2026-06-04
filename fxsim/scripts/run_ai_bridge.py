"""AI-driven live trader on the MT5 file-bridge (Opus + web search).

Opus decides direction + leverage at KEY MOMENTS only — once a day and shortly
after each high-impact USD/JPY economic release — weighing the real macro picture
(fetched live via web search) against the technical state and current position.
Sizing is the AI's conviction x a hard max-risk cap, scaled down on drawdown.

  python -m scripts.run_ai_bridge --once --dry   # one decision, no order written
  python -m scripts.run_ai_bridge --once          # one decision now (writes signal)
  python -m scripts.run_ai_bridge                 # resident: daily + post-event

Requires: SteadyBridge EA attached in MT5 (writes status/bars, executes signals),
and ANTHROPIC_API_KEY in fxsim/.env. See docs/AI_TRADER.md.
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


def _ongoing_run(start_balance: float, model: str, max_risk: float) -> int:
    for r in db.list_runs():
        if not r.get("ended_at") and "steady-ai" in (r.get("params") or ""):
            return r["id"]
    return db.create_run(mode="live", instrument="USD_JPY", granularity="D",
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
                history_csv: str, trader: AITrader, dry: bool, trigger: str) -> bool:
    status = bridge.read_status()
    if status is None or (status.get("equity") or 0) <= 0:
        print("[ai] waiting for EA status (balance/equity). Is SteadyBridge attached & synced?",
              flush=True)
        return False
    candles = bridge.read_bars(instrument, "D")
    if len(candles) < 150 and Path(history_csv).exists():
        candles = load_csv_file(Path(history_csv), instrument, "D")
    if len(candles) < 150:
        print(f"[ai] not enough daily history ({len(candles)} bars)", flush=True)
        return False

    balance = status["balance"]; equity = status["equity"]
    ctx = build_context(instrument, candles, status)
    print(f"[ai] ({trigger}) consulting Opus... trend={ctx['technical']['trend']} "
          f"price={ctx['technical']['price']} pos={status.get('position_lots')}", flush=True)
    decision = trader.decide(ctx)

    # drawdown brake on the hard cap (capital preservation)
    run_id = _ongoing_run(balance, trader.model, max_risk)
    db.record_equity(run_id, datetime.now(timezone.utc), balance, equity,
                     ctx["technical"]["price"])
    eq_hist = [e["equity"] for e in db.load_equity(run_id)] or [equity]
    brake, _, _ = AdaptiveController(AdaptiveConfig(base_risk=1.0, min_risk=0.2)).evaluate(eq_hist, [])

    pip = pip_size(instrument)
    lots = size_lots(decision.action, decision.conviction, balance,
                     ctx["technical"]["atr"], pip, max_risk, max_lots, brake)
    action = decision.action.upper()
    if lots <= 0:
        action = "FLAT"
    direction = {"LONG": 1, "SHORT": -1, "FLAT": 0}[action]
    risk_used = round(max_risk * decision.conviction * brake, 4)

    now = datetime.now(timezone.utc)
    db.record_signal(run_id, now, instrument, "combined", direction,
                     decision.conviction * direction, decision.reason,
                     {"action": action, "conviction": decision.conviction,
                      "risk_used": risk_used, "brake": round(brake, 3),
                      "target_lots": lots, "position_lots": status.get("position_lots", 0.0),
                      "factors": decision.factors, "trigger": trigger})
    print(f"[ai] decision: {action} {lots:.2f} lots | conviction {decision.conviction:.2f} "
          f"risk {risk_used:.3f} (brake {brake:.2f}) | {decision.reason}", flush=True)
    for f in decision.factors:
        print(f"      - {f}", flush=True)
    if dry:
        print("[ai][DRY] signal NOT written", flush=True)
    else:
        bridge.write_signal(action, lots)
        print(f"[ai] wrote signal: {action} {lots:.2f}", flush=True)
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--max-risk", type=float, default=0.05)
    ap.add_argument("--max-lots", type=float, default=5.0)
    ap.add_argument("--model", default=None, help="default claude-opus-4-8")
    ap.add_argument("--history", default="data/USD_JPY_D.csv")
    ap.add_argument("--poll", type=int, default=600, help="resident poll seconds")
    ap.add_argument("--daily-gap-h", type=float, default=20.0, help="hours between daily decisions")
    ap.add_argument("--event-window-min", type=float, default=45.0,
                    help="decide within this many minutes after a high-impact release")
    ap.add_argument("--calendar-mode", default="file", help="file | anthropic (refresh schedule)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    cfg = Settings(strategy="ai", granularity="D")
    db.init_db()
    trader = AITrader(model=args.model)

    if args.once:
        decide_once(cfg, args.instrument, args.max_risk, args.max_lots, args.history,
                    trader, args.dry, trigger="manual")
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
                               args.history, trader, args.dry, trigger):
                    last_decision = _time.time()
        except Exception as exc:
            print(f"[ai] loop error: {exc}", flush=True)
        _time.sleep(args.poll)


if __name__ == "__main__":
    main()
