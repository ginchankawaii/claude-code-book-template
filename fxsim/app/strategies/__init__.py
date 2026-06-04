from __future__ import annotations

from ..config import Settings, settings
from .ai import AIDecisionStrategy
from .base import Strategy
from .combined import CombinedStrategy
from .fundamental import FundamentalStrategy
from .technical import TechnicalStrategy
from .trend import TrendRegimeStrategy

__all__ = [
    "Strategy",
    "TechnicalStrategy",
    "FundamentalStrategy",
    "CombinedStrategy",
    "AIDecisionStrategy",
    "TrendRegimeStrategy",
    "build_strategy",
]


def build_strategy(cfg: Settings | None = None) -> Strategy:
    """Construct the active strategy.

    Selected by ``FXSIM_STRATEGY``:
      * "trend" — daily long-biased trend-regime filter (the OOS-validated edge;
        pair with FXSIM_USE_TAKE_PROFIT=0 so winners run).
      * "ai"    — event-aware AI decision layer (rule / hybrid / anthropic).
      * "combined" / "off" — plain mechanical technical+fundamental blend.
    """
    cfg = cfg or settings
    name = (cfg.strategy or "ai").lower()
    if name == "trend":
        return TrendRegimeStrategy(sma=cfg.trend_sma)
    if name in ("combined", "off", "none"):
        return CombinedStrategy()
    if (cfg.decision_mode or "").lower() in ("", "off", "none"):
        return CombinedStrategy()
    return AIDecisionStrategy(cfg=cfg)
