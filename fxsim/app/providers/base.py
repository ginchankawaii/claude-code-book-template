"""Provider interface for market data.

A provider returns historical candles (for backtests / warm-up) and, for live
mode, the most recent completed candle. Keeping this tiny makes it trivial to
swap OANDA for any other feed once the host is allow-listed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import Candle


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def history(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        """Return up to `count` most-recent *completed* candles, oldest first."""

    def latest(self, instrument: str, granularity: str) -> Optional[Candle]:
        bars = self.history(instrument, granularity, count=1)
        return bars[-1] if bars else None
