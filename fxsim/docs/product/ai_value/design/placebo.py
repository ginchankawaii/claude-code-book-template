"""NULL distribution only: windows at RANDOM bars (no event calendar is used anywhere).
A = no NEW entry inside the window; B = flat inside the window, re-enter after by the rule.
Operating point: 272,000 JPY, 0.01 lot. Cadence 'close' (the backtest look) for speed."""
import sys, time, json, numpy as np, pandas as pd
from scripts import research_harness as H
from scripts import monitor_envelope as M
import rp
A_ = M._arrays(); n = len(A_["cl"]); yrs = None
def windows(rng, per_year, X):
    idx = np.arange(H.WARMUP+X, n)
    k = int(round(per_year * (n-H.WARMUP)/ (24*5*52.0)))   # ~6240 trading hours a year
    ev = rng.choice(idx, size=k, replace=False)
    m = np.zeros(n, bool)
    for e in ev: m[e-X:e+1] = True
    return m, k
def run(n_sma, eb=None, xb=None, cad="close"):
    return rp.replay(cad, 5, n_sma, 272000.0, 1000, entry_block=eb, exit_block=xb, keep=True)
mode = sys.argv[1]; draws = int(sys.argv[2]); out = sys.argv[3]
lengths = [2400] if mode == "one" else list(range(2000,2801,100))
base = {L: run(L) for L in lengths}
base_entries = {L: np.array([x["i"] for x in base[L]["log"]]) for L in lengths}
print("baseline", {L: (round(base[L]["cagr"],2), round(base[L]["mdd"],1), base[L]["entries"]) for L in lengths}, flush=True)
rows = []
t0 = time.time()
for X in (6, 24):
    for d in range(draws):
        rng = np.random.default_rng(1000*X + d)
        m, k = windows(rng, 40, X)
        for L in lengths:
            a = run(L, eb=m); b = run(L, xb=m)
            rows.append(dict(X=X, d=d, L=L, k=k, frac=float(m[H.WARMUP:].mean()),
                             hit=int(m[base_entries[L]].sum()),
                             dA=a["cagr"]-base[L]["cagr"], dB=b["cagr"]-base[L]["cagr"],
                             ddA=a["mdd"]-base[L]["mdd"], ddB=b["mdd"]-base[L]["mdd"],
                             entA=a["entries"], entB=b["entries"]))
        if d % 20 == 0: print(X, d, round(time.time()-t0), flush=True)
pd.DataFrame(rows).to_csv(out, index=False)
