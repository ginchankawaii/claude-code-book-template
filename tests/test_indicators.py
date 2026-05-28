"""Unit tests for technical indicators."""

import numpy as np
import pandas as pd
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indicators.technical import add_all_indicators


def make_ohlcv(n: int = 300) -> pd.DataFrame:
    np.random.seed(42)
    close = 1000 * np.cumprod(1 + np.random.normal(0, 0.01, n))
    high = close * (1 + np.abs(np.random.normal(0, 0.005, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n)))
    volume = np.random.randint(100_000, 1_000_000, n).astype(float)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume}, index=dates)


def test_indicators_added():
    df = make_ohlcv()
    result = add_all_indicators(df)
    for col in ["rsi", "macd", "macd_signal", "bb_upper", "atr", "adx", "vol_ratio"]:
        assert col in result.columns, f"Missing column: {col}"


def test_rsi_range():
    df = make_ohlcv()
    result = add_all_indicators(df)
    assert result["rsi"].between(0, 100).all(), "RSI must be in [0, 100]"


def test_no_nan_in_result():
    df = make_ohlcv(300)
    result = add_all_indicators(df)
    assert not result.isnull().all(axis=1).any(), "No fully-NaN rows expected"


def test_bollinger_bands_order():
    df = make_ohlcv()
    result = add_all_indicators(df)
    assert (result["bb_upper"] >= result["bb_mid"]).all()
    assert (result["bb_mid"] >= result["bb_lower"]).all()
