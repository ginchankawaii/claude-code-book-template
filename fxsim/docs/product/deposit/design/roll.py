"""Scratch: if 1,000,000 JPY had been put in on a random day, where was it 1/2/3 years later?
Replay = rp.replay (closed-bar cadence, 0.01-lot steps), nine SMA lengths 2000..2800."""
import numpy as np, pandas as pd
import rp
from scripts import research_harness as H
from scripts import monitor_envelope as M

A = M._arrays(); t = pd.to_datetime(A["t"][H.WARMUP:]); sec = A["sec"][H.WARMUP:]
LENS = list(range(2000, 2801, 100))
BAL = 1_000_000.0
def stats(eq, yrs):
    # for each start bar, the equity ratio after `yrs` years (by timestamp)
    tgt = sec + int(yrs*365.25*86400)
    j = np.searchsorted(sec, tgt)
    ok = j < len(sec)
    return eq[j[ok]] / eq[np.nonzero(ok)[0]] - 1.0
res = {1: [], 2: [], 3: []}; dd_yen = []; uw = []
for risk in (0.04, 0.024):
    rp.RISK = risk
    per = {1: [], 2: [], 3: []}; cg = []; md = []
    for n in LENS:
        r = rp.replay("closedbar", 5, n, BAL, 1000); eq = r["eq"]
        cg.append(r["cagr"]); md.append(r["mdd"])
        for y in per: per[y].append(stats(eq, y))
        if risk == 0.04:
            peak = np.maximum.accumulate(eq)
            # longest stretch below a previous peak, in years
            under = eq < peak - 1e-9; best = cur = 0
            for k in range(len(eq)):
                cur = cur + 1 if under[k] else 0; best = max(best, cur)
            uw.append(best / (len(eq) / r["years"]))
    print(f"\nRISK={risk}: nine-length mean CAGR {np.mean(cg):.2f}%  mean maxDD {np.mean(md):.1f}%  worst maxDD {np.max(md):.1f}%   SMA2400 {cg[4]:.2f}% / {md[4]:.1f}%")
    for y in per:
        allr = np.concatenate(per[y]); one = per[y][4]
        f = lambda a: (f"loss in {np.mean(a<0)*100:4.1f}% of starts | worse than -10%: {np.mean(a<-0.10)*100:4.1f}% | worse than -20%: {np.mean(a<-0.20)*100:4.1f}% | "
                       f"p10 {np.percentile(a,10)*100:+6.1f}% median {np.median(a)*100:+6.1f}% p90 {np.percentile(a,90)*100:+6.1f}% worst {a.min()*100:+6.1f}% best {a.max()*100:+6.1f}%")
        print(f"  after {y}y  nine lengths pooled: {f(allr)}")
        print(f"            SMA2400 only       : {f(one)}")
        lossfr = [np.mean(p<0)*100 for p in per[y]]
        print(f"            loss share per length: " + " ".join(f"{x:.0f}" for x in lossfr))
    if risk == 0.04:
        print("  longest time below a previous high (years), per length: " + " ".join(f"{x:.1f}" for x in uw))
print("\nspan:", t[0], "->", t[-1])
