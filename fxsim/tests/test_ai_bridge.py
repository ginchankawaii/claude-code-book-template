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
                        lambda action, lots, base=None, expires_at=None:
                            written.append((action, round(lots, 2))))
    # the bundled test candles are historical: disable the live freshness guard
    monkeypatch.setattr(R, "MAX_BAR_AGE_H", 1e9)
    # keep the DB out of the unit test
    monkeypatch.setattr(db, "list_runs", lambda: [])
    monkeypatch.setattr(db, "create_run", lambda **k: 1)
    monkeypatch.setattr(db, "record_equity", lambda *a, **k: None)
    monkeypatch.setattr(db, "load_equity", lambda *a, **k: [])
    monkeypatch.setattr(db, "record_signal", lambda *a, **k: None)
    return written


def _run(monkeypatch, window, dec):
    monkeypatch.setattr(bridge, "read_bars", lambda instr="USD_JPY", gran="D", base=None: window)
    trader = _Trader(dec)
    cfg = Settings(strategy="ai", granularity="D", max_leverage=5.0)
    R.decide_once(cfg, "USD_JPY", 0.04, 5.0, str(DATA_DIR / "USD_JPY_D.csv"),
                  trader, dry=False, trigger="test", granularity="D", sma_n=90)
    return trader


def test_trend_down_stands_aside_without_calling_opus(wired, monkeypatch):
    trader = _run(monkeypatch, _DOWN, _Dec(True, "long", 0.9))
    assert wired[-1][0] == "FLAT" and wired[-1][1] == 0.0
    assert trader.calls == 0          # gate short-circuits the (paid) Opus call


def test_trend_up_no_key_trades_the_deterministic_long(wired, monkeypatch):
    _run(monkeypatch, _UP, _Dec(False, "flat", 0.0))   # Opus unavailable
    assert wired[-1][0] == "LONG" and wired[-1][1] > 0


def test_trend_up_opus_veto_stands_aside(wired, monkeypatch):
    _run(monkeypatch, _UP, _Dec(True, "flat", 0.0))
    assert wired[-1][0] == "FLAT"


def test_trend_up_never_shorts(wired, monkeypatch):
    _run(monkeypatch, _UP, _Dec(True, "short", 0.9))
    assert wired[-1][0] == "FLAT"


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
                        lambda: [{"id": 7, "ended_at": None, "params": '{"system": "steady-ai"}'}])
    monkeypatch.setattr(db, "load_signals", lambda rid: rows)
    intent, stop, ts = R._restore_state()
    assert intent == "LONG" and stop == 158.917 and ts > 0
    # ...but a FLAT after the stop-exit means no stop and FLAT intent
    rows.append({"source": "combined", "direction": 0, "time": "2026-07-03T00:00:00+00:00",
                 "components": '{"trigger": "stop"}'})
    intent, stop, _ = R._restore_state()
    assert intent == "FLAT" and stop is None
