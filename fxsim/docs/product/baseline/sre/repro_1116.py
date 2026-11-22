"""Reconstruct the 2026-11-16 incident against the real brain loop (R.main) with a
model of the EA's expiry branch. Read-only on the repo; DB and bridge in scratch."""
import os, sys, io, contextlib
SCR = __import__("tempfile").mkdtemp(prefix="fxsim-baseline-")   # never write beside this file: it lives in the repository
os.environ["FXSIM_DB"] = os.path.join(SCR, "t.db")
os.environ["MT5_COMMON_FILES"] = os.path.join(SCR, "common")
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
from datetime import datetime, timedelta, timezone
from app import bridge, db, monitor
from app.models import Candle
import scripts.run_ai_bridge as R

U = timezone.utc
JST = timezone(timedelta(hours=9))
WEEKDAY = len(sys.argv) > 1 and sys.argv[1] == "weekday"
def ts(*a): return datetime(*a, tzinfo=JST).timestamp()
def j(t): return datetime.fromtimestamp(t, JST).strftime("%m-%d %H:%M:%S")

reboot   = ts(2026, 11, 16, 1, 40)
brain_up = reboot + 150                  # docker + container back
login    = ts(2026, 11, 16, 6, 54, 41)   # terminal logs in
mkt_open = ts(2026, 11, 16, 7, 3, 30) if not WEEKDAY else 0   # weekday: market already open
end      = ts(2026, 11, 16, 8, 30)
clock = {"t": brain_up}
class _Stop(BaseException): pass
class _FakeTime:
    @staticmethod
    def time(): return clock["t"]
    @staticmethod
    def sleep(s):
        ea_run(clock["t"], clock["t"] + s)
        clock["t"] += s
        if clock["t"] >= end: raise _Stop()
class _DT(datetime):
    @classmethod
    def now(cls, tz=None): return datetime.fromtimestamp(clock["t"], tz)
R._time = _FakeTime; R.datetime = _DT
R._acquire_brain_lock = lambda poll: None            # lock is out of scope here
R.get_calendar = lambda *a, **k: type("C", (), {"for_instrument": lambda self, i: [], "unreadable": False})()
class _NoAI:
    model = "none"
    def __init__(self, *a, **k): pass
    def decide(self, ctx):
        return type("D", (), {"ok": False, "action": "long", "conviction": 0.0, "reason": "no key", "factors": [], "plan": ""})()
R.AITrader = _NoAI

# bars: last H1 bar Friday close (server-time label read as UTC), uptrend
last_bar = datetime(2026, 11, 13, 23, tzinfo=U)
bars = [Candle(instrument="USD_JPY", granularity="H1", time=last_bar - timedelta(hours=130 - i),
               open=150.0 + i * 0.05, high=150.1 + i * 0.05, low=149.95 + i * 0.05,
               close=150.05 + i * 0.05) for i in range(131)]
bridge.read_bars = lambda *a, **k: bars

# --- EA model (SteadyBridge.mq5 ExportAll + ProcessSignal expiry branch) ---
seq0 = int(reboot) - 86400 * 5
book = {"lots": 0.08, "closed_at": None}
signal = {"action": "LONG", "lots": 0.08, "seq": seq0, "expires_at": int(reboot - 240) + 7200, "sl": 150.0}
ea_log, writes = [], []
def logged_in(t): return t >= login
def status_at(t):
    if not logged_in(t):   # ACCOUNT_BALANCE=0, PositionsTotal()=0 while not logged in
        return {"balance": 0.0, "equity": 0.0, "position_lots": 0.0, "exec_seq": seq0, "ea_time": int(t), "build": bridge.EA_BUILD_EXPECTED}
    return {"balance": 272000.0, "equity": 272000.0, "position_lots": book["lots"], "exec_seq": seq0, "ea_time": int(t), "build": bridge.EA_BUILD_EXPECTED}
bridge.read_status = lambda *a, **k: status_at(clock["t"])
bridge.read_signal = lambda *a, **k: dict(signal)
def write_signal(action, lots, base=None, expires_at=None, sl=None, seq=None):
    signal.update(action=action, lots=lots, seq=seq, expires_at=expires_at, sl=sl)
    writes.append((clock["t"], action, round(lots, 2), expires_at, seq))
bridge.write_signal = write_signal
def ea_run(t0, t1):
    t = (int(t0) // 30 + 1) * 30 + 11
    while t < t1:
        cur = book["lots"] if logged_in(t) else 0.0     # CurrentLots() sees nothing when not logged in
        exp = signal.get("expires_at") or 0
        if exp and t > exp and abs(cur) > 0:              # mq5:335-341
            if t >= mkt_open:
                book["lots"] = 0.0; book["closed_at"] = t
                ea_log.append((t, "FLAT fail-safe -> CLOSED"))
            else:
                ea_log.append((t, "FLAT fail-safe -> close failed [Market closed]"))
        t += 30

db.init_db()
rid = db.create_run(mode="live", instrument="USD_JPY", granularity="H1", initial_balance=272000.0,
                    params={"system": "steady-ai", "model": "none", "max_risk": 0.04})
db.record_equity(rid, datetime.fromtimestamp(reboot - 86400 * 5, U), 272000.0, 272000.0, 155.0)
db.record_equity(rid, datetime.fromtimestamp(reboot - 3600 * 6, U), 272000.0, 272000.0, 156.0)
db.record_signal(rid, datetime.fromtimestamp(reboot - 3600 * 6, U), "USD_JPY", "combined", 1, 0.0,
                 "hold", {"action": "LONG", "trigger": "daily", "cadence": "closed-bar", "stop_price": 150.0,
                          "seq": seq0, "position_lots": 0.08, "target_lots": 0.08})

# monitor snapshot helper, at a chosen instant
def monitor_at(t, label):
    st = status_at(t)
    live_pos = "LONG" if (st["position_lots"] or 0) > 1e-9 else "FLAT"
    last_w = max([w[0] for w in writes if w[0] <= t], default=reboot - 240)
    eq = db.load_equity(rid)
    rep = monitor.build_report(
        initial_balance=272000.0, equity_values=[e["equity"] for e in eq], span_days=5.0,
        actions=["LONG"], live_position=live_pos, trend_basis="LONG",
        staleness_days=(t - datetime.fromisoformat(str(eq[-1]["time"])).replace(tzinfo=U).timestamp()) / 86400.0,
        ea_build=st["build"], status_missing=False, ea_status_age_s=1.0,
        bars_age_h=(t - last_bar.timestamp()) / 3600.0, bars_count=2500, bars_need=2405, bars_limit_h=75.0,
        brain_signal_age_s=t - last_w, signal_expired=t > (signal.get("expires_at") or 0),
        last_decision_age_s=t - (reboot - 3600 * 6), blocked_on_lock=None)
    print(f"--- run_monitor checks at {j(t)} JST ({label}) ---")
    for c in rep["checks"]:
        if c["name"] in ("脳稼働", "EA稼働", "執行一致", "稼働鮮度", "バー鮮度", "時計"):
            print("   ", c["flag"], c["name"], c["msg"][:150])
    print("    verdict:", rep["verdict"][:40])

sys.argv = ["run_ai_bridge.py", "--poll", "600", "--sma", "90"]
buf = io.StringIO()
snap = {}
orig_sleep = _FakeTime.sleep
def sleep2(s):
    t = clock["t"]
    for name, at in (("mid-outage 04:00", ts(2026, 11, 16, 4, 0)), ("after recovery 08:00", ts(2026, 11, 16, 8, 0))):
        if name not in snap and t >= at:
            snap[name] = (t, signal.get("expires_at"), list(writes))
    orig_sleep(s)
_FakeTime.sleep = staticmethod(sleep2)
lines = []
class Tee(io.TextIOBase):
    def write(self, s):
        for ln in s.splitlines():
            if ln.strip(): lines.append((clock["t"], ln))
        return len(s)
try:
    with contextlib.redirect_stdout(Tee()):
        R.main()
except _Stop:
    pass

print("SCENARIO:", "WEEKDAY (market open at login)" if WEEKDAY else "ACTUAL (Monday, market closed until 07:03:30)")
print(f"standing EXP before reboot = {j(signal['expires_at'] if not writes else int(reboot - 240) + 7200)} JST")
print("=== brain log (deduplicated by message shape) ===")
seen = {}
for t, ln in lines:
    key = "".join(ch for ch in ln if not ch.isdigit())[:70]
    seen.setdefault(key, [t, t, 0, ln]); seen[key][1] = t; seen[key][2] += 1
for key, (t0, t1, n, ln) in seen.items():
    print(f"  {j(t0)} .. {j(t1)}  x{n:<3} {ln[:170]}")
print("=== heartbeat writes ===")
print("  count:", len(writes), "| first:", (j(writes[0][0]), writes[0][1:]) if writes else None)
print("=== EA fail-safe attempts ===")
print("  count:", len(ea_log), "| first:", (j(ea_log[0][0]), ea_log[0][1]) if ea_log else None,
      "| last:", (j(ea_log[-1][0]), ea_log[-1][1]) if ea_log else None)
print("  book lots at end:", book["lots"], "| closed_at:", j(book["closed_at"]) if book["closed_at"] else None)
sigs = db.load_signals(rid)
print("=== DB rows written during/after the incident ===")
for s in sigs[1:]:
    print("  ", str(s["time"])[:19], s["reason"][:120])
print("  (rows:", len(sigs) - 1, ")")
# monitor views
clock_save = clock["t"]
w_all = list(writes)
writes[:] = [w for w in w_all if w[0] <= ts(2026, 11, 16, 4, 0)]
exp_save = signal["expires_at"]; signal["expires_at"] = int(reboot - 240) + 7200
monitor_at(ts(2026, 11, 16, 4, 0), "mid-outage")
writes[:] = w_all; signal["expires_at"] = exp_save
monitor_at(ts(2026, 11, 16, 8, 0), "after recovery")
