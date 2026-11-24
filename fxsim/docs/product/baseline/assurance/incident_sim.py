"""Replay of the 2026-11-16 incident shape against the REAL brain (scripts.run_ai_bridge.main)
and the repo's own FakeEA transcription (tests/test_ea_protocol.py), over real bridge files.

World: Windows reboots; MT5 + Docker come back, MT5 is NOT logged in for 5h20m (EA sees an
empty book and balance 0, keeps exporting status every 30 s), then the terminal logs in.
Variant "weekday": the market is open at login. Variant "weekend": closes are rejected.

Nothing in the repo is written: DB and bridge files live under the scratch dir given as argv[1].
"""
import io
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRATCH = Path(sys.argv[1])
VARIANT = sys.argv[2]
REPO = Path("/home/user/claude-code-book-template/fxsim")
work = SCRATCH / f"incident_{VARIANT}"
if work.exists():
    for p in work.iterdir():
        p.unlink()
work.mkdir(parents=True, exist_ok=True)
os.environ["MT5_COMMON_FILES"] = str(work)
os.environ["FXSIM_DB"] = str(work / "sim.db")
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
os.chdir(SCRATCH)

from app import bridge, db                      # noqa: E402
import scripts.run_ai_bridge as R               # noqa: E402
from test_ea_protocol import FakeEA             # noqa: E402  (the repo's own EA transcription)

T0 = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc).timestamp()   # a Wednesday
clock = {"t": T0}
REBOOT_AT = T0 + 3 * 3600 + 40 * 60            # 03:40 into the run
LOGIN_AT = REBOOT_AT + 5 * 3600 + 20 * 60      # MT5 logs in 5h20m later
END_AT = LOGIN_AT + 40 * 60
world = {"logged_in": True, "market_open": True, "bars_until": T0, "restart_pending": False,
         "restarted": False, "close_attempts": 0}
ea = FakeEA(lots=0.0, exec_seq=0, bid=0.0)
log = []


def say(msg):
    t = datetime.fromtimestamp(clock["t"], timezone.utc).strftime("%a %H:%M:%S")
    log.append(f"{t}  {msg}")


def price_at(i):
    return 140.0 + i * 0.1


def export_bars():
    """EA ExportAll(): CopyRates(start=0) -> the last row is the forming bar. No login = no new bars."""
    if world["logged_in"]:
        world["bars_until"] = clock["t"]
    last_hour = int((world["bars_until"] - T0) // 3600)
    rows = ["time,open,high,low,close"]
    for i in range(-130, last_hour + 1):
        t = datetime.fromtimestamp(T0 + i * 3600, timezone.utc)
        c = price_at(i + 130)
        rows.append(f"{t:%Y.%m.%d %H:%M:%S},{c:.5f},{c + 0.05:.5f},{c - 0.05:.5f},{c:.5f}")
    (work / bridge.BARS_FILE).write_text("\n".join(rows) + "\n")
    return price_at(last_hour + 130)


def export_status():
    bal = 272000.0 if world["logged_in"] else 0.0
    lots = ea.lots if world["logged_in"] else 0.0
    tmp = work / (bridge.STATUS_FILE + ".tmp")
    tmp.write_text("balance,equity,position_lots,exec_seq,ea_time,build\n"
                   f"{bal:.2f},{bal:.2f},{lots:.3f},{ea.exec_seq},{int(clock['t'])},{bridge.EA_BUILD_EXPECTED}\n")
    os.replace(tmp, work / bridge.STATUS_FILE)


def ea_timer():
    """One 30-second OnTimer(): ExportAll(); ProcessSignal()."""
    ea.bid = export_bars()
    export_status()
    real_lots = ea.lots
    if not world["logged_in"]:
        ea.lots = 0.0                           # not logged in: PositionsTotal() == 0
    n = len(ea.actions)
    ea.tick(work, now=int(clock["t"]))
    new = ea.actions[n:]
    if not world["logged_in"]:
        ea.lots = real_lots                     # the broker still holds the position
    elif any("closeall" in a for a in new) and not world["market_open"]:
        ea.lots = real_lots                     # "Market closed": the close is rejected
        world["close_attempts"] += 1
        new = [a + " REJECTED (market closed)" for a in new]
    for a in new:
        if a not in ("held-flat",):
            say(f"EA   {a}  -> book {ea.lots:.2f}")


class _Stop(BaseException):
    pass


class _FakeTime:
    @staticmethod
    def time():
        return clock["t"]

    @staticmethod
    def sleep(s):
        end = clock["t"] + s
        while clock["t"] < end:
            clock["t"] += 30
            if world["logged_in"] and REBOOT_AT <= clock["t"] < LOGIN_AT:
                world["logged_in"] = False
                world["restart_pending"] = True
                say("WORLD Windows Update reboot: MT5 + Docker restart, MT5 NOT logged in")
            if not world["logged_in"] and clock["t"] >= LOGIN_AT:
                world["logged_in"] = True
                say("WORLD MT5 terminal logs in to the broker")
            ea_timer()
        if clock["t"] >= END_AT or world["restart_pending"]:
            raise _Stop()


class _DT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.fromtimestamp(clock["t"], tz)


class _Dec:
    ok, action, conviction, reason, factors, plan = False, "long", 0.0, "no key", [], ""


class _NoAI:
    model = "none"

    def __init__(self, *a, **k):
        pass

    def decide(self, ctx):
        return _Dec()


R._time = _FakeTime
R.datetime = _DT
R.AITrader = _NoAI
R.get_calendar = lambda *a, **k: type("C", (), {"for_instrument": lambda self, i: []})()
R._arm_lock_release = lambda lock: None
world["market_open"] = True
sys.argv = ["run_ai_bridge.py", "--poll", "600", "--sma", "90"]


class _Tee(io.StringIO):
    def write(self, s):
        for ln in s.splitlines():
            if ln.strip() and "[ai]" in ln:
                keep = ("BLIND", "wrote signal", "decision:", "restored", "EXTERNALLY", "brain build",
                        "adopting", "settling", "waiting for EA status", "loop error")
                if any(k in ln for k in keep):
                    say("BRAIN " + ln.strip()[:150])
        return len(s)


ea_timer()
with redirect_stdout(_Tee()):
    for incarnation in range(3):
        try:
            R.main()
        except _Stop:
            pass
        if clock["t"] >= END_AT:
            break
        world["restart_pending"] = False
        if VARIANT == "weekend":
            world["market_open"] = False
        say("WORLD brain container restarted by Docker")

# collapse the repeated BLIND lines
out, blind = [], 0
for ln in log:
    if "BLIND" in ln:
        blind += 1
        if blind > 2:
            continue
    out.append(ln)
print("\n".join(out))
print(f"\n[{VARIANT}] BLIND lines printed: {blind}; rejected close attempts: {world['close_attempts']}; "
      f"final broker book: {ea.lots:.2f} lots")
sigs = db.load_signals(db.list_runs()[0]["id"]) if db.list_runs() else []
print(f"[{VARIANT}] decision rows in DB: " + " | ".join(
    f"{str(s['time'])[11:16]} dir={s['direction']} {str(s['reason'])[:48]}" for s in sigs))
