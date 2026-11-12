import pytest
from app.ai_trader import AIDecision, _parse, size_lots


def test_parse_valid():
    d = _parse('here is my call ```json\n{"action":"short","conviction":0.7,'
               '"reason":"weak US data","factors":["NFP miss","USD soft"]}\n``` done')
    assert d.action == "short" and abs(d.conviction - 0.7) < 1e-9
    assert "NFP miss" in d.factors


def test_parse_invalid_is_flat():
    assert _parse("no json here").action == "flat"
    assert _parse('{"action":"banana","conviction":2}').action == "flat"  # bad action -> flat


def test_parse_clamps_conviction():
    assert _parse('{"action":"long","conviction":5}').conviction == 1.0
    assert _parse('{"action":"long","conviction":-1}').conviction == 0.0


def test_size_flat_is_zero():
    assert size_lots("flat", 1.0, 3_000_000, 1.0, 0.01, 0.05, 5.0) == 0.0
    assert size_lots("long", 0.0, 3_000_000, 1.0, 0.01, 0.05, 5.0) == 0.0


def test_size_scales_with_conviction():
    full = size_lots("long", 1.0, 3_000_000, 1.0, 0.01, 0.05, 5.0)
    half = size_lots("long", 0.5, 3_000_000, 1.0, 0.01, 0.05, 5.0)
    assert full > 0 and abs(half - full / 2) < 0.02     # ~half the size


def test_size_respects_brake_and_cap():
    base = size_lots("long", 1.0, 3_000_000, 1.0, 0.01, 0.05, 5.0)
    braked = size_lots("long", 1.0, 3_000_000, 1.0, 0.01, 0.05, 5.0, brake=0.5)
    assert braked < base
    capped = size_lots("long", 1.0, 3_000_000, 0.001, 0.01, 0.05, 0.10)  # tiny stop -> huge units
    assert capped == 0.10                                 # hard max-lots cap


def test_a_rate_limited_consult_never_sleeps_on_retry_after(tmp_path, monkeypatch):
    """Round-10B: anthropic 1.x sleeps for the server's retry-after with no cap
    before retrying, so with max_retries=1 one 429 could hold the single-
    threaded trading loop — and its heartbeat — for as long as the server
    asked. Driven against a LOCAL fake endpoint (no real API call, no key): a
    429 asking for an hour must come back at once as 'unavailable', on all
    three FX-side call sites."""
    import http.server
    import threading
    import time as _t

    import anthropic  # noqa: F401  (the pinned SDK must be importable)

    hits = []

    class _H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            self.rfile.read(int(self.headers.get("content-length") or 0))
            body = b'{"type":"error","error":{"type":"rate_limit_error","message":"slow down"}}'
            self.send_response(429)
            self.send_header("retry-after", "3600")
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    slept = []          # recorded, not performed: a regression must not hang the suite
    monkeypatch.setattr(_t, "sleep", lambda s: slept.append(s))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    from app import ai_trader as A, events as E
    from app.config import settings as S
    monkeypatch.setattr(S, "anthropic_api_key", "sk-test-not-a-key", raising=False)
    monkeypatch.setattr(A.default_settings, "anthropic_api_key", "sk-test-not-a-key", raising=False)
    monkeypatch.setattr(E, "CALENDAR_FILE", tmp_path / "calendar.json")
    try:
        t0 = _t.monotonic()
        d = A.AITrader(model="claude-sonnet-4-6").decide({"instrument": "USD_JPY"})
        assert not d.ok and _t.monotonic() - t0 < 10
        t0 = _t.monotonic()
        E.AnthropicCalendar(model="claude-sonnet-4-6").fetch({"USD", "JPY"})
        assert _t.monotonic() - t0 < 10
        from app.fundamental import analyzer as F
        monkeypatch.setattr(F.settings, "anthropic_api_key", "sk-test-not-a-key", raising=False)
        t0 = _t.monotonic()
        with pytest.raises(Exception, match="429|rate"):
            F.AnthropicAnalyzer(model="claude-sonnet-4-6").view("USD_JPY")
        assert _t.monotonic() - t0 < 10
    finally:
        srv.shutdown()
    assert len(hits) == 3, hits                 # one request per call site: no SDK retry
    assert not [s for s in slept if s > 5], slept   # and no wait on the retry-after
