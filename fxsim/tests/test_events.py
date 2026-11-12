from datetime import datetime, timedelta, timezone

from app.events import EconomicCalendar, EconomicEvent, instrument_currencies

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


def _cal():
    return EconomicCalendar([
        EconomicEvent(NOW + timedelta(minutes=30), "USD", "CPI", "high"),
        EconomicEvent(NOW + timedelta(hours=5), "USD", "Fed speak", "medium"),
        EconomicEvent(NOW + timedelta(hours=20), "JPY", "BOJ Rate", "high"),
        EconomicEvent(NOW - timedelta(days=2), "USD", "Old NFP", "high"),
        EconomicEvent(NOW + timedelta(hours=2), "EUR", "ECB", "high"),  # not in USD_JPY
    ])


def test_instrument_currencies():
    assert instrument_currencies("USD_JPY") == {"USD", "JPY"}


def test_for_instrument_filters_by_currency():
    titles = {e.title for e in _cal().for_instrument("USD_JPY")}
    assert "ECB" not in titles
    assert {"CPI", "Fed speak", "BOJ Rate", "Old NFP"} <= titles


def test_upcoming_excludes_past_and_far():
    up = _cal().upcoming("USD_JPY", NOW, within_hours=6)
    titles = [e.title for e in up]
    assert "CPI" in titles and "Fed speak" in titles
    assert "BOJ Rate" not in titles      # beyond 6h
    assert "Old NFP" not in titles       # in the past


def test_imminent_high_impact_blackout_window():
    cal = _cal()
    # CPI is +30m, blackout window 60m -> caught
    ev = cal.imminent_high_impact("USD_JPY", NOW, window_min=60)
    assert ev is not None and ev.title == "CPI"
    # tiny window -> nothing imminent
    assert cal.imminent_high_impact("USD_JPY", NOW, window_min=10) is None
    # medium-impact "Fed speak" must never trigger a high-impact blackout:
    # at +5h the only nearby event is the medium one, so nothing is imminent.
    near_fed = NOW + timedelta(hours=5)
    assert cal.imminent_high_impact("USD_JPY", near_fed, window_min=20) is None


def test_next_high_impact_and_minutes():
    nxt = _cal().next_high_impact("USD_JPY", NOW)
    assert nxt.title == "CPI"
    assert abs(nxt.minutes_until(NOW) - 30.0) < 1e-6


def test_summary_shape():
    s = _cal().summary("USD_JPY", NOW, within_hours=24)
    assert s and all({"in_minutes", "currency", "title", "impact"} <= set(d) for d in s)


def test_anthropic_calendar_skips_paid_refresh_when_cache_is_fresh(tmp_path, monkeypatch):
    # A restart storm burned 810 paid web-search calls in two days because
    # fetch() never checked the cache age. A fresh cache must short-circuit
    # BEFORE any SDK/API access.
    import app.events as E
    fresh = tmp_path / "calendar.json"
    fresh.write_text('[{"time": "2026-08-20T12:30:00+00:00", "currency": "USD", '
                     '"title": "CPI", "impact": "high"}]')
    monkeypatch.setattr(E, "CALENDAR_FILE", fresh)
    monkeypatch.setattr(E.settings, "anthropic_api_key", "sk-test")

    import builtins
    real_import = builtins.__import__

    def bomb(name, *a, **k):
        if name == "anthropic":
            raise AssertionError("paid path touched despite fresh cache")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", bomb)

    cal = E.AnthropicCalendar().fetch({"USD", "JPY"})
    assert any(e.title == "CPI" for e in cal.events)


def test_paid_refresh_is_gated_on_the_ATTEMPT_not_the_success(tmp_path, monkeypatch):
    # The original gate only closed when a fetch SUCCEEDED and parsed. A
    # failing refresh (expired key, blocked network, unparseable reply) left
    # the cache old, so every container restart paid for another web search —
    # the exact storm the gate was added to stop (810 calls / ~8.6M tokens).
    from app import events as E
    cal_file = tmp_path / "calendar.json"
    monkeypatch.setattr(E, "CALENDAR_FILE", cal_file)
    monkeypatch.setattr(E.settings, "anthropic_api_key", "sk-test", raising=False)

    calls = {"n": 0}

    class _Boom:
        def __init__(self, *a, **k): pass
        @property
        def messages(self): return self
        def create(self, **k):
            calls["n"] += 1
            raise RuntimeError("API error / expired key")

    import sys, types
    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Boom
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    cal = E.AnthropicCalendar(model="m")
    for _ in range(20):                       # 20 restarts in a row
        cal.fetch({"USD", "JPY"})
    assert calls["n"] == 1, f"a failing refresh billed {calls['n']} times, not 1"
    assert not cal_file.exists()              # nothing was ever cached


def test_a_malformed_calendar_file_never_raises(tmp_path, monkeypatch):
    """Round-10B: a null entry, a dict with no 'events' list or a Shift-JIS file
    raised AttributeError / UnicodeDecodeError out of the loader — at the start
    of the brain (before its lock, on every supervisor restart) and in its
    daily refresh. A bad calendar must load as fewer events, never as a crash,
    in both the 'file' mode and the default 'anthropic' mode without a key."""
    import app.events as E
    f = tmp_path / "calendar.json"
    monkeypatch.setattr(E, "CALENDAR_FILE", f)
    monkeypatch.setattr(E.settings, "anthropic_api_key", "", raising=False)
    good = '{"time": "2026-12-10T19:00:00Z", "currency": "USD", "title": "FOMC", "impact": "high"}'
    cases = {
        f'{{"events": [{good}, null]}}': 1,
        f'[{good}, "FOMC", 5, []]': 1,
        '{"updated": "2026-11-12", "items": []}': 0,
        '{"events": {"2026-11-13": []}}': 0,
        '{"events": 5}': 0,
        '["FOMC 2026-12-10"]': 0,
        '5': 0,
        '"text"': 0,
        'null': 0,
        '[{"time": "soon", "currency": "USD"}]': 0,
        '[{"time": null}]': 0,
        '{"events": [1, 2,]}': 0,                       # not JSON at all
    }
    for text, n in cases.items():
        f.write_text(text, encoding="utf-8")
        for mode in ("file", "anthropic"):
            cal = E.get_calendar(mode, "USD_JPY")
            assert len(cal.events) == n, (text, mode)
    f.write_bytes(("\ufeff[" + good + "]").encode("utf-8"))          # Notepad's UTF-8 BOM
    assert [e.title for e in E.get_calendar("file").events] == ["FOMC"]
    f.write_bytes('[{"time": "2026-12-10T19:00:00Z", "title": "日銀"}]'.encode("shift_jis"))
    assert E.get_calendar("file").events == []
    assert E._parse_events_json(f'text [{good}, null] text')[0].title == "FOMC"


def test_a_calendar_that_cannot_load_never_stops_the_brain(monkeypatch, capsys):
    from scripts import run_ai_bridge as R
    prev = EconomicCalendar([EconomicEvent(NOW, "USD", "CPI", "high")])

    def boom(*a, **k):
        raise AttributeError("'NoneType' object has no attribute 'get'")
    monkeypatch.setattr(R, "get_calendar", boom)
    assert R._safe_calendar("file", "USD_JPY").events == []
    assert R._safe_calendar("file", "USD_JPY", prev) is prev
    assert "calendar load failed" in capsys.readouterr().out


def test_a_calendar_file_that_goes_bad_keeps_the_calendar_already_loaded(tmp_path, monkeypatch):
    # review of dae5183: a file overwritten with {"events": null} or [null] at
    # 23:00 replaced the good in-memory calendar with an empty one at midnight
    import app.events as E
    from scripts import run_ai_bridge as R
    f = tmp_path / "calendar.json"
    monkeypatch.setattr(E, "CALENDAR_FILE", f)
    monkeypatch.setattr(E.settings, "anthropic_api_key", "", raising=False)
    f.write_text('[{"time": "2026-12-02T00:20:00Z", "currency": "USD", "title": "CPI", "impact": "high"}]')
    good = R._safe_calendar("file", "USD_JPY")
    assert [e.title for e in good.events] == ["CPI"] and not good.unreadable
    for bad in ('{"events": null}', '[null]', '{"items": []}', 'not json', '[{"time": "soon"}]'):
        f.write_text(bad)
        for mode in ("file", "anthropic"):
            assert R._safe_calendar(mode, "USD_JPY", good) is good, (bad, mode)
    f.write_text('[]')                                   # a valid, empty calendar is believed
    assert R._safe_calendar("file", "USD_JPY", good).events == []
    f.write_text('{"events": []}')
    assert R._safe_calendar("file", "USD_JPY", good).events == []
    f.unlink()                                           # no file at all: no events
    assert R._safe_calendar("file", "USD_JPY", good).events == []
