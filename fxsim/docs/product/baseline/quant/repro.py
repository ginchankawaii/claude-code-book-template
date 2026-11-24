"""Reproduction checks only (no new strategy variants)."""
import sys, time
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
import numpy as np
from scripts import research_harness as H

# (1) Round-10 neighbourhood: production (scale-in off) at SMA2000..2800
rows = []
for n in range(2000, 2801, 100):
    st = H.sim_scalein(n, keep_trades=False)             # doc defaults: comm=0, max_units=None
    st2 = H.sim_scalein(n, comm=50.0, max_units=100_000)  # engine defaults
    cagr = ((st["final"] / 500000) ** (1 / st["years"]) - 1) * 100
    cagr2 = ((st2["final"] / 500000) ** (1 / st2["years"]) - 1) * 100
    rows.append((n, cagr, st["mdd"], st["sharpe"], cagr2, st2["mdd"]))
    print(f"SMA{n}: comm0/nocap CAGR {cagr:5.2f} DD {st['mdd']:4.1f} Sh {st['sharpe']:.2f} | engine-defaults CAGR {cagr2:5.2f} DD {st2['mdd']:4.1f}")
a = np.array(rows)
print("9-pt (comm0): mean %.2f min %.2f max %.2f sd(pop) %.2f sd(sample) %.2f meanDD %.1f worstDD %.1f meanSh %.3f" % (
    a[:,1].mean(), a[:,1].min(), a[:,1].max(), a[:,1].std(), a[:,1].std(ddof=1), a[:,2].mean(), a[:,2].max(), a[:,3].mean()))
print("9-pt (engine defaults): mean %.2f min %.2f max %.2f" % (a[:,4].mean(), a[:,4].min(), a[:,4].max()))

# (2) real engine vs harness with the PRODUCTION ramp on, long-only, on a slice
from app.config import Settings
from app.engine import PaperTradingEngine
from app.models import Signal
from app.backtest import WARMUP
df = H.data()
arr = H.arrays()
sig = H.ls_signal(2400, arr, "L")
for i1 in (2400 + 6000,):
    cfg = Settings(initial_balance=500_000.0, risk_per_trade=0.04, max_leverage=5.0,
                   max_position_units=100_000, spread_pips=0.8, commission_per_million=50.0,
                   dyn_leverage=True, dyn_lev_atr_mult=1.5, dyn_lev_floor=1.0, dyn_lev_pow=1.0,
                   use_take_profit=False, trend_sma=2400, granularity="H1")
    eng = PaperTradingEngine(0, "USD_JPY", None, cfg, persist=False)
    t0 = time.time()
    for i in range(WARMUP, i1):
        s = int(sig[i])
        eng.step(df.iloc[: i + 1], Signal(s, 0.6, "t") if s else Signal.flat("f"))
    eng.force_close(df.iloc[:i1])
    st = H.sim(H.trend_mask(2400), H.dyn_lev(1.5, 1.0, 5.0, 1.0), i1=i1)
    print(f"ENGINE(ramp on) bars..{i1}: bal {eng.balance:,.2f} trades {len(eng.closed_trades)} | harness bal {st['final']:,.2f} trades {st['trades']}  ({time.time()-t0:.0f}s)")
