"""Live paper-trading loop.

Polls the data provider once per completed candle, runs one engine step, and
persists everything to SQLite — identical decision logic to the backtester, so
behaviour is consistent between simulation and live.

This is still PAPER trading: prices are real (OANDA) but fills are simulated.
"""
from __future__ import annotations

import signal
import time as _time
from datetime import datetime, timezone

from . import db
from .config import Settings, settings as default_settings
from .engine import PaperTradingEngine
from .indicators import candles_to_df, enrich
from .providers import get_provider
from .strategies import build_strategy

_GRAN_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D": 86400,
}


class LiveTrader:
    def __init__(
        self,
        instrument: str,
        cfg: Settings | None = None,
        history_bars: int = 200,
    ) -> None:
        self.cfg = cfg or default_settings
        self.instrument = instrument
        self.history_bars = history_bars
        self.provider = get_provider(self.cfg.data_provider)
        self.strategy = build_strategy(self.cfg)
        self._stop = False

        db.init_db()
        self.run_id = db.create_run(
            mode="live",
            instrument=instrument,
            granularity=self.cfg.granularity,
            initial_balance=self.cfg.initial_balance,
            params={"provider": self.provider.name, "granularity": self.cfg.granularity},
        )
        self.engine = PaperTradingEngine(self.run_id, instrument, self.strategy, self.cfg)
        self._last_bar_time: datetime | None = None

    def stop(self, *_: object) -> None:
        self._stop = True

    def poll_once(self) -> bool:
        """Fetch latest candles; if a new completed bar appeared, step once.
        Returns True if a step was taken."""
        candles = self.provider.history(
            self.instrument, self.cfg.granularity, self.history_bars
        )
        if not candles:
            return False
        latest = candles[-1]
        if self._last_bar_time is not None and latest.time <= self._last_bar_time:
            return False  # no new bar yet
        self._last_bar_time = latest.time

        db.upsert_candles(candles)
        df = enrich(candles_to_df(candles))
        signal_obj = self.strategy.generate(self.instrument, df)
        t = df.iloc[-1]["time"]
        t = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
        db.record_signal(
            self.run_id, t, self.instrument, "technical",
            self.strategy.last_technical.direction, self.strategy.last_technical.score,
            self.strategy.last_technical.reason, self.strategy.last_technical.components,
        )
        db.record_signal(
            self.run_id, t, self.instrument, "fundamental",
            self.strategy.last_fundamental.direction, self.strategy.last_fundamental.score,
            self.strategy.last_fundamental.reason, self.strategy.last_fundamental.components,
        )
        db.record_signal(
            self.run_id, t, self.instrument, "combined",
            signal_obj.direction, signal_obj.score, signal_obj.reason, signal_obj.components,
        )
        self.engine.step(df, signal_obj)
        return True

    def run(self, poll_seconds: int | None = None, max_iterations: int | None = None) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        interval = poll_seconds or max(15, _GRAN_SECONDS.get(self.cfg.granularity, 900) // 4)
        # refresh fundamental view at the start
        # Refresh news + event calendar at the start (AI strategy) or just the
        # fundamental view (plain combined strategy). Network/key issues here
        # must not kill the loop.
        try:
            if hasattr(self.strategy, "refresh"):
                self.strategy.refresh(self.instrument)
            else:
                self.strategy.fundamental.refresh(self.instrument)
        except Exception as exc:
            print(f"[live] context refresh skipped: {exc}")

        print(
            f"[live] run #{self.run_id} {self.instrument} {self.cfg.granularity} "
            f"provider={self.provider.name} poll={interval}s"
        )
        iterations = 0
        while not self._stop:
            try:
                stepped = self.poll_once()
                if stepped:
                    eq = self.engine.equity_curve[-1][2] if self.engine.equity_curve else self.cfg.initial_balance
                    print(f"[live] {datetime.now(timezone.utc):%H:%M:%S} bar stepped, equity={eq:,.2f}")
            except Exception as exc:
                print(f"[live] poll error: {exc}")
            iterations += 1
            if max_iterations and iterations >= max_iterations:
                break
            for _ in range(interval):
                if self._stop:
                    break
                _time.sleep(1)
        db.finish_run(self.run_id)
        print(f"[live] stopped run #{self.run_id}")
