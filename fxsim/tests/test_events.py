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
