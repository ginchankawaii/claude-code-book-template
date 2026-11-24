"""Scratch replay (reviewer's own copy of scripts/monitor_envelope.replay with hooks).
Adds: bal0, lot step, per-bar entry_block (candidate A: no NEW entry in the bar),
per-bar exit_block (candidate B: flat during the bar; re-enter after by the rule), trade log."""
import math, numpy as np, pandas as pd
from scripts import research_harness as H
from scripts import monitor_envelope as M

RISK, STOP_ATR, CAP, HS = 0.04, 1.5, 5.0, 0.8*0.01/2
def ramp(price, sma, atr):
    if math.isnan(sma) or not atr > 0: return CAP
    return 1.0 + (CAP-1.0)*min(max((price-sma)/(STOP_ATR*atr),0.0),1.0)

def size(bal, sd, lev, price, lot):
    x = min(int(bal*RISK/sd), int(lev*bal/price))
    return (x//lot)*lot

def replay(cadence="close", phase_min=5, n_sma=2400, bal0=500_000.0, lot=1,
           entry_block=None, exit_block=None, keep=False):
    A = M._arrays()
    cl, hi, lo, op, atr, t, sec = (A[k] for k in ("cl","hi","lo","op","atr","t","sec"))
    sma = H.sma(n_sma, A["src"]); n = len(cl)
    eb = entry_block if entry_block is not None else np.zeros(n, bool)
    xb = exit_block if exit_block is not None else np.zeros(n, bool)
    bal, u, entry, stop = float(bal0), 0, 0.0, 0.0
    last_gate = -1e18; trades = 0; nent = 0
    eqs = np.empty(n-H.WARMUP); live = cadence=="closedbar"; stop_bar = -1
    looks = [(phase_min+m)/60.0 for m in range(0,60,10)] if live else [1.0]
    log = []; cur = None
    def close_at(fill, when, why):
        nonlocal bal,u,trades,last_gate,cur
        pnl = u*(fill-entry); bal += pnl
        if keep:
            cur.update(exit_sec=when, pnl=pnl, why=why, ret=pnl/cur["bal"]*100); log.append(cur); cur=None
        u = 0; trades += 1; last_gate = when
    def open_at(x, px, sd, when, lev, i):
        nonlocal u, entry, stop, cur, nent, last_gate
        u, entry, stop = x, px+HS, px+HS-sd; nent += 1
        if keep: cur = dict(entry_sec=when, i=i, lev=lev, eff=x*px/bal, bal=bal, units=x)
    for k,i in enumerate(range(H.WARMUP, n)):
        o,h_,l_,c = op[i],hi[i],lo[i],cl[i]
        if not live:
            if u and l_ <= stop: close_at(stop-HS, sec[i]+3600, "stop")
            if not math.isnan(sma[i]):
                av = atr[i] if not math.isnan(atr[i]) else 0.1
                if u and (not c > sma[i]): close_at(c-HS, sec[i]+3600, "trend")
                elif u and xb[i]: close_at(c-HS, sec[i]+3600, "event")
                elif not u and c > sma[i] and not eb[i] and not xb[i]:
                    sd = max(av*STOP_ATR, 0.05); lv = ramp(c, sma[i], av)
                    x = size(bal, sd, lv, c, lot)
                    if x > 0: open_at(x, c, sd, sec[i]+3600, lv, i)
            eqs[k] = bal + u*(c-entry); continue
        av = atr[i-1] if not math.isnan(atr[i-1]) else 0.1
        fprev = 0.0
        if u and o <= stop:
            close_at(o-HS, sec[i], "stop"); stop_bar = i
        for f in looks+[1.0]:
            if u:
                cand = [fprev,f]+[v for v in (1/3,2/3) if fprev < v < f]
                if min(M._path(o,l_,h_,c,g) for g in cand) <= stop:
                    close_at(stop-HS, sec[i]+int(f*3600), "stop"); stop_bar = i
            fprev = f
            if f == 1.0 or math.isnan(sma[i-1]): continue
            p = M._path(o,l_,h_,c,f); now = sec[i]+int(f*3600)
            if now-last_gate < 15*60: continue
            up = cl[i-1] > sma[i-1]
            if not u and stop_bar == i: continue
            if u and not up: close_at(p-HS, now, "trend")
            elif u and xb[i]: close_at(p-HS, now, "event")
            elif not u and up and not eb[i] and not xb[i]:
                sd = max(av*STOP_ATR, 0.05); lv = ramp(cl[i-1], sma[i-1], av)
                x = size(bal, sd, lv, p, lot)
                if x > 0:
                    open_at(x, p, sd, now, lv, i); last_gate = now
        eqs[k] = bal + u*(c-entry)
    if u:
        close_at(cl[-1]-HS, sec[-1]+3600, "end")
    yrs = (pd.Timestamp(t[-1])-pd.Timestamp(t[H.WARMUP])).days/365.25
    peak = np.maximum.accumulate(eqs); mdd = float(np.max((peak-eqs)/peak)*100)
    return dict(final=bal, cagr=((bal/bal0)**(1/yrs)-1)*100, mdd=mdd, trades=trades, entries=nent,
                log=log, years=yrs, eq=eqs)
