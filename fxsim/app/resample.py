"""Resample candles to a coarser granularity (e.g. M1 -> M15).

HistData and most free intraday feeds ship 1-minute bars. Backtesting an
LLM-in-the-loop strategy on M1 is needlessly expensive (one decision per
minute); aggregating to M15 keeps the same price information at 1/15th the bar
count. Aggregation is the standard OHLCV roll-up, bucketed to wall-clock
boundaries in UTC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import Candle

_GRAN_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D": 1440,
}


def granularity_minutes(granularity: str) -> int:
    return _GRAN_MINUTES.get(granularity.upper(), 15)


def _floor(t: datetime, minutes: int) -> datetime:
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    if minutes >= 1440:
        return t.replace(hour=0, minute=0, second=0, microsecond=0)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    n = int((t - epoch).total_seconds() // (minutes * 60))
    return epoch + timedelta(minutes=minutes * n)


def resample(candles: list[Candle], target: str, instrument: str | None = None) -> list[Candle]:
    """Aggregate finer candles into `target` granularity (OHLCV roll-up)."""
    if not candles:
        return []
    minutes = granularity_minutes(target)
    instrument = instrument or candles[0].instrument
    candles = sorted(candles, key=lambda c: c.time)

    out: list[Candle] = []
    bucket: list[Candle] = []
    cur: datetime | None = None
    for c in candles:
        b = _floor(c.time, minutes)
        if cur is None or b != cur:
            if bucket:
                out.append(_merge(bucket, instrument, target, cur))
            bucket, cur = [c], b
        else:
            bucket.append(c)
    if bucket:
        out.append(_merge(bucket, instrument, target, cur))
    return out


def _merge(bucket: list[Candle], instrument: str, granularity: str, t: datetime) -> Candle:
    return Candle(
        instrument=instrument,
        granularity=granularity,
        time=t,
        open=bucket[0].open,
        high=max(c.high for c in bucket),
        low=min(c.low for c in bucket),
        close=bucket[-1].close,
        volume=sum(c.volume for c in bucket),
    )
