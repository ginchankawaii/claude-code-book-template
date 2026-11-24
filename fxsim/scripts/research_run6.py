"""Strictest honesty check: choose the SMA length itself OUT-OF-SAMPLE via
walk-forward, so nothing is picked in hindsight. Also test a no-pick ensemble
and an ATR-trailing-stop overlay for drawdown control."""
from __future__ import annotations
import sys, os
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
os.chdir("/home/user/claude-code-book-template/fxsim")
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from app.providers.csv import load_csv_file
import scripts.research as R
from scripts.research_run import walk_forward


def load(since=None):
    cs = load_csv_file(Path("data/USD_JPY_D.csv"), "USD_JPY", "D")
    if since:
        cut=datetime(since,1,1,tzinfo=timezone.utc); cs=[c for c in cs if c.time>=cut]
    return R.to_df(cs)


def sma_filter_pos(df, n):
    return (df["close"] > df["close"].rolling(n).mean()).astype(float)


def trailing_overlay(df, pos, atr_mult=4.0, atr_n=14):
    """Flatten a long if price falls atr_mult*ATR below its peak since entry."""
    a = R.atr(df, atr_n).values
    close = df["close"].values
    p = pos.values.copy()
    in_pos = False; peak = 0.0
    for i in range(len(p)):
        if p[i] > 0 and not in_pos:
            in_pos = True; peak = close[i]
        elif p[i] > 0 and in_pos:
            peak = max(peak, close[i])
            if not np.isnan(a[i]) and close[i] < peak - atr_mult * a[i]:
                p[i] = 0.0; in_pos = False     # stopped out
        else:
            in_pos = False
    return pd.Series(p, index=pos.index)


def evalp(df, pos, spread=0.8, bpy=252):
    net, eq, p = R.backtest(df, pos, spread_pips=spread, vol_target=0.15)
    return R.metrics(net, eq, p, bpy), net


def main():
    grid = (100, 150, 200, 250)
    for since,lbl in [(2000,"2000+"),(2010,"2010+"),(2015,"2015+")]:
        df = load(since)
        nets = {f"sma{n}": evalp(df, sma_filter_pos(df, n))[1] for n in grid}
        oos, eq, picks = walk_forward(df, nets, folds=8)
        m = R.metrics(oos, eq, pd.Series(np.where(oos!=0,1,0)))
        bh,_ = evalp(df, R.pos_buyhold(df))
        # no-pick ensemble (avg of all SMA filters)
        ens = sum(sma_filter_pos(df,n) for n in grid)/len(grid)
        me,_ = evalp(df, ens)
        # ensemble + trailing stop
        mt,_ = evalp(df, trailing_overlay(df, (ens>0).astype(float)*ens))
        from collections import Counter
        pk = ",".join(f"{p}({c})" for p,c in Counter(picks).most_common())
        print(f"\n[{lbl}] {len(df)} bars")
        print(f"  buy&hold                       CAGR {bh['cagr']:+5.1f}%  Sharpe {bh['sharpe']:+5.2f}  maxDD {bh['maxdd']:5.1f}%")
        print(f"  trend, SMA chosen OOS (WF)     CAGR {m['cagr']:+5.1f}%  Sharpe {m['sharpe']:+5.2f}  maxDD {m['maxdd']:5.1f}%   picks {pk}")
        print(f"  trend ensemble (no pick)       CAGR {me['cagr']:+5.1f}%  Sharpe {me['sharpe']:+5.2f}  maxDD {me['maxdd']:5.1f}%")
        print(f"  ensemble + ATR4 trailing stop  CAGR {mt['cagr']:+5.1f}%  Sharpe {mt['sharpe']:+5.2f}  maxDD {mt['maxdd']:5.1f}%")
    print("\nDONE")

if __name__ == "__main__":
    main()
