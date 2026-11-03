"""Forward paper-trading daemon — Steady on a live OANDA price feed.

Phase 1 of going live: REAL prices from an OANDA *practice* (demo) account,
fills still SIMULATED locally (no real orders are placed). This lets you watch
the exact strategy + adaptive risk run forward in real time on the dashboard,
for months, before risking a cent.

Resident OR cron: call ``poll_once()`` from a scheduler once a day, or use
``run()`` to stay resident and poll on an interval. Daily timeframe => it acts
at most once per completed daily bar; extra polls are cheap no-ops.

Network failures never kill the loop (logged + retried with backoff).
"""
from __future__ import annotations

import signal as _signal
import time as _time
from datetime import datetime, timezone
from typing import Optional

from . import db
from .adaptive import AdaptiveConfig, AdaptiveController
from .config import Settings, settings as default_settings
from .engine import PaperTradingEngine
from .indicators import candles_to_df, enrich
from .providers import get_provider
from .strategies.trend import TrendRegimeStrategy

_GRAN_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                 "H1": 3600, "H4": 14400, "D": 86400}


class SteadyLiveTrader:
    def __init__(
        self,
        instrument: str,
        cfg: Optional[Settings] = None,
        history_bars: int = 400,
        provider_name: Optional[str] = None,
    ) -> None:
        self.cfg = cfg or default_settings
        self.cfg.use_take_profit = False          # trend mode: let winners run
        self.instrument = instrument
        self.history_bars = history_bars
        self.provider = get_provider(provider_name or self.cfg.data_provider)
        self.strategy = TrendRegimeStrategy(sma=self.cfg.trend_sma)
        self.controller = AdaptiveController(AdaptiveConfig(base_risk=self.cfg.risk_per_trade))
        self._stop = False
        self._last_bar_time: Optional[datetime] = None

        db.init_db()
        self.run_id = db.create_run(
            mode="live", instrument=instrument, granularity=self.cfg.granularity,
            initial_balance=self.cfg.initial_balance,
            params={"system": "steady-live", "provider": self.provider.name,
                    "trend_sma": self.cfg.trend_sma, "base_risk": self.controller.cfg.base_risk},
        )
        self.engine = PaperTradingEngine(self.run_id, instrument, self.strategy,
                                         self.cfg, persist=True)

    def stop(self, *_: object) -> None:
        self._stop = True

    def _adapt(self, when: datetime) -> None:
        pnls = [t.pnl for t in self.engine.closed_trades]
        equity = [row[2] for row in self.engine.equity_curve]
        if not equity:
            return
        target, reason, metrics = self.controller.evaluate(equity, pnls)
        if self.controller.changed(self.cfg.risk_per_trade, target):
            old = self.cfg.risk_per_trade
            self.cfg.risk_per_trade = target
            db.record_adjustment(self.run_id, when, "risk_per_trade",
                                 round(old, 6), target, reason, metrics)
            print(f"[steady-live] risk {old:.4f} -> {target:.4f} ({reason})", flush=True)

    def poll_once(self) -> bool:
        """Fetch latest candles; act once if a NEW completed bar appeared."""
        candles = self.provider.history(self.instrument, self.cfg.granularity, self.history_bars)
        if not candles:
            return False
        latest = candles[-1]
        if self._last_bar_time is not None and latest.time <= self._last_bar_time:
            return False
        self._last_bar_time = latest.time

        db.upsert_candles(candles)
        df = enrich(candles_to_df(candles))
        sig = self.strategy.generate(self.instrument, df)
        t = df.iloc[-1]["time"]
        t = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
        db.record_signal(self.run_id, t, self.instrument, "combined",
                         sig.direction, sig.score, sig.reason, sig.components)
        self.engine.step(df, sig)
        self._adapt(t)
        eq = self.engine.equity_curve[-1][2] if self.engine.equity_curve else self.cfg.initial_balance
        pos = "LONG" if self.engine.state else "flat"
        print(f"[steady-live] {t:%Y-%m-%d %H:%M} new bar: {pos} "
              f"eq={eq:,.0f} risk={self.cfg.risk_per_trade:.4f} :: {sig.reason}", flush=True)
        return True

    def run(self, poll_seconds: Optional[int] = None) -> None:
        _signal.signal(_signal.SIGINT, self.stop)
        _signal.signal(_signal.SIGTERM, self.stop)
        interval = poll_seconds or max(30, _GRAN_SECONDS.get(self.cfg.granularity, 86400) // 8)
        print(f"[steady-live] run #{self.run_id} {self.instrument} {self.cfg.granularity} "
              f"provider={self.provider.name} poll={interval}s — REAL prices, SIMULATED fills",
              flush=True)
        backoff = 2
        while not self._stop:
            try:
                self.poll_once()
                backoff = 2
            except Exception as exc:                      # network/API hiccup
                print(f"[steady-live] poll error: {exc} (retry in {backoff}s)", flush=True)
                _time.sleep(min(backoff, 60)); backoff = min(backoff * 2, 60); continue
            for _ in range(interval):
                if self._stop:
                    break
                _time.sleep(1)
        db.finish_run(self.run_id)
        print(f"[steady-live] stopped run #{self.run_id}", flush=True)
