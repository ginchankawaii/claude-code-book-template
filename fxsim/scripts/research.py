"""Overnight research harness: hunt for an edge that survives out-of-sample.

Principles (kept honest on purpose):
  * Costs dominate at high frequency -> favour low-frequency swing/trend systems.
  * Optimise on a TRAIN window, score only on the next TEST window (walk-forward).
    In-sample numbers are reported too, purely to expose the overfit gap.
  * Use the long 55y daily history for statistical weight; M15 month is a
    side sanity-check, never an optimisation target.

No look-ahead: a signal computed from data up to bar t sets the position held
over bar t+1. Costs are charged on position turnover.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import pip_size


# --------------------------------------------------------------------------- #
# data + indicators (computed inline for parameter flexibility)
# --------------------------------------------------------------------------- #
def to_df(candles) -> pd.DataFrame:
    return pd.DataFrame({
        "time": [c.time for c in candles],
        "open": [c.open for c in candles], "high": [c.high for c in candles],
        "low": [c.low for c in candles], "close": [c.close for c in candles],
    })


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


# --------------------------------------------------------------------------- #
# position generators: return target position in {-1,0,+1} decided AT bar t
# --------------------------------------------------------------------------- #
def pos_ma_cross(df, fast, slow):
    ef = df["close"].ewm(span=fast, adjust=False).mean()
    es = df["close"].ewm(span=slow, adjust=False).mean()
    return np.sign(ef - es)


def pos_tsmom(df, k):
    return np.sign(df["close"] - df["close"].shift(k))


def pos_donchian(df, n):
    hi = df["high"].rolling(n).max().shift(1)
    lo = df["low"].rolling(n).min().shift(1)
    pos = pd.Series(np.nan, index=df.index)
    pos[df["close"] >= hi] = 1.0
    pos[df["close"] <= lo] = -1.0
    return pos.ffill().fillna(0.0)


def pos_rsi_meanrev(df, period, lo, hi):
    d = df["close"].diff()
    g = d.clip(lower=0).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    ll = (-d.clip(upper=0)).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rsi = 100 - 100/(1 + g/ll)
    pos = pd.Series(np.nan, index=df.index)
    pos[rsi < lo] = 1.0       # oversold -> long
    pos[rsi > hi] = -1.0      # overbought -> short
    pos[(rsi > 45) & (rsi < 55)] = 0.0
    return pos.ffill().fillna(0.0)


def pos_buyhold(df):
    return pd.Series(1.0, index=df.index)


def pos_trend_filtered_mr(df, ma=200, period=14, lo=30, hi=70):
    """Mean-revert, but only in the direction of the long-term trend."""
    trend = np.sign(df["close"] - df["close"].rolling(ma).mean())
    mr = pos_rsi_meanrev(df, period, lo, hi)
    out = mr.copy()
    out[(trend > 0) & (mr < 0)] = 0.0   # no shorts in an uptrend
    out[(trend < 0) & (mr > 0)] = 0.0   # no longs in a downtrend
    return out


# --------------------------------------------------------------------------- #
# cost-aware backtest with optional volatility targeting
# --------------------------------------------------------------------------- #
def backtest(df, pos, instrument="USD_JPY", spread_pips=0.8, bars_per_year=252,
             vol_target=None, atr_n=14):
    pip = pip_size(instrument)
    close = df["close"].reset_index(drop=True)
    pos = pd.Series(pos).reset_index(drop=True).fillna(0.0)

    if vol_target is not None:
        a = atr(df, atr_n).reset_index(drop=True)
        unit_vol = (a / close).replace(0, np.nan)
        scale = (vol_target / np.sqrt(bars_per_year)) / unit_vol
        scale = scale.clip(upper=3.0).fillna(0.0)
        pos = (pos * scale)

    # return of bar t+1, position decided at t
    bar_ret = close.shift(-1) / close - 1.0
    gross = pos * bar_ret
    # cost on turnover (round-trip spread is spread_pips; per side half)
    cost_frac = (spread_pips * pip) / close
    turnover = pos.diff().abs().fillna(pos.abs())
    cost = turnover * cost_frac
    net = (gross - cost).fillna(0.0)
    eq = (1 + net).cumprod()
    return net, eq, pos


def metrics(net, eq, pos, bars_per_year=252):
    net = net.dropna()
    if len(net) == 0 or eq.iloc[-1] <= 0:
        return dict(ret=-100, cagr=-100, sharpe=0, maxdd=100, trades=0, exposure=0)
    yrs = len(net) / bars_per_year
    total = eq.iloc[-1] - 1
    cagr = eq.iloc[-1] ** (1/yrs) - 1 if yrs > 0 else 0
    sharpe = (net.mean() / net.std() * np.sqrt(bars_per_year)) if net.std() > 0 else 0
    roll_max = eq.cummax()
    maxdd = (1 - eq / roll_max).max()
    trades = int((pos.diff().abs() > 1e-9).sum())
    exposure = float((pos.abs() > 1e-9).mean())
    return dict(ret=total*100, cagr=cagr*100, sharpe=sharpe, maxdd=maxdd*100,
                trades=trades, exposure=exposure*100)
