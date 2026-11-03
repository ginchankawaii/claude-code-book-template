"""Offline stock simulator: synthetic prices + in-memory margin book, and the
rule-based (no-key) picker. Lets the stock system be demoed without kabuステーション.
"""
from app.ai_stock_trader import RuleStockTrader, StockDecision
from app.brokers.kabu_sim import SimKabuStation


def test_sim_market_data_and_ranking():
    k = SimKabuStation(seed=1)
    k.step()
    assert k.trading_unit("7203") == 100
    assert k.price("7203") > 0
    # an unknown ticker still gets a deterministic synthetic price (Opus may pick it)
    assert k.price("9999") > 0
    turn = k.ranking(limit=5)
    assert len(turn) == 5 and turn[0] == "8306"          # most-liquid first (insertion order)
    assert isinstance(k.ranking("1", limit=3), list)      # momentum ranking


def test_sim_margin_buy_and_mark_to_market():
    k = SimKabuStation(start_cash=3_000_000.0, seed=2)
    k.step()
    p0 = k.price("8306")
    k.margin_buy("8306", 500)
    pos = k.positions()
    assert len(pos) == 1 and pos[0].symbol == "8306" and pos[0].qty == 500
    # margin power dropped by the entry notional; equity tracks unrealised PnL
    assert k.margin_power() < k.cash * k.leverage
    for _ in range(5):
        k.step()
    expected = k.cash + 500 * (k.price("8306") - p0)
    # price() rounds to 0.1 yen for display while equity marks the raw walk,
    # so allow a few sen per share of rounding slack.
    assert abs(k.total_assets() - expected) < 500 * 0.2


def test_sim_close_realises_pnl():
    k = SimKabuStation(seed=3)
    k.step()
    k.margin_buy("7203", 300)
    cash0 = k.cash
    k.step()
    k.margin_close_long("7203", 300)
    assert k.positions() == []
    assert k.cash != cash0          # PnL realised into cash (up or down)


def test_rule_picker_buys_top_unheld_and_holds_existing():
    trader = RuleStockTrader(max_positions=3)
    ctx = {"account": {"held": [{"symbol": "8306", "qty": 500, "price": 1700}]},
           "candidates": [{"symbol": s} for s in ["8306", "7203", "6758", "8316", "7267"]]}
    dec = trader.decide(ctx)
    assert isinstance(dec, StockDecision) and dec.ok
    actions = {c.symbol: c.action for c in dec.calls}
    assert actions["8306"] == "hold"        # already held & still top
    assert actions.get("7203") == "buy"     # top unheld -> buy
    buys = [c for c in dec.calls if c.action == "buy"]
    assert 0 < len(buys) <= 3 and all(0 < c.conviction <= 1 for c in buys)
