"""Live trader on the MT5 file-bridge: validated trend edge + Opus overlay.

The DECISION is the OOS-validated long-or-flat trend filter (be long only while
price > its long SMA, else stand aside — docs/RESEARCH.md). The AI is consulted
at the KEY MOMENTS only (once a day, shortly after each high-impact USD/JPY
release, and on fresh gate entries); how much it may OVERRULE is bounded by
FXSIM_AI_AUTHORITY (round-3 inquest — the AI overlay is the only unvalidated
layer): "shadow" (default) logs its view but the validated edge decides;
"entry" lets it veto fresh entries only (never liquidate a hold); "full" is the
legacy behavior. It never shorts and never opens a long the trend filter
doesn't already justify. With no API key the trend edge runs on its own.
Sizing = conviction x hard max-risk x a conviction-scaled leverage cap (<=5x:
convex ramp — near the floor at the SMA, full cap only when the trend is well
established; app/sizing.py, docs/RESEARCH.md), scaled down on drawdown; in
shadow authority the conviction is pinned to the validated 0.6 reference.

Round-2 execution model (docs/RESEARCH.md: the daily-only loop cost ~half the
CAGR and doubled drawdown vs the backtest):
  * GATE WATCH  — every poll tick the trend state is compared to the live book;
    a mismatch (trend up & flat, or trend down & long) triggers a decision NOW
    instead of waiting for the daily slot. Exits never wait on the AI.
  * NO RETARGET — while a long is open its size is held (sizing happens at entry
    only, like the engine). Intra-trade resize was tested and is net harmful.
  * PYTHON STOP — the EA places no SL, so this loop enforces the engine's
    1.5-ATR protective stop between decisions and re-enters via the gate when
    the trend still holds. Survives restarts (recovered from the last signal).
  * VETO TTL    — a vetoed entry suppresses gate re-entries for --veto-ttl-h so
    the (paid) AI isn't re-consulted every poll while it says stand-aside.

  python -m scripts.run_ai_bridge --once --dry   # one decision, no order written
  python -m scripts.run_ai_bridge --once          # one decision now (writes signal)
  python -m scripts.run_ai_bridge                 # resident: daily + post-event

Default timeframe is H1 / SMA2400 (~100-day filter — the best OOS recipe,
docs/RESEARCH.md). The SteadyBridge EA must publish H1 bars (InpTimeframe=PERIOD_H1,
InpBars>=2405); see docs/AI_TRADER.md. To fall back to daily: `--granularity D --sma 90`.

Requires: SteadyBridge EA attached in MT5 (writes status/bars, executes signals).
ANTHROPIC_API_KEY in fxsim/.env enables the Opus veto; without it the trend edge
still trades. See docs/AI_TRADER.md.
"""
from __future__ import annotations

import argparse
import atexit
import json
import math
import os
import signal
import socket
import sys as _sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app import bridge, db
from app.adaptive import AdaptiveConfig, AdaptiveController
from app.ai_trader import AITrader, size_lots
from app.config import Settings, pip_size
from app.events import get_calendar
from app.indicators import candles_to_df, enrich
from app.providers.csv import load_csv_file
from app.sizing import conviction_leverage


def _find_run(granularity: str = "H1") -> Optional[int]:
    """The ongoing steady-ai run id FOR THIS GRANULARITY, or None. Read-only.

    Round-4 chaos audit (worst finding of the round): matching on the params
    string alone let a restart adopt an unrelated, never-ended run from an
    older era — whose 180-day-old stop instantly liquidated a healthy
    position. The run must match the configuration it will govern."""
    for r in db.list_runs():
        if (not r.get("ended_at") and "steady-ai" in (r.get("params") or "")
                and (r.get("granularity") or "H1") == granularity):
            return r["id"]
    return None


def _ongoing_run(start_balance: float, model: str, max_risk: float,
                 granularity: str = "H1") -> int:
    rid = _find_run(granularity)
    if rid is not None:
        return rid
    return db.create_run(mode="live", instrument="USD_JPY", granularity=granularity,
                         initial_balance=start_balance,
                         params={"system": "steady-ai", "model": model, "max_risk": max_risk})


# Bars older than this are refused (weekend + a Monday holiday still passes;
# a wedged/detached EA feed or a frozen fallback CSV does not).
MAX_BAR_AGE_H = 75.0
# A last bar further than this from the previous close is quarantined as a
# feed glitch (Round-4: a single corrupt print — close=0.001, or a +15% spike —
# drove REAL orders; USD/JPY has never moved 3% in one H1 bar).
MAX_BAR_JUMP_PCT = 3.0


def _load_bars(instrument: str, granularity: str, sma_n: int, history_csv: str):
    """Candles for BOTH the poll probe and the decision — ONE threshold, ONE
    freshness rule, ONE plausibility rule, so the two can never disagree about
    the data source. Returns None when the feed can't be trusted this tick;
    callers must skip, never guess (and the resident loop's stop-liveness
    heartbeat then fails the book safe within the signal TTL)."""
    need = sma_n + 5
    candles = bridge.read_bars(instrument, granularity)
    src = "ea"
    if len(candles) < need:
        # Bootstrap only: an EA that has published NOTHING yet. A repo CSV must
        # never silently replace a live feed, and even then it must be fresh.
        if len(candles) == 0 and Path(history_csv).exists():
            candles = load_csv_file(Path(history_csv), instrument, granularity)
            src = "csv"
        if len(candles) < need:
            print(f"[ai] bars not ready ({len(candles)}/{need} bars from {src}); skipping",
                  flush=True)
            return None
    last_t = candles[-1].time
    if last_t.tzinfo is None:
        last_t = last_t.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - last_t).total_seconds() / 3600.0
    if age_h > MAX_BAR_AGE_H:
        print(f"[ai] bars STALE (last {last_t.isoformat()} = {age_h:.0f}h old, src={src}); "
              f"refusing to trade on them", flush=True)
        return None
    # Plausibility: quarantine an implausible last print instead of trading it.
    last_c, prev_c = float(candles[-1].close), float(candles[-2].close)
    if not (last_c > 0 and prev_c > 0):
        print(f"[ai] bars IMPLAUSIBLE (close {last_c}/{prev_c}); quarantining feed", flush=True)
        return None
    jump = abs(last_c / prev_c - 1) * 100
    if jump > MAX_BAR_JUMP_PCT:
        print(f"[ai] bars IMPLAUSIBLE ({jump:.1f}% single-bar jump {prev_c:.3f}->{last_c:.3f} "
              f"> {MAX_BAR_JUMP_PCT}%); quarantining feed", flush=True)
        return None
    return candles


# A book below this is dust, not a position: it is never adopted as intent,
# never heartbeated as LONG, and a decision over it sizes a FRESH entry (the
# EA's dust rule then converges the residue into the new target). One shared
# epsilon — the final-fuzz round found three inconsistent thresholds wedging
# a 0.007-lot intent into a heartbeat-less, fail-safe-less limbo.
FLAT_EPS = 0.01

# How often a blocked challenger re-evaluates the incumbent's lock, and how
# often it says so. Waiting is deliberately boring: the loop below NEVER exits.
LOCK_WAIT_TICK_S = 30.0
LOCK_WAIT_LOG_EVERY_S = 300.0


def _lock_line(poll: int) -> str:
    return f"{os.getpid()} {int(_time.time())} {int(poll)} {socket.gethostname()}\n"


def _holder_is_alive(pid: int, host: str) -> Optional[bool]:
    """Is the lock holder a RUNNING brain? None when we cannot know (the lock
    was written by another host/container, whose PIDs are invisible here)."""
    if not host or host != socket.gethostname():
        return None
    if pid <= 0 or pid == os.getpid():
        # Our own PID from a previous incarnation: a container restart hands
        # the successor the same PID, so this is provably a dead predecessor.
        return False
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace")
    except Exception:
        return False                      # no such process
    return "run_ai_bridge" in cmdline


def _lock_verdict(lock: Path, poll: int) -> tuple[str, str]:
    """What to do about an existing lock: ("take" | "wait", human message).

    There is deliberately no third answer. Earlier revisions could conclude
    "refuse and exit", and that verdict — not any double-brain — is what took
    the system down three times: the supervisor restarted the process, it
    re-read the same lock, exited again, and the account ran unsupervised for
    12-30 minutes at a stretch. A challenger that merely waits is strictly
    safer: it still cannot write, and it takes over the instant the incumbent
    stops heartbeating.

    Lock line: "<pid> <epoch> <poll> <host>". Liveness decides first, age is
    only the fallback for holders we cannot see (another container's PID
    namespace) — a dead predecessor's lock still looks fresh."""
    try:
        age = _time.time() - lock.stat().st_mtime
    except FileNotFoundError:
        return "take", "lock released by its holder"
    pid, holder_poll, host, parsed = 0, poll, "", False
    try:
        parts = lock.read_text().split()
        if len(parts) >= 1:
            pid = int(parts[0])
            parsed = True
        if len(parts) >= 3:
            holder_poll = max(1, int(float(parts[2])))
        if len(parts) >= 4:
            host = parts[3]
    except Exception:
        parsed = False
    if not parsed:
        # Unreadable/torn/garbage lock. Adopting it unconditionally let a torn
        # read pre-empt a LIVE incumbent (round-5). Wait one tick instead: a
        # torn read heals on the next write, a truly corrupt lock ages out.
        return "wait", f"brain lock is unreadable ({age:.0f}s old) — re-reading"
    # LIVENESS BEFORE AGE. The age fallback exists only for holders we cannot
    # see; applying it to a holder we CAN see evicts a brain that is provably
    # running the moment it misses one heartbeat (round-5: a single slow tick
    # or an errored tick was enough), which is the double-brain the lock exists
    # to prevent.
    alive = _holder_is_alive(pid, host)
    if alive is False:
        return "take", f"previous brain (pid {pid}) is gone — taking over its lock"
    if alive is True:
        return "wait", (f"another brain is LIVE (pid {pid}@{host}) — standing by until "
                        f"it stops")
    stale_after = holder_poll + 120                # one missed heartbeat + slack
    if age >= stale_after:
        return "take", (f"brain lock is stale ({age:.0f}s old > {stale_after:.0f}s) and "
                        f"its holder is unreachable — taking over")
    if not host:
        # Pre-upgrade lock format (no host field). Those were only ever written
        # from inside this container, so the PID is meaningful here even though
        # the lock does not say so — check it before adopting, rather than
        # assuming the writer has exited (round-5: that assumption evicted a
        # live incumbent still running the previous release).
        if _holder_is_alive(pid, socket.gethostname()) is True:
            return "wait", (f"legacy brain lock whose pid {pid} is LIVE here — standing "
                            f"by until it stops")
        return "take", f"legacy brain lock (no host field, {age:.0f}s old) — taking over"
    return "wait", (f"lock held by {pid}@{host}, liveness unknowable — standing by until "
                    f"its heartbeat lapses (~{stale_after - age:.0f}s)")


def _acquire_brain_lock(poll: int) -> Optional[Path]:
    """Block until this process is the single writer on the bridge.

    Two resident brains on one bridge ping-pong LONG/FLAT (Round-4 chaos:
    21 spurious round trips in 45s), so only one may hold the lock. This
    function never terminates the process to enforce that: it waits, re-judging
    every LOCK_WAIT_TICK_S, and acquires as soon as the incumbent is gone."""
    try:
        d = bridge.common_files_dir()
        d.mkdir(parents=True, exist_ok=True)
        lock = d / "steady_brain.lock"
        waited, last_log = 0.0, -LOCK_WAIT_LOG_EVERY_S
        while lock.exists():
            verdict, msg = _lock_verdict(lock, poll)
            if verdict == "take":
                print(f"[ai] {msg}", flush=True)
                break
            if waited - last_log >= LOCK_WAIT_LOG_EVERY_S:
                print(f"[ai] {msg}. Waiting, not exiting (waited {waited:.0f}s).",
                      flush=True)
                last_log = waited
            _time.sleep(LOCK_WAIT_TICK_S)
            waited += LOCK_WAIT_TICK_S
        _touch_lock(lock, poll)
        _arm_lock_release(lock)
        return lock
    except Exception as exc:
        print(f"[ai] brain lock unavailable ({exc}); continuing WITHOUT single-writer "
              f"protection", flush=True)
        return None


def _release_lock(lock: Optional[Path]) -> None:
    """Drop the lock if we still own it, so a successor starts immediately.

    Ownership is (pid, host), never pid alone: every containerised brain is
    PID 1, so a pid-only check made any brain delete any other brain's lock on
    shutdown — handing the bridge to a second writer (round-5)."""
    if lock is None:
        return
    try:
        parts = lock.read_text().split()
        mine = int(parts[0]) == os.getpid()
        same_host = len(parts) < 4 or parts[3] == socket.gethostname()
        if mine and same_host:
            lock.unlink()
    except Exception:
        pass


def _arm_lock_release(lock: Path) -> None:
    """Release the lock on a graceful stop (docker restart sends SIGTERM), so
    the successor never has to wait out a dead predecessor's grace period."""
    atexit.register(_release_lock, lock)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, lambda *_a, _l=lock: (_release_lock(_l), _sys.exit(0)))
        except Exception:
            pass


def _touch_lock(lock: Optional[Path], poll: int) -> None:
    """Heartbeat the lock. Atomic tmp+rename: an in-place rewrite gave readers
    a torn line, and a torn line used to be adopted as a free lock."""
    if lock is None:
        return
    try:
        tmp = lock.with_name(lock.name + f".{os.getpid()}.tmp")
        tmp.write_text(_lock_line(poll))
        os.replace(tmp, lock)
    except Exception:
        pass


def _trend_gate(instrument: str, granularity: str, sma_n: int,
                history_csv: str) -> Optional[tuple[bool, float, float]]:
    """Cheap poll probe: (trend_up, last_close, position_lots), or None if the
    bridge isn't ready. No AI call, no DB write — safe to run every poll tick."""
    status = bridge.read_status()
    if status is None or (status.get("equity") or 0) <= 0:
        return None
    candles = _load_bars(instrument, granularity, sma_n, history_csv)
    if candles is None:
        return None
    closes = [c.close for c in candles]
    price = float(closes[-1])
    ma = sum(closes[-sma_n:]) / float(sma_n)
    return price > ma, price, float(status.get("position_lots") or 0.0)


def _restore_state(granularity: str = "H1") -> tuple[Optional[str], Optional[float], float]:
    """After a restart: (intent "LONG"/"FLAT"/None, protective stop, epoch of
    the last decision). The stop is searched backward through the unbroken run
    of long decisions (older records may carry stop_price=null on holds), so a
    single poisoned hold record can't silently disarm an open position."""
    try:
        rid = _find_run(granularity)
        if rid is None:
            return None, None, 0.0
        sigs = [s for s in db.load_signals(rid) if s.get("source") == "combined"]
        if not sigs:
            return None, None, 0.0
        last = sigs[-1]
        intent = "LONG" if last.get("direction") == 1 else "FLAT"
        try:
            last_ts = datetime.fromisoformat(str(last.get("time"))).timestamp()
        except Exception:
            last_ts = 0.0
        stop = None
        if intent == "LONG":
            for s in reversed(sigs):
                if s.get("direction") != 1:
                    break
                comp = s.get("components")
                comp = json.loads(comp) if isinstance(comp, str) else (comp or {})
                sp = comp.get("stop_price")
                if sp:
                    stop = float(sp)
                    break
            if stop is None:
                print("[ai] WARNING: restored a LONG intent with NO recoverable stop — "
                      "the loop will re-arm one on the next decision", flush=True)
        return intent, stop, last_ts
    except Exception as exc:
        print(f"[ai] state restore failed: {exc}", flush=True)
        return None, None, 0.0


def build_context(instrument: str, candles, status: dict, granularity: str = "D") -> dict:
    df = enrich(candles_to_df(candles))
    last = df.iloc[-1]
    closes = df["close"]
    sma150 = float(closes.iloc[-150:].mean())
    sma50 = float(closes.iloc[-50:].mean())
    price = float(last["close"])
    atr = float(last["atr"]) if not math.isnan(last["atr"]) else price * 0.005
    rsi = float(last["rsi"]) if not math.isnan(last["rsi"]) else 50.0
    mom20 = (price / float(closes.iloc[-21]) - 1) * 100 if len(closes) > 21 else 0.0
    mom60 = (price / float(closes.iloc[-61]) - 1) * 100 if len(closes) > 61 else 0.0
    # Field names carry the bar timeframe honestly: on H1 a 20-bar momentum is
    # ~20 hours, not 20 days (round-3 inquest: the old *_20d labels misled the AI).
    return {
        "instrument": instrument,
        "bar_timeframe": granularity,
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "technical": {
            "price": round(price, 3),
            "sma150bar": round(sma150, 3),
            "dist_from_sma150bar_pct": round((price / sma150 - 1) * 100, 2),
            "sma50bar": round(sma50, 3),
            "rsi14": round(rsi, 1),
            "atr": round(atr, 3),
            "momentum_20bar_pct": round(mom20, 2),
            "momentum_60bar_pct": round(mom60, 2),
            "trend": "up" if price > sma150 else "down",
        },
        "account": {
            "balance": status.get("balance"),
            "equity": status.get("equity"),
            "current_position_lots": status.get("position_lots", 0.0),
        },
    }


def _next_seq(prev: int) -> int:
    """Mint an order id for the bridge's SEQ token.

    Wall-clock seconds, so it keeps increasing across brain restarts — a
    counter that restarted at 1 would read to the EA as a brand-new order and
    re-open a position closed while the brain was down. The +1 keeps it
    strictly increasing if two orders land inside the same second."""
    return max(int(prev) + 1, int(_time.time()))


def decide_once(cfg: Settings, instrument: str, max_risk: float, max_lots: float,
                history_csv: str, trader: AITrader, dry: bool, trigger: str,
                granularity: str = "D", sma_n: int = 90,
                prev_stop: Optional[float] = None, seq: int = 0) -> Optional[dict]:
    """One full decision. Returns {"action","lots","stop","fresh","seq"} or None
    if the bridge wasn't ready. "stop" is the protective stop the resident loop
    must enforce (new on fresh entries, carried on holds, None when flat).
    "seq" is the bridge order id: a HOLD re-asserts the standing order's id so
    the EA does not treat it as a new entry, anything else mints a fresh one."""
    status = bridge.read_status()
    if status is None or (status.get("equity") or 0) <= 0:
        print("[ai] waiting for EA status (balance/equity). Is SteadyBridge attached & synced?",
              flush=True)
        return None
    candles = _load_bars(instrument, granularity, sma_n, history_csv)
    if candles is None:
        return None

    balance = status["balance"]; equity = status["equity"]
    ctx = build_context(instrument, candles, status, granularity)
    # VALIDATED EDGE: long only while price > long SMA, else stand aside.
    closes = enrich(candles_to_df(candles))["close"]
    price = float(closes.iloc[-1]); ma = float(closes.iloc[-sma_n:].mean())
    trend_up = price > ma
    trend_txt = f"price {price:.3f} {'>' if trend_up else '<'} SMA{sma_n} {ma:.3f}"

    factors: list = []; plan = ""
    ai_view: dict = {}
    holding = float(status.get("position_lots") or 0.0) >= FLAT_EPS
    authority = getattr(cfg, "ai_authority", "shadow")
    if not trend_up:
        # Below the trend filter -> flat. No Opus call needed (edge stands aside).
        action, conviction, reason = "FLAT", 0.0, f"trend-down: {trend_txt} -> stand aside"
        print(f"[ai] ({trigger}) {reason}", flush=True)
    else:
        # Trend says long. The AI overlay is consulted at the key moments; how
        # much it may OVERRULE is bounded by cfg.ai_authority (round-3 inquest:
        # the overlay is the only unvalidated layer — the edge's profit sits in
        # a few long-held trends, so vetoed entries and AI-forced exits carry
        # unbounded opportunity cost while a stopped-out entry is bounded).
        print(f"[ai] ({trigger}) trend-up ({trend_txt}); consulting AI "
              f"(authority={authority})... pos={status.get('position_lots')}", flush=True)
        decision = trader.decide(ctx)
        veto = decision.ok and decision.action != "long"
        veto_binds = veto and (authority == "full" or (authority == "entry" and not holding))
        if decision.ok:
            ai_view = {"ai_action": decision.action, "ai_conviction": decision.conviction,
                       "ai_binding": veto_binds if veto else authority != "shadow"}
        if not decision.ok:
            # No key / API error: the deterministic trend edge still says LONG.
            action, conviction, reason = "LONG", 0.6, f"trend-up; AI unavailable ({decision.reason})"
        elif veto_binds:
            # Opted-in veto (never short): fresh entries in "entry" mode, plus
            # holds in legacy "full" mode.
            action, conviction, reason = "FLAT", 0.0, \
                f"trend-up but AI veto ({decision.action}): {decision.reason}"
            factors = decision.factors
        elif veto:
            # Advisory only: log the dissent, follow the validated edge at the
            # reference conviction.
            action, conviction = "LONG", 0.6
            reason = (f"trend-up; AI dissent logged (advisory, authority={authority}, "
                      f"ai={decision.action}): {decision.reason}")
            factors, plan = decision.factors, decision.plan
        elif authority == "shadow":
            # Confirmed long; in shadow mode sizing stays at the validated
            # reference (conviction scaling is unvalidated, reduce-only).
            action, conviction, reason = "LONG", 0.6, decision.reason
            factors, plan = decision.factors, decision.plan
        else:
            action, conviction, reason = "LONG", decision.conviction, decision.reason
            factors, plan = decision.factors, decision.plan

    # Dry runs must not touch the live run's history (audit: --dry created runs
    # and poisoned the signal/equity records the restart-restore and monitor read).
    now = datetime.now(timezone.utc)
    if dry:
        run_id = _find_run(granularity)
        eq_hist = ([e["equity"] for e in db.load_equity(run_id)] if run_id is not None else [])
    else:
        run_id = _ongoing_run(balance, trader.model, max_risk, granularity)
        db.record_equity(run_id, now, balance, equity, price)
        eq_hist = [e["equity"] for e in db.load_equity(run_id)]
    eq_hist = eq_hist or [equity]
    # Drawdown brake: OFF by default since Round-4 — the equivalence audit
    # backtested this live-only layer for the first time and it cost -4.3pp
    # CAGR while WORSENING maxDD (23.8 -> 27.1) on 11y USD/JPY: it de-levers
    # into recoveries. Opt back in with FXSIM_DD_BRAKE=1.
    if getattr(cfg, "dd_brake", False):
        brake, _, _ = AdaptiveController(AdaptiveConfig(base_risk=1.0, min_risk=0.2)).evaluate(eq_hist, [])
    else:
        brake = 1.0

    # Conviction-scaled leverage: within the same hard 5x cap, pull exposure down
    # toward the floor when price is near the SMA (whipsaw zone), full cap only
    # when the trend is well established. Matches the backtest engine
    # (docs/RESEARCH.md; convex ramp via dyn_lev_pow).
    atr_now = ctx["technical"]["atr"]
    eff_leverage = cfg.max_leverage
    if action == "LONG" and getattr(cfg, "dyn_leverage", False):
        eff_leverage = conviction_leverage(price, ma, atr_now, cfg.max_leverage,
                                           cfg.dyn_lev_atr_mult, cfg.dyn_lev_floor,
                                           getattr(cfg, "dyn_lev_pow", 1.0))
    pip = pip_size(instrument)
    pos_lots = float(status.get("position_lots") or 0.0)
    fresh = action == "LONG" and pos_lots < FLAT_EPS
    if action == "LONG" and not fresh:
        # Hold the size opened at entry. Intra-trade retargeting was tested and
        # is net harmful (round-2, docs/RESEARCH.md): it re-buys strength near
        # local tops and pays spread+commission for it. Size at entry only,
        # exactly like the backtest engine.
        lots = pos_lots
    else:
        lots = size_lots("long" if action == "LONG" else "flat", conviction, balance,
                         atr_now, pip, max_risk, max_lots, brake,
                         price=price, max_leverage=eff_leverage)
    if lots <= 0:
        action = "FLAT"
    direction = 1 if action == "LONG" else 0   # long-or-flat; never short
    risk_used = round(max_risk * conviction * brake, 4)
    # Protective stop (the engine's 1.5-ATR stop; the EA holds no SL, so the
    # resident loop enforces this between decisions): set at entry, carried
    # while holding, cleared when flat. INVARIANT (audit): an open LONG must
    # always carry a stop — if the carried one was lost (old records, manual
    # --once, wiped DB), re-arm from the current price and say so loudly.
    if action != "LONG":
        stop_price = None
    elif fresh or prev_stop is None:
        stop_price = round(price - max(1.5 * atr_now, 5 * pip), 3)
        if not fresh:
            print(f"[ai] WARNING: open position had NO stop — re-armed at "
                  f"{stop_price:.3f} (current price {price:.3f})", flush=True)
    else:
        stop_price = prev_stop

    if not dry:
        db.record_signal(run_id, now, instrument, "combined", direction,
                         conviction * direction, reason,
                         {"action": action, "conviction": conviction, "trend_up": trend_up,
                          "risk_used": risk_used, "brake": round(brake, 3),
                          "eff_leverage": round(eff_leverage, 2), "stop_price": stop_price,
                          "target_lots": lots, "position_lots": status.get("position_lots", 0.0),
                          "factors": factors, "plan": plan, "trigger": trigger,
                          # the AI's own view, recorded even when advisory — this
                          # is the forward dataset that can prove/disprove the
                          # veto skill before authority is (re)granted
                          **ai_view})
    stop_txt = f" stop {stop_price:.3f}" if stop_price else ""
    print(f"[ai] decision: {action} {lots:.2f} lots | conviction {conviction:.2f} "
          f"risk {risk_used:.3f} (brake {brake:.2f}) lev {eff_leverage:.1f}x{stop_txt} | {reason}",
          flush=True)
    for f in factors:
        print(f"      - {f}", flush=True)
    if plan:
        print(f"      ↳ 保有方針: {plan}", flush=True)
    # A HOLD re-asserts the order the EA already executed, so it MUST carry the
    # same SEQ: minting a new one would license the EA to open a position that
    # the broker stop had just closed. Everything else is a new order.
    out_seq = int(seq) if (action == "LONG" and not fresh and seq) else _next_seq(seq)
    if dry:
        print("[ai][DRY] signal NOT written", flush=True)
    else:
        bridge.write_signal(action, lots, sl=stop_price if action == "LONG" else None,
                            seq=out_seq)
        print(f"[ai] wrote signal: {action} {lots:.2f} (seq {out_seq})", flush=True)
    return {"action": action, "lots": lots, "stop": stop_price, "fresh": fresh,
            "seq": out_seq}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--max-risk", type=float, default=0.04)
    ap.add_argument("--max-lots", type=float, default=5.0)
    ap.add_argument("--granularity", default="H1", help="bars the EA publishes (H1 = best; D also ok)")
    ap.add_argument("--sma", type=int, default=2400, help="trend-filter SMA (H1 2400; daily 90)")
    ap.add_argument("--model", default=None, help="default claude-opus-4-8")
    ap.add_argument("--history", default="data/USD_JPY_H1.csv",
                    help="warmup/fallback history matching --granularity")
    ap.add_argument("--poll", type=int, default=600, help="resident poll seconds")
    ap.add_argument("--daily-gap-h", type=float, default=20.0, help="hours between daily decisions")
    ap.add_argument("--event-window-min", type=float, default=45.0,
                    help="decide within this many minutes after a high-impact release")
    ap.add_argument("--gate-cooldown-min", type=float, default=15.0,
                    help="min minutes between gate-triggered decisions")
    ap.add_argument("--veto-ttl-h", type=float, default=1.0,
                    help="suppress gate re-entries for this long after a BINDING AI veto "
                         "(inert in the default shadow authority; keep short — entry delay "
                         "is expensive for a right-tail strategy)")
    ap.add_argument("--signal-ttl-min", type=float, default=120.0,
                    help="heartbeat expiry on the signal file (EXP token; a "
                         "heartbeat-aware EA fails safe to FLAT if this brain "
                         "dies). 0 disables the token")
    ap.add_argument("--calendar-mode", default="file", help="file | anthropic (refresh schedule)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    cfg = Settings(strategy="ai", granularity=args.granularity)
    db.init_db()
    trader = AITrader(model=args.model)

    if args.once:
        # Final fuzz: --once is a second writer on a live bridge. Warn — the
        # resident's next heartbeat overwrites whatever this one-shot writes.
        try:
            lock = bridge.common_files_dir() / "steady_brain.lock"
            if not args.dry and lock.exists() and _time.time() - lock.stat().st_mtime < 3600:
                print(f"[ai] WARNING: a resident brain appears LIVE on this bridge ({lock}); "
                      f"its heartbeat will overwrite this manual signal within one poll. "
                      f"Use --dry, or stop the resident first.", flush=True)
        except Exception:
            pass
        _, prev_stop, _ = _restore_state(args.granularity)
        live = bridge.read_signal()
        decide_once(cfg, args.instrument, args.max_risk, args.max_lots, args.history,
                    trader, args.dry, trigger="manual",
                    granularity=args.granularity, sma_n=args.sma, prev_stop=prev_stop,
                    seq=int((live or {}).get("seq") or 0))
        return

    print(f"[ai] resident. model={trader.model} max_risk={args.max_risk} "
          f"daily_gap={args.daily_gap_h}h event_window={args.event_window_min}m "
          f"poll={args.poll}s gate_cd={args.gate_cooldown_min}m veto_ttl={args.veto_ttl_h}h "
          f"signal_ttl={args.signal_ttl_min}m", flush=True)
    last_gate = 0.0
    veto_until = 0.0
    acted_events: set[str] = set()
    cal = get_calendar(args.calendar_mode, args.instrument)
    cal_day = datetime.now(timezone.utc).date()

    def record_stop_exit(price: float, stop: float, pos: float, now: datetime) -> None:
        try:
            status = bridge.read_status()
            if status and (status.get("balance") or 0) > 0:
                run_id = _ongoing_run(status["balance"], trader.model,
                                      args.max_risk, args.granularity)
                db.record_signal(run_id, now, args.instrument, "combined", 0, 0.0,
                                 f"stop-loss: last {price:.3f} <= stop {stop:.3f}",
                                 {"action": "FLAT", "trigger": "stop",
                                  "stop_price": stop, "position_lots": pos})
        except Exception as exc:
            print(f"[ai] stop-exit DB record failed: {exc}", flush=True)

    brain_lock = _acquire_brain_lock(args.poll)
    # STATE IS READ ONLY AFTER THE LOCK IS OURS. _acquire_brain_lock blocks for
    # as long as an incumbent keeps trading, and the incumbent mutates exactly
    # this state — reading it first meant taking over with a snapshot minutes
    # old and then acting on it with no decision: liquidating a position the
    # incumbent had opened, or republishing a superseded stop as the live
    # broker SL (round-5, critical).
    #
    # intent = the brain's last ordered state; the loop's job is to make the
    # book converge to it and never to silently re-adopt a diverging book.
    intent, stop_price, last_decision = _restore_state(args.granularity)
    intent_lots = 0.0
    # SEQ identifies the order standing on the bridge. It must be REUSED by the
    # heartbeat and only re-minted by a fresh decision, so recover the live
    # order's SEQ from the bridge instead of minting one: a restart that minted
    # a new SEQ would read to the EA as a brand-new order and re-open a
    # position that had been stopped out while this brain was down.
    order_seq = 0
    live = bridge.read_signal()
    if live and live.get("action") == "LONG" and live.get("seq"):
        order_seq = int(live["seq"])
    seen_long = False        # a LONG intent whose fill we actually observed
    if intent:
        stop_txt = f" stop {stop_price:.3f}" if stop_price else ""
        seq_txt = f" seq {order_seq}" if order_seq else ""
        print(f"[ai] restored state: intent {intent}{stop_txt}{seq_txt}", flush=True)
    if intent == "LONG" and not order_seq:
        # The DB says LONG but the bridge carries no order id (a pre-round-5
        # signal, or none at all), so we cannot say WHICH order that intent
        # refers to — and an unidentifiable LONG heartbeat is precisely what
        # licenses the EA to re-open. Settle it against the book, once, now.
        book = float((bridge.read_status() or {}).get("position_lots") or 0.0)
        if book >= FLAT_EPS:
            intent_lots, seen_long = book, True
            order_seq = _next_seq(0)
            print(f"[ai] adopting the live book of {book:.2f} lots as order "
                  f"{order_seq}", flush=True)
        else:
            print("[ai] restored intent LONG but the book is empty and the bridge "
                  "carries no order id — adopting FLAT; re-entry goes through a "
                  "fresh gate decision", flush=True)
            intent, intent_lots, stop_price = "FLAT", 0.0, None
    last_probe_ok = _time.time()
    # While LONG and blind (no trusted probe) beyond this grace, the heartbeat
    # is withheld so the EA's EXP fail-safe can flatten the book (Round-4: the
    # old heartbeat attested "alive" even while the stop check was down, making
    # the fail-safe unreachable exactly when it was needed). At the default
    # poll this is 30min of grace + the signal TTL before the EA flattens.
    blind_grace_s = max(3 * args.poll, 60)
    entry_attempts = 0
    entry_backoff_until = 0.0

    while True:
        try:
            now = datetime.now(timezone.utc)
            # refresh the event schedule once a day
            if now.date() != cal_day:
                cal = get_calendar(args.calendar_mode, args.instrument)
                cal_day = now.date(); acted_events.clear()

            probe = _trend_gate(args.instrument, args.granularity, args.sma, args.history)
            trigger = None
            skip_scheduled = False
            if probe is not None:
                last_probe_ok = _time.time()
                trend_up, price, pos = probe
                if pos > 0:
                    entry_attempts = 0            # the book moved; breaker resets
                if intent == "LONG" and intent_lots <= 0 and pos >= FLAT_EPS:
                    intent_lots = pos      # after a restart: adopt the book's size
                    # (dust below FLAT_EPS is NOT adopted: heartbeating "LONG 0.00"
                    # reads to the EA as close-everything — Round-4 chaos (c))
                if intent == "LONG" and pos >= FLAT_EPS:
                    seen_long = True              # the order was really filled
                    if pos < intent_lots - FLAT_EPS:
                        # SHRANK without this brain ordering it (partial stop
                        # fill, manual trim, margin close). Adopt the smaller
                        # book: keeping the old target made the heartbeat
                        # re-buy the part that was just closed (round-5).
                        print(f"[ai] book SHRANK externally {intent_lots:.2f} -> "
                              f"{pos:.2f} lots — adopting the smaller size instead of "
                              f"re-buying the difference", flush=True)
                        intent_lots = pos

                # RECONCILIATION (final fuzz, critical): if a position we SAW
                # open is now gone without this brain ordering it (broker SL
                # fill, EA EXP fail-safe, operator close), adopt reality —
                # otherwise the very next heartbeat re-issues the stale LONG as
                # a brand-new full-size order with NO decision, even in a
                # downtrend. Re-entry, if warranted, must go through a fresh
                # gate decision like any other entry.
                if intent == "LONG" and seen_long and pos < FLAT_EPS:
                    print(f"[ai] book closed EXTERNALLY (broker SL / fail-safe / manual) "
                          f"while intent was LONG {intent_lots:.2f} — adopting FLAT; "
                          f"a fresh gate decision may re-enter", flush=True)
                    try:
                        status2 = bridge.read_status()
                        if status2 and (status2.get("balance") or 0) > 0:
                            rid = _ongoing_run(status2["balance"], trader.model,
                                               args.max_risk, args.granularity)
                            db.record_signal(rid, now, args.instrument, "combined", 0, 0.0,
                                             f"external close detected at {price:.3f} "
                                             f"(was LONG {intent_lots:.2f}, stop {stop_price})",
                                             {"action": "FLAT", "trigger": "external-close",
                                              "stop_price": stop_price})
                    except Exception as exc:
                        print(f"[ai] external-close DB record failed: {exc}", flush=True)
                    intent, intent_lots, stop_price = "FLAT", 0.0, None
                    seen_long = False
                    order_seq = _next_seq(order_seq)   # the standing order is void
                    last_gate = _time.time()      # cooldown before any re-entry

                # Round-4 chaos (d): a restored stop IMPLAUSIBLY far above the
                # market (stale-era record) must be discarded, not "hit" — else
                # a healthy position is liquidated on a 180-day-old stop. A real
                # gap-through-stop of >3% would exit via the trend gate anyway.
                if pos > 0 and stop_price is not None and stop_price >= price * 1.03:
                    print(f"[ai] CRITICAL: carried stop {stop_price:.3f} is implausibly "
                          f"above price {price:.3f} — discarding; will re-arm", flush=True)
                    stop_price = None

                gate_ok = (_time.time() - last_gate) >= args.gate_cooldown_min * 60
                if intent == "FLAT" and pos > 0:
                    # Ordered closed but still on the books (EA lag or detached
                    # terminal). Do NOT decide: a hold decision would re-adopt
                    # the position and overwrite the pending FLAT (audit: stop
                    # exits were silently reverted this way). The heartbeat
                    # below keeps re-asserting FLAT until the EA obeys.
                    print(f"[ai] waiting for EA to close {pos:.2f} lots (intent FLAT)",
                          flush=True)
                    skip_scheduled = True
                elif pos > 0 and stop_price is not None and price <= stop_price:
                    # Protective stop — the EA holds no SL; this loop is the stop.
                    if args.dry:
                        print(f"[ai][DRY] STOP hit ({price:.3f} <= {stop_price:.3f}); "
                              f"FLAT NOT written", flush=True)
                    else:
                        order_seq = _next_seq(order_seq)
                        bridge.write_signal("FLAT", 0.0, seq=order_seq)
                        print(f"[ai] STOP hit: last {price:.3f} <= stop {stop_price:.3f} "
                              f"-> FLAT (gate may re-enter if trend holds)", flush=True)
                        record_stop_exit(price, stop_price, pos, now)
                    intent, intent_lots, stop_price = "FLAT", 0.0, None
                    seen_long = False
                    last_gate = _time.time()          # brief pause before re-entry
                    skip_scheduled = True
                elif pos > 0 and intent == "LONG" and stop_price is None and gate_ok:
                    # INVARIANT: an open LONG must carry a stop. Heal it now.
                    trigger = "gate-rearm"
                else:
                    # State-mismatch gate: enter/exit NOW, don't wait for the
                    # daily slot (round-2: daily-only execution cost ~half the
                    # CAGR and doubled maxDD). Entries respect the veto TTL and
                    # a cooldown; exits are never suppressed.
                    wants_entry = trend_up and pos <= 0
                    wants_exit = (not trend_up) and pos > 0
                    if wants_exit and gate_ok:
                        trigger = "gate-exit"
                    elif (wants_entry and gate_ok and _time.time() >= veto_until
                          and _time.time() >= entry_backoff_until):
                        trigger = "gate-entry"

            if trigger is None and not skip_scheduled:
                if (_time.time() - last_decision) >= args.daily_gap_h * 3600:
                    trigger = "daily"
                else:
                    for e in cal.for_instrument(args.instrument):
                        if not e.is_high:
                            continue
                        mins = -e.minutes_until(now)   # minutes SINCE release
                        key = f"{e.time.isoformat()}|{e.title}"
                        if 0 <= mins <= args.event_window_min and key not in acted_events:
                            trigger = f"event:{e.title}"; acted_events.add(key); break

            if trigger:
                res = decide_once(cfg, args.instrument, args.max_risk, args.max_lots,
                                  args.history, trader, args.dry, trigger,
                                  granularity=args.granularity, sma_n=args.sma,
                                  prev_stop=stop_price, seq=order_seq)
                if res is not None:
                    order_seq = res["seq"]
                    intent = res["action"]
                    intent_lots = res["lots"] if res["action"] == "LONG" else 0.0
                    stop_price = res["stop"]
                    if res["action"] != "LONG" or res.get("fresh"):
                        seen_long = False     # new order: fill not yet observed
                    if trigger.startswith("gate"):
                        last_gate = _time.time()
                    else:
                        last_decision = _time.time()
                    # A declined entry (trend up, still flat) = AI veto: don't
                    # re-consult the paid API every poll tick while it stands.
                    if probe is not None and probe[0] and res["action"] == "FLAT":
                        veto_until = _time.time() + args.veto_ttl_h * 3600
                    # Circuit breaker (Round-4 chaos (c)): if entry orders keep
                    # not moving the book (broker lot-min mismatch, wedged EA),
                    # stop re-deciding — each retry is a paid AI consult.
                    if trigger == "gate-entry" and res["action"] == "LONG":
                        entry_attempts += 1
                        if entry_attempts >= 3:
                            entry_backoff_until = _time.time() + 3600
                            entry_attempts = 0
                            print("[ai] WARNING: 3 entry orders did not move the book — "
                                  "backing off 1h. Check the EA / broker lot spec "
                                  "(min/step) in MT5.", flush=True)

            # Heartbeat: atomically re-assert the current order with a fresh
            # expiry AND the protective stop (a broker-SL-aware EA mirrors it as
            # a real SL order — round-4 equivalence: poll-granular stop fills
            # cost ~3.4pp CAGR that a broker SL recovers for ~0.05% gap cost).
            # A heartbeat-aware EA fails safe to FLAT if this brain dies.
            # Guards: never write "LONG 0.00" (reads as close-everything);
            # STOP-LIVENESS — while LONG and blind past the grace, WITHHOLD the
            # heartbeat so the EXP lapses and the EA flattens: an unsupervised
            # position must fail safe, not ride an attested-alive token.
            hb_ok = True
            if intent == "LONG":
                blind_s = _time.time() - last_probe_ok
                if blind_s > blind_grace_s:
                    hb_ok = False
                    print(f"[ai] BLIND {blind_s / 60:.0f}m while LONG (no trusted feed) — "
                          f"withholding heartbeat so the EA fail-safe flattens at EXP; "
                          f"stop enforcement is DOWN", flush=True)
            if (not args.dry and intent is not None and hb_ok
                    and (intent == "FLAT" or intent_lots >= FLAT_EPS)):
                ttl = int(args.signal_ttl_min * 60)
                bridge.write_signal(intent, intent_lots if intent == "LONG" else 0.0,
                                    expires_at=(int(_time.time()) + ttl) if ttl > 0 else None,
                                    sl=stop_price if intent == "LONG" else None,
                                    seq=order_seq)
        except Exception as exc:
            print(f"[ai] loop error: {exc}", flush=True)
        finally:
            # LIVENESS, not success: a tick that raised still proves this
            # process is alive and still owns the bridge. Heartbeating only on
            # success let a recurring error age the lock out from under a
            # running brain, inviting the second writer the lock exists to
            # prevent (round-5).
            _touch_lock(brain_lock, args.poll)
        _time.sleep(args.poll)


if __name__ == "__main__":
    main()
