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
        inst = p.stem.replace("_H1", "") if p.stem.endswith("_H1") else "USD_JPY"
        cs = [c for c in load_csv_file(p, inst, "H1") if c.time.year >= start_year]
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





# --------------------------------------------------------------------------- #
# Round-9: long/short and other pairs. A SEPARATE function so the validated
# long-only `sim` above stays untouched; `validate_ls()` proves sim_ls equals
# sim on the four references and equals the real engine on short trades.
# --------------------------------------------------------------------------- #
PAIRS = ("USD_JPY", "EUR_USD", "GBP_JPY", "AUD_USD", "GBP_AUD")
# Conservative per-pair spreads (pips), the same as research_run9.
SPREADS = {"USD_JPY": 0.8, "GBP_JPY": 2.0, "EUR_USD": 0.8, "AUD_USD": 1.0, "GBP_AUD": 3.0}


def pip_of(pair: str) -> float:
    return 0.01 if pair.endswith("JPY") else 0.0001


def pair_arrays(pair: str, start_year: int = 2015) -> dict:
    return arrays(FXSIM / "data" / f"{pair}_H1.csv", start_year)


def ls_signal(n: int = 2400, a: dict | None = None, mode: str = "LS") -> np.ndarray:
    """+1 above SMA(n), -1 below it, 0 before it is defined. mode: 'L' long-only,
    'S' short-only, 'LS' both."""
    a = a or arrays()
    m = sma(n, a)
    sig = np.where(a["cl"] > m, 1, -1).astype(np.int8)
    sig[np.isnan(m)] = 0
    if mode == "L":
        sig[sig < 0] = 0
    elif mode == "S":
        sig[sig > 0] = 0
    return sig


def dyn_lev_ls(atr_mult=1.5, floor=1.0, cap=5.0, power=1.0, n=2400, a=None):
    """(long_cap, short_cap) per bar. The short ramp mirrors the long one:
    strength = (SMA - close) / (atr_mult*ATR). NOTE app/sizing.py's ramp is
    long-only by construction — a short there always gets the floor."""
    a = a or arrays()
    m = sma(n, a)
    bad = np.isnan(m) | ~(a["atr"] > 0)
    def ramp(dist):
        s = np.clip(dist / (atr_mult * a["atr"]), 0.0, 1.0)
        return np.where(bad, cap, floor + (cap - floor) * np.power(s, power))
    return ramp(a["cl"] - m), ramp(m - a["cl"])


def sim_ls(sig, lev_long=None, lev_short=None, *, cap=5.0, risk=0.04, pip=0.01,
           spread=0.8, comm=50.0, max_units=100_000, bal0=500_000.0, stop_atr=1.5,
           carry_long=None, carry_short=None, i0=None, i1=None, a=None,
           keep_trades=False) -> dict:
    """The engine's rules with both directions (app/engine.py step/_open/_close/
    _check_stops). Reverses on an opposite signal; exits on a zero signal.
    carry_long / carry_short: per-bar arrays (or scalars) of annual swap as a
    fraction of notional; negative = pays. max_units=None = unbounded."""
    a = a or arrays()
    cl, hi, lo, at, t = a["cl"], a["hi"], a["lo"], a["atr"], a["t"]
    n = len(cl)
    i0 = WARMUP if i0 is None else i0
    i1 = n if i1 is None else i1
    hs = spread * pip / 2.0
    LL = lev_long if lev_long is not None else np.full(n, cap)
    LS = lev_short if lev_short is not None else np.full(n, cap)
    cL = np.broadcast_to(np.asarray(carry_long if carry_long is not None else 0.0, float), (n,))
    cS = np.broadcast_to(np.asarray(carry_short if carry_short is not None else 0.0, float), (n,))
    hours = t.diff().dt.total_seconds().fillna(3600).to_numpy() / 3600.0
    bal, units, entry, stop = float(bal0), 0, 0.0, 0.0
    trades, held = 0, 0
    eqs = np.empty(i1 - i0)
    log = [] if keep_trades else None
    entry_i = 0
    cm = lambda u: abs(u) / 1_000_000.0 * comm

    def close_at(fill, i, why):
        nonlocal bal, units, trades
        bal += units * (fill - entry) - cm(units)
        if log is not None:
            log.append(dict(entry_t=t[entry_i], exit_t=t[i], dir=1 if units > 0 else -1,
                            entry=entry, exit=fill, units=units,
                            pnl=units * (fill - entry) - cm(units), why=why))
        units = 0
        trades += 1

    def open_dir(d, price, av, i):
        nonlocal bal, units, entry, stop, entry_i
        sd = max(av * stop_atr, pip * 5)
        u = int(bal * risk / sd)
        if max_units is not None:
            u = min(u, max_units)
        L = float(LL[i] if d > 0 else LS[i])
        if L > 0 and price > 0:
            u = min(u, int(L * bal / price))
        if u <= 0:
            return
        entry = price + hs * d
        stop = entry - sd * d
        bal -= cm(u)
        units = u * d
        entry_i = i

    for k, i in enumerate(range(i0, i1)):
        price = cl[i]
        av = at[i] if not math.isnan(at[i]) else pip * 10
        if units > 0 and lo[i] <= stop:                 # _check_stops, long
            close_at(stop - hs, i, "stop")
        elif units < 0 and hi[i] >= stop:               # _check_stops, short
            close_at(stop + hs, i, "stop")
        s = int(sig[i])
        if units == 0:
            if s != 0:
                open_dir(s, price, av, i)
        else:
            d = 1 if units > 0 else -1
            if s != 0 and s != d:                        # reverse
                close_at(price - hs * d, i, "reverse")
                open_dir(s, price, av, i)
            elif s == 0:                                 # signal-faded
                close_at(price - hs * d, i, "trend")
        if units:
            held += 1
            c = cL[i] if units > 0 else cS[i]
            if c:
                bal += abs(units) * price * c * hours[i] / (365.0 * 24.0)
        eqs[k] = bal + units * (price - entry)
    if units:
        d = 1 if units > 0 else -1
        close_at(cl[i1 - 1] - hs * d, i1 - 1, "end")
    return stats(eqs, t[i0], t[i1 - 1], bal, trades, bal0, held, log)


def validate_ls(verbose: bool = True) -> bool:
    """(1) long-only sim_ls == sim on all four references, bit for bit.
    (2) long/short sim_ls == the REAL PaperTradingEngine on USD/JPY and EUR/USD
        (flat cap, since the engine's ramp is long-only)."""
    ok = True
    sigL = ls_signal(2400, mode="L")
    for name, (want, spec) in REFERENCES.items():
        lv = spec["lev"]
        lev = None if lv is None else dyn_lev(lv[1], lv[2], 5.0, lv[3])
        st = sim_ls(sigL, lev)
        got = (st["cagr"], st["mdd"], st["sharpe"], st["trades"])
        ok &= got == want
        if verbose:
            print(f"VALIDATE_LS long-only {name:<7} {got} want {want}", "OK" if got == want else "MISMATCH")
    for pair in ("USD_JPY", "EUR_USD"):
        ok &= _vs_engine(pair, verbose)
    return ok


def _vs_engine(pair: str, verbose: bool) -> bool:
    from app.config import Settings
    from app.engine import PaperTradingEngine
    from app.models import Signal
    a = pair_arrays(pair)
    df = data(FXSIM / "data" / f"{pair}_H1.csv")
    sig = ls_signal(2400, a, "LS")
    i1 = min(len(sig), 2400 + 8000)                 # a long L/S stretch, kept fast
    cfg = Settings(initial_balance=500_000.0, risk_per_trade=0.04, max_leverage=5.0,
                   max_position_units=10**12, spread_pips=SPREADS[pair],
                   commission_per_million=50.0, dyn_leverage=False, use_take_profit=False,
                   trend_sma=2400, granularity="H1")
    eng = PaperTradingEngine(0, pair, None, cfg, persist=False)
    for i in range(WARMUP, i1):
        s = int(sig[i])
        eng.step(df.iloc[: i + 1], Signal(s, 0.6 if s else 0.0, "t") if s else Signal.flat("f"))
    eng.force_close(df.iloc[:i1])
    st = sim_ls(sig, None, None, pip=pip_of(pair), spread=SPREADS[pair], comm=50.0,
                max_units=None, i1=i1, a=a, keep_trades=True)
    eb, hb = round(eng.balance, 2), round(st["final"], 2)
    nt_e, nt_h = len(eng.closed_trades), st["trades"]
    shorts = sum(1 for x in st["trades_log"] if x["dir"] < 0)
    hit = abs(eb - hb) < 0.01 and nt_e == nt_h
    if verbose:
        print(f"VALIDATE_LS vs engine {pair}: engine bal {eb:,.2f} trades {nt_e} | "
              f"sim_ls bal {hb:,.2f} trades {nt_h} ({shorts} shorts)", "OK" if hit else "MISMATCH")
    return hit


if __name__ == "__main__":
    ok = validate()
    print()
    ok &= validate_ls()
    raise SystemExit(0 if ok else 1)


# Approximate year-average central-bank policy rates, % (public history, from
# general knowledge — NOT a data feed; every carry result must be shown with a
# sensitivity, including carry=0). Retail swap = differential minus a markup.
POLICY_RATES = {
    #        USD    JPY    EUR    GBP    AUD
    2015: (0.13, 0.05, -0.20, 0.50, 2.10),
    2016: (0.40, -0.05, -0.35, 0.40, 1.60),
    2017: (1.00, -0.10, -0.40, 0.30, 1.50),
    2018: (1.80, -0.10, -0.40, 0.65, 1.50),
    2019: (2.15, -0.10, -0.45, 0.75, 1.15),
    2020: (0.40, -0.10, -0.50, 0.25, 0.35),
    2021: (0.08, -0.10, -0.50, 0.10, 0.10),
    2022: (1.70, -0.10, 0.10, 1.50, 1.30),
    2023: (5.00, -0.10, 3.30, 4.70, 3.90),
    2024: (5.15, 0.10, 3.70, 5.10, 4.35),
    2025: (4.20, 0.45, 2.30, 4.30, 4.00),
    2026: (3.70, 0.75, 2.00, 3.75, 3.60),
}
_CCY = {"USD": 0, "JPY": 1, "EUR": 2, "GBP": 3, "AUD": 4}


def carry_arrays(pair: str, a: dict | None = None, markup: float = 0.005,
                 shift: float = 0.0, rates: dict | None = None):
    """(carry_long, carry_short) per bar for BASE_QUOTE: long earns
    r_base - r_quote, short earns r_quote - r_base, each minus `markup` (the
    broker's cut, on both sides). `shift` adds to the differential (sensitivity)."""
    a = a or pair_arrays(pair)
    rates = rates or POLICY_RATES
    base, quote = pair.split("_")
    yrs = a["t"].dt.year.to_numpy()
    diff = np.array([(rates[min(max(y, 2015), 2026)][_CCY[base]]
                      - rates[min(max(y, 2015), 2026)][_CCY[quote]]) / 100.0 for y in yrs])
    diff = diff + shift
    return diff - markup, -diff - markup
