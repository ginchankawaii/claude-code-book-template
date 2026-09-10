import pandas as pd

from app.config import Settings
from app.engine import PaperTradingEngine
from app.indicators import enrich
from app.models import Signal
from app.providers.sample import SampleProvider
from app.strategies.technical import TechnicalStrategy


def _df(n=120):
    candles = SampleProvider(seed=3).history("USD_JPY", "M15", n)
    from app.indicators import candles_to_df
    return enrich(candles_to_df(candles))


def test_engine_opens_and_closes_with_pnl():
    cfg = Settings(initial_balance=100000)
    eng = PaperTradingEngine(0, "USD_JPY", TechnicalStrategy(), cfg, persist=False)
    df = _df()
    # force a long entry then a flat exit
    eng.step(df.iloc[:60], Signal(direction=1, score=0.9, reason="test long"))
    assert eng.state is not None and eng.state.position.units > 0
    eng.step(df, Signal(direction=0, score=0.0, reason="exit"))
    assert eng.state is None
    assert len(eng.closed_trades) == 1


def test_position_sizing_respects_cap():
    cfg = Settings(initial_balance=100000, risk_per_trade=0.99, max_position_units=5000)
    eng = PaperTradingEngine(0, "USD_JPY", TechnicalStrategy(), cfg, persist=False)
    df = _df()
    eng.step(df.iloc[:60], Signal(direction=1, score=0.9))
    assert abs(eng.state.position.units) <= 5000


def test_leverage_ceiling_caps_notional():
    # Tiny ATR + huge risk would size an absurd position; the leverage cap must
    # hold notional (units * price) at or below max_leverage * equity.
    cfg = Settings(initial_balance=100000, risk_per_trade=0.99,
                   max_position_units=10**12, max_leverage=5.0)
    eng = PaperTradingEngine(0, "USD_JPY", TechnicalStrategy(), cfg, persist=False)
    df = _df()
    eng.step(df.iloc[:60], Signal(direction=1, score=0.9))
    price = eng.state.position.entry_price
    notional = abs(eng.state.position.units) * price
    assert notional <= 5.0 * eng.balance * 1.001  # within rounding


def test_leverage_disabled_when_zero():
    cfg = Settings(initial_balance=100000, risk_per_trade=0.02,
                   max_position_units=10**12, max_leverage=0.0)
    eng = PaperTradingEngine(0, "USD_JPY", TechnicalStrategy(), cfg, persist=False)
    df = _df()
    eng.step(df.iloc[:60], Signal(direction=1, score=0.9))
    price = eng.state.position.entry_price
    # with the cap off, notional can exceed 5x (risk-based sizing rules)
    assert abs(eng.state.position.units) * price > 5.0 * eng.balance


def test_stop_loss_triggers():
    cfg = Settings(initial_balance=100000)
    eng = PaperTradingEngine(0, "USD_JPY", TechnicalStrategy(), cfg, persist=False)
    df = _df()
    eng.step(df.iloc[:60], Signal(direction=1, score=0.9))
    entry = eng.state.position.entry_price
    stop = eng.state.stop_price
    # craft a bar whose low pierces the stop
    bar = df.iloc[60:61].copy()
    bar.loc[bar.index[0], "low"] = stop - 0.5
    bar.loc[bar.index[0], "close"] = stop - 0.4
    # flat signal so the stop-out isn't immediately re-entered
    eng.step(bar, Signal.flat())
    assert eng.state is None
    assert eng.closed_trades[-1].reason == "stop-loss"
    assert entry > stop  # sanity: long stop is below entry


def test_equity_tracks_balance_when_flat():
    cfg = Settings(initial_balance=100000)
    eng = PaperTradingEngine(0, "USD_JPY", TechnicalStrategy(), cfg, persist=False)
    df = _df()
    eng.step(df, Signal.flat())
    assert eng.equity(df.iloc[-1]["close"]) == eng.balance
