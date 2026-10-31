#!/usr/bin/env python3
"""Run the live paper-trading loop (real prices, simulated fills).

Requires FXSIM_PROVIDER=oanda + OANDA_API_TOKEN and the OANDA host to be
allow-listed by the environment's network policy.

Usage:
    FXSIM_PROVIDER=oanda OANDA_API_TOKEN=xxx \
        python -m scripts.run_live --instrument USD_JPY --granularity M15
"""
from __future__ import annotations

import argparse

from app.config import settings
from app.live import LiveTrader


def main() -> None:
    p = argparse.ArgumentParser(description="FX live paper trading")
    p.add_argument("--instrument", default=settings.instruments[0])
    p.add_argument("--granularity", default=settings.granularity)
    p.add_argument("--poll-seconds", type=int, default=None)
    p.add_argument("--max-iterations", type=int, default=None,
                   help="stop after N polls (handy for testing)")
    args = p.parse_args()

    settings.granularity = args.granularity
    trader = LiveTrader(args.instrument)
    trader.run(poll_seconds=args.poll_seconds, max_iterations=args.max_iterations)


if __name__ == "__main__":
    main()
