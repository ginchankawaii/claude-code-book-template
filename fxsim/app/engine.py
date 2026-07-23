"""Paper-trading engine.

Processes candles one bar at a time, asks the strategy for a blended signal,
and simulates fills against the real (or sample) price path. Applies a spread +
commission cost model and risk-based position sizing with an ATR stop / target.

Assumption: the account is denominated in the pair's QUOTE currency (e.g. JPY
for USD_JPY), so P&L = units * price_change. This keeps a single-pair sim exact
without needing a separate conversion feed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from . import db
from .config import Settings, pip_size, settings as default_settings
from .indicators import enrich
from .models import Candle, Position, Signal, TradeResult
from .sizing import conviction_leverage
from .strategies.base import Strategy


@dataclass
class _OpenState:
    position: Position
    stop_price: float
    target_price: float


class PaperTradingEngine:
    def __init__(
        self,
        run_id: int,
        instrument: str,
        strategy: Strategy,
        cfg: Optional[Settings] = None,
        persist: bool = True,
    ) -> None:
        self.run_id = run_id
        self.instrument = instrument
        self.strategy = strategy
        self.cfg = cfg or default_settings
        self.persist = persist
        self.pip = pip_size(instrument)

        self.balance = self.cfg.initial_balance
        self.state: Optional[_OpenState] = None
        self.closed_trades: list[TradeResult] = []
        self.equity_curve: list[tuple[datetime, float, float, float]] = []
        # effective leverage cap for the next _open (conviction-scaled per bar);
        # None -> use the flat cfg.max_leverage.
        self._eff_leverage: Optional[float] = None

    # ------------------------------------------------------------------ #
    # sizing & costs
    # ------------------------------------------------------------------ #
    def _half_spread(self) -> float:
        return self.cfg.spread_pips * self.pip / 2.0

    def _commission(self, units: int) -> float:
        return abs(units) / 1_000_000.0 * self.cfg.commission_per_million

    def _dyn_leverage(self, df: pd.DataFrame, price: float, atr: float) -> float:
        """Conviction-scaled leverage cap for this bar (<= cfg.max_leverage).

        Full cap when price is well above the trend SMA; ramps toward
        dyn_lev_floor as price falls back toward the SMA. See app/sizing.py.
        """
        cap = self.cfg.max_leverage
        if not self.cfg.dyn_leverage or cap <= 0:
            return cap
        n = self.cfg.trend_sma
        close = df["close"]
        if n <= 0 or len(close) < n:
            return cap
        sma = float(close.iloc[-n:].mean())
        return conviction_leverage(price, sma, atr, cap,
                                   self.cfg.dyn_lev_atr_mult, self.cfg.dyn_lev_floor,
                                   getattr(self.cfg, "dyn_lev_pow", 1.0))

    def _size(self, atr: float, price: float) -> int:
        stop_distance = max(atr * 1.5, self.pip * 5)
        risk_cash = self.balance * self.cfg.risk_per_trade
        units = int(risk_cash / stop_distance)
        units = min(units, self.cfg.max_position_units)
        # Hard leverage ceiling: notional (units * price) <= max_leverage * equity.
        # Balance and price are both in the quote currency, so units * price is the
        # notional in quote terms and balance is the equity in quote terms.
        # _eff_leverage (set per bar in step) applies the conviction scaling but
        # never exceeds cfg.max_leverage.
        lev = self._eff_leverage if self._eff_leverage is not None else self.cfg.max_leverage
        if lev > 0 and price > 0:
            units = min(units, int(lev * self.balance / price))
        return max(0, units)

    # ------------------------------------------------------------------ #
    # equity
    # ------------------------------------------------------------------ #
    def equity(self, price: float) -> float:
        if self.state is None:
            return self.balance
        return self.balance + self.state.position.unrealized_pnl(price)

    # ------------------------------------------------------------------ #
    # order handling
    # ------------------------------------------------------------------ #
    def _open(self, direction: int, price: float, atr: float, time: datetime, reason: str) -> None:
        units = self._size(atr, price) * direction
        if units == 0:
            return
        fill = price + self._half_spread() * (1 if direction > 0 else -1)
        stop_distance = max(atr * 1.5, self.pip * 5)
        stop = fill - stop_distance * direction
        if self.cfg.use_take_profit:
            target = fill + stop_distance * 2.0 * direction  # 2:1 reward:risk
        else:
            # trend mode: let winners run; exit via signal-fade or the stop
            target = float("inf") if direction > 0 else float("-inf")

        trade_id = None
        if self.persist:
            trade_id = db.open_trade(
                self.run_id, self.instrument,
                "LONG" if direction > 0 else "SHORT",
                units, time, fill, reason,
            )
        self.balance -= self._commission(units)
        pos = Position(self.instrument, units, fill, time, trade_id)
        self.state = _OpenState(pos, stop, target)

    def _close(self, price: float, time: datetime, reason: str) -> None:
        if self.state is None:
            return
        pos = self.state.position
        direction = 1 if pos.units > 0 else -1
        fill = price - self._half_spread() * (1 if direction > 0 else -1)
        pnl = pos.unrealized_pnl(fill) - self._commission(pos.units)
        self.balance += pnl
        self.closed_trades.append(
            TradeResult(
                instrument=self.instrument,
                side=pos.side,
                units=pos.units,
                entry_time=pos.entry_time,
                entry_price=pos.entry_price,
                exit_time=time,
                exit_price=fill,
                pnl=pnl,
                reason=reason,
            )
        )
        if self.persist and pos.trade_id is not None:
            db.close_trade(pos.trade_id, time, fill, pnl, reason)
        self.state = None

    # ------------------------------------------------------------------ #
    # per-bar processing
    # ------------------------------------------------------------------ #
    def _check_stops(self, candle: Candle) -> bool:
        """Returns True if the bar's high/low hit our stop or target."""
        if self.state is None:
            return False
        pos = self.state.position
        if pos.units > 0:  # long
            if candle.low <= self.state.stop_price:
                self._close(self.state.stop_price, candle.time, "stop-loss")
                return True
            if candle.high >= self.state.target_price:
                self._close(self.state.target_price, candle.time, "take-profit")
                return True
        else:  # short
            if candle.high >= self.state.stop_price:
                self._close(self.state.stop_price, candle.time, "stop-loss")
                return True
            if candle.low <= self.state.target_price:
                self._close(self.state.target_price, candle.time, "take-profit")
                return True
        return False

    def step(self, df: pd.DataFrame, signal: Signal) -> None:
        """Process the most recent bar in `df` (already indicator-enriched)."""
        last = df.iloc[-1]
        candle = Candle(
            instrument=self.instrument,
            granularity=self.cfg.granularity,
            time=last["time"].to_pydatetime() if hasattr(last["time"], "to_pydatetime") else last["time"],
            open=last["open"], high=last["high"], low=last["low"],
            close=last["close"], volume=last["volume"],
        )
        price = candle.close
        atr = last["atr"] if not math.isnan(last["atr"]) else self.pip * 10
        # conviction-scaled leverage cap for any _open triggered this bar
        self._eff_leverage = self._dyn_leverage(df, price, atr)

        # 1) intrabar stop/target first
        self._check_stops(candle)

        # 2) act on the signal
        entry_th = self.cfg.entry_threshold
        exit_th = self.cfg.exit_threshold
        if self.state is None:
            if abs(signal.score) >= entry_th and signal.direction != 0:
                self._open(signal.direction, price, atr, candle.time, signal.reason)
        else:
            pos_dir = 1 if self.state.position.units > 0 else -1
            opposite = signal.direction != 0 and signal.direction != pos_dir
            if opposite and abs(signal.score) >= entry_th:
                self._close(price, candle.time, "reverse")
                self._open(signal.direction, price, atr, candle.time, signal.reason)
            elif abs(signal.score) < exit_th:
                self._close(price, candle.time, "signal-faded")

        # 3) record state
        eq = self.equity(price)
        self.equity_curve.append((candle.time, self.balance, eq, price))
        if self.persist:
            db.record_equity(self.run_id, candle.time, self.balance, eq, price)

    def force_close(self, df: pd.DataFrame) -> None:
        if self.state is not None and len(df):
            last = df.iloc[-1]
            t = last["time"].to_pydatetime() if hasattr(last["time"], "to_pydatetime") else last["time"]
            self._close(last["close"], t, "end-of-run")


def enrich_candles(candles: list[Candle]) -> pd.DataFrame:
    from .indicators import candles_to_df

    return enrich(candles_to_df(candles))
