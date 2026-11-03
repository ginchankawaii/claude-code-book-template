"""Trend-regime strategy — the one edge that survived honest OOS testing.

Finding from scripts/research_*.py on 55y of daily USD/JPY:
  * Mean-reversion (RSI/Bollinger) loses out-of-sample.
  * High-frequency mechanical trading dies to costs.
  * A simple long-biased trend filter — be long only while price is above its
    long moving average, otherwise STAND ASIDE — matches or beats buy&hold on
    risk-adjusted return while roughly halving drawdown and market exposure, and
    is robust to spread costs (it trades rarely).

Shorting the downtrends does NOT help (USD/JPY carries a structural long bias),
so this is long-or-flat. It is deliberately low-parameter to avoid overfitting:
one moving-average length, nothing tuned per period.
"""
from __future__ import annotations

import pandas as pd

from ..models import Signal
from .base import Strategy


class TrendRegimeStrategy(Strategy):
    name = "trend"

    def __init__(self, sma: int = 200, conviction: float = 0.6) -> None:
        self.sma = sma
        self.conviction = conviction
        # persistence-compat attributes (mirrors other strategies)
        self.w_tech = 1.0
        self.w_fund = 0.0
        self.last_technical: Signal = Signal.flat()
        self.last_fundamental: Signal = Signal.flat()

    def generate(self, instrument: str, df: pd.DataFrame) -> Signal:
        if len(df) < self.sma:
            sig = Signal.flat(f"warmup (<{self.sma} bars)")
        else:
            close = df["close"]
            ma = float(close.iloc[-self.sma:].mean())
            price = float(close.iloc[-1])
            dist = (price - ma) / ma
            if price > ma:
                sig = Signal(1, self.conviction,
                             f"trend-up: close {price:.3f} > SMA{self.sma} {ma:.3f} ({dist:+.2%})")
            else:
                sig = Signal.flat(
                    f"trend-down/flat: close {price:.3f} < SMA{self.sma} {ma:.3f} ({dist:+.2%})")
        self.last_technical = sig
        self.last_fundamental = Signal.flat()
        return sig
