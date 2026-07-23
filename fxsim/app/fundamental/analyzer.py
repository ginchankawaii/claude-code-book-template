"""Fundamental analysis: turn macro news into a directional bias per pair.

Three interchangeable backends (FXSIM_FUND_MODE):

  stub       neutral – always 0 bias (used by tests / pure-technical runs).
  file       reads data/fundamental.json. This is the default and is designed
             so Claude (the agent) — or the `anthropic` backend below — can drop
             fresh views in without the trading loop needing live network.
  anthropic  calls the Claude API with the web-search tool to read current FX
             news and emit a structured bias. Requires ANTHROPIC_API_KEY and the
             api.anthropic.com host to be allow-listed.

A "bias" is a float in [-1, 1] for the BASE currency vs the QUOTE currency
(e.g. for USD_JPY, +1 = very bullish USD/JPY). Views carry an `asof` timestamp
and decay linearly to zero over `half_life_hours * 2` so stale news stops
driving trades.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config import DATA_DIR, settings

FUND_FILE = DATA_DIR / "fundamental.json"


@dataclass
class FundamentalView:
    instrument: str
    bias: float                      # [-1, 1]
    reason: str = ""
    asof: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    half_life_hours: float = 24.0

    def decayed_bias(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        asof = self.asof if self.asof.tzinfo else self.asof.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - asof).total_seconds() / 3600.0)
        span = max(1e-6, self.half_life_hours * 2)
        factor = max(0.0, 1.0 - age_h / span)
        return float(self.bias * factor)


class Analyzer:
    def view(self, instrument: str, now: datetime | None = None) -> FundamentalView:
        raise NotImplementedError


class StubAnalyzer(Analyzer):
    def view(self, instrument: str, now: datetime | None = None) -> FundamentalView:
        return FundamentalView(instrument, 0.0, "stub: neutral", now or datetime.now(timezone.utc))


class FileAnalyzer(Analyzer):
    """Reads cached views written by Claude or the anthropic backend."""

    def __init__(self, path: Path = FUND_FILE) -> None:
        self.path = path

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def view(self, instrument: str, now: datetime | None = None) -> FundamentalView:
        data = self._load().get(instrument)
        if not data:
            return FundamentalView(instrument, 0.0, "no fundamental view on file", now)
        asof_raw = data.get("asof")
        asof = (
            datetime.fromisoformat(asof_raw)
            if asof_raw
            else datetime.now(timezone.utc)
        )
        return FundamentalView(
            instrument=instrument,
            bias=float(data.get("bias", 0.0)),
            reason=str(data.get("reason", "")),
            asof=asof,
            half_life_hours=float(data.get("half_life_hours", 24.0)),
        )


class AnthropicAnalyzer(Analyzer):
    """Uses the Claude API + web search to read live FX news.

    Results are cached to the file backend so the trading loop and the
    dashboard can read them without repeated API calls.
    """

    PROMPT = (
        "You are an FX macro analyst. Research the very latest news, central-bank "
        "policy, rate expectations and economic data relevant to the currency pair "
        "{pair}. Decide a short-term (next 1-3 days) directional bias for the pair.\n\n"
        "Respond with ONLY a JSON object: {{\"bias\": <float -1..1, + = base "
        "currency strengthens vs quote>, \"reason\": <one sentence>, "
        "\"half_life_hours\": <int>}}."
    )

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.anthropic_model

    def view(self, instrument: str, now: datetime | None = None) -> FundamentalView:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("anthropic package not installed") from exc
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set for fundamental_mode=anthropic")

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        pair = instrument.replace("_", "/")
        resp = client.messages.create(
            model=self.model,
            max_tokens=1024,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{"role": "user", "content": self.PROMPT.format(pair=pair)}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        bias, reason, hl = _parse_json_bias(text)
        view = FundamentalView(instrument, bias, reason, now or datetime.now(timezone.utc), hl)
        _cache_view(view)
        return view


def _parse_json_bias(text: str) -> tuple[float, str, float]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return 0.0, "could not parse model output", 24.0
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return 0.0, "invalid json from model", 24.0
    bias = max(-1.0, min(1.0, float(obj.get("bias", 0.0))))
    return bias, str(obj.get("reason", "")), float(obj.get("half_life_hours", 24.0))


def _cache_view(view: FundamentalView) -> None:
    data = {}
    if FUND_FILE.exists():
        try:
            data = json.loads(FUND_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    data[view.instrument] = {
        "bias": view.bias,
        "reason": view.reason,
        "asof": view.asof.isoformat(),
        "half_life_hours": view.half_life_hours,
    }
    FUND_FILE.write_text(json.dumps(data, indent=2))


def get_analyzer(mode: str | None = None) -> Analyzer:
    mode = (mode or settings.fundamental_mode).lower()
    if mode == "stub":
        return StubAnalyzer()
    if mode == "file":
        return FileAnalyzer()
    if mode == "anthropic":
        return AnthropicAnalyzer()
    raise ValueError(f"Unknown fundamental mode: {mode!r}")
