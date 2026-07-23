"""Economic calendar — scheduled, high-impact events known *in advance*.

FX moves violently around scheduled releases (FOMC, BOJ, CPI, NFP, employment)
and central-bank / 要人 (key official) speeches. A purely technical system walks
into these blind and gets stopped out on the spike. This module gives the
decision layer *forward* knowledge of what is coming and when, so it can:

  * stand aside (no new risk) just before/after a high-impact event, and
  * let the AI decider reason about event risk explicitly.

Backends (FXSIM_CALENDAR_MODE):
  stub       no events — pure-technical behaviour / tests.
  file       data/calendar.json — the default. Claude (the agent) or the
             `anthropic` backend writes upcoming events here; the trading loop
             reads them with no live network.
  anthropic  Claude API + web search compiles the upcoming calendar and caches
             it to the file backend. Requires ANTHROPIC_API_KEY and an
             allow-listed api.anthropic.com.

Times are timezone-aware UTC. An event's `currency` (e.g. "USD", "JPY") is
matched against the two legs of an instrument ("USD_JPY" -> {USD, JPY}).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_DIR, settings

CALENDAR_FILE = DATA_DIR / "calendar.json"

_HIGH_TOKENS = {"high", "3", "red", "high impact", "★★★", "h"}


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def instrument_currencies(instrument: str) -> set[str]:
    return {p.upper() for p in instrument.split("_") if p}


@dataclass
class EconomicEvent:
    time: datetime
    currency: str
    title: str
    impact: str = "medium"            # "high" | "medium" | "low"
    forecast: str = ""
    previous: str = ""
    actual: str = ""

    def __post_init__(self) -> None:
        self.time = _as_utc(self.time)
        self.currency = self.currency.upper()

    @property
    def is_high(self) -> bool:
        return self.impact.strip().lower() in _HIGH_TOKENS

    def minutes_until(self, now: datetime) -> float:
        """Signed minutes: positive = still ahead, negative = already passed."""
        return (self.time - _as_utc(now)).total_seconds() / 60.0

    def to_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "currency": self.currency,
            "title": self.title,
            "impact": self.impact,
            "forecast": self.forecast,
            "previous": self.previous,
            "actual": self.actual,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EconomicEvent":
        raw_t = d.get("time") or d.get("datetime") or d.get("date")
        t = datetime.fromisoformat(str(raw_t).replace("Z", "+00:00"))
        return cls(
            time=t,
            currency=str(d.get("currency", d.get("ccy", ""))),
            title=str(d.get("title", d.get("event", ""))),
            impact=str(d.get("impact", "medium")),
            forecast=str(d.get("forecast", "")),
            previous=str(d.get("previous", "")),
            actual=str(d.get("actual", "")),
        )


@dataclass
class EconomicCalendar:
    events: list[EconomicEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.events = sorted(self.events, key=lambda e: e.time)

    def for_instrument(self, instrument: str) -> list[EconomicEvent]:
        ccys = instrument_currencies(instrument)
        return [e for e in self.events if e.currency in ccys]

    def upcoming(
        self, instrument: str, now: datetime, within_hours: float = 48.0,
        limit: int | None = None,
    ) -> list[EconomicEvent]:
        horizon = within_hours * 60.0
        evs = [
            e for e in self.for_instrument(instrument)
            if 0.0 <= e.minutes_until(now) <= horizon
        ]
        return evs[:limit] if limit else evs

    def imminent_high_impact(
        self, instrument: str, now: datetime, window_min: float,
    ) -> EconomicEvent | None:
        """Nearest high-impact event whose time is within +/- window_min of now
        (covers both the run-up to, and the volatile minutes after, a release)."""
        cands = [
            e for e in self.for_instrument(instrument)
            if e.is_high and abs(e.minutes_until(now)) <= window_min
        ]
        if not cands:
            return None
        return min(cands, key=lambda e: abs(e.minutes_until(now)))

    def next_high_impact(
        self, instrument: str, now: datetime,
    ) -> EconomicEvent | None:
        ahead = [
            e for e in self.for_instrument(instrument)
            if e.is_high and e.minutes_until(now) >= 0
        ]
        return ahead[0] if ahead else None

    def summary(
        self, instrument: str, now: datetime, within_hours: float = 48.0,
        limit: int = 8,
    ) -> list[dict]:
        """Compact, AI-friendly list of what's coming."""
        out = []
        for e in self.upcoming(instrument, now, within_hours, limit):
            out.append({
                "in_minutes": round(e.minutes_until(now)),
                "currency": e.currency,
                "title": e.title,
                "impact": e.impact,
                "forecast": e.forecast,
                "previous": e.previous,
            })
        return out


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #
def _load_file(path: Path = CALENDAR_FILE) -> EconomicCalendar:
    if not path.exists():
        return EconomicCalendar([])
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return EconomicCalendar([])
    items = raw.get("events", raw) if isinstance(raw, dict) else raw
    events: list[EconomicEvent] = []
    for it in items or []:
        try:
            events.append(EconomicEvent.from_dict(it))
        except (ValueError, TypeError, KeyError):
            continue
    return EconomicCalendar(events)


def _cache_events(events: list[EconomicEvent], path: Path = CALENDAR_FILE) -> None:
    path.write_text(json.dumps({"events": [e.to_dict() for e in events]}, indent=2))


class AnthropicCalendar:
    """Compiles the upcoming high-impact calendar via Claude + web search.

    The result is cached to data/calendar.json so the trading loop and dashboard
    read it without repeated API calls. Falls back to the file backend on any
    error so a network/key problem never stops trading.
    """

    PROMPT = (
        "You are an FX economic-calendar assistant. Using web search, list the "
        "scheduled, market-moving economic events and central-bank / official "
        "speeches over the NEXT 7 DAYS for these currencies: {ccys}. Include "
        "regular releases (CPI, employment, GDP, PMIs, rate decisions) and known "
        "speeches.\n\n"
        "Respond with ONLY a JSON array; each element: {{\"time\": <ISO-8601 UTC>, "
        "\"currency\": <e.g. USD>, \"title\": <short>, \"impact\": "
        "<\"high\"|\"medium\"|\"low\">, \"forecast\": <str or \"\">, "
        "\"previous\": <str or \"\">}}."
    )

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.decision_model

    def fetch(self, currencies: set[str]) -> EconomicCalendar:
        try:
            import anthropic
        except ImportError:
            return _load_file()
        if not settings.anthropic_api_key:
            return _load_file()
        try:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            resp = client.messages.create(
                model=self.model,
                max_tokens=2048,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
                messages=[{
                    "role": "user",
                    "content": self.PROMPT.format(ccys=", ".join(sorted(currencies))),
                }],
            )
            text = "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text"
            )
            events = _parse_events_json(text)
            if events:
                _cache_events(events)
                return EconomicCalendar(events)
        except Exception:  # pragma: no cover - network/SDK issues
            pass
        return _load_file()


def _parse_events_json(text: str) -> list[EconomicEvent]:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        arr = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    out: list[EconomicEvent] = []
    for it in arr:
        try:
            out.append(EconomicEvent.from_dict(it))
        except (ValueError, TypeError, KeyError):
            continue
    return out


def get_calendar(mode: str | None = None, instrument: str | None = None) -> EconomicCalendar:
    mode = (mode or settings.calendar_mode).lower()
    if mode == "stub":
        return EconomicCalendar([])
    if mode == "file":
        return _load_file()
    if mode == "anthropic":
        ccys = instrument_currencies(instrument) if instrument else {"USD", "JPY"}
        return AnthropicCalendar().fetch(ccys)
    raise ValueError(f"Unknown calendar mode: {mode!r}")
