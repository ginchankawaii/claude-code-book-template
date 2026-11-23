"""Scratch: table 3 again, the way the live brain treats a deposit (after the independent check, 2026-11-23).

stage.py values added money as if it joined the open position at once (ADD * eq[T] / eq[t]).
The live brain does not do that: while a position is held it keeps the lots opened at entry
(scripts/run_ai_bridge.py decide_once: `lots = pos_lots`), and only a FRESH entry is sized from the
new balance. So added money is idle until the position that is open at the deposit closes:
    value = ADD * eq[T] / eq[e],  e = the bar at whose close that position is gone (e = t if flat).
The lot step is ignored, as in stage.py. Nine lengths, closed-bar cadence, 1,000,000 JPY.
Run from fxsim/:  FXSIM_DB=<scratch>/scratch.db PYTHONPATH=docs/product/ai_value/design:. python docs/product/deposit/design/stage_live.py"""
import numpy as np
import rp
from scripts import research_harness as H
from scripts import monitor_envelope as M

A = M._arrays(); sec = A["sec"][H.WARMUP:]; N = len(sec)
LENS = list(range(2000, 2801, 100)); ADD = 700_000.0; DAY = 86400; MO = 30.44*DAY
idx = lambda x: np.searchsorted(sec, x)
plans = {
  "lump today":                       [(0.0, 1.0)],
  "lump after 6 weeks":               [(1.5, 1.0)],
  "half at 6 weeks, half at 4.5 m":   [(1.5, 0.5), (4.5, 0.5)],
  "thirds at 1.5 / 4.5 / 7.5 m":      [(1.5, 1/3), (4.5, 1/3), (7.5, 1/3)],
}
runs = []
for n in LENS:
    r = rp.replay("closedbar", 5, n, 1_000_000.0, 1000, keep=True)
    close = sec + 3600                       # eq[k] is marked at the close of bar k
    ex = np.arange(N)                        # bar at whose close the position open at close(k) is gone
    held = np.zeros(N, bool)
    for tr in r["log"]:
        a = np.searchsorted(close, tr["entry_sec"], "left")      # first bar whose close is at/after the entry
        b = np.searchsorted(close, tr["exit_sec"], "left")       # first bar whose close is at/after the exit
        b = min(b, N-1)
        if b > a:
            ex[a:b] = b; held[a:b] = True
    runs.append((r["eq"], ex, held))

h = np.concatenate([hd for _, _, hd in runs])
wait = np.concatenate([(sec[ex] - sec)[hd] / DAY for _, ex, hd in runs])
print(f"in a position at {h.mean()*100:.1f}% of hours. From a held hour, days until that trade is closed: "
      f"median {np.median(wait):.1f}, mean {wait.mean():.1f}, p90 {np.percentile(wait,90):.1f}, max {wait.max():.0f}; "
      f"longer than 6 weeks {np.mean(wait>42)*100:.1f}%, longer than 4.5 months {np.mean(wait>4.5*30.44)*100:.1f}%")

def table(Hy, live, only_held=None):
    out = {}
    for name, plan in plans.items():
        vs = []
        for eq, ex, held in runs:
            T = idx(sec + int(Hy*365.25*DAY)); ok = T < N; i0 = np.nonzero(ok)[0]
            if only_held is not None: i0 = i0[held[i0] == only_held]
            Tk = T[i0]; val = np.zeros(len(i0))
            for m, w in plan:
                ti = np.minimum(idx(sec[i0] + int(m*MO)), N-1)
                e = np.minimum(ex[ti], Tk) if live else ti
                val += ADD*w*eq[Tk]/eq[e]
            vs.append(val - ADD)
        out[name] = np.concatenate(vs)
    return out

for Hy in (1, 2, 3):
    for live, lab in ((False, "as stage.py (money joins the open position at once)"), (True, "LIVE RULE (money waits for the next fresh entry)")):
        for sub, slab in ((None, "all starts"), (True, "starts with a position OPEN (the owner's case today)")):
            if not live and sub is not None: continue
            if Hy > 1 and sub is None and not live: continue
            o = table(Hy, live, sub); base = o["lump today"]
            print(f"\n--- +{Hy}y, {lab}, {slab}, n={base.size} ---")
            for name, v in o.items():
                d = v - base; eqv = np.abs(d) < 0.5
                print(f"{name:32s} mean {v.mean():+9,.0f} median {np.median(v):+9,.0f} p10 {np.percentile(v,10):+9,.0f} worst {v.min():+9,.0f} loss {np.mean(v<-0.5)*100:4.1f}% zero {np.mean(np.abs(v)<0.5)*100:4.1f}%"
                      + ("" if name == "lump today" else f" | vs lump today: mean {d.mean():+8,.0f}; better {np.mean(d>0.5)*100:4.1f}% same {eqv.mean()*100:4.1f}% worse {np.mean(d<-0.5)*100:4.1f}%"))
