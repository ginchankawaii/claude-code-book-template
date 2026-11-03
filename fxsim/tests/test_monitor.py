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
    actions = ["LONG", "FLAT"] * 30                    # 59 flips over ~40 days -> ~500/yr
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


def test_production_never_reads_red_on_its_own_backtest():
    import numpy as np
    from scripts import monitor_envelope as ME
    st = ME.production_run()
    tv, eq = st["t"].to_numpy(), st["eq"]
    ct = ME.change_times(st).to_numpy()
    # spans ON and BETWEEN the envelope's rows, and beyond its last row
    for W in (30, 45, 60, 75, 120, 200, 270, 365, 500, 730, 1000, 1460, 1800, 2400):
        yellow = n = 0
        for k in range(0, len(tv), 24 * 7):
            s = tv[k] - np.timedelta64(W, "D")
            if s < tv[0]:
                continue
            j = int(np.searchsorted(tv, s))
            n_ch = int(((ct > s) & (ct <= tv[k])).sum())
            rep = monitor.build_report(initial_balance=eq[j], equity_values=[eq[j], eq[k]],
                                       span_days=float(W), actions=_alternating(n_ch))
            for c in rep["checks"]:
                if c["name"] in ("取引頻度", "リターン"):
                    assert c["flag"] != RED, (W, str(tv[k])[:10], c["msg"])
                    yellow += c["flag"] == YELLOW
            n += 1
        if W >= 60:                    # both checks judge from 60 days on
            assert yellow / (2 * n) < 0.15, (W, yellow / (2 * n))


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
    T = monitor.ENVELOPE_CHANGES
    assert monitor.envelope_at(T, 29.9, "scale") is None
    assert monitor.envelope_at(T, float("nan"), "scale") is None
    assert monitor.envelope_at(T, 30, "scale") == (12, 31)
    lo, hi = monitor.envelope_at(T, 45, "scale")
    assert 12 < lo < 19 and 31 < hi < 43                    # linear between rows
    assert monitor.envelope_at(T, 2920, "scale") == (380.0, 396.0)   # counts scale with span
    R = monitor.ENVELOPE_RETURN
    assert monitor.envelope_at(R, 5000, "hold") == (18.8, -1.3)      # returns hold the last row
    for (w0, p0, m0), (w1, p1, m1) in zip(T, T[1:]):
        assert w1 > w0 and p1 >= p0 and m1 >= m0 and m0 >= p0      # sane, monotone table


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
