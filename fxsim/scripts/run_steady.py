"""Launch the SteadyTrader on historical data (replay) -> writes to SQLite.

  python -m scripts.run_steady --data data/USD_JPY_D.csv --since 2010
  python -m scripts.run_steady --pace 0.02        # paced replay for a live feel

Then watch it on the dashboard:  python -m app.server  (http://localhost:8000)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from app.adaptive import AdaptiveConfig
from app.config import Settings
from app.providers.csv import load_csv_file
from app.steady import SteadyTrader


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/USD_JPY_D.csv")
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--granularity", default="D")
    ap.add_argument("--since", type=int, default=None)
    ap.add_argument("--sma", type=int, default=150)
    ap.add_argument("--risk", type=float, default=0.01)
    ap.add_argument("--pace", type=float, default=0.0, help="seconds to sleep per bar")
    args = ap.parse_args()

    candles = load_csv_file(Path(args.data), args.instrument, args.granularity)
    if args.since:
        cut = datetime(args.since, 1, 1, tzinfo=timezone.utc)
        candles = [c for c in candles if c.time >= cut]

    cfg = Settings(strategy="trend", granularity=args.granularity, trend_sma=args.sma,
                   risk_per_trade=args.risk, use_take_profit=False, initial_balance=100000)
    trader = SteadyTrader(args.instrument, candles, cfg=cfg,
                          adaptive=AdaptiveConfig(base_risk=args.risk))
    print(f"[steady] run #{trader.run_id} starting: {len(candles)} bars, "
          f"SMA{args.sma}, base risk {args.risk:.2%}")
    rid = trader.run(step_sleep=args.pace, log_every=max(1, len(candles)//20))
    print(f"[steady] done. run_id={rid}. View: python -m app.server")


if __name__ == "__main__":
    main()
