"""Python brain for the MT5 file-bridge (build-independent, no MT5 IPC).

Reads the bars + account status the EA exported, runs the trend + adaptive-risk
logic, writes the order signal the EA will execute, and persists everything to
SQLite for the /live dashboard.

  python -m scripts.run_bridge --once      # one cycle (Task Scheduler, daily)
  python -m scripts.run_bridge             # resident loop

Requires the SteadyBridge EA attached to a USDJPY,D1 chart in MT5 (see
docs/MT5_BRIDGE.md). Daily timeframe => acts on each new daily bar.
"""
from __future__ import annotations

import argparse
import math
import time as _time
from datetime import datetime, timezone

from app import bridge, db
from app.adaptive import AdaptiveConfig, AdaptiveController
from app.config import Settings, pip_size
from app.indicators import candles_to_df, enrich
from app.strategies.trend import TrendRegimeStrategy

UNITS_PER_LOT = 100_000.0


def _ongoing_run(cfg: Settings) -> int:
    for r in db.list_runs():
        if not r.get("ended_at") and "steady-bridge" in (r.get("params") or ""):
            return r["id"]
    return db.create_run(mode="live", instrument="USD_JPY", granularity=cfg.granularity,
                         initial_balance=cfg.initial_balance,
                         params={"system": "steady-bridge", "trend_sma": cfg.trend_sma,
                                 "base_risk": cfg.risk_per_trade})


def cycle(cfg: Settings, instrument: str, max_lots: float, dry: bool) -> bool:
    candles = bridge.read_bars(instrument, cfg.granularity)
    status = bridge.read_status()
    if not candles or status is None:
        print("[bridge] waiting for EA files (steady_bars.csv / steady_status.csv). "
              "Is the SteadyBridge EA attached to USDJPY,D1 with algo-trading on?", flush=True)
        return False

    run_id = _ongoing_run(cfg)
    df = enrich(candles_to_df(candles))
    strat = TrendRegimeStrategy(sma=cfg.trend_sma)
    sig = strat.generate(instrument, df)

    balance, equity = status["balance"], status["equity"]
    now = df.iloc[-1]["time"]
    now = now.to_pydatetime() if hasattr(now, "to_pydatetime") else now
    db.record_equity(run_id, datetime.now(timezone.utc), balance, equity,
                     float(df.iloc[-1]["close"]))

    # adaptive risk from the persisted equity history (drawdown brake)
    eq_hist = [e["equity"] for e in db.load_equity(run_id)] or [equity]
    controller = AdaptiveController(AdaptiveConfig(base_risk=cfg.risk_per_trade))
    target_risk, reason, metrics = controller.evaluate(eq_hist, [])
    adjs = db.load_adjustments(run_id)
    prev_risk = adjs[-1]["new_val"] if adjs else cfg.risk_per_trade
    if controller.changed(prev_risk, target_risk):
        db.record_adjustment(run_id, datetime.now(timezone.utc), "risk_per_trade",
                             round(prev_risk, 6), target_risk, reason, metrics)

    # position sizing (long-or-flat)
    if sig.direction > 0:
        pip = pip_size(instrument)
        atr = df.iloc[-1]["atr"]
        if math.isnan(atr):
            atr = pip * 10
        stop = max(atr * 1.5, pip * 5)
        units = (balance * target_risk) / stop
        lots = min(units / UNITS_PER_LOT, max_lots)
        lots = max(0.01, round(lots / 0.01) * 0.01)
        action = "LONG"
    else:
        lots, action = 0.0, "FLAT"

    db.record_signal(run_id, now, instrument, "combined",
                     sig.direction, sig.score, sig.reason, sig.components)
    if dry:
        print(f"[bridge][DRY] {action} {lots:.2f} lots (risk {target_risk:.4f}) — signal NOT written")
    else:
        bridge.write_signal(action, lots)
        print(f"[bridge] wrote signal: {action} {lots:.2f} lots | eq={equity:,.0f} "
              f"risk={target_risk:.4f} | {sig.reason}", flush=True)
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--sma", type=int, default=150)
    ap.add_argument("--risk", type=float, default=0.03)
    ap.add_argument("--balance", type=float, default=100000)
    ap.add_argument("--max-lots", type=float, default=5.0)
    ap.add_argument("--poll", type=int, default=60)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true", help="compute but do NOT write the signal file")
    args = ap.parse_args()

    cfg = Settings(strategy="trend", granularity="D", trend_sma=args.sma,
                   risk_per_trade=args.risk, use_take_profit=False,
                   initial_balance=args.balance)
    db.init_db()
    if args.once:
        cycle(cfg, args.instrument, args.max_lots, args.dry)
    else:
        print(f"[bridge] resident (poll {args.poll}s). Common files: {bridge.common_files_dir()}",
              flush=True)
        while True:
            try:
                cycle(cfg, args.instrument, args.max_lots, args.dry)
            except Exception as exc:
                print(f"[bridge] error: {exc}", flush=True)
            _time.sleep(args.poll)


if __name__ == "__main__":
    main()
