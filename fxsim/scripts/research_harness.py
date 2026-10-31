"""Fast, validated replica of app/engine.py for research sweeps.

The real engine re-slices the frame every bar (O(n^2) over ~70k H1 bars), so it
cannot drive a parameter sweep. This module replays the SAME rules in one linear
pass. It has been lost twice to a wiped scratch directory; it lives in the repo
now, and it must be re-validated before any number it produces is trusted:

    python -m scripts.research_harness          # prints VALIDATE lines

Every VALIDATE line must reproduce the documented references (docs/RESEARCH.md):
    flat 5x cap               12.4 / 34.2 / 0.58 / 219
    linear ramp atr1.5 fl1.0  15.3 / 26.7 / 0.83 / 219   <- production config
    linear ramp atr2.0 fl1.0  13.3 / 25.6 / 0.81 / 219
    convex ramp pow 2         15.5 / 24.6 / 0.89 / 219

Engine conventions mirrored (app/engine.py, app/strategies/trend.py):
  * signal: long while close > SMA(n) including the current bar, else flat
    (score 0.6 vs entry 0.20 / exit 0.08 -> plain enter/exit)
  * per bar: intrabar stop FIRST (low <= stop -> exit at stop - half spread),
    then the signal, so a stopped trade can re-open on the same bar
  * entry fill = close + half spread; stop = fill - max(1.5*ATR, 5 pips)
  * size = min(int(bal*risk/stop_dist), max_units, int(lev*bal/price))
  * commission per side = |units|/1e6 * comm; equity marked at the close
  * conviction-scaled leverage from app/sizing.conviction_leverage
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

FXSIM = Path(__file__).resolve().parent.parent
if str(FXSIM) not in sys.path:
    sys.path.insert(0, str(FXSIM))

from app.backtest import WARMUP, candles_to_df  # noqa: E402
from app.indicators import enrich  # noqa: E402
from app.providers.csv import load_csv_file  # noqa: E402

PIP = 0.01
UNITS_PER_LOT = 100_000
_cache: dict = {}


def data(path: str | Path | None = None, start_year: int = 2015) -> pd.DataFrame:
    key = ("df", str(path), start_year)
    if key not in _cache:
        p = Path(path) if path else FXSIM / "data" / "USD_JPY_H1.csv"
        cs = [c for c in load_csv_file(p, "USD_JPY", "H1") if c.time.year >= start_year]
        _cache[key] = enrich(candles_to_df(cs)).reset_index(drop=True)
    return _cache[key]


def arrays(path=None, start_year: int = 2015) -> dict:
    key = ("arr", str(path), start_year)
    if key not in _cache:
        df = data(path, start_year)
        _cache[key] = dict(cl=df["close"].to_numpy(float), hi=df["high"].to_numpy(float),
                           lo=df["low"].to_numpy(float), atr=df["atr"].to_numpy(float),
                           t=pd.to_datetime(df["time"]).reset_index(drop=True), n=len(df),
                           close=df["close"])
    return _cache[key]


def sma(n: int, a: dict | None = None) -> np.ndarray:
    a = a or arrays()
    return a["close"].rolling(n).mean().to_numpy()


def trend_mask(n: int = 2400, a: dict | None = None) -> np.ndarray:
    a = a or arrays()
    return np.nan_to_num(a["cl"] > sma(n, a)).astype(bool)


def dyn_lev(atr_mult=1.5, floor=1.0, cap=5.0, power=1.0, n=2400, a=None) -> np.ndarray:
    """Per-bar leverage cap, vectorised app/sizing.conviction_leverage. Bars
    before the SMA is defined get the flat cap, as the engine does."""
    a = a or arrays()
    m = sma(n, a)
    s = np.clip((a["cl"] - m) / (atr_mult * a["atr"]), 0.0, 1.0)
    lev = floor + (cap - floor) * np.power(s, power)
    return np.where(np.isnan(m) | ~(a["atr"] > 0), cap, lev)


def sim(long_mask, lev=None, *, cap=5.0, risk=0.04, spread=0.8, comm=50.0,
        max_units=100_000, bal0=500_000.0, stop_atr=1.5, i0=None, i1=None,
        carry=0.0, a=None, keep_trades=False, size_mode="engine") -> dict:
    """One pass of the engine's rules. `carry` = annual swap as a fraction of
    notional, credited per held hour (0 reproduces the engine, which books no
    swap). Returns CAGR %, maxDD %, Sharpe (hourly, x sqrt(252*24)), trades.

    Research-only extensions (defaults reproduce the engine exactly):
      stop_atr=None      no protective stop (buy-and-hold, SMA-exit-only)
      size_mode="lev"    size purely by leverage: units = int(lev*bal/price),
                         ignoring risk and max_units (buy-and-hold benchmarks)"""
    a = a or arrays()
    cl, hi, lo, at, t = a["cl"], a["hi"], a["lo"], a["atr"], a["t"]
    n = len(cl)
    i0 = WARMUP if i0 is None else i0
    i1 = n if i1 is None else i1
    hs = spread * PIP / 2.0
    levs = lev if lev is not None else np.full(n, cap)
    hours = t.diff().dt.total_seconds().fillna(3600).to_numpy() / 3600.0
    bal, units, entry, stop = float(bal0), 0, 0.0, 0.0
    trades, held_bars = 0, 0
    eqs = np.empty(i1 - i0)
    log = [] if keep_trades else None
    entry_i = 0

    def cm(u):
        return abs(u) / 1_000_000.0 * comm

    def close_at(fill, i, why):
        nonlocal bal, units, trades
        pnl = units * (fill - entry) - cm(units)
        bal += pnl
        if log is not None:
            log.append(dict(entry_t=t[entry_i], exit_t=t[i], entry=entry, exit=fill,
                            units=units, pnl=pnl, why=why, bars=i - entry_i))
        units = 0
        trades += 1

    for k, i in enumerate(range(i0, i1)):
        price = cl[i]
        av = at[i] if not math.isnan(at[i]) else PIP * 10
        if units and stop_atr is not None and lo[i] <= stop:
            close_at(stop - hs, i, "stop")
        if units == 0:
            if long_mask[i]:
                L = float(levs[i])
                if size_mode == "lev":
                    u = int(L * bal / price) if (L > 0 and price > 0) else 0
                    sd = None
                else:
                    sd = max(av * (stop_atr if stop_atr is not None else 1.5), PIP * 5)
                    u = min(int(bal * risk / sd), max_units)
                    if L > 0 and price > 0:
                        u = min(u, int(L * bal / price))
                if u > 0:
                    entry = price + hs
                    stop = (entry - sd) if (stop_atr is not None and sd is not None) else -1e18
                    bal -= cm(u)
                    units = u
                    entry_i = i
        elif not long_mask[i]:
            close_at(price - hs, i, "trend")
        if units:
            held_bars += 1
            if carry:
                bal += units * price * carry * hours[i] / (365.0 * 24.0)
        eqs[k] = bal + units * (price - entry)
    if units:
        close_at(cl[i1 - 1] - hs, i1 - 1, "end")
    return stats(eqs, t[i0], t[i1 - 1], bal, trades, bal0, held_bars, log)


def stats(eqs, t0, t1, final, trades, bal0, held_bars=0, log=None) -> dict:
    peak = np.maximum.accumulate(eqs)
    mdd = float(np.max((peak - eqs) / peak) * 100) if len(eqs) else 0.0
    yrs = (t1 - t0).days / 365.25
    cagr = ((final / bal0) ** (1 / yrs) - 1) * 100 if final > 0 and yrs > 0 else -100.0
    r = pd.Series(eqs).pct_change().dropna()
    sh = float(r.mean() / r.std() * math.sqrt(252 * 24)) if r.std() > 0 else 0.0
    out = dict(cagr=round(cagr, 1), mdd=round(mdd, 1), sharpe=round(sh, 2), trades=trades,
               mult=round(final / bal0, 2), exposure=round(held_bars / max(1, len(eqs)), 3),
               eq=eqs, final=final, years=round(yrs, 2))
    if log is not None:
        out["trades_log"] = log
    return out


def line(name: str, st: dict) -> str:
    return (f"{name:<44}{st['cagr']:>7}{st['mdd']:>8}{st['sharpe']:>8}{st['trades']:>7}"
            f"{st['mult']:>7}x {st['exposure'] * 100:>5.1f}%")


REFERENCES = {
    "flat5x": ((12.4, 34.2, 0.58, 219), dict(lev=None)),
    "lin1.5": ((15.3, 26.7, 0.83, 219), dict(lev=("dyn", 1.5, 1.0, 1.0))),
    "lin2.0": ((13.3, 25.6, 0.81, 219), dict(lev=("dyn", 2.0, 1.0, 1.0))),
    "convex": ((15.5, 24.6, 0.89, 219), dict(lev=("dyn", 1.5, 1.0, 2.0))),
}


def validate(verbose: bool = True) -> bool:
    m = trend_mask(2400)
    ok = True
    if verbose:
        print(f"{'variant':<44}{'CAGR%':>7}{'maxDD%':>8}{'Sharpe':>8}{'trades':>7}{'mult':>8} expo")
    for name, (want, spec) in REFERENCES.items():
        lv = spec["lev"]
        lev = None if lv is None else dyn_lev(lv[1], lv[2], 5.0, lv[3])
        st = sim(m, lev)
        got = (st["cagr"], st["mdd"], st["sharpe"], st["trades"])
        hit = got == want
        ok &= hit
        if verbose:
            print(line(f"VALIDATE {name} (want {'/'.join(map(str, want))})", st),
                  "OK" if hit else "MISMATCH")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if validate() else 1)
