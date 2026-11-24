"""Terminal loses the broker connection mid-week (ISP/router/broker): the EA keeps
exporting its cached account + cached bars with an advancing local clock."""
import os, sys
SCR = __import__("tempfile").mkdtemp(prefix="fxsim-baseline-")   # never write beside this file: it lives in the repository
os.environ["FXSIM_DB"] = os.path.join(SCR, "t2.db"); os.environ["MT5_COMMON_FILES"] = os.path.join(SCR, "c2")
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
from datetime import datetime, timedelta, timezone
from app import bridge, monitor
from app.models import Candle
import scripts.run_ai_bridge as R
U = timezone.utc
last_bar = datetime(2026, 11, 17, 10, tzinfo=U)          # Tuesday 10:00 — connection lost here
bars = [Candle(instrument="USD_JPY", granularity="H1", time=last_bar - timedelta(hours=130 - i),
               open=150 + i * .05, high=150.1 + i * .05, low=149.95 + i * .05, close=150.05 + i * .05) for i in range(131)]
bridge.read_bars = lambda *a, **k: bars
for hours in (2, 12, 36, 60, 74, 76):
    now = last_bar + timedelta(hours=hours)
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None): return now
    R.datetime = _DT
    bridge.read_status = lambda *a, **k: {"balance": 272000.0, "equity": 272000.0, "position_lots": 0.08,
                                          "exec_seq": 1, "ea_time": int(now.timestamp()), "build": bridge.EA_BUILD_EXPECTED}
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        probe = R._trend_gate("USD_JPY", "H1", 90, "nope.csv")
    rep = monitor.build_report(initial_balance=272000.0, equity_values=[272000.0, 272000.0], span_days=30,
        actions=["LONG"], live_position="LONG", trend_basis="LONG", staleness_days=0.3,
        ea_build=bridge.EA_BUILD_EXPECTED, status_missing=False, ea_status_age_s=5.0,
        bars_age_h=hours, bars_count=2500, bars_need=2405, bars_limit_h=75.0,
        brain_signal_age_s=300.0, signal_expired=False, last_decision_age_s=3600.0, blocked_on_lock=None)
    flags = {c["name"]: c["flag"] for c in rep["checks"] if c["name"] in ("脳稼働", "EA稼働", "バー鮮度", "執行一致")}
    print(f"feed frozen {hours:>2}h ({now:%a %H:%M} UTC): brain probe {'TRUSTED -> heartbeat renewed' if probe else 'blind'} | monitor {flags}")
