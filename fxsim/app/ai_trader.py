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
You are a disciplined, risk-first FX portfolio manager trading {instrument} on a \
daily horizon. Decide the target position for the account below.

Use web search NOW to check, for USD and JPY:
  - the latest economic releases in the past ~5 days (ACTUAL vs forecast: e.g. \
Nonfarm Payrolls, CPI/PCE, unemployment, GDP, retail sales, ISM/PMI, BOJ/Fed),
  - any central-bank guidance or market-moving headlines,
  - what high-impact events are scheduled in the next ~3 days.

Then weigh that macro picture together with the TECHNICAL STATE and the CURRENT
POSITION, and choose:
  - action: "long", "short", or "flat" (stand aside / close),
  - conviction: 0.0-1.0 (how strongly; this scales position size),
  - reason: one or two sentences, IN JAPANESE, citing the concrete data (e.g.
    "5月の米雇用統計は172k（予想85k）と大幅上振れ。利上げ観測が…"),
  - factors: 2-5 short JAPANESE bullet strings naming the key drivers (with the
    actual numbers/events you found),
  - plan: ONE JAPANESE sentence on how long / under what condition you'd hold or
    exit this (e.g. "6/16のBOJ会合まで保有、159.0(SMA50)割れで撤退").

Principles:
  - Avoiding bad trades matters more than catching every move. If the macro and
    technicals conflict or it's a coin-flip, choose "flat" or low conviction.
  - Prefer HOLDING the current position unless there is a clear reason to change
    (avoid churn / overtrading).
  - Don't take a fresh directional bet into an imminent high-impact release;
    wait for the result unless already positioned with conviction.
  - You may go short when the macro genuinely favours JPY strength / USD weakness.

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
              min_lot: float = 0.01) -> float:
    """Convert an AI decision into MT5 lots within the hard risk cap.

    risk_used = max_risk * conviction * brake   (brake<1 after drawdowns)
    units = balance * risk_used / stop_distance ; lots = units / 100k (capped).
    """
    if action == "flat" or conviction <= 0 or balance <= 0:
        return 0.0
    stop = max(atr * 1.5, pip * 5)
    risk_used = max_risk * max(0.0, min(1.0, conviction)) * max(0.0, min(1.0, brake))
    units = (balance * risk_used) / stop
    lots = min(units / UNITS_PER_LOT, max_lots)
    lots = round(lots / min_lot) * min_lot
    return lots if lots >= min_lot else 0.0
