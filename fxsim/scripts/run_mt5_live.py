"""Full-auto live trading on MT5 (OANDA証券 MT5 demo first, then live).

WINDOWS ONLY. Requires a running MT5 terminal + `pip install MetaTrader5`.
See docs/MT5_SETUP.md for the full setup.

Examples:
  # dry-run (no orders sent) — confirms data + decisions on your demo terminal
  python -m scripts.run_mt5_live --once

  # send REAL orders to the connected (demo!) account, resident
  python -m scripts.run_mt5_live --live

Credentials: if the MT5 terminal is already logged in, none are needed. Else set
MT5_LOGIN / MT5_PASSWORD / MT5_SERVER (and optionally MT5_PATH) in the env/.env.
"""
from __future__ import annotations

import argparse
import os

from app.brokers import MT5Broker
from app.config import Settings
from app.mt5_live import MT5LiveTrader


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--granularity", default="D")
    ap.add_argument("--sma", type=int, default=150)
    ap.add_argument("--risk", type=float, default=0.03)
    ap.add_argument("--balance", type=float, default=100000)
    ap.add_argument("--max-lots", type=float, default=5.0)
    ap.add_argument("--poll", type=int, default=None)
    ap.add_argument("--live", action="store_true", help="send REAL orders (default: dry-run)")
    ap.add_argument("--once", action="store_true", help="check once and exit (cron)")
    args = ap.parse_args()

    cfg = Settings(strategy="trend", granularity=args.granularity, trend_sma=args.sma,
                   risk_per_trade=args.risk, use_take_profit=False,
                   initial_balance=args.balance, max_position_units=10_000_000)
    broker = MT5Broker(
        instrument=args.instrument,
        login=int(os.getenv("MT5_LOGIN")) if os.getenv("MT5_LOGIN") else None,
        password=os.getenv("MT5_PASSWORD") or None,
        server=os.getenv("MT5_SERVER") or None,
        terminal_path=os.getenv("MT5_PATH") or None,
        dry_run=not args.live,
        max_lots=args.max_lots,
    )
    trader = MT5LiveTrader(args.instrument, broker, cfg=cfg)

    if args.once:
        broker.connect()
        try:
            acted = trader.poll_once()
            print(f"[mt5-live] one-shot: {'acted' if acted else 'no new bar'}")
        finally:
            import app.db as db
            db.finish_run(trader.run_id); broker.shutdown()
    else:
        trader.run(poll_seconds=args.poll)


if __name__ == "__main__":
    main()
