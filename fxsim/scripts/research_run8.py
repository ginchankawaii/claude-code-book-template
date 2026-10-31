"""Research run #8 — multi-timeframe trend study on 11 years of intraday USD/JPY.

Supersedes run #7's intraday section. run #7 only had 1 MONTH of M15 data and
(correctly, for that sample) concluded intraday could not be validated. With
real MT5 history (M15/M30/H1/H4, 2015-01..2026-06) the honest answer changes:

  * A ~100-day trend filter sampled on H1 bars (SMA~2400) compounds at ~12% CAGR
    / ~34% DD over 2015-2026 — BEATING the best daily config (~9.5%) and H4.
  * The finer granularity adds real value: at the SAME ~66-day horizon, daily
    SMA66 = 7.1% but H4 SMA400 = 11.2% (better entry/exit timing within trends).
  * It is COST-ROBUST: H1 SMA2400 still makes 10.8% at a 2.5-pip spread (only
    ~26 trades/year), so the edge is not a spread illusion.
  * Walk-forward (train 2015-2020 -> OOS 2021-2026) confirms intraday >= daily
    OOS, BUT every config was flat/negative in 2015-2020 and strong in 2021-2026:
    the returns are a regime story (USD/JPY trended hard 2022-2024). Long-only
    trend bleeds in ranges and prints in sustained up-trends. Not a free lunch.

Only D / H4 / H1 are committed (M15/M30 raw exports are gitignored — too large;
they only confirmed shorter = more churn = more cost drag).

    python -m scripts.research_run8
"""
from __future__ import annotations

import time
from pathlib import Path

from app.backtest import WARMUP, candles_to_df
from app.config import Settings
from app.engine import PaperTradingEngine
from app.indicators import enrich
from app.models import Signal
from app.providers.csv import load_csv_file
from app.strategies.trend import TrendRegimeStrategy

DATA = Path(__file__).resolve().parent.parent / "data"
FILES = {"D": "USD_JPY_D.csv", "H4": "USD_JPY_H4.csv", "H1": "USD_JPY_H1.csv"}
_LONG, _FLAT = Signal(1, 0.6, "up"), Signal(0, 0.0, "flat")
_cache: dict = {}


def enriched(tf: str, y0: int = 2015, y1: int = 9999):
    key = (tf, y0, y1)
    if key not in _cache:
        cs = [c for c in load_csv_file(DATA / FILES[tf], "USD_JPY", tf) if y0 <= c.time.year <= y1]
        _cache[key] = enrich(candles_to_df(cs))
    return _cache[key]


def run(df, sma, risk=0.04, lev=5.0, gran="H1", spread=0.8, tp=False, bal=100_000.0):
    cfg = Settings()
    cfg.granularity = gran
    cfg.use_take_profit = tp
    cfg.risk_per_trade = risk
    cfg.max_leverage = lev
    cfg.initial_balance = bal
    cfg.max_position_units = 10**12
    cfg.spread_pips = spread
    cfg.commission_per_million = 50.0
    close = df["close"]
    long = (close > close.rolling(sma).mean()).to_numpy()
    cl = close.to_numpy()
    eng = PaperTradingEngine(0, "USD_JPY", TrendRegimeStrategy(sma=sma), cfg, persist=False)
    eqs, pk, n = [], 0.0, len(df)
    for i in range(WARMUP, n):
        eng.step(df.iloc[i:i + 1], _LONG if long[i] else _FLAT)
        px = cl[i]
        if eng.state is not None:
            pk = max(pk, abs(eng.state.position.units) * px / max(1e-9, eng.equity(px)))
        eqs.append(eng.equity(px))
    eng.force_close(df)
    if len(eqs) < 3:
        return None
    final, peak, mdd = eng.balance, -1e18, 0.0
    for e in eqs:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak * 100 if peak > 0 else 0)
    span = (df.iloc[n - 1]["time"] - df.iloc[WARMUP]["time"]).days / 365.25
    cagr = ((final / bal) ** (1 / span) - 1) * 100 if final > 0 and span > 0 else -100
    return dict(cagr=cagr, mdd=mdd, lev=pk, trades=len(eng.closed_trades), final=final)


def main():
    t0 = time.time()

    print("[1] BEST SMA per timeframe  (risk 4% / 5x / TP off / 2015-2026)")
    print(f"{'TF':<4}{'SMA':>6}{'~horizon':>10}{'CAGR%':>8}{'maxDD%':>8}{'trades':>8}{'mult':>8}")
    grids = {"D": [66, 90, 125], "H4": [300, 400, 500], "H1": [1800, 2400, 3000]}
    hbars = {"D": 1, "H4": 6, "H1": 24}  # bars per day -> horizon in days
    for tf in ("D", "H4", "H1"):
        df = enriched(tf)
        for s in grids[tf]:
            m = run(df, s, gran=tf)
            print(f"{tf:<4}{s:>6}{str(round(s/hbars[tf]))+'d':>10}"
                  f"{m['cagr']:>8.1f}{m['mdd']:>8.1f}{m['trades']:>8}{m['final']/100000:>7.1f}x")
        print()
    print("  -> the ~2-3 month trend filter wins; on H1 it beats daily. Same horizon,")
    print("     finer bars = better timing (daily SMA66=7.1% vs H4 SMA400=11.2%).")

    print("\n[2] WALK-FORWARD  train 2015-2020 -> OOS 2021-2026")
    for tf, grid in (("D", [66, 90, 125, 150]), ("H4", [300, 400, 500]), ("H1", [1800, 2400, 3000])):
        tr, te = enriched(tf, 2015, 2020), enriched(tf, 2021)
        best = max(((s, run(tr, s, gran=tf)) for s in grid), key=lambda z: z[1]["cagr"])
        s, mtr = best
        mte = run(te, s, gran=tf)
        print(f"  {tf:<3} train-best SMA{s}: train CAGR {mtr['cagr']:>5.1f}%  ->  "
              f"OOS CAGR {mte['cagr']:>5.1f}%  DD {mte['mdd']:>4.1f}%  mult {mte['final']/100000:.1f}x")
    print("  -> intraday >= daily OOS, but ALL train years were flat/negative: the")
    print("     profit is the 2022-2024 yen trend, not a regime-proof edge.")

    print("\n[3] COST ROBUSTNESS  (full 2015-2026, risk 4% / 5x) — spread 0.8 / 1.5 / 2.5 pips")
    for tf, s in (("D", 90), ("H4", 400), ("H1", 2400)):
        df = enriched(tf)
        cells = [f"{run(df, s, gran=tf, spread=sp)['cagr']:.1f}%" for sp in (0.8, 1.5, 2.5)]
        print(f"  {tf:<3} SMA{s:<5} CAGR: {cells[0]:>7} -> {cells[1]:>7} -> {cells[2]:>7}")
    print("  -> H1 SMA2400 keeps 10.8% even at 2.5 pips (~26 trades/yr). Not a spread mirage.")

    print("\n[4] RISK SWEEP  H1 SMA2400 (5x cap) — leverage cap is the binding constraint")
    df = enriched("H1")
    print(f"{'risk':>6}{'CAGR%':>8}{'maxDD%':>8}{'pkLev':>7}")
    for r in (0.02, 0.03, 0.04, 0.05, 0.06):
        m = run(df, 2400, risk=r, gran="H1")
        print(f"{int(r*100):>5}%{m['cagr']:>8.1f}{m['mdd']:>8.1f}{m['lev']:>7.2f}")
    print("  -> CAGR/DD plateau by risk ~5% (the 5x cap binds). More risk buys nothing.")

    print(f"\n(elapsed {time.time()-t0:.0f}s)")
    print("WINNER: H1 / SMA2400 (~100-day trend filter) / risk 4-5% / 5x cap / TP off")


if __name__ == "__main__":
    main()
