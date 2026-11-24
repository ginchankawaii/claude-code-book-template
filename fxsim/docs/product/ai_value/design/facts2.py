import time, numpy as np, pandas as pd
from scripts import monitor_envelope as M
import rp
t0=time.time()
# 1. validate my copy against the repository's replay (no hooks, same balance, lot=1)
for cad in ("close","closedbar"):
    a = M.replay(cad, 5, 2400); b = rp.replay(cad, 5, 2400)
    print("VALIDATE copy", cad, a["trades"], b["trades"], round(a["final"],2), round(b["final"],2), abs(a["final"]-b["final"])<0.01)
print("sec", time.time()-t0)
def conc(name, r):
    log = pd.DataFrame(r["log"]); net = log.pnl.sum(); top = log.sort_values("pnl", ascending=False)
    hold = (top.exit_sec-top.entry_sec)/86400
    print(f"{name}: CAGR {r['cagr']:.1f} DD {r['mdd']:.1f} trades {len(log)} ({len(log)/r['years']:.1f}/yr) win% {(log.pnl>0).mean()*100:.1f} net {net:,.0f}"
          f" top1 {top.pnl.iloc[0]/net*100:.0f}% top3 {top.pnl.iloc[:3].sum()/net*100:.0f}% top6 {top.pnl.iloc[:6].sum()/net*100:.0f}%"
          f" top3 hold(cal days) {[round(x) for x in hold.iloc[:3]]} top3 lev {[round(x,2) for x in top.eff.iloc[:3]]}"
          f" stops {int((log.why=='stop').sum())}")
    return log
# 2. the CURRENT rule: closed-bar cadence, operating point (272k, 0.01 lot = 1000 units)
for n in (2400,):
    for ph in (1,5,9):
        conc(f"closedbar op-point SMA{n} phase{ph}", rp.replay("closedbar", ph, n, 272000.0, 1000, keep=True))
conc("close(backtest) op-point SMA2400", rp.replay("close", 5, 2400, 272000.0, 1000, keep=True))
conc("close(backtest) 500k lot1 SMA2400", rp.replay("close", 5, 2400, 500000.0, 1, keep=True))
rows=[]
for n in range(2000,2801,100):
    r = rp.replay("closedbar", 5, n, 272000.0, 1000, keep=True)
    log = conc(f"closedbar op-point SMA{n}", r)
    net=log.pnl.sum(); top=log.sort_values("pnl",ascending=False)
    rows.append(dict(n=n,cagr=r["cagr"],mdd=r["mdd"],win=(log.pnl>0).mean()*100, top3=top.pnl.iloc[:3].sum()/net*100, top1=top.pnl.iloc[0]/net*100, ent=len(log)/r["years"]))
d=pd.DataFrame(rows); print(d.round(1).to_string()); print("mean", d.mean().round(1).to_dict())
print("sec", time.time()-t0)
