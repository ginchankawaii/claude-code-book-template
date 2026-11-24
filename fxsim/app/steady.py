"""SteadyTrader — capital-preservation-first, self-tuning trend follower.

Ties together the three pieces the brief asked for:
  * a from-scratch, evidence-based core strategy (daily trend-regime: long only
    while price is above its long SMA, else stand aside — the one edge that
    survived honest out-of-sample testing);
  * an adaptive controller that tunes position risk from realised results
    (drawdown / losing-streak / win-rate brakes), every change logged;
  * full persistence to SQLite (runs / trades / equity / signals / adjustments)
    so the live dashboard can show what is happening in real time.

It runs by stepping candles one bar at a time, so the exact same code path works
for a fast historical replay (demo) and for a paced live loop.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timezone
from typing import Optional

from . import db
from .adaptive import AdaptiveConfig, AdaptiveController
from .backtest import WARMUP
from .config import Settings, settings as default_settings
from .engine import PaperTradingEngine
from .indicators import candles_to_df, enrich
from .models import Candle
from .strategies.trend import TrendRegimeStrategy


class SteadyTrader:
    def __init__(
        self,
        instrument: str,
        candles: list[Candle],
        cfg: Optional[Settings] = None,
        adaptive: Optional[AdaptiveConfig] = None,
        persist: bool = True,
    ) -> None:
        self.instrument = instrument
        self.candles = candles
        self.cfg = cfg or Settings(strategy="trend", use_take_profit=False)
        # trend mode: let winners run, low frequency
        self.cfg.use_take_profit = False
        self.strategy = TrendRegimeStrategy(sma=self.cfg.trend_sma)
        self.controller = AdaptiveController(adaptive or AdaptiveConfig(
            base_risk=self.cfg.risk_per_trade))
        self.persist = persist
        self.run_id = 0
        if persist:
            db.init_db()
            self.run_id = db.create_run(
                mode="live", instrument=instrument, granularity=self.cfg.granularity,
                initial_balance=self.cfg.initial_balance,
                params={"system": "steady", "trend_sma": self.cfg.trend_sma,
                        "base_risk": self.controller.cfg.base_risk},
            )
        self.engine = PaperTradingEngine(self.run_id, instrument, self.strategy,
                                         self.cfg, persist=persist)

    def _adapt(self, when: datetime) -> None:
        pnls = [t.pnl for t in self.engine.closed_trades]
        equity = [row[2] for row in self.engine.equity_curve]
        if not equity:
            return
        target, reason, metrics = self.controller.evaluate(equity, pnls)
        if self.controller.changed(self.cfg.risk_per_trade, target):
            old = self.cfg.risk_per_trade
            self.cfg.risk_per_trade = target
            if self.persist:
                db.record_adjustment(self.run_id, when, "risk_per_trade",
                                     round(old, 6), target, reason, metrics)

    def run(self, step_sleep: float = 0.0, log_every: int = 0) -> int:
        df = enrich(candles_to_df(self.candles))
        n = len(df)
        for i in range(WARMUP, n):
            window = df.iloc[: i + 1]
            sig = self.strategy.generate(self.instrument, window)
            if self.persist:
                t = window.iloc[-1]["time"]
                t = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
                db.record_signal(self.run_id, t, self.instrument, "combined",
                                 sig.direction, sig.score, sig.reason, sig.components)
            self.engine.step(window, sig)
            when = window.iloc[-1]["time"]
            when = when.to_pydatetime() if hasattr(when, "to_pydatetime") else when
            self._adapt(when)
            if log_every and (i - WARMUP) % log_every == 0:
                eq = self.engine.equity_curve[-1][2] if self.engine.equity_curve else 0
                print(f"[steady] {when:%Y-%m-%d} eq={eq:,.0f} risk={self.cfg.risk_per_trade:.4f} "
                      f"pos={'LONG' if self.engine.state else 'flat'}", flush=True)
            if step_sleep:
                _time.sleep(step_sleep)
        self.engine.force_close(df)
        if self.persist:
            db.finish_run(self.run_id)
        return self.run_id
