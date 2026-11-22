import sys, time
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
from scripts import research_harness as H
from app.config import Settings
from app.engine import PaperTradingEngine
from app.models import Signal
from app.backtest import WARMUP
df = H.data(); arr = H.arrays(); sig = H.ls_signal(2400, arr, "L"); n = len(sig)
cfg = Settings(initial_balance=500_000.0, risk_per_trade=0.04, max_leverage=5.0,
               max_position_units=100_000, spread_pips=0.8, commission_per_million=50.0,
               dyn_leverage=True, dyn_lev_atr_mult=1.5, dyn_lev_floor=1.0, dyn_lev_pow=1.0,
               use_take_profit=False, trend_sma=2400, granularity="H1")
eng = PaperTradingEngine(0, "USD_JPY", None, cfg, persist=False)
t0 = time.time()
for i in range(WARMUP, n):
    s = int(sig[i])
    eng.step(df.iloc[: i + 1], Signal(s, 0.6, "t") if s else Signal.flat("f"))
    if i % 10000 == 0: print(i, round(time.time()-t0), flush=True)
eng.force_close(df)
st = H.sim(H.trend_mask(2400), H.dyn_lev(1.5, 1.0, 5.0, 1.0), keep_trades=True)
print(f"FULL ENGINE(ramp on): bal {eng.balance:,.2f} trades {len(eng.closed_trades)} | harness bal {st['final']:,.2f} trades {st['trades']} ({time.time()-t0:.0f}s)")
