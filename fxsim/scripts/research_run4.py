"""Validate TrendRegimeStrategy through the REAL PaperTradingEngine (with costs,
ATR stop, sizing) — not just the vectorized model — vs always-long and the
mechanical rule strategy."""
from __future__ import annotations
import sys, os
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
os.chdir("/home/user/claude-code-book-template/fxsim")
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from app.providers.csv import load_csv_file
from app.indicators import enrich, candles_to_df
from app.engine import PaperTradingEngine
from app.backtest import WARMUP, compute_stats
from app.config import Settings
from app.models import Signal
from app.strategies.base import Strategy
from app.strategies.trend import TrendRegimeStrategy
from app.strategies.ai import AIDecisionStrategy, RuleDecider


class AlwaysLong(Strategy):
    name = "buyhold"
    w_tech = 1.0; w_fund = 0.0
    last_technical = Signal.flat(); last_fundamental = Signal.flat()
    def generate(self, instrument, df):
        return Signal(1, 0.6, "always long")


def run(strat, candles, use_tp):
    cfg = Settings(fundamental_mode="stub", granularity="D", initial_balance=100000,
                   use_take_profit=use_tp)
    df = enrich(candles_to_df(candles)); eng = PaperTradingEngine(0,"USD_JPY",strat,cfg,persist=False)
    for i in range(WARMUP, len(df)):
        w = df.iloc[:i+1]; eng.step(w, strat.generate("USD_JPY", w))
    eng.force_close(df)
    return compute_stats(0,"USD_JPY",cfg.initial_balance,eng.equity_curve,eng.closed_trades)


def main():
    allc = load_csv_file(Path("data/USD_JPY_D.csv"), "USD_JPY", "D")
    def sl(y): cut=datetime(y,1,1,tzinfo=timezone.utc); return [c for c in allc if c.time>=cut]
    for y,lbl in [(2010,"2010+"),(2015,"2015+"),(2020,"2020+")]:
        cs = sl(y)
        print(f"\n{'='*84}\n[{lbl}] {len(cs)} daily bars  (REAL engine, spread 0.8p, risk 2%/trade)\n{'='*84}")
        rows = [
            ("always-long (buy&hold)", run(AlwaysLong(), cs, use_tp=False)),
            ("mechanical rule",        run(AIDecisionStrategy(cfg=Settings(fundamental_mode='stub',granularity='D'),
                                           fundamental_mode='stub', decider=RuleDecider()), cs, use_tp=True)),
            ("TREND SMA200 (long/flat)", run(TrendRegimeStrategy(sma=200), cs, use_tp=False)),
            ("TREND SMA100 (long/flat)", run(TrendRegimeStrategy(sma=100), cs, use_tp=False)),
        ]
        for name,s in rows:
            print(f"  {name:26s} trades {s.num_trades:4d}  win {s.win_rate:4.0f}%  "
                  f"ret {s.total_return_pct:+8.1f}%  maxDD {s.max_drawdown_pct:5.1f}%  Sharpe {s.sharpe:+5.2f}  final {s.final_equity:,.0f}")
    print("\nDONE")

if __name__ == "__main__":
    main()
