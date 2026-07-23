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
