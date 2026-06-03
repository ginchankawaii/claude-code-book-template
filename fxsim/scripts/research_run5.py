"""Robustness of the SMA length (overfit check) + equity-curve chart via the
real engine."""
from __future__ import annotations
import sys, os
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
os.chdir("/home/user/claude-code-book-template/fxsim")
from datetime import datetime, timezone
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
    name="buyhold"; w_tech=1.0; w_fund=0.0
    last_technical=Signal.flat(); last_fundamental=Signal.flat()
    def generate(self, instrument, df): return Signal(1,0.6,"always long")


def run(strat, candles, use_tp, want_curve=False):
    cfg=Settings(fundamental_mode="stub",granularity="D",initial_balance=100000,use_take_profit=use_tp)
    df=enrich(candles_to_df(candles)); eng=PaperTradingEngine(0,"USD_JPY",strat,cfg,persist=False)
    for i in range(WARMUP,len(df)):
        w=df.iloc[:i+1]; eng.step(w,strat.generate("USD_JPY",w))
    eng.force_close(df)
    s=compute_stats(0,"USD_JPY",cfg.initial_balance,eng.equity_curve,eng.closed_trades)
    if want_curve:
        return s,[p[0] for p in eng.equity_curve],[p[2] for p in eng.equity_curve]
    return s


def main():
    allc=load_csv_file(Path("data/USD_JPY_D.csv"),"USD_JPY","D")
    def sl(y): cut=datetime(y,1,1,tzinfo=timezone.utc); return [c for c in allc if c.time>=cut]

    print("SMA-length robustness (overfit check) — REAL engine, trend long/flat")
    for y,lbl in [(2010,"2010+"),(2015,"2015+"),(2020,"2020+")]:
        cs=sl(y); print(f"\n[{lbl}]")
        for n in (50,100,150,200,250):
            s=run(TrendRegimeStrategy(sma=n),cs,use_tp=False)
            print(f"  SMA{n:3d}: ret {s.total_return_pct:+8.1f}%  maxDD {s.max_drawdown_pct:5.1f}%  "
                  f"Sharpe {s.sharpe:+5.2f}  trades {s.num_trades}")

    # chart on 2010+
    cs=sl(2010)
    s_t,t_t,e_t=run(TrendRegimeStrategy(sma=150),cs,use_tp=False,want_curve=True)
    s_b,t_b,e_b=run(AlwaysLong(),cs,use_tp=False,want_curve=True)
    s_m,t_m,e_m=run(AIDecisionStrategy(cfg=Settings(fundamental_mode='stub',granularity='D'),
                    fundamental_mode='stub',decider=RuleDecider()),cs,use_tp=True,want_curve=True)
    fig,ax=plt.subplots(figsize=(11,6))
    ax.plot(t_m,e_m,color="tab:red",lw=1.3,label=f"mechanical rule (your EA type): {s_m.total_return_pct:+.0f}%, Sharpe {s_m.sharpe:.2f}")
    ax.plot(t_b,e_b,color="gray",lw=1.3,label=f"buy & hold: {s_b.total_return_pct:+.0f}%, Sharpe {s_b.sharpe:.2f}")
    ax.plot(t_t,e_t,color="tab:green",lw=1.8,label=f"TREND SMA150 long/flat: {s_t.total_return_pct:+.0f}%, Sharpe {s_t.sharpe:.2f}, {s_t.num_trades} trades")
    ax.axhline(100000,color="black",ls="--",lw=0.6)
    ax.set_title("USD/JPY daily 2010-2026 (real engine): trend-regime beats buy&hold; mechanical bleeds")
    ax.set_ylabel("equity (JPY)"); ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig("data/trend_vs_all.png",dpi=110); print("\nsaved data/trend_vs_all.png\nDONE")

if __name__ == "__main__":
    main()
