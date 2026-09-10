#!/usr/bin/env python3
"""Run a backtest and print performance stats.

Usage:
    python -m scripts.run_backtest --instrument USD_JPY --bars 1500
    python -m scripts.run_backtest --provider oanda --instrument EUR_USD --bars 2000
"""
from __future__ import annotations

import argparse
import json

from app.backtest import run_backtest, stats_dict
from app.config import settings
from app.providers import get_provider


def main() -> None:
    p = argparse.ArgumentParser(description="FX backtest")
    p.add_argument("--instrument", default=settings.instruments[0])
    p.add_argument("--granularity", default=settings.granularity)
    p.add_argument("--bars", type=int, default=1500)
    p.add_argument("--provider", default=settings.data_provider,
                   choices=["sample", "oanda", "csv"])
    p.add_argument("--no-persist", action="store_true")
    args = p.parse_args()

    settings.granularity = args.granularity
    settings.data_provider = args.provider
    provider = get_provider(args.provider)
    print(f"Fetching {args.bars} {args.granularity} candles for {args.instrument} "
          f"from {provider.name} ...")
    candles = provider.history(args.instrument, args.granularity, args.bars)
    print(f"Got {len(candles)} candles. Running backtest ...\n")

    stats = run_backtest(candles, args.instrument, persist=not args.no_persist)
    print(json.dumps(stats_dict(stats), indent=2, default=str))
    print("\nView the dashboard with:  python -m app.server   (http://localhost:8000)")


if __name__ == "__main__":
    main()
