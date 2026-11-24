"""Daily-bar port of the production rules, for the long USD/JPY history (Round-9).

The H1 data starts in 2015, so every H1 result is one regime (2015-26, a
yen-weakening carry trend). data/USD_JPY_D.csv goes back to 1971: close-only
before 1995 (Open=High=Low=Close), true OHLC from 1995-01. This module replays
the engine rules (app/engine.py as mirrored by research_harness.sim_ls) on those
daily bars so the shorts question can be asked out of sample.

    python -m scripts.research_daily_port      # validation + the Round-9 verdict table

It must print FOUR "OK" lines first: fed the H1 arrays, the port's loop equals
research_harness.sim_ls bit for bit (L, LS1, LS, S). Its LEVELS do not match H1
(production 2015-26: port 7.3/30.8/0.56 vs H1 18.8/26.9/1.00 — about four times
fewer trades, no intrabar stop/re-entry churn), only the SIGNS of the
candidate-minus-production differences do (decision rule D0). Treat every
number as a pessimistic proxy, never as a forecast.

Rules, per bar, in the engine's order:
  1. stop check FIRST: long stopped if Low <= stop, short if High >= stop; if
     the Open is already through the stop, fill at the Open. Close-only rows
     (pre-1995) can only stop on the Close. Fills are -/+ half the spread.
  2. signal at the Close: +1 above SMA100 (~SMA2400 H1), -1 below, 0 before the
     SMA exists. Modes L, S, LS (mirrored ramp), LS1 (short cap fixed at 1x —
     what app/sizing.py would give a short). Reverse on an opposite signal;
     a stopped trade may re-open at the same Close.
  3. swap per calendar day held (Fri->Mon = 3 days): long earns d-0.5%, short
     earns -d-0.5%, d = USD minus JPY policy rate (approximate table below).
Sizing: units = min(int(bal*0.04/stop_dist), int(lev*bal/price)), lev = the
production ramp 1 + 4*clip((C-SMA)/(kramp*ATR), 0, 1). ATR is 14-day Wilder on
the true range; pre-1995 it is f*|dClose| with f fitted on 1995-2026.
Variants: P-wide (stop and ramp at 1.5 daily ATRs; PRIMARY, chosen on 2015-26
only), P-cal (both at 1.5*rho daily ATRs, rho = median H1 ATR / median daily
ATR), P-nostop (ramp at 1.5*rho, no stop).
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

from scripts import research_harness as H  # noqa: E402

CSV = FXSIM / "data" / "USD_JPY_D.csv"
PIP = 0.01
OHLC_START = pd.Timestamp("1995-01-01")
FLOAT_START = "1973-03-01"          # before this the yen was pegged

# US effective fed funds / Japan call rate, % per year: approximate year
# averages from general knowledge, NOT a data feed. 2015+ from H.POLICY_RATES.
RATES_PRE = {
    1973: (8.7, 7.7), 1974: (10.5, 12.5), 1975: (5.8, 10.7), 1976: (5.0, 7.0),
    1977: (5.5, 5.7), 1978: (7.9, 4.4), 1979: (11.2, 5.9), 1980: (13.4, 10.9),
    1981: (16.4, 7.4), 1982: (12.3, 6.9), 1983: (9.1, 6.4), 1984: (10.2, 6.1),
    1985: (8.1, 6.5), 1986: (6.8, 4.8), 1987: (6.7, 3.5), 1988: (7.6, 3.6),
    1989: (9.2, 4.9), 1990: (8.1, 7.2), 1991: (5.7, 7.5), 1992: (3.5, 4.6),
    1993: (3.0, 3.1), 1994: (4.2, 2.2), 1995: (5.8, 1.2), 1996: (5.3, 0.5),
    1997: (5.5, 0.5), 1998: (5.4, 0.4), 1999: (5.0, 0.1), 2000: (6.2, 0.1),
    2001: (3.9, 0.1), 2002: (1.7, 0.0), 2003: (1.1, 0.0), 2004: (1.4, 0.0),
    2005: (3.2, 0.0), 2006: (5.0, 0.1), 2007: (5.0, 0.5), 2008: (1.9, 0.5),
    2009: (0.2, 0.1), 2010: (0.2, 0.1), 2011: (0.1, 0.1), 2012: (0.1, 0.1),
    2013: (0.1, 0.1), 2014: (0.1, 0.1),
}


def rate_diff(year: int) -> float:
    """USD minus JPY policy rate, as a fraction."""
    if year >= 2015:
        r = H.POLICY_RATES[min(year, 2026)]
        return (r[0] - r[1]) / 100.0
    u, j = RATES_PRE[year]
    return (u - j) / 100.0


def wilder(x: pd.Series, n: int = 14) -> pd.Series:
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


_RAW: pd.DataFrame | None = None


def raw() -> pd.DataFrame:
    global _RAW
    if _RAW is None:
        d = pd.read_csv(CSV, parse_dates=["Date"])
        d["close_only"] = d["Date"] < OHLC_START
        co = (d.Open == d.Close) & (d.High == d.Close) & (d.Low == d.Close)
        assert co[d.close_only].all(), "pre-1995 rows are expected to be close-only"
        assert (d.High[~d.close_only] >= d.Low[~d.close_only]).all()
        _RAW = d
    return _RAW


def _true_range(d: pd.DataFrame) -> pd.Series:
    pc = d.Close.shift(1)
    return pd.concat([d.High - d.Low, (d.High - pc).abs(), (d.Low - pc).abs()], axis=1).max(axis=1)


def calib_f() -> float:
    """f = median(Wilder ATR) / median(Wilder mean |dClose|) on 1995-01..2026-06."""
    o = raw()
    o = o[~o.close_only].reset_index(drop=True)
    return float(np.nanmedian(wilder(_true_range(o))) / np.nanmedian(wilder(o.Close.diff().abs())))


def prepare(start: str = FLOAT_START, f: float | None = None, force_close_only: bool = False) -> dict:
    """Arrays for the slice of the daily file from `start` on (SMA100 and ATR are
    built on that slice only). force_close_only treats every row as close-only."""
    d = raw()
    d = d[d.Date >= pd.Timestamp(start)].reset_index(drop=True)
    f = calib_f() if f is None else f
    co = d.close_only.to_numpy() | force_close_only
    tr = pd.Series(np.where(co, f * d.Close.diff().abs(), _true_range(d)), index=d.index)
    tr.iloc[0] = np.nan
    atr = wilder(tr)
    dates = d.Date
    o, h, l, c = (d[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    if force_close_only:
        o = h = l = c
    return dict(t=dates, o=o, h=h, l=l, c=c, co=co, atr=atr.to_numpy(float),
                sma=d.Close.rolling(100).mean().to_numpy(float),
                days=dates.shift(-1).sub(dates).dt.days.fillna(1).to_numpy(float),
                diff=np.array([rate_diff(y) for y in dates.dt.year]), f=f, n=len(d))


def idx(a: dict, date: str) -> int:
    return int(a["t"].searchsorted(pd.Timestamp(date)))


def signal(a: dict, mode: str) -> np.ndarray:
    m = a["sma"]
    s = np.where(a["c"] > m, 1, -1).astype(np.int8)
    s[np.isnan(m)] = 0
    if mode == "L":
        s[s < 0] = 0
    elif mode == "S":
        s[s > 0] = 0
    return s


def levs(a: dict, kramp: float, mode: str):
    m, c, at = a["sma"], a["c"], a["atr"]
    bad = np.isnan(m) | ~(at > 0)

    def ramp(dist):
        return np.where(bad, 5.0, 1.0 + 4.0 * np.clip(dist / (kramp * at), 0.0, 1.0))
    lL, lS = ramp(c - m), ramp(m - c)
    if mode == "LS1":
        lS = np.ones_like(lS)
    return lL, lS


def calib_rho() -> float:
    """median(H1 ATR) / median(daily ATR) over the H1 window (2015-01..2026-06)."""
    ha = H.pair_arrays("USD_JPY")
    t0, t1 = ha["t"].iloc[0].tz_localize(None), ha["t"].iloc[-1].tz_localize(None)
    a = prepare(FLOAT_START)
    m = ((a["t"] >= t0.normalize()) & (a["t"] <= t1)).to_numpy()
    return float(np.nanmedian(ha["atr"]) / np.nanmedian(a["atr"][m]))


def variants(rho: float | None = None) -> dict:
    k = 1.5 * (calib_rho() if rho is None else rho)
    return {"P-wide": dict(kstop=1.5, kramp=1.5, stop=True),        # PRIMARY (chosen on 2015-26)
            "P-cal": dict(kstop=k, kramp=k, stop=True),
            "P-nostop": dict(kstop=None, kramp=k, stop=False)}


PRIMARY = "P-wide"


def sim(a: dict, mode: str, var: dict, i0: int = 0, i1: int | None = None, *, spread: float = 0.8,
        swap: bool = True, shift: float = 0.0, markup: float = 0.005, bal0: float = 500_000.0,
        risk: float = 0.04, keep_trades: bool = False, gap: bool = True, ann: float = 252.0) -> dict:
    n = a["n"]
    i1 = n if i1 is None else i1
    o, h, l, c, co, at, t = a["o"], a["h"], a["l"], a["c"], a["co"], a["atr"], a["t"]
    sig = signal(a, "LS" if mode == "LS1" else mode)
    lL, lS = levs(a, var["kramp"], mode)
    d = a["diff"] + shift
    cL = d - markup if swap else np.zeros(n)
    cS = -d - markup if swap else np.zeros(n)
    hs = spread * PIP / 2.0
    use_stop = var["stop"]
    bal, units, entry, stop = float(bal0), 0, 0.0, 0.0
    trades, held = 0, 0
    eqs = np.empty(i1 - i0)
    log = [] if keep_trades else None
    cur = None

    def close_at(fill, i, why):
        nonlocal bal, units, trades, cur
        pnl = units * (fill - entry)
        bal += pnl
        if log is not None:
            cur.update(exit_i=i, exit_t=t[i], exit=fill, price_pnl=pnl, why=why)
            log.append(cur)
        cur = None
        units = 0
        trades += 1

    def open_dir(dd, price, av, i):
        nonlocal units, entry, stop, cur
        L = float(lL[i] if dd > 0 else lS[i])
        if use_stop:
            sd = max(av * var["kstop"], PIP * 5)
            u = int(bal * risk / sd)
            if L > 0 and price > 0:
                u = min(u, int(L * bal / price))
        else:
            sd = None
            u = int(L * bal / price) if (L > 0 and price > 0) else 0
        if u <= 0:
            return
        entry = price + hs * dd
        stop = (entry - sd * dd) if use_stop else (-1e18 if dd > 0 else 1e18)
        units = u * dd
        if log is not None:
            cur = dict(dir=dd, entry_i=i, entry_t=t[i], entry=entry, units=units,
                       bal_at_entry=bal, lev=L, swap=0.0)

    for k, i in enumerate(range(i0, i1)):
        price = c[i]
        av = at[i] if not math.isnan(at[i]) else PIP * 10
        if units > 0 and use_stop:
            if co[i]:
                if price <= stop:
                    close_at(price - hs, i, "stop")
            elif l[i] <= stop:
                close_at((o[i] if (gap and o[i] <= stop) else stop) - hs, i, "stop")
        elif units < 0 and use_stop:
            if co[i]:
                if price >= stop:
                    close_at(price + hs, i, "stop")
            elif h[i] >= stop:
                close_at((o[i] if (gap and o[i] >= stop) else stop) + hs, i, "stop")
        s = int(sig[i])
        if units == 0:
            if s != 0:
                open_dir(s, price, av, i)
        else:
            dd = 1 if units > 0 else -1
            if s != 0 and s != dd:
                close_at(price - hs * dd, i, "reverse")
                open_dir(s, price, av, i)
            elif s == 0:
                close_at(price - hs * dd, i, "trend")
        if units:
            held += 1
            cc = cL[i] if units > 0 else cS[i]
            if cc and i < i1 - 1:
                sw = abs(units) * price * cc * a["days"][i] / 365.0
                bal += sw
                if cur is not None:
                    cur["swap"] += sw
        eqs[k] = bal + units * (price - entry)
    if units:
        dd = 1 if units > 0 else -1
        close_at(c[i1 - 1] - hs * dd, i1 - 1, "end")
    return stats(eqs, t[i0], t[i1 - 1], bal, trades, bal0, held, log, t.iloc[i0:i1], ann)


def stats(eqs, t0, t1, final, trades, bal0, held, log, tt, ann=252.0) -> dict:
    peak = np.maximum.accumulate(eqs)
    mdd = float(np.max((peak - eqs) / peak) * 100) if len(eqs) else 0.0
    yrs = (t1 - t0).days / 365.25
    cagr = ((final / bal0) ** (1 / yrs) - 1) * 100 if final > 0 and yrs > 0 else -100.0
    r = pd.Series(eqs).pct_change().dropna()
    sh = float(r.mean() / r.std() * math.sqrt(ann)) if r.std() > 0 else 0.0
    out = dict(cagr=cagr, mdd=mdd, sharpe=sh, trades=trades, expo=held / max(1, len(eqs)),
               final=final, mult=final / bal0, eq=eqs, tt=tt.reset_index(drop=True), years=yrs)
    if log is not None:
        out["log"] = log
    return out


def h1_as_port(n_sma: int = 2400) -> dict:
    """The H1 harness arrays in this module's format (validation only)."""
    a = H.pair_arrays("USD_JPY")
    n = len(a["cl"])
    return dict(t=a["t"].dt.tz_localize(None), o=a["cl"] * np.nan, h=a["hi"], l=a["lo"], c=a["cl"],
                co=np.zeros(n, bool), atr=a["atr"], sma=H.sma(n_sma, a), days=np.ones(n),
                diff=np.zeros(n), f=1.0, n=n)


def validate(verbose: bool = True) -> bool:
    """Fed the H1 arrays (SMA2400, H1 ATR, 1.5 stop/ramp, no gap rule, no swap),
    the port's loop must equal research_harness.sim_ls bit for bit."""
    a = h1_as_port()
    ha = H.pair_arrays("USD_JPY")
    lL, lS = H.dyn_lev_ls(1.5, 1.0, 5.0, 1.0, n=2400, a=ha)
    ok = True
    for mode in ("L", "LS1", "LS", "S"):
        st = sim(a, mode, dict(kstop=1.5, kramp=1.5, stop=True), i0=H.WARMUP, swap=False,
                 gap=False, ann=252 * 24)
        hs = H.sim_ls(H.ls_signal(2400, ha, "LS" if mode == "LS1" else mode), lL,
                      np.ones_like(lS) if mode == "LS1" else lS, pip=0.01, spread=0.8, comm=0.0,
                      max_units=None, a=ha)
        hit = abs(st["final"] - hs["final"]) < 1e-6 and st["trades"] == hs["trades"]
        ok &= hit
        if verbose:
            print(f"VALIDATE_PORT {mode:4s} port-loop bal {st['final']:,.2f} trades {st['trades']} | "
                  f"harness bal {hs['final']:,.2f} trades {hs['trades']}", "OK" if hit else "MISMATCH")
    return ok


PERIODS = [("D1 1995-2014 (out of sample)", "1995-01-01", "2015-01-01"),
           ("D2 1995-2026", "1995-01-01", "2026-07-01"),
           ("D3 1973-94 (close-only, supporting)", "1973-03-01", "1995-01-01"),
           ("2007-2012 (yen rally)", "2007-01-01", "2013-01-01")]


def main() -> int:
    if not validate():
        print("port loop MISMATCH — do not trust anything below")
        return 1
    V = variants()
    a = prepare(FLOAT_START)
    print("\nCAGR/maxDD/Sharpe, daily port, warm SMA from 1973-03, spread 0.8 pip, modelled swap "
          "[LS1 minus L Sharpe at swap / swap 0 / +1pp / -1pp]")
    for vn, var in V.items():
        print(f"\n== {vn}{' (PRIMARY)' if vn == PRIMARY else ''} ==")
        for name, s0, s1 in PERIODS:
            i0, i1 = idx(a, s0), idx(a, s1)
            r = {m: sim(a, m, var, i0, i1) for m in ("L", "LS1", "LS")}
            dd = []
            for use, sh in ((True, 0.0), (False, 0.0), (True, 0.01), (True, -0.01)):
                dd.append(sim(a, "LS1", var, i0, i1, swap=use, shift=sh)["sharpe"]
                          - sim(a, "L", var, i0, i1, swap=use, shift=sh)["sharpe"])
            row = " | ".join(f"{m} {x['cagr']:5.1f}/{x['mdd']:5.1f}/{x['sharpe']:6.3f}" for m, x in r.items())
            print(f"  {name:38s} {row}  [{' / '.join(f'{v:+.3f}' for v in dd)}]")
    i0, i1 = idx(a, "1995-01-01"), idx(a, "2015-01-01")
    st = sim(a, "L", V[PRIMARY], i0, i1, bal0=272_000.0)
    print(f"\nProduction (L, {PRIMARY}) 1995-01..2014-12 from 272,000 JPY: {st['final']:,.0f} JPY, "
          f"CAGR {st['cagr']:.2f}%, maxDD {st['mdd']:.1f}%, Sharpe {st['sharpe']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
