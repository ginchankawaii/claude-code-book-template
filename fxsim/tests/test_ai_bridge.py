"""run_ai_bridge decision = validated long-or-flat trend edge + Opus veto gate.

The bridge must: stand aside below the trend filter (without even paying for an
Opus call), trade the deterministic long when Opus is unavailable, let Opus veto
or size a long when the trend is up, and NEVER short.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.run_ai_bridge as R
from app import bridge, db
from app.config import DATA_DIR, Settings
from app.providers.csv import load_csv_file

_DAILY = load_csv_file(DATA_DIR / "USD_JPY_D.csv", "USD_JPY", "D")
_UP = [c for c in _DAILY if c.time.year >= 2024]                       # price > SMA90
_DOWN = [c for c in _DAILY if c.time <= datetime(2011, 8, 1, tzinfo=timezone.utc)]  # price < SMA90


class _Dec:
    def __init__(self, ok, action, conviction):
        self.ok, self.action, self.conviction = ok, action, conviction
        self.reason, self.factors, self.plan = "r", [], ""


class _Trader:
    model = "fake"

    def __init__(self, dec):
        self.dec, self.calls = dec, 0

    def decide(self, ctx):
        self.calls += 1
        return self.dec


@pytest.fixture
def wired(monkeypatch):
    written = []
    monkeypatch.setattr(bridge, "read_status",
                        lambda *a, **k: {"balance": 500000.0, "equity": 500000.0, "position_lots": 0.0})
    monkeypatch.setattr(bridge, "write_signal",
                        lambda action, lots, base=None, expires_at=None, sl=None:
                            written.append((action, round(lots, 2))))
    # the bundled test candles are historical: disable the live freshness and
    # single-bar-jump guards (daily bars legitimately move >3%)
    monkeypatch.setattr(R, "MAX_BAR_AGE_H", 1e9)
    monkeypatch.setattr(R, "MAX_BAR_JUMP_PCT", 1e9)
    # keep the DB out of the unit test
    monkeypatch.setattr(db, "list_runs", lambda: [])
    monkeypatch.setattr(db, "create_run", lambda **k: 1)
    monkeypatch.setattr(db, "record_equity", lambda *a, **k: None)
    monkeypatch.setattr(db, "load_equity", lambda *a, **k: [])
    monkeypatch.setattr(db, "record_signal", lambda *a, **k: None)
    return written


def _run(monkeypatch, window, dec, authority="entry", position_lots=None):
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: window)
    if position_lots is not None:
        monkeypatch.setattr(bridge, "read_status",
                            lambda *a, **k: {"balance": 500000.0, "equity": 500000.0,
                                             "position_lots": position_lots})
    trader = _Trader(dec)
    cfg = Settings(strategy="ai", granularity="D", max_leverage=5.0, ai_authority=authority)
    res = R.decide_once(cfg, "USD_JPY", 0.04, 5.0, str(DATA_DIR / "USD_JPY_D.csv"),
                        trader, dry=False, trigger="test", granularity="D", sma_n=90)
    return trader, res


def test_trend_down_stands_aside_without_calling_opus(wired, monkeypatch):
    trader, _ = _run(monkeypatch, _DOWN, _Dec(True, "long", 0.9))
    assert wired[-1][0] == "FLAT" and wired[-1][1] == 0.0
    assert trader.calls == 0          # gate short-circuits the (paid) AI call


def test_trend_up_no_key_trades_the_deterministic_long(wired, monkeypatch):
    _run(monkeypatch, _UP, _Dec(False, "flat", 0.0))   # AI unavailable
    assert wired[-1][0] == "LONG" and wired[-1][1] > 0


def test_entry_authority_veto_blocks_fresh_entry(wired, monkeypatch):
    _run(monkeypatch, _UP, _Dec(True, "flat", 0.0), authority="entry")
    assert wired[-1][0] == "FLAT"


def test_never_shorts_in_any_mode(wired, monkeypatch):
    # "short" from the AI can at most force FLAT (entry mode) or be logged
    # (shadow) — a short order is never produced.
    _run(monkeypatch, _UP, _Dec(True, "short", 0.9), authority="entry")
    assert wired[-1][0] == "FLAT"
    _run(monkeypatch, _UP, _Dec(True, "short", 0.9), authority="shadow")
    assert wired[-1][0] == "LONG"     # advisory dissent, edge decides; never SHORT


def test_shadow_authority_veto_is_advisory_only(wired, monkeypatch):
    # Round-3 inquest: default authority follows the validated edge and only
    # LOGS the AI's dissent (the veto path is unvalidated and return-negative).
    _, res = _run(monkeypatch, _UP, _Dec(True, "flat", 0.0), authority="shadow")
    assert wired[-1][0] == "LONG" and wired[-1][1] > 0
    assert res["action"] == "LONG"


def test_entry_authority_never_liquidates_a_hold(wired, monkeypatch):
    # An AI veto while a position is OPEN must not flatten it in "entry" mode —
    # that exit path exists in no backtest.
    _, res = _run(monkeypatch, _UP, _Dec(True, "flat", 0.0),
                  authority="entry", position_lots=0.09)
    assert res["action"] == "LONG"
    assert wired[-1] == ("LONG", 0.09)          # hold kept at entry size


def test_full_authority_veto_can_flatten_a_hold(wired, monkeypatch):
    # Legacy opt-in keeps the old semantics.
    _, res = _run(monkeypatch, _UP, _Dec(True, "flat", 0.0),
                  authority="full", position_lots=0.09)
    assert res["action"] == "FLAT" and wired[-1][0] == "FLAT"


def test_shadow_sizing_pins_reference_conviction(wired, monkeypatch):
    # Shadow authority sizes at the validated 0.6 reference even when the AI
    # confirms with a different conviction (conviction scaling is unvalidated).
    _run(monkeypatch, _UP, _Dec(True, "long", 0.2), authority="shadow")
    a_shadow = wired[-1]
    _run(monkeypatch, _UP, _Dec(False, "flat", 0.0), authority="shadow")  # AI down -> 0.6 path
    assert a_shadow == wired[-1]


def test_trend_up_opus_long_sizes_within_leverage_cap(wired, monkeypatch):
    _run(monkeypatch, _UP, _Dec(True, "long", 0.8))
    action, lots = wired[-1]
    assert action == "LONG"
    # 0.8 conviction * 4% risk, but the 5x leverage cap on a ¥500k book binds:
    # lots*100k*price <= 5*500k  ->  ~0.16 lots at price ~160
    assert 0 < lots <= 0.20


def test_fresh_entry_carries_a_protective_stop(wired, monkeypatch):
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: _UP)
    cfg = Settings(strategy="ai", granularity="D", max_leverage=5.0)
    res = R.decide_once(cfg, "USD_JPY", 0.04, 5.0, str(DATA_DIR / "USD_JPY_D.csv"),
                        _Trader(_Dec(True, "long", 0.8)), dry=False, trigger="test",
                        granularity="D", sma_n=90)
    assert res["action"] == "LONG" and res["fresh"] is True
    assert res["stop"] is not None and res["stop"] < _UP[-1].close


def test_holding_keeps_entry_size_and_stop(wired, monkeypatch):
    # While a long is open, decisions must NOT retarget the size (round-2: the
    # intra-trade resize loop is net harmful) and must carry the entry stop.
    monkeypatch.setattr(bridge, "read_status",
                        lambda *a, **k: {"balance": 500000.0, "equity": 500000.0,
                                         "position_lots": 0.09})
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: _UP)
    cfg = Settings(strategy="ai", granularity="D", max_leverage=5.0)
    res = R.decide_once(cfg, "USD_JPY", 0.04, 5.0, str(DATA_DIR / "USD_JPY_D.csv"),
                        _Trader(_Dec(True, "long", 1.0)), dry=False, trigger="test",
                        granularity="D", sma_n=90, prev_stop=123.456)
    assert res["action"] == "LONG" and res["fresh"] is False
    assert wired[-1] == ("LONG", 0.09)          # held, not retargeted
    assert res["stop"] == 123.456               # carried, not recomputed


def test_flat_decision_clears_the_stop(wired, monkeypatch):
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: _DOWN)
    cfg = Settings(strategy="ai", granularity="D", max_leverage=5.0)
    res = R.decide_once(cfg, "USD_JPY", 0.04, 5.0, str(DATA_DIR / "USD_JPY_D.csv"),
                        _Trader(_Dec(True, "long", 0.9)), dry=False, trigger="test",
                        granularity="D", sma_n=90, prev_stop=123.456)
    assert res["action"] == "FLAT" and res["stop"] is None


def test_trend_gate_probe(monkeypatch):
    monkeypatch.setattr(R, "MAX_BAR_AGE_H", 1e9)
    monkeypatch.setattr(R, "MAX_BAR_JUMP_PCT", 1e9)
    monkeypatch.setattr(bridge, "read_status",
                        lambda *a, **k: {"balance": 500000.0, "equity": 500000.0,
                                         "position_lots": 0.05})
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: _UP)
    up, price, pos = R._trend_gate("USD_JPY", "D", 90, str(DATA_DIR / "USD_JPY_D.csv"))
    assert up is True and price == _UP[-1].close and pos == 0.05
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: _DOWN)
    up, _, _ = R._trend_gate("USD_JPY", "D", 90, str(DATA_DIR / "USD_JPY_D.csv"))
    assert up is False


def test_trend_gate_not_ready_returns_none(monkeypatch):
    monkeypatch.setattr(bridge, "read_status", lambda *a, **k: None)
    assert R._trend_gate("USD_JPY", "D", 90, "no-such-file.csv") is None


# ---- audit fixes (round-2 money-path bug hunt) -----------------------------

def test_stale_bars_are_refused(monkeypatch):
    # The audit found real orders placeable on a weeks-old fallback CSV. Any
    # candle set whose last bar is older than MAX_BAR_AGE_H must be refused —
    # for the probe AND (via the shared loader) for decisions.
    monkeypatch.setattr(bridge, "read_status",
                        lambda *a, **k: {"balance": 500000.0, "equity": 500000.0,
                                         "position_lots": 0.0})
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: _UP)
    assert R._trend_gate("USD_JPY", "D", 90, "no-such-file.csv") is None  # _UP ends years ago


def test_short_live_feed_does_not_fall_back_to_csv(monkeypatch):
    # A truncated/partial live bars file (torn EA write) must SKIP the tick,
    # never silently substitute the bundled history CSV.
    monkeypatch.setattr(R, "MAX_BAR_AGE_H", 1e9)
    monkeypatch.setattr(R, "MAX_BAR_JUMP_PCT", 1e9)
    monkeypatch.setattr(bridge, "read_bars",
                        lambda instr="USD_JPY", gran="D", base=None: _UP[:50])  # < sma_n+5
    assert R._load_bars("USD_JPY", "D", 90, str(DATA_DIR / "USD_JPY_D.csv")) is None


def test_dry_run_writes_nothing(monkeypatch):
    written, recorded = [], []
    monkeypatch.setattr(bridge, "read_status",
                        lambda *a, **k: {"balance": 500000.0, "equity": 500000.0,
                                         "position_lots": 0.0})
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: _UP)
    monkeypatch.setattr(bridge, "write_signal",
                        lambda *a, **k: written.append(a))
    monkeypatch.setattr(R, "MAX_BAR_AGE_H", 1e9)
    monkeypatch.setattr(R, "MAX_BAR_JUMP_PCT", 1e9)
    monkeypatch.setattr(db, "list_runs", lambda: [])
    monkeypatch.setattr(db, "create_run",
                        lambda **k: (_ for _ in ()).throw(AssertionError("dry created a run")))
    monkeypatch.setattr(db, "record_equity",
                        lambda *a, **k: recorded.append("equity"))
    monkeypatch.setattr(db, "load_equity", lambda *a, **k: [])
    monkeypatch.setattr(db, "record_signal",
                        lambda *a, **k: recorded.append("signal"))
    cfg = Settings(strategy="ai", granularity="D", max_leverage=5.0)
    res = R.decide_once(cfg, "USD_JPY", 0.04, 5.0, str(DATA_DIR / "USD_JPY_D.csv"),
                        _Trader(_Dec(True, "long", 0.8)), dry=True, trigger="test",
                        granularity="D", sma_n=90)
    assert res["action"] == "LONG"
    assert written == [] and recorded == []   # --dry touches neither EA nor DB


def test_hold_with_lost_stop_rearms(wired, monkeypatch):
    # INVARIANT: an open LONG must carry a stop. If the carried stop was lost
    # (old records, manual --once, wiped DB), the hold decision re-arms one.
    monkeypatch.setattr(bridge, "read_status",
                        lambda *a, **k: {"balance": 500000.0, "equity": 500000.0,
                                         "position_lots": 0.09})
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: _UP)
    cfg = Settings(strategy="ai", granularity="D", max_leverage=5.0)
    res = R.decide_once(cfg, "USD_JPY", 0.04, 5.0, str(DATA_DIR / "USD_JPY_D.csv"),
                        _Trader(_Dec(True, "long", 1.0)), dry=False, trigger="test",
                        granularity="D", sma_n=90, prev_stop=None)
    assert res["action"] == "LONG" and res["fresh"] is False
    assert res["stop"] is not None and res["stop"] < _UP[-1].close


def test_restore_state_scans_back_for_the_stop(monkeypatch):
    # A hold record with stop_price=null must not disarm the restore: the scan
    # walks back through the unbroken run of LONG decisions to the entry stop.
    rows = [
        {"source": "combined", "direction": 1, "time": "2026-07-01T00:00:00+00:00",
         "components": '{"stop_price": 158.917}'},
        {"source": "combined", "direction": 1, "time": "2026-07-02T00:00:00+00:00",
         "components": '{"stop_price": null}'},
    ]
    monkeypatch.setattr(db, "list_runs",
                        lambda: [{"id": 7, "ended_at": None, "granularity": "H1", "params": '{"system": "steady-ai"}'}])
    monkeypatch.setattr(db, "load_signals", lambda rid: rows)
    intent, stop, ts = R._restore_state()
    assert intent == "LONG" and stop == 158.917 and ts > 0
    # ...but a FLAT after the stop-exit means no stop and FLAT intent
    rows.append({"source": "combined", "direction": 0, "time": "2026-07-03T00:00:00+00:00",
                 "components": '{"trigger": "stop"}'})
    intent, stop, _ = R._restore_state()
    assert intent == "FLAT" and stop is None


# ---- round-4 fixes ---------------------------------------------------------

def test_implausible_last_bar_quarantines_feed(monkeypatch):
    # Round-4 chaos (b): a corrupt print (close=0.001 or a +15% spike) must
    # quarantine the feed, never reach a trading decision.
    monkeypatch.setattr(R, "MAX_BAR_AGE_H", 1e9)
    corrupt = list(_UP)
    bad = type(corrupt[-1])(instrument="USD_JPY", granularity="D",
                            time=corrupt[-1].time, open=0.001, high=0.001,
                            low=0.001, close=0.001, volume=1.0)
    monkeypatch.setattr(bridge, "read_bars",
                        lambda instr="USD_JPY", gran="D", base=None: corrupt[:-1] + [bad])
    assert R._load_bars("USD_JPY", "D", 90, "no-such-file.csv") is None
    spike = type(corrupt[-1])(instrument="USD_JPY", granularity="D",
                              time=corrupt[-1].time, open=corrupt[-2].close,
                              high=corrupt[-2].close * 1.2, low=corrupt[-2].close,
                              close=corrupt[-2].close * 1.15, volume=1.0)
    monkeypatch.setattr(bridge, "read_bars",
                        lambda instr="USD_JPY", gran="D", base=None: corrupt[:-1] + [spike])
    assert R._load_bars("USD_JPY", "D", 90, "no-such-file.csv") is None


def test_find_run_filters_on_granularity(monkeypatch):
    # Round-4 chaos (d): a restart must never adopt an unrelated old run —
    # its stale stop instantly liquidated a healthy position in the repro.
    monkeypatch.setattr(db, "list_runs", lambda: [
        {"id": 3, "ended_at": None, "granularity": "D",
         "params": '{"system": "steady-ai"}'},
        {"id": 9, "ended_at": None, "granularity": "H1",
         "params": '{"system": "steady-ai"}'},
    ])
    assert R._find_run("H1") == 9
    assert R._find_run("D") == 3
    assert R._find_run("H4") is None


def test_dd_brake_default_off(wired, monkeypatch):
    # Round-4 equivalence: the live-only brake cost -4.3pp CAGR AND worsened
    # maxDD when finally backtested -> default follows the validated edge.
    calls = []
    from app import adaptive
    monkeypatch.setattr(adaptive.AdaptiveController, "evaluate",
                        lambda self, eq, tr: calls.append(1) or (0.5, "", {}))
    _run(monkeypatch, _UP, _Dec(True, "long", 0.8))
    assert calls == []                # brake never evaluated by default
    cfg = Settings(strategy="ai", granularity="D", max_leverage=5.0, dd_brake=True)
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: _UP)
    R.decide_once(cfg, "USD_JPY", 0.04, 5.0, str(DATA_DIR / "USD_JPY_D.csv"),
                  _Trader(_Dec(True, "long", 0.8)), dry=False, trigger="test",
                  granularity="D", sma_n=90)
    assert calls == [1]               # opt-in path still works


def test_dyn_lev_pow_reverted_to_linear():
    # Round-4 tribunal (pre-registered rule): convex failed its deflated-Sharpe
    # charge at every assumed N -> the default is the linear ramp again.
    assert Settings().dyn_lev_pow == 1.0


# ---- brain lock: liveness first, age only as fallback ----------------------

def _write_lock(d, pid, poll, host, age_s=0):
    import os as _os, time as _t
    p = d / "steady_brain.lock"
    p.write_text(f"{pid} {int(_t.time()) - age_s} {poll} {host}\n")
    if age_s:
        _os.utime(p, (_t.time() - age_s, _t.time() - age_s))
    return p


def test_lock_taken_over_when_predecessor_is_dead(tmp_path, monkeypatch):
    # A container restart hands the successor the same PID; the old lock looks
    # fresh but its writer is gone. Waiting 3x poll (30min) left the protective
    # stop unsupervised — liveness must win over age.
    import os, socket
    monkeypatch.setattr(bridge, "common_files_dir", lambda: tmp_path)
    _write_lock(tmp_path, os.getpid(), 600, socket.gethostname(), age_s=5)
    lock = R._acquire_brain_lock(600)
    assert lock is not None and str(os.getpid()) in lock.read_text()


def test_live_holder_makes_the_challenger_wait_and_never_exit(tmp_path, monkeypatch):
    # THE regression that mattered most: a challenger that exits on a live-
    # looking lock hands the supervisor a restart loop, and the account runs
    # unsupervised for as long as it lasts (12 and 30 minutes, twice, live).
    # Correct behaviour is to stand by and acquire the moment the holder stops.
    import os, socket
    monkeypatch.setattr(bridge, "common_files_dir", lambda: tmp_path)
    _write_lock(tmp_path, 4242, 600, socket.gethostname(), age_s=30)
    ticks = {"n": 0}
    monkeypatch.setattr(R, "_holder_is_alive", lambda pid, host: ticks["n"] < 3)

    def fake_sleep(_s):
        ticks["n"] += 1
        assert ticks["n"] < 20, "waited without ever re-judging the lock"
    monkeypatch.setattr(R._time, "sleep", fake_sleep)

    lock = R._acquire_brain_lock(600)                 # no SystemExit, ever
    assert lock is not None and str(os.getpid()) in lock.read_text()
    assert ticks["n"] == 3                            # it really did wait


def test_lock_taken_over_from_unknowable_holder_after_one_missed_heartbeat(tmp_path, monkeypatch):
    # Another container's PIDs are invisible: fall back to age, but only one
    # missed heartbeat + slack (poll+120), not 3x poll.
    monkeypatch.setattr(bridge, "common_files_dir", lambda: tmp_path)
    monkeypatch.setattr(R._time, "sleep", lambda s: None)
    # already past the staleness window (poll+120) -> adopted immediately
    _write_lock(tmp_path, 4242, 600, "other-container", age_s=800)
    assert R._acquire_brain_lock(600) is not None


def test_lock_released_on_graceful_stop(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(bridge, "common_files_dir", lambda: tmp_path)
    lock = R._acquire_brain_lock(600)
    assert lock.exists()
    R._release_lock(lock)
    assert not lock.exists()          # successor starts immediately
    # a lock owned by someone else is never released by us
    _write_lock(tmp_path, os.getpid() + 1, 600, "other")
    R._release_lock(tmp_path / "steady_brain.lock")
    assert (tmp_path / "steady_brain.lock").exists()


def test_legacy_format_lock_is_adopted(tmp_path, monkeypatch):
    # Pre-upgrade locks have no host field; treating them as "unknowable" left
    # the operator crash-looping for 12 minutes after upgrading.
    monkeypatch.setattr(bridge, "common_files_dir", lambda: tmp_path)
    (tmp_path / "steady_brain.lock").write_text("1 1786947797 600\n")   # old format
    assert R._acquire_brain_lock(600) is not None


def test_unknowable_holder_is_waited_out_not_crash_looped(tmp_path, monkeypatch):
    # A holder in another PID namespace: stand by and watch its heartbeat.
    # While it keeps beating we wait; when it stops, we take the lock. Never
    # patch time.time globally here — it hangs pytest.
    import os as _os, time as _t
    monkeypatch.setattr(bridge, "common_files_dir", lambda: tmp_path)
    lock = _write_lock(tmp_path, 4242, 1, "other-container", age_s=100)  # poll=1 -> 121s window
    monkeypatch.setattr(R._time, "sleep", lambda s: None)
    assert R._acquire_brain_lock(1) is not None          # already lapsed -> ours

    lock = _write_lock(tmp_path, 4242, 1, "other-container")             # fresh
    ticks = {"n": 0}

    def holder_beats_then_dies(_s):
        ticks["n"] += 1
        assert ticks["n"] < 20, "never re-judged the lock"
        if ticks["n"] < 4:
            lock.touch()                                 # holder heartbeat
        else:
            old = _t.time() - 300                        # holder stopped; window lapsed
            _os.utime(lock, (old, old))
    monkeypatch.setattr(R._time, "sleep", holder_beats_then_dies)

    assert R._acquire_brain_lock(1) is not None          # waited, then acquired
    assert ticks["n"] == 4                               # 3 beats survived, 4th lapsed
