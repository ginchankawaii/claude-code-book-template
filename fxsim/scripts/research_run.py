"""Run the research harness with walk-forward out-of-sample evaluation."""
from __future__ import annotations

import sys, os
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
os.chdir("/home/user/claude-code-book-template/fxsim")
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.providers.csv import load_csv_file
import scripts.research as R


def load(gran, since=None):
    f = "data/USD_JPY_D.csv" if gran == "D" else "data/USD_JPY_M15.csv"
    cs = load_csv_file(Path(f), "USD_JPY", gran)
    if since:
        cut = datetime(since, 1, 1, tzinfo=timezone.utc)
        cs = [c for c in cs if c.time >= cut]
    return R.to_df(cs)


def walk_forward(df, family_nets: dict, folds=8, bpy=252):
    """family_nets: {param_label: net_series(full)}. Expanding train, rolling test."""
    n = len(df)
    edges = [int(n * i / folds) for i in range(folds + 1)]
    oos = pd.Series(0.0, index=range(n))
    picks = []
    for k in range(1, folds):                       # first fold is train-only seed
        tr0, tr1 = 0, edges[k]
        te0, te1 = edges[k], edges[k + 1]
        best, best_s = None, -1e9
        for label, net in family_nets.items():
            seg = net.iloc[tr0:tr1].dropna()
            s = (seg.mean()/seg.std()*np.sqrt(bpy)) if seg.std() > 0 else -1e9
            if s > best_s:
                best_s, best = s, label
        picks.append(best)
        oos.iloc[te0:te1] = family_nets[best].iloc[te0:te1].fillna(0.0).values
    eq = (1 + oos).cumprod()
    return oos, eq, picks


def family(df, name):
    """Return {label: net_series} for a strategy family across its param grid."""
    out = {}
    def bt(pos, vt=None):
        net, eq, p = R.backtest(df, pos, vol_target=vt)
        return net
    if name == "ma_cross":
        for fast in (10, 20, 50):
            for slow in (50, 100, 200):
                if fast < slow:
                    out[f"ma{fast}/{slow}"] = bt(R.pos_ma_cross(df, fast, slow), vt=0.15)
    elif name == "tsmom":
        for k in (20, 40, 60, 90, 120, 250):
            out[f"mom{k}"] = bt(R.pos_tsmom(df, k), vt=0.15)
    elif name == "donchian":
        for nn in (20, 40, 55, 100):
            out[f"don{nn}"] = bt(R.pos_donchian(df, nn), vt=0.15)
    elif name == "rsi_mr":
        for per in (2, 7, 14):
            for lo, hi in ((10, 90), (20, 80), (30, 70)):
                out[f"rsi{per}/{lo}-{hi}"] = bt(R.pos_rsi_meanrev(df, per, lo, hi))
    elif name == "trend_mr":
        for ma in (100, 200):
            for per in (2, 14):
                out[f"tmr{ma}/{per}"] = bt(R.pos_trend_filtered_mr(df, ma, per), vt=0.15)
    return out


def report(title, df, since_label, bpy=252):
    print(f"\n{'='*78}\n{title}  ({since_label}, {len(df)} bars)\n{'='*78}")
    # baseline buy & hold
    bh_net, bh_eq, bh_pos = R.backtest(df, R.pos_buyhold(df), vol_target=0.15)
    bm = R.metrics(bh_net, bh_eq, bh_pos, bpy)
    print(f"{'[baseline] buy&hold (vol-tgt)':28s} OOS  ret {bm['ret']:+8.1f}%  CAGR {bm['cagr']:+6.1f}%  "
          f"Sharpe {bm['sharpe']:+5.2f}  maxDD {bm['maxdd']:5.1f}%  trades {bm['trades']}")
    results = []
    for fam in ("ma_cross", "tsmom", "donchian", "rsi_mr", "trend_mr"):
        nets = family(df, fam)
        if not nets:
            continue
        # in-sample best (overfit reference)
        is_best, is_s = None, -1e9
        for lbl, net in nets.items():
            seg = net.dropna()
            s = seg.mean()/seg.std()*np.sqrt(bpy) if seg.std() > 0 else -1e9
            if s > is_s: is_s, is_best = s, lbl
        # walk-forward OOS
        oos, eq, picks = walk_forward(df, nets, bpy=bpy)
        m = R.metrics(oos, eq, pd.Series(np.where(oos!=0,1,0)), bpy)
        # recompute trades/exposure from chosen positions is complex; report return-based
        from collections import Counter
        pk = ",".join(f"{p}" for p,_ in Counter(picks).most_common(3))
        print(f"{fam:12s} IS-best {is_best:14s}  ->  OOS ret {m['ret']:+8.1f}%  CAGR {m['cagr']:+6.1f}%  "
              f"Sharpe {m['sharpe']:+5.2f}  maxDD {m['maxdd']:5.1f}%   picks: {pk}")
        results.append((fam, m, is_best, picks))
    return results


if __name__ == "__main__":
    for since, lbl in [(None, "1971+"), (2000, "2000+"), (2010, "2010+")]:
        df = load("D", since)
        report(f"DAILY trend/MR families, walk-forward OOS", df, lbl)
    print("\nDONE")
