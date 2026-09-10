"""Pure-pandas technical indicators (no external TA dependency)."""
from __future__ import annotations

import pandas as pd

from .models import Candle


def candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "time": [c.time for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    )
    return df


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    # avg_loss == 0 with gains => rs=inf => RSI=100; both zero => NaN => neutral 50.
    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    out = out.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return out.fillna(50.0)


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return lower, mid, upper


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Attach all indicator columns the technical strategy needs."""
    out = df.copy()
    close = out["close"]
    out["sma_fast"] = sma(close, 10)
    out["sma_slow"] = sma(close, 30)
    out["ema_fast"] = ema(close, 12)
    out["ema_slow"] = ema(close, 26)
    out["rsi"] = rsi(close, 14)
    macd_line, signal_line, hist = macd(close)
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    lower, mid, upper = bollinger(close, 20, 2.0)
    out["bb_lower"] = lower
    out["bb_mid"] = mid
    out["bb_upper"] = upper
    out["atr"] = atr(out, 14)
    return out
