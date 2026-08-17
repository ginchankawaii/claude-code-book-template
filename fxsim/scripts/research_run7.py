"""Research run #7 — leverage & timeframe study (aggressive compounding).

Answers two questions the honest way:
  1. How hard can we push leverage before COMPOUND growth stops improving?
     (Spoiler: ~5x. Past that, drawdown grows but CAGR falls — volatility drag.)
  2. Do shorter timeframes (M15/M30/H1/H4) beat the daily trend edge?
     (Spoiler: no. They get killed by costs, and we only have 1 month of
      intraday data so nothing intraday can be validated for compounding.)

Everything runs on the REAL engine (costs + ATR stops + the hard leverage cap),
so the numbers match production sizing. Reproduces docs/RESEARCH.md.

    python -m scripts.research_run7
"""
from __future__ import annotations

import math
import statistics as st
from pathlib import Path

from app.backtest import WARMUP, candles_to_df
from app.config import Settings
from app.engine import PaperTradingEngine
from app.indicators import enrich
from app.providers.csv import load_csv_file
from app.resample import resample
from app.strategies.technical import TechnicalStrategy
from app.strategies.trend import TrendRegimeStrategy

DATA = Path(__file__).resolve().parent.parent / "data"
DAILY = load_csv_file(DATA / "USD_JPY_D.csv", "USD_JPY", "D")


def window(cands, y0, y1=9999):
    return [c for c in cands if y0 <= c.time.year <= y1]


def run(cands, strat, risk, tp, lev, gran="D", bal=100_000.0, bars_per_year=252):
    cfg = Settings()
    cfg.granularity = gran
    cfg.use_take_profit = tp
    cfg.risk_per_trade = risk
    cfg.max_leverage = lev
    cfg.initial_balance = bal
    cfg.max_position_units = 10**12  # let the leverage cap be the only ceiling
    cfg.spread_pips = 0.8
    cfg.commission_per_million = 50.0
    eng = PaperTradingEngine(0, "USD_JPY", strat, cfg, persist=False)
    df = enrich(candles_to_df(cands))
    eqs, peak_lev = [], 0.0
    for i in range(WARMUP, len(df)):
        w = df.iloc[: i + 1]
        eng.step(w, eng.strategy.generate("USD_JPY", w))
        px = w.iloc[-1]["close"]
        if eng.state is not None:
            peak_lev = max(peak_lev, abs(eng.state.position.units) * px / max(1e-9, eng.equity(px)))
        eqs.append(eng.equity(px))
    eng.force_close(df)
    if len(eqs) < 3:
        return None
    final = eng.balance
    peak, mdd = -1e18, 0.0
    for e in eqs:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak * 100 if peak > 0 else 0)
    yrs = (df.iloc[-1]["time"] - df.iloc[WARMUP]["time"]).days / 365.25
    cagr = ((final / bal) ** (1 / yrs) - 1) * 100 if final > 0 and yrs > 0 else -100
    rets = [eqs[i] / eqs[i - 1] - 1 for i in range(1, len(eqs)) if eqs[i - 1] > 0]
    sharpe = (st.mean(rets) / st.pstdev(rets) * math.sqrt(bars_per_year)
              if len(rets) > 2 and st.pstdev(rets) > 0 else 0.0)
    return dict(ret=(final / bal - 1) * 100, cagr=cagr, mdd=mdd, sharpe=sharpe,
                lev=peak_lev, trades=len(eng.closed_trades), final=final, yrs=yrs)


def row(label, m):
    if m is None:
        print(f"{label:<26} (no data)")
        return
    print(f"{label:<26}{m['cagr']:>7.1f}{m['mdd']:>8.1f}{m['sharpe']:>8.2f}"
          f"{m['lev']:>7.2f}{m['trades']:>7}{m['final']/100000:>9.1f}x")


def head():
    print(f"{'config':<26}{'CAGR%':>7}{'maxDD%':>8}{'Sharpe':>8}{'pkLev':>7}{'trades':>7}{'mult':>10}")


def main():
    base = window(DAILY, 2000)

    print("\n[1] RISK SWEEP — where compounding peaks  (SMA150 / 5x cap / TP off / 2000+)")
    head()
    for r in (0.02, 0.03, 0.04, 0.05, 0.06, 0.08):
        row(f"risk {int(r*100)}%", run(base, TrendRegimeStrategy(sma=150), r, False, 5.0))
    print("  -> CAGR peaks at risk 3-4% (peak leverage ~5x). More risk = bigger DD, LOWER CAGR.")

    print("\n[2] SMA ROBUSTNESS  (risk 4% / 5x / TP off / 2000+)")
    head()
    for s in (100, 125, 150, 175, 200, 250):
        row(f"SMA{s}", run(base, TrendRegimeStrategy(sma=s), 0.04, False, 5.0))

    print("\n[3] SUB-PERIOD breakdown  (SMA150 / risk 4% / 5x / TP off) — regime dependence")
    head()
    for y0 in (2000, 2010, 2015, 2020):
        row(f"{y0}+", run(window(DAILY, y0), TrendRegimeStrategy(sma=150), 0.04, False, 5.0))

    print("\n[4] WALK-FORWARD — train 2000-2014, pick best, test 2015-2026 OOS")
    train, test = window(DAILY, 2000, 2014), window(DAILY, 2015)
    scored = []
    for s in (100, 125, 150, 175, 200, 250):
        for r in (0.03, 0.04, 0.05):
            m = run(train, TrendRegimeStrategy(sma=s), r, False, 5.0)
            if m:
                scored.append(((s, r), m["cagr"]))
    (bs, br), incagr = max(scored, key=lambda z: z[1])
    oos = run(test, TrendRegimeStrategy(sma=bs), br, False, 5.0)
    print(f"  in-sample best: SMA{bs} risk{int(br*100)}%  train CAGR {incagr:.1f}%")
    print(f"  OOS 2015-2026:  CAGR {oos['cagr']:.1f}%  DD {oos['mdd']:.1f}%  "
          f"Sharpe {oos['sharpe']:.2f}  mult {oos['final']/100000:.1f}x")
    print("  -> recent-window returns are regime luck; OOS is humbler. Don't over-fit the SMA.")

    print("\n[5] INTRADAY reality check  (ONLY 1 month of M15 data exists — not validatable)")
    m15 = load_csv_file(DATA / "USD_JPY_M15.csv", "USD_JPY", "M15")
    print(f"  data span: {m15[0].time.date()} .. {m15[-1].time.date()}")
    print(f"{'timeframe / strategy':<26}{'monthRet':>9}{'maxDD%':>8}{'trades':>8}{'mult':>9}")
    bpy = {"M15": 252*24*4, "M30": 252*24*2, "H1": 252*24, "H4": 252*6}
    for tf in ("M15", "M30", "H1", "H4"):
        cands = m15 if tf == "M15" else resample(m15, tf, "USD_JPY")
        for sma in (50, 150):
            m = run(cands, TrendRegimeStrategy(sma=sma), 0.04, False, 5.0, gran=tf, bars_per_year=bpy[tf])
            if m:
                print(f"{tf+' trend SMA'+str(sma):<26}{m['ret']:>8.1f}%{m['mdd']:>8.1f}"
                      f"{m['trades']:>8}{m['final']/100000:>8.2f}x")
        m = run(cands, TechnicalStrategy(), 0.04, True, 5.0, gran=tf, bars_per_year=bpy[tf])
        if m:
            print(f"{tf+' technical':<26}{m['ret']:>8.1f}%{m['mdd']:>8.1f}"
                  f"{m['trades']:>8}{m['final']/100000:>8.2f}x")
    print("  -> shorter = more trades = more cost drag. M15 loses; H1/H4 have too few")
    print("     trades over 1 month to mean anything. No intraday compounding edge to deploy.")


if __name__ == "__main__":
    main()
