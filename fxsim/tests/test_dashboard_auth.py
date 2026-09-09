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
