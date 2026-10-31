"""Fundamental strategy wrapper around the news analyzer.

To keep backtests cheap and deterministic the view is fetched lazily and
cached per-instrument; live runs can refresh it on a schedule.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from ..fundamental import FundamentalView, get_analyzer
from ..models import Signal
from .base import Strategy


class FundamentalStrategy(Strategy):
    name = "fundamental"

    def __init__(self, mode: str | None = None) -> None:
        self.analyzer = get_analyzer(mode)
        self._cache: dict[str, FundamentalView] = {}

    def refresh(self, instrument: str) -> FundamentalView:
        view = self.analyzer.view(instrument)
        self._cache[instrument] = view
        return view

    def generate(self, instrument: str, df: pd.DataFrame) -> Signal:
        view = self._cache.get(instrument)
        if view is None:
            view = self.refresh(instrument)

        now = df.iloc[-1]["time"] if len(df) else datetime.utcnow()
        if hasattr(now, "to_pydatetime"):
            now = now.to_pydatetime()
        score = view.decayed_bias(now)
        direction = 1 if score > 0.05 else (-1 if score < -0.05 else 0)
        return Signal(
            direction=direction,
            score=score,
            reason=view.reason or "fundamental",
            components={"raw_bias": view.bias, "decayed": score},
        )
