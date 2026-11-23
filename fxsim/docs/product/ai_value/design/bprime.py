"""B' = flat inside a RANDOM window, then (if the rule still says long and price is above the old stop)
restore the SAME units and the SAME stop. Separates 'being out for the window + spread' from
'stop re-anchored / size re-drawn'. Close cadence, operating point. Null only (random windows)."""
import math, numpy as np, pandas as pd
from scripts import research_harness as H
from scripts import monitor_envelope as M
import rp
A = M._arrays(); cl,hi,lo,atr,t = A["cl"],A["hi"],A["lo"],A["atr"],A["t"]; n=len(cl); HS=rp.HS
def run(n_sma, xb, restore, bal0=272000.0, lot=1000):
    sma = H.sma(n_sma, A["src"]); bal,u,entry,stop = bal0,0,0.0,0.0; mem=None; ent=0
    eqs = np.empty(n-H.WARMUP)
    for k,i in enumerate(range(H.WARMUP,n)):
        c=cl[i]
        if u and lo[i] <= stop: bal += u*(stop-HS-entry); u=0; mem=None
        if not math.isnan(sma[i]):
            av = atr[i] if not math.isnan(atr[i]) else 0.1
            up = c > sma[i]
            if u and not up: bal += u*(c-HS-entry); u=0; mem=None
            elif u and xb[i]:
                bal += u*(c-HS-entry); mem=(u,stop) if restore else None; u=0
            elif not u and up and not xb[i]:
                if mem is not None and c > mem[1]:
                    u,stop = mem; entry=c+HS; ent+=1
                else:
                    sd=max(av*1.5,0.05); x=rp.size(bal,sd,rp.ramp(c,sma[i],av),c,lot)
                    if x>0: u,entry,stop = x,c+HS,c+HS-sd; ent+=1
                mem=None
            elif not u and not up: mem=None
        eqs[k]=bal+u*(c-entry)
    if u: bal += u*(cl[-1]-HS-entry)
    yrs=(pd.Timestamp(t[-1])-pd.Timestamp(t[H.WARMUP])).days/365.25
    pk=np.maximum.accumulate(eqs)
    return ((bal/bal0)**(1/yrs)-1)*100, float(np.max((pk-eqs)/pk)*100), ent
z = np.zeros(n,bool)
b0 = run(2400, z, False); print("baseline (must equal 15.12/25.8/219):", [round(x,2) for x in b0])
rows=[]
for X in (6,24):
    for d in range(100):
        rng=np.random.default_rng(1000*X+d)
        idx=np.arange(H.WARMUP+X,n); k=int(round(40*(n-H.WARMUP)/(24*5*52.0)))
        ev=rng.choice(idx,size=k,replace=False); m=np.zeros(n,bool)
        for e in ev: m[e-X:e+1]=True
        b=run(2400,m,False); bp=run(2400,m,True)
        rows.append(dict(X=X,dB=b[0]-b0[0],ddB=b[1]-b0[1],entB=b[2],dBp=bp[0]-b0[0],ddBp=bp[1]-b0[1],entBp=bp[2]))
d=pd.DataFrame(rows)
for X,g in d.groupby("X"):
    for c,dd in (("dB","ddB"),("dBp","ddBp")):
        s=g[c]; print(f"X={X} {c}: mean {s.mean():+.2f}pp sd {s.std():.2f} p5 {s.quantile(.05):+.2f} p95 {s.quantile(.95):+.2f} max {s.max():+.2f} P(>0)={np.mean(s>0):.2f}; maxDD change mean {g[dd].mean():+.1f} p95 {g[dd].quantile(.95):+.1f}")
