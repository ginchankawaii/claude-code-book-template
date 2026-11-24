"""Research run #9 — multi-currency diversification study (H1, 2015-2026).

Question (user): does adding more pairs lower DD and/or raise profit?
Answer: **NO — not with this rule.** The edge is USD/JPY-specific.

Method (pre-registered to avoid cherry-picking):
  * The validated rule UNCHANGED: H1, SMA2400 trend filter, ATR stop, risk 4%,
    5x leverage cap, TP off. Realistic per-pair spreads.
  * Direction policy fixed by STRUCTURE before looking at results:
    yen pairs (USDJPY, GBPJPY) long-only (carry + yen drift); non-yen pairs
    (EURUSD, AUDUSD, GBPAUD) symmetric long+short (no drift prior).
  * Portfolios = 1/N capital split, each sleeve compounds independently
    (exactly what running N separate live instances would do).

Findings (2015-2026, ~71k H1 bars/pair):
  * Per pair:    USDJPY +12.4%/34%DD ... and everything else loses:
                 GBPJPY +3.7%/47%, EURUSD(L+S) -7.6%/84%,
                 AUDUSD(L+S) -29.5%/99%, GBPAUD(L+S) -16.2%/94%.
  * Correlations between sleeves are LOW (0.0-0.4) — diversification math
    would work — but diversification only helps when sleeves have POSITIVE
    expectancy. Mixing losers into a winner just dilutes it:
    every portfolio is worse than USDJPY alone (best: +8.9%/34% vs +12.4%/33%).
  * Same-DD rescaling doesn't save it (0.8%-8.5% vs 12.4% at equal DD).
  * Robustness: failures persist across SMA 1200/2400/3600 — structural,
    not a parameter accident. Whipsaw losses + spread kill the non-yen pairs;
    only USD/JPY had the persistent policy-divergence trend + carry.

Decision: do NOT deploy multi-pair with this rule; no live multi-symbol
support will be built for it. Diversification would need genuinely different
edges (other asset classes / other rule families), not more FX pairs.

    python -m scripts.research_run9          (~4 min)
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import pandas as pd

from app.backtest import WARMUP, candles_to_df
from app.config import Settings
from app.engine import PaperTradingEngine
from app.indicators import enrich
from app.models import Signal
from app.providers.csv import load_csv_file
from app.strategies.trend import TrendRegimeStrategy

DATA = Path(__file__).resolve().parent.parent / "data"
FILES = {"USD_JPY": "USD_JPY_H1.csv", "GBP_JPY": "GBP_JPY_H1.csv",
         "EUR_USD": "EUR_USD_H1.csv", "AUD_USD": "AUD_USD_H1.csv",
         "GBP_AUD": "GBP_AUD_H1.csv"}
SPREADS = {"USD_JPY": 0.8, "GBP_JPY": 2.0, "EUR_USD": 0.8, "AUD_USD": 1.0, "GBP_AUD": 3.0}

_L, _S, _F = Signal(1, 0.6, "L"), Signal(-1, 0.6, "S"), Signal(0, 0.0, "F")
_dfs: dict = {}


def df_of(pair: str):
    if pair not in _dfs:
        cs = [c for c in load_csv_file(DATA / FILES[pair], pair, "H1") if c.time.year >= 2015]
        _dfs[pair] = enrich(candles_to_df(cs))
    return _dfs[pair]


def run(pair: str, mode: str, sma: int = 2400, bal: float = 500_000.0):
    """One sleeve on the real engine. mode: long | short | ls."""
    df = df_of(pair)
    close = df["close"]; cl = close.to_numpy()
    above = (close > close.rolling(sma).mean()).to_numpy()
    t = df["time"].reset_index(drop=True); n = len(df)
    cfg = Settings(granularity="H1", use_take_profit=False, risk_per_trade=0.04,
                   max_leverage=5.0, initial_balance=bal, max_position_units=10**12,
                   spread_pips=SPREADS[pair], commission_per_million=50.0)
    eng = PaperTradingEngine(0, pair, TrendRegimeStrategy(sma=sma), cfg, persist=False)
    times, eqs = [], []
    for i in range(WARMUP, n):
        up = above[i]
        if mode == "long":
            sig = _L if up else _F
        elif mode == "short":
            sig = _F if up else _S
        else:
            sig = _L if up else _S
        eng.step(df.iloc[i:i + 1], sig)
        times.append(t.iloc[i]); eqs.append(eng.equity(cl[i]))
    eng.force_close(df)
    ser = pd.Series(eqs, index=pd.DatetimeIndex(times)).resample("D").last().dropna() / bal
    final = eng.balance; peak, mdd = -1e18, 0.0
    for e in eqs:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak * 100 if peak > 0 else 0)
    yrs = (t.iloc[n - 1] - t.iloc[WARMUP]).days / 365.25
    cagr = ((final / bal) ** (1 / yrs) - 1) * 100 if final > 0 else -100
    return dict(cagr=cagr, mdd=mdd, trades=len(eng.closed_trades), mult=final / bal), ser


def curve_stats(ser: pd.Series, label: str) -> dict:
    ser = ser.dropna()
    yrs = (ser.index[-1] - ser.index[0]).days / 365.25
    cagr = ((ser.iloc[-1] / ser.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    peak = ser.cummax(); mdd = ((peak - ser) / peak).max() * 100
    r = ser.pct_change().dropna()
    sharpe = r.mean() / r.std() * math.sqrt(252) if r.std() > 0 else 0
    return dict(label=label, cagr=cagr, mdd=mdd, sharpe=sharpe, mult=ser.iloc[-1] / ser.iloc[0])


def show(rows):
    print(f"{'portfolio':<34}{'CAGR%':>7}{'maxDD%':>8}{'Sharpe':>8}{'mult':>7}")
    for s in rows:
        print(f"{s['label']:<34}{s['cagr']:>7.1f}{s['mdd']:>8.1f}{s['sharpe']:>8.2f}{s['mult']:>6.2f}x")


def main():
    t0 = time.time()
    print("[1] PER-PAIR, rule unchanged (policy directions, realistic spreads)")
    jobs = [("USD_JPY", "long"), ("GBP_JPY", "long"),
            ("EUR_USD", "ls"), ("AUD_USD", "ls"), ("GBP_AUD", "ls")]
    curves = {}
    for pair, mode in jobs:
        st, ser = run(pair, mode)
        curves[f"{pair}:{mode}"] = ser
        print(f"  {pair} {mode:<5} CAGR {st['cagr']:>6.1f}%  maxDD {st['mdd']:>5.1f}%  "
              f"trades {st['trades']:>4}  mult {st['mult']:.2f}x", flush=True)

    C = pd.DataFrame(curves)
    ports = {
        "USDJPY単体(基準)": ["USD_JPY:long"],
        "円デュオ(+GBPJPY)": ["USD_JPY:long", "GBP_JPY:long"],
        "+非円2(EUR,AUD両建て)": ["USD_JPY:long", "EUR_USD:ls", "AUD_USD:ls"],
        "4ペア(円2+非円2)": ["USD_JPY:long", "GBP_JPY:long", "EUR_USD:ls", "AUD_USD:ls"],
        "5ペア(+GBPAUD両建て)": list(curves),
    }
    print("\n[2] 1/N PORTFOLIOS (no rebalance — N independent live instances)")
    rows = [curve_stats(C[k].ffill().dropna().mean(axis=1), nm) for nm, k in ports.items()]
    show(rows)

    print("\n[3] DAILY-RETURN CORRELATIONS (low! but sleeves lose -> dilution, not diversification)")
    print(C.ffill().dropna().pct_change().dropna().corr().round(2).to_string())

    print("\n[4] SAME-DD RESCALING (lever each portfolio to the baseline's DD)")
    base = rows[0]
    for s in rows[1:]:
        k = base["mdd"] / s["mdd"] if s["mdd"] > 0 else 1
        print(f"  {s['label']:<32} x{k:.2f} -> ~CAGR {s['cagr']*k:.1f}% at DD {base['mdd']:.0f}%")

    print("\n[5] ROBUSTNESS — failure is structural, not the SMA choice")
    for pair, mode, sma in [("EUR_USD", "ls", 1200), ("EUR_USD", "ls", 3600),
                            ("AUD_USD", "ls", 3600), ("GBP_JPY", "long", 3600)]:
        st, _ = run(pair, mode, sma=sma)
        print(f"  {pair} {mode} @SMA{sma}: CAGR {st['cagr']:>6.1f}%  maxDD {st['mdd']:.1f}%", flush=True)

    print(f"\n(elapsed {time.time()-t0:.0f}s)")
    print("VERDICT: every portfolio < USDJPY alone. The edge does not travel; "
          "do not deploy multi-pair with this rule.")


if __name__ == "__main__":
    main()
