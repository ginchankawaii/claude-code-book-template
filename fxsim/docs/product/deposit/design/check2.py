"""Scratch: second-pass figures for the deposit record (after the independent check, 2026-11-23).
  (a) calendar-year returns of the nine lengths (closed-bar cadence, 1,000,000 JPY, 0.01-lot steps)
  (b) the lowest point reached DURING the first 1/2/3 years after a start (table 2 only looks at the end)
  (c) the same rolling table split by start period, and a 1-year block bootstrap of the loss share
  (d) the largest one-hour falls and weekend/holiday gaps in the tape
Run from fxsim/:  FXSIM_DB=<scratch>/scratch.db PYTHONPATH=docs/product/ai_value/design:. python docs/product/deposit/design/check2.py"""
import numpy as np, pandas as pd
import rp
from scripts import research_harness as H
from scripts import monitor_envelope as M

A = M._arrays()
t = pd.to_datetime(A["t"][H.WARMUP:]); sec = A["sec"][H.WARMUP:]
LENS = list(range(2000, 2801, 100)); BAL = 1_000_000.0
eqs = [rp.replay("closedbar", 5, n, BAL, 1000)["eq"] for n in LENS]
print("span:", t[0], "->", t[-1], "bars", len(t))

# (a) calendar years
yrs = sorted(set(t.year)); tab = {}
print("\n(a) calendar-year return %, per length 2000..2800, then the nine-length mean")
for y in yrs:
    m = np.asarray(t.year == y); i = np.nonzero(m)[0]
    row = []
    for eq in eqs:
        start = eq[i[0]-1] if i[0] > 0 else BAL
        row.append((eq[i[-1]]/start-1)*100)
    tab[y] = row
    print(f"  {y}{' (to '+str(t[i[-1]].date())+')' if y==yrs[-1] else ''}: " + " ".join(f"{x:+6.1f}" for x in row) + f"   mean {np.mean(row):+6.1f}   SMA2400 {row[4]:+6.1f}")
full = [y for y in yrs if y < yrs[-1]]
neg = sum(np.mean(tab[y]) < 0 for y in yrs)
print(f"  nine-length mean negative in {neg} of {len(yrs)} calendar years (the last one partial)")
print("  SMA2400 negative years:", [y for y in yrs if tab[y][4] < 0])
print("  mean yen per 1,000,000 by year:", {y: int(round(np.mean(tab[y])*10000, -3)) for y in yrs})

# (b) lowest point during the window
print("\n(b) lowest point reached during the window (H1 closes), nine lengths pooled")
for Y in (1, 2, 3):
    lows = []; ends = []
    for eq in eqs:
        j = np.searchsorted(sec, sec + int(Y*365.25*86400)); ok = j < len(sec); i0 = np.nonzero(ok)[0]
        # running minimum over [i, j] via a sparse-table-free trick: process with a deque is slow in numpy; use strides on log scale
        n = len(eq); lg = np.log(eq)
        # sliding window minimum with variable right edge: windows are almost constant length; do exact with reduceat on sorted bounds
        mn = np.minimum.reduceat(np.concatenate([lg, [np.inf]]), np.stack([i0, j[ok]+1], 1).ravel())[::2]
        lows.append(np.exp(mn)/eq[i0]-1); ends.append(eq[j[ok]]/eq[i0]-1)
    lo = np.concatenate(lows); en = np.concatenate(ends)
    print(f"  {Y}y: end below start {np.mean(en<0)*100:4.1f}% | end worse than -10%: {np.mean(en<-0.10)*100:4.1f}% | "
          f"below -10% at SOME point: {np.mean(lo<-0.10)*100:4.1f}% | below -20% at some point: {np.mean(lo<-0.20)*100:4.1f}% | "
          f"median lowest {np.median(lo)*100:+5.1f}% | deepest {lo.min()*100:+5.1f}% | worst end {en.min()*100:+5.1f}%")

# (c) by start period, and a block bootstrap
print("\n(c) one year later, by start period (nine lengths pooled)")
j = np.searchsorted(sec, sec + int(365.25*86400)); ok = j < len(sec); i0 = np.nonzero(ok)[0]
R = np.stack([eq[j[ok]]/eq[i0]-1 for eq in eqs])            # 9 x starts
sy = np.asarray(t.year)[i0]
for lab, m in (("starts 2015-2020", sy <= 2020), ("starts 2021-2025", sy >= 2021)):
    a = R[:, m].ravel(); print(f"  {lab}: loss {np.mean(a<0)*100:4.1f}%  median {np.median(a)*100:+5.1f}%  n={a.size}")
print("  loss share by start year:", " ".join(f"{y}:{np.mean(R[:, sy==y]<0)*100:.0f}%" for y in sorted(set(sy))))
rng = np.random.default_rng(20261123); st = sec[i0]; blk = ((st - st[0]) // int(365.25*86400)).astype(int); nb = blk.max()+1
out = []
for _ in range(2000):
    pick = rng.integers(0, nb, nb); cols = np.concatenate([np.nonzero(blk == b)[0] for b in pick])
    a = R[:, cols].ravel(); out.append((np.mean(a < 0)*100, np.median(a)*100))
out = np.array(out)
print(f"  1-year block bootstrap (2000 draws, {nb} blocks): loss share 95% range {np.percentile(out[:,0],2.5):.0f}%..{np.percentile(out[:,0],97.5):.0f}%, "
      f"median return {np.percentile(out[:,1],2.5):+.1f}%..{np.percentile(out[:,1],97.5):+.1f}%")

# (d) price jumps in the tape
op, lo_, hi, cl, tt, ss = (A[k] for k in ("op", "lo", "hi", "cl", "t", "sec"))
fall = op - lo_; k = np.argsort(-fall)[:6]
print("\n(d) largest falls inside one H1 bar (open - low, yen):")
for i in k: print(f"  {pd.Timestamp(tt[i])}  open {op[i]:.3f} low {lo_[i]:.3f} close {cl[i]:.3f}  fall {fall[i]:.3f}")
gap = op[1:] - cl[:-1]; dt = ss[1:] - ss[:-1]; closed = dt > 2*3600
g = np.where(closed, gap, 0.0); k = np.argsort(g)[:5]
print(f"  closures (gap between bars > 2h): {int(closed.sum())}; largest downward gaps at a reopening (yen):")
for i in k: print(f"  {pd.Timestamp(tt[i+1])}  prev close {cl[i]:.3f} open {op[i+1]:.3f}  gap {gap[i]:+.3f}")
atr = A["atr"]; print(f"  H1 ATR: median {np.nanmedian(atr):.3f}  p90 {np.nanpercentile(atr,90):.3f}  p99 {np.nanpercentile(atr,99):.3f}  -> stop distance 1.5xATR median {1.5*np.nanmedian(atr):.3f} yen")

# (e) poll phase and live sizing: the level of "about 9%" (table 1 uses phase 5 and risk 0.04)
print("\n(e) nine-length mean CAGR / mean maxDD / worst maxDD at 1,000,000 by poll phase; risk 0.04 (harness) and 0.024 (live: 0.04 x conviction 0.6)")
for risk in (0.04, 0.024):
    rp.RISK = risk; means = []
    for ph in (1, 3, 5, 7, 9):
        rs = [rp.replay("closedbar", ph, n, BAL, 1000) for n in LENS]
        cg = [r["cagr"] for r in rs]; md = [r["mdd"] for r in rs]; means.append(np.mean(cg))
        print(f"  risk {risk} phase {ph}: CAGR mean {np.mean(cg):.2f}% (min {min(cg):.2f} .. max {max(cg):.2f}) | maxDD mean {np.mean(md):.1f}% worst {max(md):.1f}% | SMA2400 {cg[4]:.2f}% / {md[4]:.1f}%")
    print(f"  risk {risk}: mean over the five phases {np.mean(means):.2f}%")
rp.RISK = 0.04
