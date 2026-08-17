import pandas as pd

from app.indicators import bollinger, ema, enrich, macd, rsi, sma


def _series():
    return pd.Series([float(x) for x in range(1, 60)])


def test_sma_ema_basic():
    s = _series()
    assert sma(s, 5).iloc[-1] == s.iloc[-5:].mean()
    # EMA of a rising line is below the latest value but above SMA
    assert ema(s, 5).iloc[-1] < s.iloc[-1]


def test_rsi_bounds():
    s = _series()  # strictly increasing -> RSI near 100
    r = rsi(s, 14)
    assert (r.dropna() >= 0).all() and (r.dropna() <= 100).all()
    assert r.iloc[-1] > 70


def test_macd_shapes():
    s = _series()
    m, sig, hist = macd(s)
    assert len(m) == len(s) == len(sig) == len(hist)


def test_bollinger_order():
    s = _series()
    lower, mid, upper = bollinger(s, 20, 2.0)
    assert lower.iloc[-1] <= mid.iloc[-1] <= upper.iloc[-1]


def test_enrich_columns():
    df = pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=60, freq="h"),
        "open": range(60), "high": range(1, 61), "low": range(60),
        "close": range(60), "volume": [100] * 60,
    })
    out = enrich(df)
    for col in ["sma_fast", "rsi", "macd_hist", "bb_upper", "atr"]:
        assert col in out.columns
