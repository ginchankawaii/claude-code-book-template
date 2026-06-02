from app import indicators, market


def test_mock_history_is_deterministic():
    h1 = market.get_history("7203", days=60)
    h2 = market.get_history("7203", days=60)
    assert h1 == h2
    assert len(h1) > 0
    # 別銘柄は別系列
    assert market.get_history("6758", days=60)[-1]["close"] != h1[-1]["close"]


def test_history_fields():
    h = market.get_history("9984", days=30)
    row = h[-1]
    for key in ("date", "open", "high", "low", "close", "volume"):
        assert key in row
    assert row["high"] >= row["low"]


def test_quote_has_change():
    q = market.get_quote("7203")
    assert q["currency"] == "JPY"
    assert q["price"] > 0
    assert "change_pct" in q


def test_indicators_summarize():
    h = market.get_history("7203", days=120)
    s = indicators.summarize(h)
    assert s["sma5"] is not None
    assert s["sma25"] is not None
    assert s["trend"] in ("uptrend", "downtrend", "sideways", "unknown")
    assert 0 <= s["rsi14"] <= 100
