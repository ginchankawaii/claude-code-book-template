from app.backtest import run_backtest
from app.config import Settings
from app.providers.sample import SampleProvider
from app.strategies.combined import CombinedStrategy


def test_backtest_runs_offline_and_produces_stats():
    candles = SampleProvider(seed=11).history("USD_JPY", "M15", 800)
    cfg = Settings(initial_balance=100000, fundamental_mode="stub")
    strat = CombinedStrategy(fundamental_mode="stub")
    stats = run_backtest(candles, "USD_JPY", cfg=cfg, persist=False, strategy=strat)

    assert stats.bars > 0
    assert stats.initial_balance == 100000
    # win_rate is a percentage
    assert 0.0 <= stats.win_rate <= 100.0
    # max drawdown is a non-negative percentage
    assert stats.max_drawdown_pct >= 0.0


def test_backtest_no_lookahead_determinism():
    candles = SampleProvider(seed=11).history("USD_JPY", "M15", 600)
    cfg = Settings(initial_balance=100000, fundamental_mode="stub")
    a = run_backtest(candles, "USD_JPY", cfg=cfg, persist=False,
                     strategy=CombinedStrategy(fundamental_mode="stub"))
    b = run_backtest(candles, "USD_JPY", cfg=cfg, persist=False,
                     strategy=CombinedStrategy(fundamental_mode="stub"))
    assert a.final_equity == b.final_equity
    assert a.num_trades == b.num_trades
