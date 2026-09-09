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
    rep = monitor.build_report(initial_balance=500000, equity_values=[500000, 500000],
                               span_days=120, actions=["LONG"], live_position="LONG",
                               staleness_days=3.0)
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
    assert _report(staleness_days=2.0)["worst"] != monitor.RED       # a long weekend


def test_old_ea_build_is_red():
    r = _report(ea_build="")                       # readable status, no build column
    assert any(c["name"] == "EAビルド" and c["flag"] == monitor.RED for c in r["checks"])
    assert not any(c["name"] == "EAビルド" for c in _report(ea_build=monitor.EA_BUILD_EXPECTED)["checks"])
    assert any(c["name"] == "EAビルド" and c["flag"] == monitor.RED          # one build behind
               for c in _report(ea_build="r6c-status")["checks"])
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
