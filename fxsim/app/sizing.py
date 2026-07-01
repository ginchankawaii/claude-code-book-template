"""Conviction-scaled leverage — the one improvement that survived OOS testing.

Finding (scripts/research.py + verify, 11y USD/JPY H1, docs/RESEARCH.md):
  Scaling leverage by how far price sits above the trend SMA — measured in ATR
  units — cuts max drawdown ~34%→26% at equal-or-higher CAGR (Sharpe 0.58→0.83),
  robust across the whole parameter neighborhood, in both walk-forward halves,
  and under 3x cost stress. It adds NO trades (same 219), it only resizes.

Mechanism: the position sits at the full leverage cap ~95% of the time (strong,
established trend). Only in the ~5% of bars where price drifts back toward the
SMA — the whipsaw / trend-failure zone where drawdowns are born — does it pull
exposure down toward the floor. It NEVER exceeds the hard cap: this is not "more
leverage", it is "less leverage exactly where it hurts".

    strength = clip((price - sma) / (atr_mult * atr), 0, 1)   # 0 at SMA .. 1 far above
    leverage = floor + (cap - floor) * strength               # floor .. cap

Both the backtest engine (app/engine._size) and the live bridge
(scripts/run_ai_bridge -> app/ai_trader.size_lots) call this one function so the
simulated edge and the live order use identical maths.
"""
from __future__ import annotations


def conviction_leverage(price: float, sma: float, atr: float, cap: float,
                        atr_mult: float = 1.5, floor: float = 1.0) -> float:
    """Effective leverage in [floor, cap] from distance-above-SMA in ATR units.

    Returns ``cap`` unchanged when the inputs can't be trusted (non-positive
    cap/atr, or a NaN slips in) so the caller degrades to the plain fixed cap
    rather than to zero size. Only ever returns <= cap — the hard leverage
    ceiling is never breached.
    """
    if cap <= 0:
        return cap
    lo = max(0.0, min(floor, cap))
    # Guard against NaN / zero ATR (warmup, gaps): fall back to the full cap.
    if not (atr > 0) or not (atr_mult > 0) or price != price or sma != sma:
        return cap
    strength = (price - sma) / (atr_mult * atr)
    strength = 0.0 if strength < 0 else (1.0 if strength > 1 else strength)
    return lo + (cap - lo) * strength
