"""Scratch: money added at once vs in parts. Value of the ADDED money at t0+H years, as a percentage of it
(1% of 1,000,000 added = 10,000 JPY). Uses the 1,000,000-JPY replay equity curve as the growth index
(closed-bar cadence, nine lengths). NOTE: this values the money as if it joined the open position at once,
which the live brain does not do; see stage_live.py for the live rule."""
import numpy as np, pandas as pd
import rp
from scripts import research_harness as H
from scripts import monitor_envelope as M
A = M._arrays(); sec = A["sec"][H.WARMUP:]
LENS = list(range(2000, 2801, 100)); ADD = 100.0   # per cent of the added money
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
    print(f"\n--- gain on the added money after {Hy} year(s), % of the added money (nine lengths pooled) ---")
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
        print(f"{name:32s} mean {v.mean():+7.2f}%  median {np.median(v):+7.2f}%  p10 {np.percentile(v,10):+7.2f}%  worst {v.min():+7.2f}%"
              f"  loss {np.mean(v<0)*100:4.1f}%  worse than -10%: {np.mean(v<-10)*100:4.1f}%  | vs lump: mean {np.mean(v-base):+6.2f} pt, better in {np.mean(v>base)*100:4.1f}%")
