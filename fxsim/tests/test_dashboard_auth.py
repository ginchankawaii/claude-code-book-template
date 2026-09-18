"""Dashboard HTTP Basic auth gate (off when no password set, enforced when set)."""
import app.server as srv
from fastapi.testclient import TestClient

client = TestClient(srv.app)


def test_open_when_no_password(monkeypatch):
    monkeypatch.setattr(srv, "_DASH_PASS", "")
    r = client.get("/api/config")
    assert r.status_code == 200          # local mode: no login required


def test_blocks_without_credentials_when_password_set(monkeypatch):
    monkeypatch.setattr(srv, "_DASH_PASS", "s3cret")
    monkeypatch.setattr(srv, "_DASH_USER", "admin")
    r = client.get("/api/config")
    assert r.status_code == 401          # no creds -> blocked


def test_rejects_wrong_and_accepts_right(monkeypatch):
    monkeypatch.setattr(srv, "_DASH_PASS", "s3cret")
    monkeypatch.setattr(srv, "_DASH_USER", "admin")
    assert client.get("/api/config", auth=("admin", "nope")).status_code == 401
    assert client.get("/api/config", auth=("admin", "s3cret")).status_code == 200


# ---- round-6: the internet-exposed surface ---------------------------------

def test_tunnel_without_password_refuses_every_request(monkeypatch):
    # docs call the password "mandatory" before tunnelling; nothing enforced it.
    monkeypatch.setattr(srv, "_DASH_PASS", "")
    monkeypatch.setattr(srv, "_TUNNEL_TOKEN", "eyJ-some-token")
    r = client.get("/api/config")
    assert r.status_code == 503 and "FXSIM_DASH_PASS" in r.json()["detail"]
    monkeypatch.setattr(srv, "_DASH_PASS", "s3cret")
    assert client.get("/api/config", auth=("admin", "s3cret")).status_code == 200


def test_backtest_request_cannot_mutate_process_settings(monkeypatch):
    monkeypatch.setattr(srv, "_DASH_PASS", "")
    monkeypatch.setattr(srv, "_TUNNEL_TOKEN", "")
    before = srv.settings.granularity
    def _boom(*a, **k):
        raise RuntimeError("stub: never runs a real backtest in this test")
    monkeypatch.setattr(srv, "run_backtest", _boom)
    client.post("/api/backtest", json={"granularity": "M15", "provider": "sample", "bars": 300})
    assert srv.settings.granularity == before        # untouched by the request


def test_backtest_rejects_live_broker_provider(monkeypatch):
    monkeypatch.setattr(srv, "_DASH_PASS", "")
    monkeypatch.setattr(srv, "_TUNNEL_TOKEN", "")
    r = client.post("/api/backtest", json={"provider": "oanda", "bars": 300})
    assert r.status_code == 400


def test_backtest_bars_are_clamped(monkeypatch):
    monkeypatch.setattr(srv, "_DASH_PASS", "")
    monkeypatch.setattr(srv, "_TUNNEL_TOKEN", "")
    seen = {}

    class _P:
        def history(self, inst, gran, bars):
            seen["bars"] = bars
            return []
    monkeypatch.setattr(srv, "get_provider", lambda name=None: _P())
    r = client.post("/api/backtest", json={"provider": "sample", "bars": 10_000_000})
    assert seen["bars"] == srv.MAX_BACKTEST_BARS and r.status_code == 400   # 400: no candles


# ---- round-7: the phone page must not show a green dot for a dead brain ----

def test_api_live_reports_stalled_when_the_brain_heartbeat_is_old(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "_DASH_PASS", ""); monkeypatch.setattr(srv, "_TUNNEL_TOKEN", "")
    import time
    from app import bridge
    monkeypatch.setattr(bridge, "common_files_dir", lambda: tmp_path)
    (tmp_path / bridge.SIGNAL_FILE).write_text("FLAT 0.00 SEQ 1 EXP 2\n")
    old = time.time() - 68 * 3600
    import os
    os.utime(tmp_path / bridge.SIGNAL_FILE, (old, old))
    monkeypatch.setattr(srv.db, "latest_live_run_id", lambda kind=None: 1)
    monkeypatch.setattr(srv.db, "get_run", lambda rid: {"id": 1, "instrument": "USD_JPY",
                                                        "granularity": "H1", "ended_at": None,
                                                        "initial_balance": 272000.0})
    for fn in ("load_equity", "list_trades", "load_adjustments"):
        monkeypatch.setattr(srv.db, fn, lambda *a, **k: [])
    monkeypatch.setattr(srv, "_recent_decisions", lambda rid: [])
    monkeypatch.setattr(srv, "_latest_holdings", lambda rid: [])
    monkeypatch.setattr(bridge, "read_status", lambda *a, **k: None)
    d = client.get("/api/live?kind=fx").json()
    assert d["status"] == "stalled"
    assert d["health"]["healthy"] is False and "脳の心拍" in d["health"]["why"]
