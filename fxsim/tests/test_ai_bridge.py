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
                        lambda action, lots, base=None: written.append((action, round(lots, 2))))
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
