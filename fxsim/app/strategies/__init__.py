from ..config import Settings, settings
from .ai import AIDecisionStrategy
from .base import Strategy
from .combined import CombinedStrategy
from .fundamental import FundamentalStrategy
from .technical import TechnicalStrategy

__all__ = [
    "Strategy",
    "TechnicalStrategy",
    "FundamentalStrategy",
    "CombinedStrategy",
    "AIDecisionStrategy",
    "build_strategy",
]


def build_strategy(cfg: Settings | None = None) -> Strategy:
    """Construct the active strategy.

    Default is the event-aware AI decision layer (``decision_mode`` = "rule" or
    "anthropic"). Set ``FXSIM_DECISION_MODE=off`` to fall back to the plain
    mechanical technical+fundamental blend.
    """
    cfg = cfg or settings
    if (cfg.decision_mode or "").lower() in ("", "off", "none"):
        return CombinedStrategy()
    return AIDecisionStrategy(cfg=cfg)
