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
      * "ai"    — DEFAULT. Event-aware decision layer whose technical base is the
        validated trend filter (FXSIM_AI_BASE=trend), with the hybrid decider so
        Opus only weighs in at the key moments. Offline/keyless it reduces exactly
        to the bare trend edge; live it adds the event blackout + Opus veto.
      * "trend" — the bare long-biased trend-regime filter (pair with
        FXSIM_USE_TAKE_PROFIT=0 so winners run).
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
