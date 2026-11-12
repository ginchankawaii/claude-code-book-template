import math

from app import monitor
from app.monitor import GREEN, RED, YELLOW


def test_equity_stats_return_and_drawdown():
    s = monitor.equity_stats([100, 120, 90, 110])   # peak 120, trough 90
    assert round(s["return_pct"], 1) == 10.0          # 100 -> 110
    assert round(s["max_dd_pct"], 1) == 25.0          # (120-90)/120
    assert round(s["cur_dd_pct"], 1) == round((120 - 110) / 120 * 100, 1)


def test_annualize():
    assert round(monitor.annualize(10, 1), 1) == 10.0
    assert monitor.annualize(-100, 1) == -100.0       # wiped out
    assert monitor.annualize(5, 0) == 0.0             # no time -> 0


def test_count_position_changes():
    assert monitor.count_position_changes(["FLAT", "LONG", "LONG", "FLAT", "LONG"]) == 3
    assert monitor.count_position_changes(["LONG", "LONG", "LONG"]) == 0
    assert monitor.count_position_changes([]) == 0


def test_early_life_is_yellow_not_red():
    # only a few days of data -> verdict should be 観察 (yellow), never RED
    rep = monitor.build_report(initial_balance=500000, equity_values=[500000, 503000],
                               span_days=3, actions=["LONG"])
    assert rep["worst"] in (GREEN, YELLOW)
    assert rep["ann_return_pct"] is None               # too early to annualize


def test_drawdown_breach_flags_red():
    # 40% drawdown over a long-enough window -> RED (exceeds the 34% envelope)
    eq = [500000, 600000, 360000, 380000]              # 40% DD from 600k
    rep = monitor.build_report(initial_balance=500000, equity_values=eq,
                               span_days=200, actions=["LONG", "FLAT", "LONG"])
    dd = next(c for c in rep["checks"] if c["name"] == "ドローダウン")
    assert dd["flag"] == RED and rep["worst"] == RED


def test_execution_drift_flags_red_when_book_disagrees_with_decision():
    # system last decided LONG but the book is FLAT -> real drift
    rep = monitor.build_report(initial_balance=500000, equity_values=[500000, 510000],
                               span_days=120, actions=["FLAT", "LONG"], live_position="FLAT")
    ex = next(c for c in rep["checks"] if c["name"] == "執行一致")
    assert ex["flag"] == RED


def test_legit_opus_veto_is_not_drift():
    # raw trend is LONG, but the system decided FLAT (Opus veto) and the book is
    # FLAT -> that is CORRECT execution, must NOT flag red.
    rep = monitor.build_report(initial_balance=500000, equity_values=[500000, 500000],
                               span_days=120, actions=["LONG", "FLAT"],
                               live_position="FLAT", trend_basis="LONG")
    ex = next(c for c in rep["checks"] if c["name"] == "執行一致")
    assert ex["flag"] == GREEN
    assert rep["worst"] != RED


def test_staleness_flags_yellow():
    # Thresholds follow the loop's own cadence (round-7): one daily gap (20h)
    # yellow, 1.5 gaps red. 1.0 day is one missed decision — yellow.
    rep = monitor.build_report(initial_balance=500000, equity_values=[500000, 500000],
                               span_days=120, actions=["LONG"], live_position="LONG",
                               staleness_days=1.0)
    st = next(c for c in rep["checks"] if c["name"] == "稼働鮮度")
    assert st["flag"] == YELLOW


def test_overtrading_flags_red():
    # a flip-flopping brain (every few polls) -> far beyond any window of the
    # same length, in the backtest or in either live cadence
    actions = ["LONG", "FLAT"] * 300                   # 599 flips over 40 days
    rep = monitor.build_report(initial_balance=500000,
                               equity_values=[500000, 500000], span_days=40, actions=actions)
    tf = next(c for c in rep["checks"] if c["name"] == "取引頻度")
    assert tf["flag"] == RED


# ---- round-6: the operator's instruments must not lie --------------------

def _report(**kw):
    base = dict(initial_balance=272000.0, equity_values=[272000.0, 272500.0],
                span_days=30.0, actions=["LONG"] * 3)
    base.update(kw)
    return monitor.build_report(**base)


def test_dead_brain_is_red_not_yellow():
    r = _report(staleness_days=13.0)
    assert r["worst"] == monitor.RED
    assert any(c["name"] == "稼働鮮度" and c["flag"] == monitor.RED for c in r["checks"])
    # Round-7: the real outage was 2.82 days and the old 3-day threshold rated
    # it 🟡. The brain decides at least every 20h, so 1.5 cycles is already red.
    assert any(c["name"] == "稼働鮮度" and c["flag"] == monitor.RED
               for c in _report(staleness_days=2.82)["checks"])
    assert _report(staleness_days=0.5)["worst"] != monitor.RED       # a weekend


def test_old_ea_build_is_red():
    r = _report(ea_build="")                       # readable status, no build column
    assert any(c["name"] == "EAビルド" and c["flag"] == monitor.RED for c in r["checks"])
    assert not any(c["name"] == "EAビルド" for c in _report(ea_build=monitor.EA_BUILD_EXPECTED)["checks"])
    assert any(c["name"] == "EAビルド" and c["flag"] == monitor.RED          # one build behind
               for c in _report(ea_build="r6d-status")["checks"])
    assert not any(c["name"] == "EAビルド" for c in _report(ea_build=None)["checks"])


def test_trend_gap_is_not_blamed_on_opus_unless_it_bound():
    kw = dict(actions=["LONG", "FLAT"], live_position="FLAT", trend_basis="LONG")
    msg = next(c["msg"] for c in _report(**kw, last_ai_binding=False)["checks"] if c["name"] == "執行一致")
    assert "Opus" not in msg and "脳停止" in msg
    msg = next(c["msg"] for c in _report(**kw, last_ai_binding=True)["checks"] if c["name"] == "執行一致")
    assert "Opus拒否" in msg


def test_latest_live_run_id_ignores_dashboard_backtests(tmp_path):
    from app import db
    path = str(tmp_path / "t.db")
    db.init_db(path)
    live = db.create_run(mode="live", instrument="USD_JPY", granularity="H1",
                         initial_balance=272000.0, params={"system": "steady-ai"}, db_path=path)
    db.create_run(mode="backtest", instrument="USD_JPY", granularity="H1",
                  initial_balance=500000.0, params={}, db_path=path)          # newer row
    assert db.latest_run_id("fx", db_path=path) != live                       # the old bug
    assert db.latest_live_run_id("fx", db_path=path) == live


# ---- round-6f: the monitor must judge the bridge's LIVENESS, not its presence

def test_frozen_status_never_yields_a_green_execution_match():
    kw = dict(actions=["LONG"], live_position="LONG", trend_basis="LONG")
    r = _report(**kw, ea_status_age_s=3 * 3600.0)             # EA stopped writing 3h ago
    assert any(c["name"] == "EA稼働" and c["flag"] == monitor.RED for c in r["checks"])
    assert not any(c["name"] == "執行一致" and c["flag"] == monitor.GREEN for c in r["checks"])
    assert r["worst"] == monitor.RED


def test_missing_status_is_red_not_silent():
    r = _report(actions=["LONG"], live_position=None, status_missing=True)
    assert any(c["name"] == "EA稼働" and c["flag"] == monitor.RED for c in r["checks"])


def test_stale_bars_are_red_and_block_the_match():
    r = _report(actions=["LONG"], live_position="LONG", trend_basis=None, bars_age_h=80.0)
    assert any(c["name"] == "バー鮮度" and c["flag"] == monitor.RED for c in r["checks"])
    assert not any(c["name"] == "執行一致" and c["flag"] == monitor.GREEN for c in r["checks"])


def test_bar_freshness_uses_the_brains_own_limit():
    # Round-10B: the monitor half of the holiday fix was untested — reverting it
    # left every test passing. 77 h into the Christmas closure is healthy.
    kw = dict(actions=["LONG"], live_position="LONG", trend_basis="LONG",
              bars_count=3000, bars_need=2405)
    r = _report(bars_age_h=77.0, bars_limit_h=99.0, **kw)
    assert not any(c["name"] == "バー鮮度" for c in r["checks"])
    r = _report(bars_age_h=77.0, bars_limit_h=None, **kw)          # the plain 75 h rule
    assert any(c["name"] == "バー鮮度" and c["flag"] == monitor.RED for c in r["checks"])
    r = _report(bars_age_h=100.0, bars_limit_h=99.0, **kw)
    c = next(c for c in r["checks"] if c["name"] == "バー鮮度")
    assert c["flag"] == monitor.RED and "99h" in c["msg"]


def test_health_check_judges_a_christmas_closure_by_the_brains_rule(monkeypatch):
    """run_monitor end to end on 27 December 23:00 UTC, 77 h after the last bar
    (24 December 18:00): the limit handed to build_report and used for the
    trend basis must be the brain's 99 h, not the plain 75 h."""
    import sys as _sys
    from datetime import datetime as _datetime, timedelta, timezone as _tz
    from app.models import Candle
    from scripts import run_monitor as M

    pinned = _datetime(2026, 12, 27, 23, tzinfo=_tz.utc)

    class _DT(_datetime):
        @classmethod
        def now(cls, tz=None):
            return pinned
    monkeypatch.setattr(M, "datetime", _DT)
    last = _datetime(2026, 12, 24, 18, tzinfo=_tz.utc)
    bars = [Candle(instrument="USD_JPY", granularity="H1", time=last - timedelta(hours=2500 - i),
                   open=150.0, high=150.1, low=149.9, close=140.0 + i * 0.01) for i in range(2501)]
    monkeypatch.setattr(M.bridge, "read_bars", lambda *a, **k: bars)
    assert M._current_strategy_signal(M.Settings(granularity="H1", trend_sma=2400),
                                      "USD_JPY", "no-such.csv") == "LONG"
    seen = {}

    class _Captured(BaseException):
        pass

    def capture(**kw):
        seen.update(kw)
        raise _Captured()
    monkeypatch.setattr(M.db, "init_db", lambda: None)
    monkeypatch.setattr(M.db, "latest_live_run_id", lambda kind: 1)
    monkeypatch.setattr(M.db, "get_run", lambda rid: {"mode": "live", "granularity": "H1",
                                                      "started_at": "2026-06-18", "instrument": "USD_JPY",
                                                      "initial_balance": 300_000.0})
    monkeypatch.setattr(M.db, "load_equity", lambda rid: [
        {"time": "2026-06-18T00:00:00+00:00", "equity": 300_000.0},
        {"time": "2026-12-27T22:00:00+00:00", "equity": 280_000.0}])
    for name, val in (("_actions", ["LONG"]), ("_live_position", "LONG"),
                      ("_bridge_liveness", {"missing": False, "age_s": 20.0, "legacy": False}),
                      ("_brain_liveness", {"signal_age_s": 60.0, "expired": False}),
                      ("_last_ai_binding", None), ("_ea_build", "r6e-status"),
                      ("_last_decision_age_s", 3600.0), ("_blocked_on_lock", None),
                      ("_closed_bar_segment", None)):
        monkeypatch.setattr(M, name, (lambda v: (lambda *a, **k: v))(val))
    monkeypatch.setattr(M.monitor, "build_report", capture)
    monkeypatch.setattr(_sys, "argv", ["run_monitor.py"])
    with __import__("pytest").raises(_Captured):
        M.main()
    assert seen["bars_limit_h"] == 99.0 and round(seen["bars_age_h"]) == 77
    assert seen["trend_basis"] == "LONG"


def test_clock_skew_is_named():
    r = _report(actions=["LONG"], live_position="LONG", ea_status_age_s=-7200.0)
    assert any(c["name"] == "時計" and "wsl --shutdown" in c["msg"] for c in r["checks"])


def test_live_bridge_keeps_the_old_verdict():
    r = _report(actions=["LONG"], live_position="LONG", trend_basis="LONG",
                ea_status_age_s=20.0, bars_age_h=1.0)
    assert not any(c["name"] in ("EA稼働", "バー鮮度", "時計") for c in r["checks"])
    assert any(c["name"] == "執行一致" and c["flag"] == monitor.GREEN for c in r["checks"])


def test_short_or_missing_bars_are_red_and_block_the_match():
    for n in (0, 1000, 2404):
        r = _report(actions=["LONG"], live_position="LONG", trend_basis=None,
                    bars_count=n, bars_need=2405, bars_age_h=1.0 if n else None)
        assert any(c["name"] == "バー本数" and c["flag"] == monitor.RED for c in r["checks"]), n
        assert not any(c["name"] == "執行一致" and c["flag"] == monitor.GREEN for c in r["checks"]), n
    r = _report(actions=["LONG"], live_position="LONG", trend_basis="LONG",
                bars_count=2500, bars_need=2405, bars_age_h=1.0)
    assert not any(c["name"] == "バー本数" for c in r["checks"])


# ---- round-7: the brain must be judged by its own heartbeat ---------------

def test_brain_heartbeat_stale_is_red_and_blocks_the_match():
    r = _report(actions=["FLAT"], live_position="FLAT", brain_signal_age_s=68 * 3600.0)
    assert any(c["name"] == "脳稼働" and c["flag"] == monitor.RED for c in r["checks"])
    assert r["worst"] == monitor.RED
    # the exact 67.7h outage shape: brain dead, book flat, decision matches
    assert not any(c["name"] == "執行一致" and c["flag"] == monitor.GREEN for c in r["checks"])


def test_blocked_on_lock_is_named_with_its_remedy():
    r = _report(actions=["FLAT"], live_position="FLAT", brain_signal_age_s=10.0,
                blocked_on_lock="BLOCKED on the brain lock for 4065 min: unreadable")
    c = next(c for c in r["checks"] if c["name"] == "脳稼働")
    assert c["flag"] == monitor.RED and "steady_brain.lock" in c["msg"]


def test_a_decision_older_than_a_daily_gap_cannot_be_a_green_match():
    r = _report(actions=["FLAT"], live_position="FLAT", brain_signal_age_s=10.0,
                last_decision_age_s=30 * 3600.0)
    assert not any(c["name"] == "執行一致" and c["flag"] == monitor.GREEN for c in r["checks"])
    r = _report(actions=["FLAT"], live_position="FLAT", brain_signal_age_s=10.0,
                last_decision_age_s=2 * 3600.0)
    assert any(c["name"] == "執行一致" and c["flag"] == monitor.GREEN for c in r["checks"])


def test_live_brain_still_reads_green():
    r = _report(actions=["LONG"], live_position="LONG", trend_basis="LONG",
                brain_signal_age_s=45.0, ea_status_age_s=20.0, bars_age_h=1.0,
                bars_count=2500, bars_need=2405, last_decision_age_s=3600.0,
                staleness_days=0.1)
    assert r["worst"] != monitor.RED          # only the data-insufficiency yellow
    assert any(c["name"] == "脳稼働" and c["flag"] == monitor.GREEN for c in r["checks"])
    assert any(c["name"] == "執行一致" and c["flag"] == monitor.GREEN for c in r["checks"])
    assert not any(c["name"] in ("EA稼働", "バー鮮度", "バー本数", "時計", "稼働鮮度")
                   for c in r["checks"])


# ---- round-9: the performance checks must not cry wolf ----------------------
# They compared the live run with the old flat-5x recipe's single numbers (20
# trades/yr, +12.4%/yr) and annualised short spans, so production's OWN
# backtest read 🔴 in 12-25% of trailing windows (trade rate) and 21-23% of
# 60-90-day windows (return). A RED on normal behaviour teaches the owner to
# ignore REDs — and REDs are how a dead brain or EA is reported.

def _alternating(n_changes: int) -> list[str]:
    return ["LONG" if i % 2 == 0 else "FLAT" for i in range(n_changes + 1)]


def test_production_never_reads_red_on_its_own_behaviour():
    # Every 7th whole-day span from 30 to 1500 days, every window end (daily),
    # for the backtest and the closed-bar live brain: neither envelope check
    # ever reads RED, and YELLOW stays rare. The forming-bar brain the June
    # run began with is OUTSIDE the envelope by design (second review: covering
    # it made the monitor blind to that very defect) — it must not read GREEN.
    import numpy as np
    from scripts import monitor_envelope as ME
    runs = {"close": ME.replay("close"), "closedbar": ME.replay("closedbar", 5),
            # the count reference's neighbours at the live cadence (Round-10B) ...
            "closedbar2300": ME.replay("closedbar", 5, n_sma=2300),
            "closedbar2500": ME.replay("closedbar", 5, n_sma=2500),
            # ... and the return neighbourhood: an ordinary unlucky draw must not read RED (Round-10)
            "closedbar2700": ME.replay("closedbar", 9, n_sma=2700),
            **{f"close{n}": ME.replay("close", n_sma=n) for n in ME.NEIGHBOURHOOD if n != 2400}}
    counted = ("close", "closedbar", "closedbar2300", "closedbar2500")
    for name, r in runs.items():
        yellow = n = 0
        for W in range(30, 1501, 7):
            counts = ME.window_counts(r, W) if name in counted else np.array([], dtype=int)
            rets = ME.window_returns(r, W) if W >= 60 else np.array([])
            for c in np.unique(counts):
                rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1.0],
                                           span_days=float(W), actions=_alternating(int(c)))
                f = next(x for x in rep["checks"] if x["name"] == "取引頻度")["flag"]
                assert f != RED, (name, W, int(c))
                yellow += (f == YELLOW) * int((counts == c).sum())
            n += len(counts)
            for v in (rets.min(), np.percentile(rets, 5)) if len(rets) else ():
                rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1 + v / 100],
                                           span_days=float(W), actions=["LONG"])
                f = next(x for x in rep["checks"] if x["name"] == "リターン")["flag"]
                assert f != RED, (name, W, float(v))
        if n:
            # the live length: YELLOW stays rare. Its busier neighbours sit above
            # the pooled top-10% line more often by construction, and from 1095
            # days above SMA2400's own record too (SMA2300: 29% of those
            # windows read 'unprecedented' YELLOW; never RED) — final pass
            assert yellow / n < (0.12 if name in ("close", "closedbar") else 0.20), (name, yellow / n)
    forming = ME.replay("live", 5)
    counts = ME.window_counts(forming, 365)
    flagged = sum(next(x for x in monitor.build_report(
        initial_balance=1.0, equity_values=[1.0, 1.0], span_days=365.0,
        actions=_alternating(int(c)))["checks"] if x["name"] == "取引頻度")["flag"] != GREEN
        for c in counts)
    assert flagged / len(counts) > 0.3, flagged / len(counts)   # vs <12% for the fixed brain


def test_a_regression_to_the_forming_bar_cadence_is_visible():
    # second review: ~100 changes/yr (the pre-fix brain) read GREEN when the
    # tables covered it
    def flag(span, n):
        rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1.0],
                                   span_days=float(span), actions=_alternating(n))
        return next(x for x in rep["checks"] if x["name"] == "取引頻度")["flag"]
    assert flag(365, 100) != GREEN
    assert flag(90, 70) != GREEN
    assert flag(180, 100) == RED
    assert flag(365, 159) == RED


def test_envelope_checks_judge_only_the_closed_bar_segment():
    # a run that began under the forming-bar brain: its early whipsaw must not
    # be judged against the closed-bar envelope; before the first closed-bar
    # decision both checks wait, after it they judge that segment alone
    rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 0.70], span_days=150.0,
                               actions=_alternating(150), segment={"pending": True})
    for name in ("取引頻度", "リターン"):
        c = next(x for x in rep["checks"] if x["name"] == name)
        assert c["flag"] == YELLOW and "判定保留" in c["msg"]
    seg = {"equity_values": [1.0, 1.01], "actions": _alternating(4), "span_days": 70.0,
           "since": "2026-11-04T00:00:00+00:00"}
    rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 0.60], span_days=150.0,
                               actions=_alternating(150), segment=seg)
    for name in ("取引頻度", "リターン"):
        c = next(x for x in rep["checks"] if x["name"] == name)
        assert c["flag"] == GREEN and "2026-11-04以降" in c["msg"], c
    assert any(x["name"] == "ドローダウン" and x["flag"] == RED for x in rep["checks"])  # whole run


def test_an_ended_lock_wait_is_not_reported_as_blocked(monkeypatch):
    import json as _json
    from datetime import datetime, timedelta, timezone
    from scripts import run_monitor
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    rows = [{"source": "combined", "time": (now - timedelta(hours=4)).isoformat(),
             "components": _json.dumps({"action": "LONG", "trigger": "daily"})},
            {"source": "combined", "time": (now - timedelta(seconds=120)).isoformat(),
             "reason": "BLOCKED on the brain lock for 0 min",
             "components": _json.dumps({"action": "FLAT", "trigger": "blocked-on-lock"})}]
    monkeypatch.setattr(run_monitor.db, "load_signals", lambda rid: rows)
    assert run_monitor._blocked_on_lock(1, now=now)                 # still waiting
    assert run_monitor._blocked_on_lock(1, now=now + timedelta(hours=5)) is None   # wait ended
    assert run_monitor.BLOCKED_FRESH_S > 300                        # one log period + slack


def test_trend_basis_ignores_the_forming_bar(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.config import Settings
    from app.models import Candle
    from scripts import run_monitor
    t0 = datetime.now(timezone.utc) - timedelta(hours=200)
    bars = [Candle(instrument="USD_JPY", granularity="H1", time=t0 + timedelta(hours=i),
                   open=100.0, high=100.2, low=99.8, close=100.0) for i in range(120)]
    bars.append(Candle(instrument="USD_JPY", granularity="H1", time=t0 + timedelta(hours=120),
                       open=100.0, high=101.1, low=99.9, close=101.0))     # forming: above
    monkeypatch.setattr(run_monitor.bridge, "read_bars", lambda *a, **k: bars)
    monkeypatch.setattr(run_monitor.bridge, "MAX_BAR_AGE_H", 1e9)
    assert run_monitor._current_strategy_signal(Settings(trend_sma=90), "USD_JPY", "x") == "FLAT"


def test_live_page_decision_list_skips_blocked_rows(monkeypatch):
    import json as _json
    from app import server
    rows = [{"source": "combined", "time": "2026-11-03T10:00:00+00:00", "reason": "hold",
             "components": _json.dumps({"action": "LONG", "trigger": "daily"})},
            {"source": "combined", "time": "2026-11-03T10:05:00+00:00", "reason": "BLOCKED",
             "components": _json.dumps({"action": "FLAT", "trigger": "blocked-on-lock"})}]
    monkeypatch.setattr(server.db, "load_signals", lambda rid: rows)
    assert [d["action"] for d in server._recent_decisions(1)] == ["LONG"]


def test_real_anomalies_still_read_red():
    # a flip-flopping signal (a bug) and a loss far beyond anything the
    # backtest did over the same span
    over = monitor.build_report(initial_balance=272000, equity_values=[272000, 272000],
                                span_days=60, actions=_alternating(200))
    assert any(c["name"] == "取引頻度" and c["flag"] == RED for c in over["checks"])
    loss = monitor.build_report(initial_balance=272000, equity_values=[272000, 163000],
                                span_days=90, actions=["LONG"])
    assert any(c["name"] == "リターン" and c["flag"] == RED for c in loss["checks"])
    ok = monitor.build_report(initial_balance=272000, equity_values=[272000, 260000],
                              span_days=90, actions=_alternating(20))
    assert not any(c["name"] in ("取引頻度", "リターン") and c["flag"] == RED for c in ok["checks"])


def test_envelope_lookup():
    import math
    T = monitor.ENVELOPE_CHANGES
    assert monitor.envelope_at(T, 29.9, "scale") is None
    assert monitor.envelope_at(T, float("nan"), "scale") is None
    assert monitor.envelope_at(T, float("inf"), "scale") is None       # never raises
    assert monitor.envelope_at(T, 30, "scale") == (16.0, 32.0, 47.0)
    assert monitor.envelope_at(T, 44.9, "scale") == (16.0, 32.0, 47.0)  # a step, not interpolated
    assert monitor.envelope_at(T, 45, "scale") == (19.0, 45.0, 57.0)
    assert monitor.envelope_at(T, 2920, "scale") == (404.0, 404.0, 506.0)   # counts scale with span
    R_ = monitor.ENVELOPE_RETURN
    loosest = (min(r[1] for r in R_), min(r[2] for r in R_))
    assert monitor.envelope_at(R_, 5000, "loosest") == loosest         # long runs: never stricter
    for (w0, p0, m0, r0), (w1, p1, m1, r1) in zip(T, T[1:]):
        assert w1 > w0 and p1 >= p0 and m1 >= m0 and r1 >= r0 and r0 >= m0 >= p0
    for w, p90, most, red in T:     # RED is beyond a quarter above the live length's busiest
        assert red >= math.ceil(most * monitor.CHANGES_RED_MARGIN)
    for w, p10, worst in R_:
        assert worst <= p10 and math.isfinite(worst)
    # a span beyond the table is never judged more strictly than the last row
    rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1 + loosest[1] / 100],
                               span_days=4000.0, actions=["LONG"])
    assert next(c for c in rep["checks"] if c["name"] == "リターン")["flag"] != RED


def test_overtrading_is_still_caught_while_neighbour_whipsaw_is_not_red():
    """Round-10C (review of dae5183): with every line from 2300-2500 a steady
    doubled trade rate never read RED and the forming-bar defect read RED
    months later; with every line from SMA2400 alone, the whipsaw SMA2300 and
    SMA2500 really had read RED. Pinned at fixed horizons on the tape."""
    import numpy as np
    from scripts import monitor_envelope as ME
    def first_red_day(rate):
        return next((d for d in range(30, 3000) if rate * d / 365.25 > math.ceil(
            monitor.envelope_at(monitor.ENVELOPE_CHANGES, float(d), "scale")[2])), None)
    assert first_red_day(2 * 38.3) <= 900          # a steady doubled rate (it never did in Round-10B)
    # and from the table's end on, RED keeps the documented rule (1.25 x the live length's record)
    w, p90, most, red = monitor.ENVELOPE_CHANGES[-1]
    assert p90 <= most and red == max(math.ceil(most * monitor.CHANGES_RED_MARGIN), red)
    assert first_red_day(150) <= 240 and first_red_day(100) <= 600
    def red_starts(r, mult, within):
        t = r["t"].astype("datetime64[s]").astype(np.int64)
        hit = n = 0
        for s in t[::24]:
            spans = np.arange(30, within + 1)
            ends = s + spans * 86400
            if ends[-1] > t[-1]:
                break
            c = mult * (np.searchsorted(r["changes"], ends, side="right")
                        - np.searchsorted(r["changes"], s, side="right"))
            red = np.array([math.ceil(monitor.envelope_at(monitor.ENVELOPE_CHANGES, float(x), "scale")[2])
                            for x in spans])
            hit += bool((c > red).any()); n += 1
        return hit / n
    live = ME.replay("closedbar", 5)
    assert red_starts(live, 2, 365) >= 0.2          # 25% across poll phases (16% in Round-10B)
    assert red_starts(live, 1, 1460) == 0.0          # production itself never
    for n_sma in (2300, 2500):                       # ordinary neighbour whipsaw never RED
        assert red_starts(ME.replay("closedbar", 5, n_sma=n_sma), 1, 1460) == 0.0, n_sma


def test_beyond_history_but_inside_the_margin_says_so():
    # worse than every window of the same length, not yet RED: the message must
    # say "例のない水準", never the benign "this is what whipsaw periods look like"
    p10, worst = monitor.envelope_at(monitor.ENVELOPE_RETURN, 90, "loosest")
    rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1 + (worst - 1) / 100],
                               span_days=90.0, actions=["LONG"])
    c = next(x for x in rep["checks"] if x["name"] == "リターン")
    assert c["flag"] == YELLOW and "例のない" in c["msg"] and "よくある" not in c["msg"]
    p90, most, red = monitor.envelope_at(monitor.ENVELOPE_CHANGES, 90, "scale")
    rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1.0], span_days=90.0,
                               actions=_alternating(int(most) + 1))
    c = next(x for x in rep["checks"] if x["name"] == "取引頻度")
    assert c["flag"] == YELLOW and "例のない" in c["msg"]
    assert "想定内" not in rep["verdict"]


def test_stock_runs_are_not_judged_against_the_fx_backtest():
    rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 0.5], span_days=200.0,
                               actions=_alternating(500), kind="stocks")
    assert not any(c["name"] in ("取引頻度", "リターン") for c in rep["checks"])


def test_blocked_rows_are_not_decisions(monkeypatch):
    import json
    from scripts import run_monitor
    rows = [{"source": "combined", "components": json.dumps({"action": "LONG"})},
            {"source": "combined", "components": json.dumps({"action": "FLAT", "trigger": "blocked-on-lock"})},
            {"source": "combined", "components": json.dumps({"action": "FLAT", "trigger": "blocked-on-lock"})},
            {"source": "combined", "components": json.dumps({"action": "LONG"})},
            {"source": "combined", "components": json.dumps({"action": "FLAT", "trigger": "stop"})},
            {"source": "ai", "components": json.dumps({"action": "FLAT"})}]
    monkeypatch.setattr(run_monitor.db, "load_signals", lambda rid: rows)
    acts = run_monitor._actions(1)
    assert acts == ["LONG", "LONG", "FLAT"]                  # a stop IS a position change
    assert monitor.count_position_changes(acts) == 1


# ---- round-9 third review ---------------------------------------------------

def test_return_envelope_never_gets_stricter_with_span():
    # a -26.5% drawdown that merely stayed flat for 25 more days flipped 🟡 to
    # 🔴 at day 545 when the worst column rose again
    worsts = [w for _, _, w in monitor.ENVELOPE_RETURN]
    assert all(b <= a for a, b in zip(worsts, worsts[1:])), worsts
    def flag(span, ret):
        rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1 + ret / 100],
                                   span_days=float(span), actions=["LONG"])
        return next(x for x in rep["checks"] if x["name"] == "リターン")["flag"]
    assert flag(520, -26.5) != RED and flag(545, -26.5) != RED and flag(800, -26.5) != RED


def test_pending_wording_distinguishes_recorded_from_absent():
    one = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1.0], span_days=100.0,
                               actions=["LONG"], segment={"pending": "one-row"})
    none = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1.0], span_days=100.0,
                                actions=["LONG"], segment={"pending": True})
    m1 = next(x for x in one["checks"] if x["name"] == "取引頻度")["msg"]
    m2 = next(x for x in none["checks"] if x["name"] == "取引頻度")["msg"]
    assert "記録済み" in m1 and "まだありません" in m2


def test_live_page_health_names_a_fresh_lock_wait(monkeypatch):
    import json as _json
    from datetime import datetime, timedelta, timezone
    from app import server
    from scripts import run_monitor
    assert server.LOCK_WAIT_FRESH_S == run_monitor.BLOCKED_FRESH_S
    now = datetime.now(timezone.utc)
    rows = [{"source": "combined", "time": (now - timedelta(seconds=90)).isoformat(),
             "reason": "BLOCKED on the brain lock for 5 min: lock held by 1@old",
             "components": _json.dumps({"action": "FLAT", "trigger": "blocked-on-lock"})}]
    monkeypatch.setattr(server.db, "load_signals", lambda rid: rows)
    assert "BLOCKED" in (server._fresh_lock_wait(7) or "")
    rows[0]["time"] = (now - timedelta(hours=3)).isoformat()          # the wait has ended
    assert server._fresh_lock_wait(7) is None


# ---- round-10: the expectation is the neighbourhood, not the lucky path -----

def test_expectation_shown_is_the_neighbourhood_not_the_lucky_path():
    # SMA2400's own 15.3%/yr is the top of the entry-size draw (5th of 81 lengths)
    assert monitor.BT_CAGR_PCT < 10 and monitor.BT_CAGR_RANGE == (2.0, 15.3)
    # the alarm line sits just above the worst neighbour at the live cadence
    assert 0 <= monitor.EXP_MAXDD_PCT - monitor.BT_MAXDD_PCT < 1


def test_an_ordinary_unlucky_draw_is_not_under_performance():
    # 2015-01..2021-09: the nine lengths average about zero for 6.7 years; a flat
    # account after four years must not read RED, and a run like SMA2500's
    # (the 2021-22 trend held at 1x) must not read RED at any span
    def flag(span, ret):
        rep = monitor.build_report(initial_balance=1.0, equity_values=[1.0, 1 + ret / 100],
                                   span_days=float(span), actions=["LONG"])
        return next(x for x in rep["checks"] if x["name"] == "リターン")["flag"]
    assert flag(1460, 0.0) == GREEN
    assert flag(1460, -15.0) != RED
    assert flag(365, -20.0) != RED
    assert flag(365, -45.0) == RED           # far beyond every length's worst year


def test_current_entry_reports_the_draw(monkeypatch):
    import json as _json
    from scripts import run_monitor
    def row(day, action, **comp):
        return {"source": "combined", "time": f"2026-11-{day:02d}T00:00:00+00:00",
                "components": _json.dumps({"action": action, **comp})}
    rows = [row(1, "LONG", eff_leverage=5.0, target_lots=0.08, position_lots=0.0),
            row(2, "FLAT", trigger="stop"),
            row(3, "LONG", eff_leverage=1.3, target_lots=0.02, trigger="gate-entry", position_lots=0.0),
            row(4, "FLAT", trigger="blocked-on-lock"),
            row(5, "LONG", eff_leverage=5.0, target_lots=0.02, trigger="daily", position_lots=0.02)]
    monkeypatch.setattr(run_monitor.db, "load_signals", lambda rid: rows)
    e = run_monitor._current_entry(1)
    assert e["eff_leverage"] == 1.3 and e["lots"] == 0.02 and e["time"].startswith("2026-11-03")
    rows.append(row(6, "FLAT", trigger="gate-exit"))
    assert run_monitor._current_entry(1) is None


def test_current_entry_is_the_order_that_filled(monkeypatch):
    """Round-10B: an entry the EA did not fill (algo trading off, back-off) is
    re-decided on a later bar at a new ramp; the line showed the unfilled
    order's 1.8x for a book held at 5.0x."""
    import json as _json
    from scripts import run_monitor
    def row(h, action, **comp):
        return {"source": "combined", "time": f"2026-11-10T{h:02d}:00:00+00:00",
                "components": _json.dumps({"action": action, **comp})}
    rows = [row(15, "FLAT", trigger="gate-exit"),
            row(16, "LONG", eff_leverage=1.79, target_lots=0.03, trigger="gate-entry", position_lots=0.0),
            row(17, "LONG", eff_leverage=5.0, target_lots=0.09, trigger="gate-entry", position_lots=0.0)]
    monkeypatch.setattr(run_monitor.db, "load_signals", lambda rid: rows)
    assert run_monitor._current_entry(1)["eff_leverage"] == 5.0        # the newest order is the live one
    rows += [row(18, "LONG", trigger="restart-settle", position_lots=0.09),   # no ramp on this row
             row(19, "LONG", eff_leverage=2.2, target_lots=0.09, trigger="daily", position_lots=0.09),
             row(20, "LONG", eff_leverage=4.0, target_lots=0.09, trigger="gate-rearm", position_lots=0.09)]
    e = run_monitor._current_entry(1)
    assert e["eff_leverage"] == 5.0 and e["time"].startswith("2026-11-10T17")
    rows.append(row(21, "FLAT", trigger="stop"))
    rows.append(row(22, "LONG", trigger="restart-settle", position_lots=0.05))
    assert run_monitor._current_entry(1)["eff_leverage"] is None      # unknown draw: the line is omitted

def test_health_check_prints_the_held_size_and_its_real_multiple(monkeypatch, capsys):
    """Round-10B: at 272,000 JPY the 0.01-lot step truncates a ramp of 1.0-1.1x
    to about 0.55x real, and an external trim is adopted by the brain: the line
    must show the book's lots and the real multiple next to the ramp's."""
    import sys as _sys
    from datetime import datetime as _datetime, timedelta, timezone as _tz
    from app.models import Candle
    from scripts import run_monitor as M
    now = _datetime.now(_tz.utc).replace(minute=0, second=0, microsecond=0)
    bars = [Candle(instrument="USD_JPY", granularity="H1", time=now - timedelta(hours=2500 - i),
                   open=150.0, high=150.1, low=149.9, close=140.0 + i * 0.004) for i in range(2501)]
    monkeypatch.setattr(M.bridge, "read_bars", lambda *a, **k: bars)
    monkeypatch.setattr(M.bridge, "read_status", lambda *a, **k: {
        "balance": 272_000.0, "equity": 272_000.0, "position_lots": 0.01})
    monkeypatch.setattr(M.db, "init_db", lambda: None)
    monkeypatch.setattr(M.db, "latest_live_run_id", lambda kind: 1)
    monkeypatch.setattr(M.db, "get_run", lambda rid: {"mode": "live", "granularity": "H1",
                                                      "started_at": "2026-06-18", "instrument": "USD_JPY",
                                                      "initial_balance": 300_000.0})
    monkeypatch.setattr(M.db, "load_equity", lambda rid: [
        {"time": "2026-06-18T00:00:00+00:00", "equity": 300_000.0},
        {"time": now.isoformat(), "equity": 272_000.0}])
    monkeypatch.setattr(M, "_current_entry", lambda rid: {
        "time": "2026-11-10T17:00:00+00:00", "eff_leverage": 1.08, "lots": 0.01})
    for name, val in (("_actions", ["LONG"]),
                      ("_bridge_liveness", {"missing": False, "age_s": 20.0, "legacy": False}),
                      ("_brain_liveness", {"signal_age_s": 60.0, "expired": False}),
                      ("_last_ai_binding", None), ("_ea_build", "r6e-status"),
                      ("_last_decision_age_s", 3600.0), ("_blocked_on_lock", None),
                      ("_closed_bar_segment", None)):
        monkeypatch.setattr(M, name, (lambda v: (lambda *a, **k: v))(val))
    monkeypatch.setattr(_sys, "argv", ["run_monitor.py"])
    M.main()
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if "今の建玉" in l)
    real = 0.01 * 100_000 * bars[-1].close / 272_000.0
    assert "0.01ロット" in line and f"実効{real:.1f}倍" in line and "ランプ倍率 1.1倍" in line, line
    assert "UTC建て" in line and "2026-11-10 17:00" in line, line
    head = next(l for l in out.splitlines() if "基準" in l)
    assert "年+9%前後（2〜15%）" in head and "警告線36%" in head and "最悪35%" in head, head


def test_a_stuck_long_stays_an_execution_mismatch_however_old_the_decision():
    """Review of dae5183: the EA ignores a FLAT (algo trading off). The brain
    keeps heartbeating FLAT and writes no rows; after 20 h the stale-decision
    branch read the real mismatch as 判定不能 and, from 30 h, 稼働鮮度 told the
    owner to restart a healthy brain."""
    for age_h in (2.0, 21.0, 31.0, 72.0):
        r = _report(actions=["LONG", "FLAT"], live_position="LONG", trend_basis="FLAT",
                    brain_signal_age_s=60.0, ea_status_age_s=20.0, bars_age_h=1.0,
                    bars_count=3000, bars_need=2405, last_decision_age_s=age_h * 3600,
                    staleness_days=age_h / 24.0)
        ex = next(c for c in r["checks"] if c["name"] == "執行一致")
        assert ex["flag"] == RED and "アルゴ取引" in ex["msg"], (age_h, ex)
        fr = [c for c in r["checks"] if c["name"] == "稼働鮮度"]
        assert not any("up -d fx" in c["msg"] for c in fr), (age_h, fr)
        if age_h > 30:
            assert fr and fr[0]["flag"] == RED and "再起動では直らない" in fr[0]["msg"]
            assert "執行しない" in fr[0]["msg"] and "アルゴ取引" in fr[0]["msg"]
    # final pass: MT5 closed while FLAT -> the brain is blind on a frozen EA; the
    # freshness text must name the EA, not "waiting for the EA to close"
    r = _report(actions=["FLAT"], live_position="FLAT", brain_signal_age_s=60.0,
                ea_status_age_s=31 * 3600.0, bars_age_h=31.0, bars_count=3000, bars_need=2405,
                last_decision_age_s=31 * 3600.0, staleness_days=31 / 24.0)
    fr = next(c for c in r["checks"] if c["name"] == "稼働鮮度")
    assert "EA稼働" in fr["msg"] and "執行しない" not in fr["msg"] and "up -d fx" not in fr["msg"], fr
    assert any(c["name"] == "EA稼働" and c["flag"] == RED for c in r["checks"])
    # a dead brain is still sent to the restart, and an agreeing stale decision is still 判定不能
    r = _report(actions=["LONG", "FLAT"], live_position="LONG", brain_signal_age_s=4000.0,
                ea_status_age_s=20.0, last_decision_age_s=31 * 3600.0, staleness_days=31 / 24.0)
    assert any(c["name"] == "稼働鮮度" and "up -d fx" in c["msg"] for c in r["checks"])
    r = _report(actions=["LONG"], live_position="LONG", trend_basis="LONG", brain_signal_age_s=60.0,
                ea_status_age_s=20.0, bars_age_h=1.0, last_decision_age_s=21 * 3600.0)
    assert next(c for c in r["checks"] if c["name"] == "執行一致")["flag"] == YELLOW
