"""Unit tests for signal generation and risk management."""

import numpy as np
import pandas as pd
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indicators.technical import add_all_indicators
from src.strategy.signals import SignalGenerator
from src.strategy.risk_manager import RiskManager


CONFIG = {
    "trading": {
        "risk_per_trade": 0.015,
        "max_position_pct": 0.15,
        "max_positions": 8,
        "min_cash_reserve": 0.10,
    },
    "strategy": {"signal_threshold": 4},
    "risk": {
        "stop_loss_atr_multiplier": 2.5,
        "take_profit_1_pct": 0.06,
        "take_profit_2_pct": 0.10,
        "trailing_stop_trigger_pct": 0.04,
        "max_drawdown_halt": 0.10,
    },
}


def make_ohlcv(n: int = 300) -> pd.DataFrame:
    np.random.seed(0)
    close = 1000 * np.cumprod(1 + np.random.normal(0, 0.01, n))
    high = close * 1.005
    low = close * 0.995
    volume = np.random.randint(500_000, 2_000_000, n).astype(float)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume}, index=dates)


def test_signal_action_is_valid():
    df = add_all_indicators(make_ohlcv())
    gen = SignalGenerator(CONFIG)
    signal = gen.generate("TEST", df)
    assert signal.action in ("BUY", "HOLD")


def test_signal_stop_loss_below_price():
    df = add_all_indicators(make_ohlcv())
    gen = SignalGenerator(CONFIG)
    signal = gen.generate("TEST", df)
    assert signal.stop_loss < df["close"].iloc[-1]


def test_position_size_nonzero():
    rm = RiskManager(CONFIG)
    portfolio_val = 3_000_000
    entry = 1000.0
    stop = 950.0
    qty = rm.calc_position_size(portfolio_val, entry, stop)
    assert qty > 0


def test_position_size_respects_max_pct():
    rm = RiskManager(CONFIG)
    portfolio_val = 3_000_000
    entry = 10.0     # 超安値で max_pct が効く
    stop = 9.5
    qty = rm.calc_position_size(portfolio_val, entry, stop)
    assert qty * entry <= portfolio_val * rm.max_position_pct + 1


def test_drawdown_halt():
    rm = RiskManager(CONFIG)
    assert rm.check_drawdown_halt(1_000_000, 850_000) is True   # 15% > 10%
    assert rm.check_drawdown_halt(1_000_000, 950_000) is False  # 5% < 10%
