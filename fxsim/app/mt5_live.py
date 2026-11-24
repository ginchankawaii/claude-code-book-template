"""Full-auto live trader on MT5 (OANDA証券 MT5 demo -> live).

Strategy + adaptive risk (our Python brain) drive REAL position changes through
an MT5 terminal. Long-or-flat only. Equity/risk are read from the broker; the
adaptive controller brakes risk on drawdown / losing streaks exactly as in the
backtest. Everything is persisted to SQLite for the /live dashboard.

Safety: broker defaults to dry_run (no orders sent) until you pass live=True.
Daily timeframe => acts at most once per completed bar; extra polls are no-ops.
"""
from __future__ import annotations

import math
import signal as _signal
import time as _time
from datetime import datetime, timezone
from typing import Optional

from . import db
from .adaptive import AdaptiveConfig, AdaptiveController
from .brokers import MT5Broker
from .config import Settings, pip_size, settings as default_settings
from .indicators import candles_to_df, enrich
from .strategies import build_strategy

_GRAN_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                 "H1": 3600, "H4": 14400, "D": 86400}


class MT5LiveTrader:
    def __init__(self, instrument: str, broker: MT5Broker,
                 cfg: Optional[Settings] = None, history_bars: int = 400) -> None:
        self.cfg = cfg or default_settings
        self.instrument = instrument
        self.broker = broker
        self.pip = pip_size(instrument)
        # The shared "brain": same factory the backtest/paper paths use, so live
        # runs the configured strategy (default: trend edge + Opus/event overlay).
        self.strategy = build_strategy(self.cfg)
        # Need at least trend_sma + warmup bars of history for the filter to wake.
        self.history_bars = max(history_bars, self.cfg.trend_sma + 64)
        # Refresh the live fundamental view + economic calendar ~once per day of
        # bars (so Opus sees fresh macro/event data), if the strategy supports it.
        self._can_refresh = hasattr(self.strategy, "refresh")
        gs = _GRAN_SECONDS.get(self.cfg.granularity, 86400)
        self._refresh_every = max(1, 86400 // gs)
        self._bars_seen = 0
        self.controller = AdaptiveController(AdaptiveConfig(base_risk=self.cfg.risk_per_trade))
        self._stop = False
        self._last_bar_time: Optional[datetime] = None
        self._equity: list[float] = []
        self._pnls: list[float] = []
        self._in_pos = False
        self._entry_equity = 0.0
        # Long-or-flat book; mirror the engine's entry/exit hysteresis so live
        # acts on the SAME thresholds as the backtest (not just the signal sign).
        self._want_long = False

        db.init_db()
        self.run_id = db.create_run(
            mode="live", instrument=instrument, granularity=self.cfg.granularity,
            initial_balance=self.cfg.initial_balance,
            params={"system": "steady-mt5", "strategy": self.cfg.strategy,
                    "trend_sma": self.cfg.trend_sma, "decision_mode": self.cfg.decision_mode,
                    "base_risk": self.controller.cfg.base_risk,
                    "dry_run": self.broker.dry_run},
        )

    def _want_long_after(self, direction: int, score: float) -> bool:
        """Engine-equivalent long-or-flat gate with entry/exit hysteresis."""
        if not self._want_long:
            if direction > 0 and abs(score) >= self.cfg.entry_threshold:
                return True
            return False
        # currently long: stay unless the signal fades or turns non-long
        if direction <= 0 or abs(score) < self.cfg.exit_threshold:
            return False
        return True

    def stop(self, *_: object) -> None:
        self._stop = True

    def _target_units(self, direction: int, balance: float, atr: float,
                      price: float = 0.0) -> float:
        if direction <= 0:
            return 0.0
        stop_distance = max(atr * 1.5, self.pip * 5)
        units = (balance * self.cfg.risk_per_trade) / stop_distance
        units = min(units, self.cfg.max_position_units)
        # hard leverage ceiling: notional (units * price) <= max_leverage * equity
        if self.cfg.max_leverage > 0 and price > 0:
            units = min(units, self.cfg.max_leverage * balance / price)
        return float(units)

    def _track_and_adapt(self, equity: float, is_long: bool, when: datetime) -> None:
        # approximate per-trade pnl from equity at entry/exit (long-or-flat)
        if is_long and not self._in_pos:
            self._in_pos = True; self._entry_equity = equity
        elif not is_long and self._in_pos:
            self._in_pos = False; self._pnls.append(equity - self._entry_equity)
        self._equity.append(equity)
        target, reason, metrics = self.controller.evaluate(self._equity, self._pnls)
        if self.controller.changed(self.cfg.risk_per_trade, target):
            old = self.cfg.risk_per_trade
            self.cfg.risk_per_trade = target
            db.record_adjustment(self.run_id, when, "risk_per_trade",
                                 round(old, 6), target, reason, metrics)
            print(f"[mt5-live] risk {old:.4f} -> {target:.4f} ({reason})", flush=True)

    def poll_once(self) -> bool:
        candles = self.broker.history(self.cfg.granularity, self.history_bars)
        if not candles:
            return False
        latest = candles[-1]
        if self._last_bar_time is not None and latest.time <= self._last_bar_time:
            return False
        self._last_bar_time = latest.time

        # Refresh the live macro/event view at the configured cadence (Opus only
        # actually fires in anthropic/hybrid modes; offline this is a cheap no-op).
        if self._can_refresh and self._bars_seen % self._refresh_every == 0:
            self.strategy.refresh(self.instrument)
        self._bars_seen += 1

        db.upsert_candles(candles)
        df = enrich(candles_to_df(candles))
        sig = self.strategy.generate(self.instrument, df)
        acct = self.broker.account()
        atr = df.iloc[-1]["atr"]
        if math.isnan(atr):
            atr = self.pip * 10
        price = float(df.iloc[-1]["close"])

        # Gate to long-or-flat using the engine's entry/exit thresholds so the
        # live book matches the backtest (not just the raw signal sign).
        self._want_long = self._want_long_after(sig.direction, sig.score)
        live_dir = 1 if self._want_long else 0

        # adapt FIRST (so the new risk sizes this bar's target), then reconcile
        self._track_and_adapt(acct.equity, self._want_long, latest.time)
        target = self._target_units(live_dir, acct.balance, atr, price)
        self.broker.set_target_units(target, reason=sig.reason[:24])

        db.record_signal(self.run_id, latest.time, self.instrument, "combined",
                         live_dir, sig.score, sig.reason, sig.components)
        db.record_equity(self.run_id, latest.time, acct.balance, acct.equity,
                         float(df.iloc[-1]["close"]))
        print(f"[mt5-live] {latest.time:%Y-%m-%d %H:%M} {'LONG' if self._want_long else 'FLAT'} "
              f"target={target:,.0f}u eq={acct.equity:,.0f} risk={self.cfg.risk_per_trade:.4f} "
              f":: {sig.reason}", flush=True)
        return True

    def run(self, poll_seconds: Optional[int] = None) -> None:
        _signal.signal(_signal.SIGINT, self.stop)
        _signal.signal(_signal.SIGTERM, self.stop)
        interval = poll_seconds or max(30, _GRAN_SECONDS.get(self.cfg.granularity, 86400) // 8)
        self.broker.connect()
        print(f"[mt5-live] run #{self.run_id} {self.instrument} {self.cfg.granularity} "
              f"poll={interval}s dry_run={self.broker.dry_run}", flush=True)
        backoff = 2
        try:
            while not self._stop:
                try:
                    self.poll_once(); backoff = 2
                except Exception as exc:
                    print(f"[mt5-live] poll error: {exc} (retry {backoff}s)", flush=True)
                    _time.sleep(min(backoff, 60)); backoff = min(backoff * 2, 60); continue
                for _ in range(interval):
                    if self._stop:
                        break
                    _time.sleep(1)
        finally:
            db.finish_run(self.run_id)
            self.broker.shutdown()
            print(f"[mt5-live] stopped run #{self.run_id}", flush=True)
