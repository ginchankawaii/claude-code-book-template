import pytest

from app import engine


def test_initial_portfolio():
    p = engine.get_portfolio()
    assert p["cash"] == 1_000_000.0
    assert p["total_value"] == 1_000_000.0
    assert p["holdings"] == []


def test_buy_updates_cash_and_holdings():
    engine.buy("7203", 100, price=2000.0)
    p = engine.get_portfolio()
    assert p["cash"] == pytest.approx(1_000_000.0 - 200_000.0)
    assert len(p["holdings"]) == 1
    h = p["holdings"][0]
    assert h["code"] == "7203"
    assert h["quantity"] == 100
    assert h["avg_cost"] == pytest.approx(2000.0)


def test_buy_averages_cost():
    engine.buy("7203", 100, price=2000.0)
    engine.buy("7203", 100, price=3000.0)
    p = engine.get_portfolio()
    h = p["holdings"][0]
    assert h["quantity"] == 200
    assert h["avg_cost"] == pytest.approx(2500.0)


def test_insufficient_cash_raises():
    with pytest.raises(engine.TradeError):
        engine.buy("7203", 100, price=99_999_999.0)


def test_sell_realizes_pl_and_removes_holding():
    engine.buy("7203", 100, price=2000.0)
    res = engine.sell("7203", 100, price=2500.0)
    assert res["realized_pl"] == pytest.approx(50_000.0)
    p = engine.get_portfolio()
    assert p["holdings"] == []
    assert p["cash"] == pytest.approx(1_000_000.0 + 50_000.0)


def test_sell_more_than_held_raises():
    engine.buy("7203", 100, price=2000.0)
    with pytest.raises(engine.TradeError):
        engine.sell("7203", 200, price=2000.0)


def test_trades_recorded():
    engine.buy("7203", 100, price=2000.0)
    engine.sell("7203", 100, price=2100.0)
    trades = engine.list_trades()
    assert len(trades) == 2
    assert trades[0]["side"] == "SELL"  # 新しい順
    assert trades[1]["side"] == "BUY"
