"""Deeper validation of the momentum/trend edge found in research_run.py.

Focus: a low-parameter DIVERSIFIED momentum ensemble (consensus of several
lookbacks) — harder to overfit than a single tuned lookback — stress-tested on
cost, direction (long-only vs long/short), and year-by-year consistency.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
os.chdir("/home/user/claude-code-book-template/fxsim")
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from app.providers.csv import load_csv_file
import scripts.research as R


def load(since=None):
    cs = load_csv_file(Path("data/USD_JPY_D.csv"), "USD_JPY", "D")
    if since:
        cut = datetime(since,1,1,tzinfo=timezone.utc); cs=[c for c in cs if c.time>=cut]
    return R.to_df(cs), [c.time for c in cs]


def ensemble_pos(df, lookbacks=(40,80,120,200,250), long_only=False):
    """Consensus momentum: average sign across lookbacks -> position in [-1,1]."""
    sig = sum(np.sign(df["close"] - df["close"].shift(k)) for k in lookbacks) / len(lookbacks)
    if long_only:
        sig = sig.clip(lower=0.0)
    return sig


def evalp(df, pos, spread, times=None, bpy=252):
    net, eq, p = R.backtest(df, pos, spread_pips=spread, vol_target=0.15)
    m = R.metrics(net, eq, p, bpy)
    return m, net, eq


def main():
    print("="*86)
    print("DIVERSIFIED MOMENTUM ENSEMBLE  (consensus of 40/80/120/200/250-day, vol-target 15%)")
    print("="*86)
    for since,lbl in [(None,"1971+"),(2000,"2000+"),(2010,"2010+"),(2015,"2015+")]:
        df,times = load(since)
        bh,_,_ = evalp(df, R.pos_buyhold(df), 0.8)
        ls,_,_ = evalp(df, ensemble_pos(df), 0.8)
        lo,_,_ = evalp(df, ensemble_pos(df, long_only=True), 0.8)
        print(f"\n[{lbl}] {len(df)} bars")
        print(f"  buy&hold        ret {bh['ret']:+8.1f}%  CAGR {bh['cagr']:+5.1f}%  Sharpe {bh['sharpe']:+5.2f}  maxDD {bh['maxdd']:5.1f}%")
        print(f"  momentum L/S    ret {ls['ret']:+8.1f}%  CAGR {ls['cagr']:+5.1f}%  Sharpe {ls['sharpe']:+5.2f}  maxDD {ls['maxdd']:5.1f}%  trades {ls['trades']}")
        print(f"  momentum LONG   ret {lo['ret']:+8.1f}%  CAGR {lo['cagr']:+5.1f}%  Sharpe {lo['sharpe']:+5.2f}  maxDD {lo['maxdd']:5.1f}%  trades {lo['trades']}")

    print("\n"+"="*86)
    print("COST STRESS (2010+, momentum L/S ensemble)")
    print("="*86)
    df,_ = load(2010)
    for sp in (0.8, 1.5, 3.0, 5.0, 10.0):
        m,_,_ = evalp(df, ensemble_pos(df), sp)
        print(f"  spread {sp:4.1f} pips ->  CAGR {m['cagr']:+5.1f}%  Sharpe {m['sharpe']:+5.2f}  maxDD {m['maxdd']:5.1f}%")

    print("\n"+"="*86)
    print("YEAR-BY-YEAR (2010+, momentum L/S ensemble)")
    print("="*86)
    df,times = load(2010)
    net,eq,pos = R.backtest(df, ensemble_pos(df), spread_pips=0.8, vol_target=0.15)
    s = pd.Series(net.values, index=pd.DatetimeIndex(times))
    yr = (1+s).groupby(s.index.year).prod()-1
    pos_years = (yr>0).sum(); tot=len(yr)
    line = "  ".join(f"{y}:{v*100:+5.1f}%" for y,v in yr.items())
    print(" "+line)
    print(f"  positive years: {pos_years}/{tot} ({pos_years/tot*100:.0f}%)")
    print("\nDONE")

if __name__ == "__main__":
    main()
