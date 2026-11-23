"""Scratch: figures behind the deposit conditions (second check, 2026-11-23). All money figures are
a percentage of the ADDED money (1% of 1,000,000 added = 10,000 JPY).

  (a) the flat years: nine-length mean from the start of the tape to the end of 2020 / Sep 2021 / 2021
  (b) calendar years at the live sizing (risk 0.024 = 0.04 x conviction 0.6) next to the harness 0.04
  (c) from a state like today's (in a trade that is 10-14 days old): days until that trade is closed (T1),
      until the NEXT fresh entry (T2), until that next trade is closed (T3), until the entry after it (T4)
  (d) the price of waiting under the live rule (added money is idle until the next fresh entry):
      fixed-date plans, and the event plan "half 3 days after the next fresh entry, the rest later"
Run from fxsim/:  FXSIM_DB=<scratch>/scratch.db PYTHONPATH=docs/product/ai_value/design:. python docs/product/deposit/design/gate_stats.py"""
import numpy as np, pandas as pd
import rp
from scripts import research_harness as H
from scripts import monitor_envelope as M

A = M._arrays(); t = pd.to_datetime(A["t"][H.WARMUP:]); sec = A["sec"][H.WARMUP:]; N = len(sec)
LENS = list(range(2000, 2801, 100)); DAY = 86400; MO = 30.44*DAY; close = sec + 3600
idx = lambda x: np.searchsorted(sec, x)

def run(risk):
    rp.RISK = risk; out = []
    for n in LENS:
        r = rp.replay("closedbar", 5, n, 1_000_000.0, 1000, keep=True)
        ent = np.array([tr["entry_sec"] for tr in r["log"]]); exi = np.array([tr["exit_sec"] for tr in r["log"]])
        ex = np.arange(N); held = np.zeros(N, bool); which = np.full(N, -1)
        for k, (a_, b_) in enumerate(zip(ent, exi)):
            a = np.searchsorted(close, a_, "left"); b = min(np.searchsorted(close, b_, "left"), N-1)
            if b > a: ex[a:b] = b; held[a:b] = True; which[a:b] = k
        out.append(dict(eq=r["eq"], ex=ex, held=held, which=which, ent=ent, exi=exi))
    rp.RISK = 0.04
    return out
R4 = run(0.04); R24 = run(0.024)

print("(a) nine-length mean of equity/start - 1 at 1,000,000, risk 0.04, closed-bar phase 5")
for lab, d in (("end of 2020", "2020-12-31 23:00"), ("30 Sep 2021", "2021-09-30 23:00"), ("end of 2021", "2021-12-31 23:00")):
    i = np.searchsorted(t.values, np.datetime64(d), "right") - 1
    v = [r["eq"][i]/1_000_000-1 for r in R4]
    print(f"  to {lab}: mean {np.mean(v)*100:+.1f}%  per length " + " ".join(f"{x*100:+.0f}" for x in v) + f"  | settings below the start: {sum(x<0 for x in v)} of 9")

print("\n(b) calendar-year return %, nine-length mean (SMA2400): risk 0.04 -> risk 0.024")
for y in sorted(set(t.year)):
    i = np.nonzero(np.asarray(t.year == y))[0]
    f = lambda R: [(r["eq"][i[-1]]/(r["eq"][i[0]-1] if i[0] > 0 else 1_000_000.0)-1)*100 for r in R]
    a, b = f(R4), f(R24)
    print(f"  {y}: {np.mean(a):+6.1f} ({a[4]:+6.1f})  ->  {np.mean(b):+6.1f} ({b[4]:+6.1f})")

print("\n(c) from an hour inside a trade that is 10-14 days old (today's is 12): days until ...")
T = {k: [] for k in ("T1 that trade is closed", "T2 the next fresh entry", "T3 that next trade is closed", "T4 the entry after it")}
n_all = 0
for r in R4:
    w = r["which"]; ok = w >= 0; i0 = np.nonzero(ok)[0]; k = w[i0]
    age = (close[i0] - r["ent"][k]) / DAY; m = (age >= 10) & (age <= 14); i0, k = i0[m], k[m]; n_all += len(i0)
    last = len(r["ent"]) - 1
    def gap(arr, kk):
        v = np.where(kk <= last, arr[np.minimum(kk, last)], np.inf)     # inf = did not happen before the tape ended
        return (v - close[i0]) / DAY
    T["T1 that trade is closed"].append(gap(r["exi"], k)); T["T2 the next fresh entry"].append(gap(r["ent"], k+1))
    T["T3 that next trade is closed"].append(gap(r["exi"], k+1)); T["T4 the entry after it"].append(gap(r["ent"], k+2))
print(f"  n = {n_all} start hours")
for name, v in T.items():
    v = np.concatenate(v)
    q = lambda p: np.percentile(v, p)
    print(f"  {name:30s} median {q(50):6.1f}  p25 {q(25):6.1f}  p75 {q(75):6.1f}  p90 {q(90):6.1f} | not within 53 d: {np.mean(v>53)*100:4.1f}%  not within 90 d: {np.mean(v>90)*100:4.1f}%  not within 180 d: {np.mean(v>180)*100:4.1f}%")

print("\n(d) value of the added money after 1 and 2 years, % of the added money, live rule; starts inside a trade 10-14 days old")
def value(r, i0, Tk, plan_times_weights):
    val = np.zeros(len(i0))
    for ti, w in plan_times_weights:
        ti = np.minimum(ti, N-1); e = np.minimum(r["ex"][ti], Tk)
        val += w * np.where(ti <= Tk, r["eq"][Tk]/r["eq"][e], 1.0)       # not paid in before the horizon -> worth its face value
    return (val - 1.0) * 100
for Hy in (1, 2):
    res = {}
    for r in R4:
        Tk_all = idx(sec + int(Hy*365.25*DAY)); ok = Tk_all < N
        w = r["which"]; i0 = np.nonzero(ok & (w >= 0))[0]; k = w[i0]
        age = (close[i0] - r["ent"][k]) / DAY; m = (age >= 10) & (age <= 14); i0, k = i0[m], k[m]; Tk = Tk_all[i0]
        at = lambda days: idx(sec[i0] + int(days*DAY))
        last = len(r["ent"]) - 1
        nxt = np.where(k+1 <= last, r["ent"][np.minimum(k+1, last)], sec[-1] + 10*365*DAY)     # next fresh entry (the running build's first)
        ev = idx(nxt + 3*DAY)                                                                   # half paid in 3 days after it
        plans = {
          "all today": [(at(0), 1.0)],
          "all at 53 days": [(at(53), 1.0)],
          "half at 53 d, half at 6 months": [(at(53), .5), (at(6*30.44), .5)],
          "half at 53 d, half at 9 months": [(at(53), .5), (at(9*30.44), .5)],
          "half at 53 d, half at 12 months": [(at(53), .5), (at(12*30.44), .5)],
          "half at 53 d, the rest never": [(at(53), .5), (np.full(len(i0), N+10), .5)],
          "EVENT: half 3 d after the next fresh entry, half 6 months after that": [(ev, .5), (idx(nxt + (3+6*30.44)*DAY), .5)],
          "EVENT: half 3 d after the next fresh entry, the rest never": [(ev, .5), (np.full(len(i0), N+10), .5)],
        }
        for name, p in plans.items(): res.setdefault(name, []).append(value(r, i0, Tk, p))
    base = np.concatenate(res["all today"])
    print(f"  --- +{Hy}y, n={base.size} ---")
    for name, v in res.items():
        v = np.concatenate(v); d = v - base
        print(f"  {name:70s} mean {v.mean():+6.2f}% median {np.median(v):+6.2f}% p10 {np.percentile(v,10):+6.2f}% worst {v.min():+6.2f}%"
              + ("" if name == "all today" else f" | vs all today: mean {d.mean():+5.2f} pt; better {np.mean(d>1e-6)*100:4.1f}% same {np.mean(np.abs(d)<=1e-6)*100:4.1f}% worse {np.mean(d<-1e-6)*100:4.1f}%"))
