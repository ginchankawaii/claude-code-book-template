"""Adaptive risk controller — the system tunes itself from its own results.

Philosophy (capital-preservation first, per the brief): profits can be small,
but the account must keep trading for the long run. So position risk is scaled
DOWN automatically when results deteriorate, and allowed back toward normal when
they stabilise. It never sizes up beyond the configured base — survival over
greed.

Signals it reacts to (all read from realised results, no look-ahead):
  * drawdown from the equity peak  -> graduated brake
  * consecutive losing trades      -> exponential brake
  * recent win rate                -> mild brake when persistently poor

The decision is deterministic and explainable; every change is persisted to the
`adjustments` table with the metrics snapshot that justified it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AdaptiveConfig:
    base_risk: float = 0.01          # normal risk fraction per trade (1%)
    min_risk: float = 0.0025         # never go below 0.25%
    # graduated drawdown brakes: (drawdown_threshold, risk_multiplier)
    dd_brakes: tuple = ((0.05, 0.70), (0.10, 0.40), (0.20, 0.20))
    loss_streak_start: int = 3       # start braking at the 3rd consecutive loss
    loss_streak_decay: float = 0.80  # multiply risk by this per extra loss
    winrate_window: int = 12         # look-back trades for win-rate brake
    winrate_floor: float = 0.25      # below this (with enough trades) -> brake
    winrate_brake: float = 0.80
    rel_change_eps: float = 0.05     # only log a change if >5% relative move


@dataclass
class AdaptiveController:
    cfg: AdaptiveConfig = field(default_factory=AdaptiveConfig)

    def _drawdown(self, equity: list[float]) -> float:
        """CURRENT drawdown: how far the latest equity is below the running peak.
        Returns 0 at a fresh high, so risk is restored once we recover."""
        peak = max(equity)
        cur = equity[-1]
        return (peak - cur) / peak if peak > 0 else 0.0

    def _loss_streak(self, pnls: list[float]) -> int:
        s = 0
        for p in reversed(pnls):
            if p < 0:
                s += 1
            else:
                break
        return s

    def evaluate(self, equity: list[float], trade_pnls: list[float]) -> tuple[float, str, dict]:
        """Return (target_risk, reason, metrics) from current realised results."""
        c = self.cfg
        dd = self._drawdown(equity) if equity else 0.0
        streak = self._loss_streak(trade_pnls)
        recent = trade_pnls[-c.winrate_window:]
        winrate = (sum(1 for p in recent if p > 0) / len(recent)) if recent else None

        dd_factor = 1.0
        for th, mult in c.dd_brakes:
            if dd >= th:
                dd_factor = mult
        streak_factor = 1.0
        if streak >= c.loss_streak_start:
            streak_factor = c.loss_streak_decay ** (streak - c.loss_streak_start + 1)
        winrate_factor = 1.0
        if winrate is not None and len(recent) >= c.winrate_window and winrate < c.winrate_floor:
            winrate_factor = c.winrate_brake

        target = c.base_risk * dd_factor * streak_factor * winrate_factor
        target = max(c.min_risk, min(target, c.base_risk))

        bits = []
        if dd_factor < 1.0: bits.append(f"drawdown {dd:.0%}→×{dd_factor:.2f}")
        if streak_factor < 1.0: bits.append(f"{streak} losses→×{streak_factor:.2f}")
        if winrate_factor < 1.0: bits.append(f"winrate {winrate:.0%}→×{winrate_factor:.2f}")
        reason = "; ".join(bits) if bits else "results healthy → base risk"
        metrics = {"drawdown": round(dd, 4), "loss_streak": streak,
                   "winrate": round(winrate, 3) if winrate is not None else None,
                   "n_trades": len(trade_pnls)}
        return round(target, 6), reason, metrics

    def changed(self, old: float, new: float) -> bool:
        if old <= 0:
            return new > 0
        return abs(new - old) / old >= self.cfg.rel_change_eps
