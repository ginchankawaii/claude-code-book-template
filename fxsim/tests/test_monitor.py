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


def test_execution_drift_flags_red():
    rep = monitor.build_report(initial_balance=500000, equity_values=[500000, 510000],
                               span_days=120, actions=["LONG"],
                               strategy_signal="LONG", live_position="FLAT")
    ex = next(c for c in rep["checks"] if c["name"] == "執行一致")
    assert ex["flag"] == RED


def test_overtrading_flags_red():
    actions = ["LONG", "FLAT"] * 30                    # 59 flips over ~40 days -> ~500/yr
    rep = monitor.build_report(initial_balance=500000,
                               equity_values=[500000, 500000], span_days=40, actions=actions)
    tf = next(c for c in rep["checks"] if c["name"] == "取引頻度")
    assert tf["flag"] == RED
