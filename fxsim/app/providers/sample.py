"""Synthetic data provider for fully-offline backtests and demos.

Generates a deterministic, trend + mean-reversion + noise price path so the
dashboard and strategies have realistic-looking data to work with while the
real OANDA host is not yet allow-listed. Seeded => reproducible.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from ..config import pip_size
from ..models import Candle
from .base import DataProvider

_GRAN_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D": 1440,
}


class SampleProvider(DataProvider):
    name = "sample"

    def __init__(self, seed: int = 7, start_price: float | None = None) -> None:
        self.seed = seed
        self.start_price = start_price

    def history(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        rng = random.Random(self.seed + hash(instrument) % 10_000)
        minutes = _GRAN_MINUTES.get(granularity, 15)
        psize = pip_size(instrument)
        price = self.start_price or (150.0 if instrument.endswith("JPY") else 1.10)

        # build several macro "regimes" so trends and reversals both appear
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = end - timedelta(minutes=minutes * count)
        candles: list[Candle] = []
        regime_len = max(40, count // 8)
        drift = rng.uniform(-1, 1) * psize * 0.05
        vol = psize * rng.uniform(1.5, 3.0)

        t = start
        for i in range(count):
            if i % regime_len == 0:
                drift = rng.uniform(-1, 1) * psize * 0.08
                vol = psize * rng.uniform(1.2, 3.5)
            # mean reversion toward a slow-moving anchor + drift + noise
            cycle = math.sin(i / 60.0) * psize * 2.0
            shock = rng.gauss(0, 1) * vol
            o = price
            price = max(psize * 10, price + drift + 0.02 * cycle + shock)
            c = price
            hi = max(o, c) + abs(rng.gauss(0, 1)) * vol * 0.4
            lo = min(o, c) - abs(rng.gauss(0, 1)) * vol * 0.4
            candles.append(
                Candle(
                    instrument=instrument,
                    granularity=granularity,
                    time=t,
                    open=round(o, 5),
                    high=round(hi, 5),
                    low=round(lo, 5),
                    close=round(c, 5),
                    volume=rng.randint(200, 2000),
                )
            )
            t += timedelta(minutes=minutes)
        return candles[-count:]
