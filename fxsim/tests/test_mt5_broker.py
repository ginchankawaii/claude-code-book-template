from app.brokers import MT5Broker, to_mt5_symbol


def test_symbol_conversion():
    assert to_mt5_symbol("USD_JPY") == "USDJPY"
    assert to_mt5_symbol("EUR/USD") == "EURUSD"


def test_broker_constructs_without_metatrader5_installed():
    # construction must not import MetaTrader5 (lazy), so backtests work on Linux
    b = MT5Broker("USD_JPY", dry_run=True, max_lots=2.0)
    assert b.symbol == "USDJPY" and b.dry_run is True and b.max_lots == 2.0
