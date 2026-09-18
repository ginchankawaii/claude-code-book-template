"""Robust, low-parameter trend-regime tests.

Hypothesis: the durable edge in modern USD/JPY is not higher return but lower
drawdown — stay long only while the long-term trend is up, step aside otherwise.
Compare simple, fixed (non-optimised) trend filters against buy&hold on
risk-adjusted terms across multiple periods and a cost stress.
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
        cut=datetime(since,1,1,tzinfo=timezone.utc); cs=[c for c in cs if c.time>=cut]
    return R.to_df(cs), [c.time for c in cs]


def sma(s, n): return s.rolling(n).mean()


def variants(df):
    c = df["close"]
    up200 = (c > sma(c,200))
    up100 = (c > sma(c,100))
    mom200 = (c > c.shift(200))
    return {
        "buy&hold (always long)":      R.pos_buyhold(df),
        "long if >SMA200 else flat":   up200.astype(float),
        "long if >SMA100 else flat":   up100.astype(float),
        "long if 200d-mom>0 else flat": mom200.astype(float),
        "L/S by SMA200":               (up200.astype(float)*2-1),
        "long if >SMA200 AND mom>0":   (up200 & mom200).astype(float),
    }


def evalp(df, pos, spread=0.8, bpy=252):
    net, eq, p = R.backtest(df, pos, spread_pips=spread, vol_target=0.15)
    return R.metrics(net, eq, p, bpy), net


def main():
    for since,lbl in [(1990,"1990+"),(2000,"2000+"),(2010,"2010+"),(2015,"2015+"),(2020,"2020+")]:
        df,_ = load(since)
        print(f"\n{'='*92}\n[{lbl}]  {len(df)} bars   (vol-target 15%, spread 0.8p)\n{'='*92}")
        for name,pos in variants(df).items():
            m,_ = evalp(df,pos)
            star = " <--" if name.startswith("long if >SMA200 else") else ""
            print(f"  {name:30s} CAGR {m['cagr']:+5.1f}%  Sharpe {m['sharpe']:+5.2f}  "
                  f"maxDD {m['maxdd']:5.1f}%  exposure {m['exposure']:4.0f}%  trades {m['trades']}{star}")

    # cost stress + yearly for the SMA200 long-flat filter
    print(f"\n{'='*92}\nCOST STRESS  'long if >SMA200 else flat'  (2010+)\n{'='*92}")
    df,times = load(2010); c=df["close"]; pos=(c>sma(c,200)).astype(float)
    for sp in (0.8,1.5,3.0,5.0):
        m,_=evalp(df,pos,sp); print(f"  spread {sp:4.1f}p -> CAGR {m['cagr']:+5.1f}%  Sharpe {m['sharpe']:+5.2f}  maxDD {m['maxdd']:5.1f}%")
    print(f"\nYEAR-BY-YEAR  'long if >SMA200 else flat'  vs buy&hold (2010+)")
    _,net = evalp(df,pos); _,bh = evalp(df,R.pos_buyhold(df))
    sn=pd.Series(net.values,index=pd.DatetimeIndex(times)); sb=pd.Series(bh.values,index=pd.DatetimeIndex(times))
    yn=(1+sn).groupby(sn.index.year).prod()-1; yb=(1+sb).groupby(sb.index.year).prod()-1
    for y in yn.index:
        print(f"   {y}: filter {yn[y]*100:+6.1f}%   buy&hold {yb[y]*100:+6.1f}%")
    print(f"  filter positive years: {(yn>0).sum()}/{len(yn)}   buy&hold: {(yb>0).sum()}/{len(yb)}")
    print("\nDONE")

if __name__ == "__main__":
    main()
