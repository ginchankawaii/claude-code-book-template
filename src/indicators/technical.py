"""Technical indicators for swing trading signals."""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """全テクニカル指標を計算して DataFrame に追加。"""
    df = df.copy()
    df = _add_moving_averages(df)
    df = _add_rsi(df)
    df = _add_macd(df)
    df = _add_bollinger_bands(df)
    df = _add_atr(df)
    df = _add_adx(df)
    df = _add_volume_indicators(df)
    df = _add_momentum(df)
    df.dropna(inplace=True)
    return df


def _add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    for period in [20, 50, 200]:
        df[f"sma{period}"] = df["close"].rolling(period).mean()
        df[f"ema{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def _add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    # RSIの方向性（直近3日の変化）
    df["rsi_slope"] = df["rsi"].diff(3)
    return df


def _add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    # ゴールデンクロス検出（当日がクロス）
    df["macd_cross_up"] = (df["macd"] > df["macd_signal"]) & (
        df["macd"].shift(1) <= df["macd_signal"].shift(1)
    )
    df["macd_cross_down"] = (df["macd"] < df["macd_signal"]) & (
        df["macd"].shift(1) >= df["macd_signal"].shift(1)
    )
    return df


def _add_bollinger_bands(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    mid = df["close"].rolling(period).mean()
    sigma = df["close"].rolling(period).std()
    df["bb_upper"] = mid + std * sigma
    df["bb_mid"] = mid
    df["bb_lower"] = mid - std * sigma
    # %B: 0=下限, 0.5=中央, 1=上限
    band_width = df["bb_upper"] - df["bb_lower"]
    df["bb_pct"] = (df["close"] - df["bb_lower"]) / band_width.replace(0, np.nan)
    df["bb_width"] = band_width / mid  # バンド幅（ボラティリティ指標）
    return df


def _add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = true_range.ewm(com=period - 1, min_periods=period).mean()
    df["atr_pct"] = df["atr"] / df["close"]  # ATR / 終値（正規化）
    return df


def _add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ADX（トレンド強度）と +DI/-DI を計算。"""
    high_diff = df["high"].diff()
    low_diff = -df["low"].diff()

    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0.0)
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0.0)

    true_range = _true_range_series(df)
    atr = true_range.ewm(com=period - 1, min_periods=period).mean()

    plus_di = 100 * plus_dm.ewm(com=period - 1, min_periods=period).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(com=period - 1, min_periods=period).mean() / atr.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(com=period - 1, min_periods=period).mean()
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    return df


def _true_range_series(df: pd.DataFrame) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    return pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)


def _add_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_sma20"].replace(0, np.nan)
    # OBV（On-Balance Volume）
    obv = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()
    df["obv"] = obv
    df["obv_sma20"] = df["obv"].rolling(20).mean()
    return df


def _add_momentum(df: pd.DataFrame) -> pd.DataFrame:
    for n in [5, 10, 21]:
        df[f"ret{n}"] = df["close"].pct_change(n)
    # 52週高値からの距離
    df["high52w"] = df["high"].rolling(252).max()
    df["pct_from_high52w"] = (df["close"] - df["high52w"]) / df["high52w"]
    return df
