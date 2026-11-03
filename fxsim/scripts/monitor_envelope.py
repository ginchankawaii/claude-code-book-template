"""Derive the run_monitor envelopes from production's own behaviour.

The 取引頻度 (trade-rate) and リターン (return) checks used to compare the live
run with single numbers from the old flat-5x recipe (20 trades/yr, +12.4%/yr)
and annualised short spans, so normal production behaviour read 🔴 in 36-39%
of 60-90-day windows (Round-9). A RED that fires on normal behaviour teaches
the owner to ignore REDs, and REDs are also how a dead brain or EA is reported.

Two cadences are replayed, and every envelope covers BOTH:
  * "close" — one look per H1 close, the validated backtest (it must reproduce
    research_harness.sim_ls exactly: trades and final balance);
  * "live"  — what the live loop actually does (Round-9 review): the EA exports
    the FORMING H1 bar (CopyRates start 0) and the brain compares its current
    price with an SMA2400 that includes it on every 600 s poll, acting on a
    mismatch once 15 min have passed since the last gate action, stop or close.
    The broker SL can fire at any moment inside the bar. The path inside an
    hour is unknown from H1 data; the replay uses the smoothest path that fits
    the bar (O -> L -> H -> C, or O -> H -> L -> C on a down bar), at several
    poll phases. On real May-2026 15-minute data the live-like look logged
    1.89x the changes of one look per close; this replay logs about 2.2x.
    Its P&L matches the close cadence (CAGR 15.8% both under this model).

Position changes are counted the way the live log records them: each entry
and each exit, so a stop-out and its re-entry are two. Returns are simple
returns over the window WITHOUT swap (the live account earns swap, so this
errs toward fewer false alarms).

Each table row covers the spans from its own up to the next row's, and holds
the EXTREME over every whole-day span in that interval (no interpolation can
then understate the backtest's worst — the Round-9 review found 🔴 at spans
between sparse rows). Beyond the last row, counts scale with the span and the
return bounds hold the loosest row. Re-run whenever production changes:

    python -m scripts.monitor_envelope
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

N_SMA = 2400
RISK, STOP_ATR, CAP = 0.04, 1.5, 5.0
HS = 0.8 * 0.01 / 2.0                 # half of the 0.8-pip spread
LIVE_POLL_MIN, LIVE_COOLDOWN_MIN = 10, 15
LIVE_PHASES = (1, 3, 5, 7, 9)         # minute of the first poll after the hour
CHANGE_ROWS = (30, 45, 60, 75, 90, 120, 150, 180, 240, 300, 365, 450, 545, 640, 730,
               910, 1095, 1280, 1460)
RETURN_ROWS = CHANGE_ROWS[2:]         # the return check judges from 60 days on

_cache: dict = {}


def _arrays() -> dict:
    if "a" not in _cache:
        a = H.pair_arrays("USD_JPY")
        df = H.data(FXSIM / "data" / "USD_JPY_H1.csv")
        assert len(df) == len(a["cl"])
        t = a["t"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
        _cache["a"] = dict(cl=a["cl"], hi=a["hi"], lo=a["lo"], atr=a["atr"],
                           op=df["open"].to_numpy(float), t=t,
                           sec=t.astype("datetime64[s]").astype(np.int64),
                           sma=H.sma(N_SMA, a))
    return _cache["a"]


def _path(op, lo, hi, cl, f: float) -> float:
    """Smoothest intrahour path through the bar: O -> L -> H -> C on an up bar,
    O -> H -> L -> C on a down bar; f in [0, 1]."""
    x, y = (lo, hi) if cl >= op else (hi, lo)
    pts = (op, x, y, cl)
    s = f * 3.0
    k = min(int(s), 2)
    return pts[k] + (pts[k + 1] - pts[k]) * (s - k)


def _ramp(price: float, sma: float, atr: float) -> float:
    if math.isnan(sma) or not atr > 0:
        return CAP
    return 1.0 + (CAP - 1.0) * min(max((price - sma) / (STOP_ATR * atr), 0.0), 1.0)


def replay(cadence: str = "close", phase_min: int = 5) -> dict:
    """Production long-only. cadence: "close" (the backtest), "closedbar" (the
    live brain since Round-9: closed-bar signal at 10-min polls, re-entry after
    a stop only once the stop's bar has closed), "live" (the live brain before
    Round-9: the forming bar at 10-min polls). Returns per-bar equity (from
    H.WARMUP), the bar times, the change times, trades and the final balance."""
    A = _arrays()
    cl, hi, lo, op, atr, sma, t, sec = (A[k] for k in ("cl", "hi", "lo", "op", "atr", "sma", "t", "sec"))
    n = len(cl)
    bal, u, entry, stop = 500_000.0, 0, 0.0, 0.0
    last_gate = -1e18
    trades = 0
    changes: list = []
    eqs = np.empty(n - H.WARMUP)
    live = cadence in ("live", "closedbar")
    closedbar = cadence == "closedbar"
    stop_bar = -1
    looks = [(phase_min + m) / 60.0 for m in range(0, 60, LIVE_POLL_MIN)] if live else [1.0]

    def close_at(fill, when):
        nonlocal bal, u, trades, last_gate
        bal += u * (fill - entry)
        u = 0
        trades += 1
        changes.append(when)
        last_gate = when

    for k, i in enumerate(range(H.WARMUP, n)):
        o, h_, l_, c = op[i], hi[i], lo[i], cl[i]
        if not live:
            # the backtest: stop first (whole bar), then the signal at the close
            if u and l_ <= stop:
                close_at(stop - HS, sec[i] + 3600)
            if not math.isnan(sma[i]):
                av = atr[i] if not math.isnan(atr[i]) else 0.1
                if u and not c > sma[i]:
                    close_at(c - HS, sec[i] + 3600)
                elif not u and c > sma[i]:
                    sd = max(av * STOP_ATR, 0.05)
                    x = min(int(bal * RISK / sd), int(_ramp(c, sma[i], av) * bal / c))
                    if x > 0:
                        u, entry, stop = x, c + HS, c + HS - sd
                        changes.append(sec[i] + 3600)
            eqs[k] = bal + u * (c - entry)
            continue
        prev_sum = sma[i] * N_SMA - c if not math.isnan(sma[i]) else math.nan
        av = atr[i - 1] if not math.isnan(atr[i - 1]) else 0.1      # last CLOSED bar's ATR
        fprev = 0.0
        if u and o <= stop:                                          # gap through the SL
            close_at(o - HS, sec[i])
            stop_bar = i
        for f in looks + [1.0]:
            # broker SL anywhere on the path since the previous look
            if u:
                cand = [fprev, f] + [v for v in (1 / 3, 2 / 3) if fprev < v < f]
                if min(_path(o, l_, h_, c, g) for g in cand) <= stop:
                    close_at(stop - HS, sec[i] + int(f * 3600))
                    stop_bar = i
            fprev = f
            if f == 1.0 or math.isnan(prev_sum):
                continue                                             # the bar end is not a poll
            p = _path(o, l_, h_, c, f)
            now = sec[i] + int(f * 3600)
            if now - last_gate < LIVE_COOLDOWN_MIN * 60:
                continue
            if closedbar:
                # the fixed brain: signal, ramp and ATR from the last CLOSED
                # bar; after a stop no re-entry until the stop's bar has closed
                if math.isnan(sma[i - 1]):
                    continue
                up = cl[i - 1] > sma[i - 1]
                lev_px, lev_ma = cl[i - 1], sma[i - 1]
                if not u and stop_bar == i:
                    continue
            else:
                # today's live loop: the forming bar against an SMA including it
                s_now = (prev_sum + p) / N_SMA
                up = p > s_now
                lev_px, lev_ma = p, s_now
            if u and not up:
                close_at(p - HS, now)
            elif not u and up:
                sd = max(av * STOP_ATR, 0.05)
                x = min(int(bal * RISK / sd), int(_ramp(lev_px, lev_ma, av) * bal / p))
                if x > 0:
                    u, entry, stop = x, p + HS, p + HS - sd
                    changes.append(now)
                    last_gate = now
        eqs[k] = bal + u * (c - entry)
    if u:
        bal += u * (cl[-1] - HS - entry)
        trades += 1                                                  # the forced close at the end
    return dict(eq=eqs, t=t[H.WARMUP:], changes=np.array(changes, dtype=np.int64),
                trades=trades, final=bal)


def _ends(t: np.ndarray) -> np.ndarray:
    return np.arange(0, len(t), 24)                                  # one window end per ~day


def window_counts(r: dict, span_days: int) -> np.ndarray:
    tsec = r["t"].astype("datetime64[s]").astype(np.int64)
    ks = _ends(r["t"])
    e = tsec[ks]
    s = e - span_days * 86400
    ok = s >= tsec[0]
    ch = r["changes"]
    return np.searchsorted(ch, e[ok], side="right") - np.searchsorted(ch, s[ok], side="right")


def window_returns(r: dict, span_days: int) -> np.ndarray:
    tsec = r["t"].astype("datetime64[s]").astype(np.int64)
    ks = _ends(r["t"])
    s = tsec[ks] - span_days * 86400
    ok = s >= tsec[0]
    j = np.searchsorted(tsec, s[ok])
    return (r["eq"][ks[ok]] / r["eq"][j] - 1.0) * 100.0


def runs(phases=LIVE_PHASES) -> list[dict]:
    """Every cadence the live log may contain: the current live run began
    before the Round-9 closed-bar fix, so its history holds both."""
    return ([replay("close")] + [replay("closedbar", p) for p in phases]
            + [replay("live", p) for p in phases])


def build(rs: list[dict]) -> tuple[tuple, tuple]:
    """Step tables: each row holds the extreme over every whole-day span from
    its own to the next row's (exclusive); the last row is its span alone."""
    def rows_for(table, fn, agg):
        out = []
        for a_, b_ in zip(table, table[1:] + (table[-1] + 1,)):
            vals = [fn(r, s) for r in rs for s in range(a_, b_)]
            out.append((a_,) + agg(vals))
        return tuple(out)

    def chg_agg(vals):
        return (int(max(math.ceil(np.percentile(v, 90)) for v in vals if len(v))),
                int(max(v.max() for v in vals if len(v))))

    def ret_agg(vals):
        return (round(float(min(np.percentile(v, 10) for v in vals if len(v))) - 0.05, 1),
                round(float(min(v.min() for v in vals if len(v))) - 0.05, 1))

    return rows_for(CHANGE_ROWS, window_counts, chg_agg), rows_for(RETURN_ROWS, window_returns, ret_agg)


def validate(verbose: bool = True) -> bool:
    """The close cadence must reproduce the validated harness exactly."""
    a = H.pair_arrays("USD_JPY")
    lL, lS = H.dyn_lev_ls(1.5, 1.0, 5.0, 1.0, n=N_SMA, a=a)
    hs = H.sim_ls(H.ls_signal(N_SMA, a, "L"), lL, lS, pip=0.01, spread=0.8, comm=0.0,
                  max_units=None, a=a)
    r = replay("close")
    ok = r["trades"] == hs["trades"] and abs(r["final"] - hs["final"]) < 0.01
    if verbose:
        print(f"VALIDATE_ENVELOPE close cadence: trades {r['trades']} bal {r['final']:,.2f} | "
              f"harness trades {hs['trades']} bal {hs['final']:,.2f}", "OK" if ok else "MISMATCH")
    return ok


def main() -> int:
    if not validate():
        return 1
    rs = runs()
    yrs = (rs[0]["t"][-1] - rs[0]["t"][0]) / np.timedelta64(1, "D") / 365.25
    names = (["close"] + [f"closedbar p{p}" for p in LIVE_PHASES]
             + [f"forming-bar p{p}" for p in LIVE_PHASES])
    for r, name in zip(rs, names):
        cagr = ((r["final"] / 500_000.0) ** (1 / yrs) - 1) * 100
        eq = r["eq"]
        mdd = float(np.max(1 - eq / np.maximum.accumulate(eq)) * 100)
        print(f"# {name:13s}: CAGR {cagr:5.1f}% maxDD {mdd:4.1f}% "
              f"{len(r['changes']) / yrs:5.1f} position changes/yr")
    chg, ret = build(rs)
    print("ENVELOPE_CHANGES = (   # (from span_days, p90 count, max count), both cadences")
    for row in chg:
        print(f"    {row},")
    print(")")
    print("ENVELOPE_RETURN = (    # (from span_days, p10 return %, worst return %), no swap")
    for row in ret:
        print(f"    {row},")
    print(")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
