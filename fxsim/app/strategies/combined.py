"""Combined strategy: weighted blend of technical + fundamental conviction.

The blended score drives entries/exits in the engine. Both sub-signals are
recorded separately so the dashboard can show their individual contribution.
"""
from __future__ import annotations

import pandas as pd

from ..config import settings
from ..models import Signal
from .base import Strategy
from .fundamental import FundamentalStrategy
from .technical import TechnicalStrategy


class CombinedStrategy(Strategy):
    name = "combined"

    def __init__(
        self,
        technical_weight: float | None = None,
        fundamental_weight: float | None = None,
        fundamental_mode: str | None = None,
    ) -> None:
        self.technical = TechnicalStrategy()
        self.fundamental = FundamentalStrategy(fundamental_mode)
        self.w_tech = (
            technical_weight if technical_weight is not None else settings.technical_weight
        )
        self.w_fund = (
            fundamental_weight if fundamental_weight is not None else settings.fundamental_weight
        )
        # last sub-signals, exposed for persistence by the engine
        self.last_technical: Signal = Signal.flat()
        self.last_fundamental: Signal = Signal.flat()

    def generate(self, instrument: str, df: pd.DataFrame) -> Signal:
        tech = self.technical.generate(instrument, df)
        fund = self.fundamental.generate(instrument, df)
        self.last_technical = tech
        self.last_fundamental = fund

        # A neutral fundamental view (no current news) should not dilute the
        # technical conviction, so it only contributes weight when it has a
        # non-trivial opinion.
        w_fund = self.w_fund if abs(fund.score) >= 1e-6 else 0.0
        total_w = self.w_tech + w_fund or 1.0
        score = (tech.score * self.w_tech + fund.score * w_fund) / total_w
        score = float(max(-1.0, min(1.0, score)))
        direction = 1 if score > 0 else (-1 if score < 0 else 0)
        reason = (
            f"tech({self.w_tech:.0%})={tech.score:+.2f} | "
            f"fund({self.w_fund:.0%})={fund.score:+.2f}"
        )
        return Signal(
            direction=direction,
            score=score,
            reason=reason,
            components={
                "technical": tech.score,
                "fundamental": fund.score,
                "w_tech": self.w_tech,
                "w_fund": self.w_fund,
            },
        )
