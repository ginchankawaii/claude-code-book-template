import pandas as pd

from app.strategies.trend import TrendRegimeStrategy


def _df(prices):
    return pd.DataFrame({
        "time": pd.date_range("2020-01-01", periods=len(prices), freq="D"),
        "open": prices, "high": prices, "low": prices, "close": prices, "volume": 0,
    })


def test_long_when_above_sma():
    # rising series: last close sits well above its trailing average
    prices = [100 + i for i in range(60)]
    sig = TrendRegimeStrategy(sma=50).generate("USD_JPY", _df(prices))
    assert sig.direction == 1 and sig.score > 0


def test_flat_when_below_sma():
    # falling series: last close below its trailing average -> stand aside
    prices = [200 - i for i in range(60)]
    sig = TrendRegimeStrategy(sma=50).generate("USD_JPY", _df(prices))
    assert sig.direction == 0 and sig.score == 0.0


def test_warmup_is_flat():
    sig = TrendRegimeStrategy(sma=200).generate("USD_JPY", _df([150.0] * 10))
    assert sig.direction == 0


def test_build_strategy_selects_trend():
    from app.config import Settings
    from app.strategies import build_strategy
    s = build_strategy(Settings(strategy="trend", trend_sma=100))
    assert isinstance(s, TrendRegimeStrategy) and s.sma == 100
