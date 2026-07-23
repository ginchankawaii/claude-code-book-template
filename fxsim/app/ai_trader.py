"""AI trader — Opus weighs real economic releases + technicals and decides.

This is the "discretionary AI portfolio manager" the brief asks for: not a
mechanical formula, but Claude Opus considering the actual macro picture (US/JP
economic releases vs forecast, central-bank tone, market-moving news — fetched
live via web search) together with the technical state and current position,
then choosing direction AND leverage (size via conviction) and managing exits.

Used at "key moments" only (daily + just after high-impact releases), so the
Opus + web-search cost is spent where it matters. Hard risk caps live in the
caller; Opus sizes within them via a 0..1 conviction.

Falls back to FLAT (stand aside) on any API/parse error — never crashes the loop.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from .config import settings as default_settings


@dataclass
class AIDecision:
    action: str          # "long" | "short" | "flat"
    conviction: float    # 0..1 (drives leverage within the hard cap)
    reason: str
    factors: list        # short bullet list of what drove it
    plan: str = ""       # hold/exit plan in plain language (when/why to change)
    raw: str = ""
    ok: bool = True      # False = error/no-key fallback (caller should HOLD, not act)

    @classmethod
    def flat(cls, why: str) -> "AIDecision":
        return cls("flat", 0.0, why, [], "", "", ok=False)


PROMPT = """\
You are the risk officer for a VALIDATED systematic strategy on {instrument}: it is
long-only-or-flat, enters when price is above its ~100-day trend average, holds for
weeks-to-months, and always carries a hard protective stop. The system currently
wants to be LONG. Your ONLY job is to confirm that entry, or veto it.

Know the asymmetry before you answer: this strategy's entire 11-year profit comes
from a handful of long-held trends. A vetoed entry that runs away is UNBOUNDED
opportunity cost; a bad entry is BOUNDED by the stop (~1-2% of equity). Routine
uncertainty — mixed data, a scheduled event in the calendar, overbought readings,
"no clear direction" — is the system's normal operating weather and is NOT a veto
reason. Veto ONLY for exceptional, concrete, imminent danger the system cannot see,
e.g. capital controls, an actually-announced intervention, a market dislocation in
progress.

Use web search NOW to check, for USD and JPY: the latest economic releases (ACTUAL
vs forecast), central-bank guidance, market-moving headlines, and what high-impact
events are scheduled in the next ~3 days.

Note the context JSON below states its bar timeframe — the SMA/momentum fields are
measured in BARS of that timeframe, not days.

Respond with:
  - action: "long" (confirm — the default) or "flat" (veto; exceptional cases only),
  - conviction: 0.0-1.0 sizing hint for a confirmed entry (0.6 = normal; below 0.4
    only with concrete negative evidence; this scales position size),
  - reason: one or two sentences, IN JAPANESE, citing the concrete data,
  - factors: 2-5 short JAPANESE bullet strings naming the key drivers (with the
    actual numbers/events you found),
  - plan: ONE JAPANESE sentence on what would change your assessment.

CONTEXT (JSON):
{context}

Respond with ONLY a JSON object:
{{"action": "...", "conviction": 0.0, "reason": "...(日本語)", \
"factors": ["...(日本語)", "..."], "plan": "...(日本語)"}}
"""


class AITrader:
    def __init__(self, model: Optional[str] = None, max_web_uses: int = 6) -> None:
        self.model = model or default_settings.decision_model  # claude-opus-4-8
        self.max_web_uses = max_web_uses

    def decide(self, context: dict) -> AIDecision:
        try:
            import anthropic
        except ImportError:
            return AIDecision.flat("anthropic SDK not installed")
        if not default_settings.anthropic_api_key:
            return AIDecision.flat("ANTHROPIC_API_KEY not set")
        try:
            client = anthropic.Anthropic(api_key=default_settings.anthropic_api_key)
            resp = client.messages.create(
                model=self.model,
                max_tokens=2048,
                tools=[{"type": "web_search_20250305", "name": "web_search",
                        "max_uses": self.max_web_uses}],
                messages=[{"role": "user", "content": PROMPT.format(
                    instrument=context.get("instrument", "USD_JPY"),
                    context=json.dumps(context, ensure_ascii=False, default=str),
                )}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return _parse(text)
        except Exception as exc:  # pragma: no cover - network/SDK
            return AIDecision.flat(f"AI error: {exc}")


def _parse(text: str) -> AIDecision:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return AIDecision.flat("unparseable model output")
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return AIDecision.flat("invalid json from model")
    action = str(obj.get("action", "flat")).lower()
    if action not in ("long", "short", "flat"):
        action = "flat"
    try:
        conv = max(0.0, min(1.0, float(obj.get("conviction", 0.0))))
    except (TypeError, ValueError):
        conv = 0.0
    factors = obj.get("factors") or []
    if not isinstance(factors, list):
        factors = [str(factors)]
    return AIDecision(action, conv, str(obj.get("reason", "")),
                      [str(f) for f in factors], str(obj.get("plan", "")), text)


UNITS_PER_LOT = 100_000.0


def size_lots(action: str, conviction: float, balance: float, atr: float, pip: float,
              max_risk: float, max_lots: float, brake: float = 1.0,
              min_lot: float = 0.01, price: float = 0.0,
              max_leverage: float = 0.0) -> float:
    """Convert an AI decision into MT5 lots within the hard risk cap.

    risk_used = max_risk * conviction * brake   (brake<1 after drawdowns)
    units = balance * risk_used / stop_distance ; lots = units / 100k (capped).

    When price and max_leverage are given, also cap notional (lots * 100k * price)
    at max_leverage * balance — the same hard leverage ceiling the engine applies.
    """
    if action == "flat" or conviction <= 0 or balance <= 0:
        return 0.0
    stop = max(atr * 1.5, pip * 5)
    risk_used = max_risk * max(0.0, min(1.0, conviction)) * max(0.0, min(1.0, brake))
    units = (balance * risk_used) / stop
    lots = min(units / UNITS_PER_LOT, max_lots)
    if max_leverage > 0 and price > 0:
        lots = min(lots, max_leverage * balance / (price * UNITS_PER_LOT))
    lots = round(lots / min_lot) * min_lot
    return lots if lots >= min_lot else 0.0
