"""Lightweight domain types shared across the engine, strategies and storage."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Candle:
    instrument: str
    granularity: str
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def epoch(self) -> int:
        return int(self.time.replace(tzinfo=self.time.tzinfo or timezone.utc).timestamp())


@dataclass
class Signal:
    """A directional view for one instrument at one point in time.

    direction: -1 short, 0 flat, +1 long
    score:     continuous conviction in [-1, 1] (sign matches direction)
    """

    direction: int
    score: float
    reason: str = ""
    components: dict = field(default_factory=dict)

    @classmethod
    def flat(cls, reason: str = "") -> "Signal":
        return cls(direction=0, score=0.0, reason=reason)


@dataclass
class Position:
    instrument: str
    units: int  # signed: +long / -short
    entry_price: float
    entry_time: datetime
    trade_id: Optional[int] = None

    @property
    def side(self) -> str:
        return "LONG" if self.units > 0 else "SHORT"

    def unrealized_pnl(self, price: float, quote_to_acct: float = 1.0) -> float:
        """P&L in account currency. quote_to_acct converts quote currency to
        account currency (1.0 when the account is denominated in the quote
        currency, which is our default assumption for a single-pair sim)."""
        return self.units * (price - self.entry_price) * quote_to_acct


@dataclass
class TradeResult:
    instrument: str
    side: str
    units: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    pnl: float
    reason: str
