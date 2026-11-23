"""Scratch: 700,000 JPY added at once vs in three parts. Value of the ADDED money at t0+H years.
Uses the 1,000,000-JPY replay equity curve as the growth index (closed-bar cadence, nine lengths)."""
import numpy as np, pandas as pd
import rp
from scripts import research_harness as H
from scripts import monitor_envelope as M
A = M._arrays(); sec = A["sec"][H.WARMUP:]
LENS = list(range(2000, 2801, 100)); ADD = 700_000.0
DAY = 86400; MO = 30.44*DAY
def idx(t):  # bar index at/after timestamp array t
    return np.searchsorted(sec, t)
plans = {
  "lump now":                     [(0.0, 1.0)],
  "3 parts: now / +3m / +6m":     [(0, 1/3), (3, 1/3), (6, 1/3)],
  "3 parts: +1.5m / +4.5m / +7.5m": [(1.5, 1/3), (4.5, 1/3), (7.5, 1/3)],
  "lump at +1.5m":                [(1.5, 1.0)],
  "2 parts: +1.5m / +4.5m":       [(1.5, 0.5), (4.5, 0.5)],
}
eqs = [rp.replay("closedbar", 5, n, 1_000_000.0, 1000)["eq"] for n in LENS]
for Hy in (1, 2, 3):
    print(f"\n--- value of the added 700,000 after {Hy} year(s) from today (nine lengths pooled) ---")
    base = None
    for name, plan in plans.items():
        allv = []; worst_path = []
        for eq in eqs:
            T = idx(sec + int(Hy*365.25*DAY)); ok = T < len(sec); i0 = np.nonzero(ok)[0]
            val = np.zeros(len(i0)); lowest = np.full(len(i0), np.inf)
            for m, w in plan:
                ti = idx(sec[i0] + int(m*MO))
                val += ADD*w * eq[T[ok]] / eq[ti]
            allv.append(val)
        v = np.concatenate(allv) - ADD
        if base is None: base = v
        print(f"{name:32s} mean {v.mean():+9,.0f}  median {np.median(v):+9,.0f}  p10 {np.percentile(v,10):+9,.0f}  worst {v.min():+9,.0f}"
              f"  loss {np.mean(v<0)*100:4.1f}%  <-70k {np.mean(v<-70_000)*100:4.1f}%  | vs lump: mean {np.mean(v-base):+8,.0f}, better in {np.mean(v>base)*100:4.1f}%")
