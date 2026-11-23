import numpy as np, pandas as pd, rp
rows=[]
for L in range(2000,2801,100):
    for cad in ("close","closedbar"):
        r = rp.replay(cad,5,L,272000.0,1000,keep=True); log=pd.DataFrame(r["log"]); y=r["years"]
        los=log[log.pnl<0]
        rows.append(dict(L=L,cad=cad,cagr=r["cagr"],ent_yr=len(log)/y,losers=len(los)/len(log)*100,
                         loser_mean=los.ret.mean(),loser_pool_yr=los.ret.sum()/y,
                         log_pool_yr=np.log1p(los.ret/100).sum()/y*100))
d=pd.DataFrame(rows); print(d.round(2).to_string())
for cad,g in d.groupby("cad"):
    print(cad, "nine-mean: cagr %.1f entries/yr %.1f losers %.0f%% mean loser %.2f%% loser pool %.2f pp/yr" % (g.cagr.mean(), g.ent_yr.mean(), g.losers.mean(), g.loser_mean.mean(), g.loser_pool_yr.mean()))
    pool=-g.loser_pool_yr.mean()
    for share,lab in ((0.044,"X=6h (4.4% of hours)"),(0.148,"X=24h (14.8% of hours)")):
        print(f"   ceiling if EVERY losing entry inside a window were avoided at no cost, {lab}: {pool*share:.2f} pp/yr = {pool*share*2700:,.0f} JPY/yr at 270k; with 2x clustering {pool*share*2:.2f} pp")
