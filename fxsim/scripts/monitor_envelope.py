"""Derive the run_monitor envelopes from production's own backtest.

The 取引頻度 (trade-rate) and リターン (return) checks used to compare the live
run with single numbers from the old flat-5x recipe (20 trades/yr, +12.4%/yr)
and annualised them, so short choppy stretches of NORMAL production behaviour
read 🔴: in production's own 2015-26 backtest the shipped checks were RED in
12-25% of trailing windows (trade rate) and 21-23% of 60-90-day windows
(return) — Round-9. A RED that fires on normal behaviour teaches the owner to
ignore REDs, and REDs are also how a dead brain or EA is reported.

This prints, for each observation span, the backtest's spread of
  * position changes, counted the way the live log does (each entry and each
    exit is a change; a stop-out followed by a re-entry is two), and
  * the window's simple return (%), WITHOUT swap (the live account earns swap,
    so this errs toward fewer false alarms),
as Python literals for app/monitor.py. Re-run it whenever the production
configuration changes:

    python -m scripts.monitor_envelope
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

FXSIM = Path(__file__).resolve().parent.parent
if str(FXSIM) not in sys.path:
    sys.path.insert(0, str(FXSIM))

from scripts import research_harness as H  # noqa: E402

CHANGE_SPANS = (30, 60, 90, 180, 365, 730, 1460)
RETURN_SPANS = (60, 90, 180, 365, 730, 1460, 2190)


def production_run(swap: bool = False) -> dict:
    """Production: USD/JPY long-only, SMA2400, linear ramp 1.5 ATR, 5x cap."""
    a = H.pair_arrays("USD_JPY")
    lL, lS = H.dyn_lev_ls(1.5, 1.0, 5.0, 1.0, n=2400, a=a)
    cL, cS = H.carry_arrays("USD_JPY", a) if swap else (None, None)
    st = H.sim_ls(H.ls_signal(2400, a, "L"), lL, lS, pip=0.01, spread=0.8, comm=0.0,
                  max_units=None, carry_long=cL, carry_short=cS, a=a, keep_trades=True)
    st["t"] = a["t"].iloc[H.WARMUP:].reset_index(drop=True)
    return st


def change_times(st: dict) -> pd.Series:
    """Every entry and every exit (except the forced close at the data's end)."""
    ts = []
    for tr in st["trades_log"]:
        ts.append(tr["entry_t"])
        if tr["why"] != "end":
            ts.append(tr["exit_t"])
    return pd.Series(sorted(ts))


def envelopes(st: dict | None = None) -> tuple[list, list]:
    st = st or production_run()
    t = st["t"]
    eq = pd.Series(st["eq"])
    ct = change_times(st).to_numpy()
    tv = t.to_numpy()
    ends = range(0, len(t), 24)                      # one window end per ~day
    chg = []
    for W in CHANGE_SPANS:
        cnt = []
        for k in ends:
            e = tv[k]
            s = e - np.timedelta64(W, "D")
            if s < tv[0]:
                continue
            cnt.append(int(((ct > s) & (ct <= e)).sum()))
        cnt = np.array(cnt)
        chg.append((W, int(np.ceil(np.percentile(cnt, 90))), int(cnt.max())))
    ret = []
    for W in RETURN_SPANS:
        r = []
        for k in ends:
            e = t[k]
            j = int(t.searchsorted(e - pd.Timedelta(days=W)))
            if t[0] > e - pd.Timedelta(days=W):
                continue
            r.append((eq.iloc[k] / eq.iloc[j] - 1) * 100)
        r = np.array(r)
        ret.append((W, round(float(np.percentile(r, 10)), 1), round(float(r.min()), 1)))
    return chg, ret


def main() -> int:
    st = production_run()
    chg, ret = envelopes(st)
    n_years = (st["t"].iloc[-1] - st["t"].iloc[0]).days / 365.25
    print(f"# production backtest: {st['cagr']}/{st['mdd']}/{st['sharpe']}, {st['trades']} trades, "
          f"{len(change_times(st)) / n_years:.1f} position changes/yr")
    print("ENVELOPE_CHANGES = (   # (span_days, p90 count, max count)")
    for row in chg:
        print(f"    {row},")
    print(")")
    print("ENVELOPE_RETURN = (    # (span_days, p10 return %, min return %), no swap")
    for row in ret:
        print(f"    {row},")
    print(")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
