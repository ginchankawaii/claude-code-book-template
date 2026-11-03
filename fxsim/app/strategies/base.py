"""Strategy interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..models import Signal


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, instrument: str, df: pd.DataFrame) -> Signal:
        """Given indicator-enriched candles up to *and including* the current
        bar, return a Signal. Must not look ahead beyond the last row."""
