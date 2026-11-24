"""AI decision layer — the holistic "portfolio manager".

This is the answer to "stop trading on mechanical technicals alone". Instead of
a fixed weighted average deciding trades, the technical readout becomes one
*input* among several, and a decider weighs them all together:

    technical features  ─┐
    fundamental view    ─┤→ DecisionContext →  Decider  →  Signal
    upcoming events      ┘                     (rule | anthropic)
    current time / risk

Two hard-wired, backend-independent risk controls live here (not in the decider)
so they always apply, even with the cheap offline backend:

  * EVENT BLACKOUT — within ``event_blackout_min`` minutes either side of a
    high-impact event, force flat: no new entries and (via the engine's exit
    threshold) existing positions are closed. This is the single biggest fix for
    "got stopped out on the news spike".
  * The decider only runs when we are *not* in a blackout, which also saves API
    calls in ``anthropic`` mode.

Deciders
  rule       deterministic & offline. Blends tech + fundamentals, halves
             conviction when they disagree, and trims conviction when a
             high-impact event is on the near horizon. Fully testable, no key.
  anthropic  Claude reads the same context as JSON and returns a structured
             {action, confidence, reason}. Falls back to the rule decider on any
             error, so live trading never crashes on a network/key problem.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from ..config import Settings, settings as default_settings
from ..events import EconomicCalendar, get_calendar
from ..models import Signal
from .base import Strategy
from .fundamental import FundamentalStrategy
from .technical import TechnicalStrategy
from .trend import TrendRegimeStrategy


@dataclass
class DecisionContext:
    instrument: str
    now: datetime
    price: float
    technical_score: float
    technical_components: dict
    fundamental_bias: float
    fundamental_reason: str
    upcoming_events: list[dict]
    minutes_to_high_impact: float | None
    w_tech: float
    w_fund: float
    event_caution_min: float
    entry_threshold: float = 0.20

    def to_payload(self) -> dict:
        return {
            "instrument": self.instrument,
            "asof_utc": self.now.isoformat(),
            "price": self.price,
            "technical": {
                "score": round(self.technical_score, 4),
                "components": {k: round(v, 4) for k, v in self.technical_components.items()},
            },
            "fundamental": {
                "bias": round(self.fundamental_bias, 4),
                "reason": self.fundamental_reason,
            },
            "minutes_to_next_high_impact": self.minutes_to_high_impact,
            "upcoming_events": self.upcoming_events,
        }


def _clamp(x: float) -> float:
    return float(max(-1.0, min(1.0, x)))


class Decider:
    name = "decider"

    def decide(self, ctx: DecisionContext, tech: Signal, fund: Signal) -> Signal:
        raise NotImplementedError


class RuleDecider(Decider):
    """Deterministic, offline stand-in for the AI — and the live fallback."""

    name = "rule"

    def decide(self, ctx: DecisionContext, tech: Signal, fund: Signal) -> Signal:
        # A neutral fundamental view should not dilute technical conviction.
        w_fund = ctx.w_fund if abs(fund.score) >= 1e-6 else 0.0
        total_w = ctx.w_tech + w_fund or 1.0
        score = (tech.score * ctx.w_tech + fund.score * w_fund) / total_w

        notes: list[str] = []
        # Conviction control: disagreement between the two pillars => half size.
        if w_fund > 0 and tech.score != 0 and (tech.score > 0) != (fund.score > 0):
            score *= 0.5
            notes.append("tech/fund disagree -> half size")
        elif w_fund > 0:
            notes.append("tech/fund aligned")
        else:
            notes.append("technical-led (no fundamental view)")

        # Pre-event caution: a high-impact release on the near horizon trims size.
        m = ctx.minutes_to_high_impact
        if m is not None and 0 <= m <= ctx.event_caution_min:
            score *= 0.6
            notes.append(f"high-impact event in {m:.0f}m -> trim")

        score = _clamp(score)
        direction = 1 if score > 0.05 else (-1 if score < -0.05 else 0)
        reason = (
            f"AI(rule): tech={tech.score:+.2f} fund={fund.score:+.2f} "
            f"=> {score:+.2f} [{'; '.join(notes)}]"
        )
        return Signal(
            direction=direction,
            score=score,
            reason=reason,
            components={
                "technical": tech.score,
                "fundamental": fund.score,
                "w_tech": ctx.w_tech,
                "w_fund": ctx.w_fund,
                "ai_score": score,
                "minutes_to_high_impact": m,
            },
        )


class AnthropicDecider(Decider):
    """Claude weighs technicals + fundamentals + the event calendar and decides."""

    name = "anthropic"

    PROMPT = (
        "You are a disciplined, risk-first FX portfolio manager paper-trading "
        "{instrument}. Weigh the technical readout, the fundamental/news bias, and "
        "the UPCOMING ECONOMIC EVENTS together. Prefer standing aside to taking a "
        "low-conviction or event-exposed trade — avoiding bad trades matters more "
        "than catching every move.\n\n"
        "CONTEXT (JSON):\n{payload}\n\n"
        "Respond with ONLY a JSON object: {{\"action\": \"long\"|\"short\"|\"flat\", "
        "\"confidence\": <0..1>, \"reason\": <one sentence>}}."
    )

    def __init__(self, model: str | None = None) -> None:
        self.model = model or default_settings.decision_model
        self._fallback = RuleDecider()

    def decide(self, ctx: DecisionContext, tech: Signal, fund: Signal) -> Signal:
        try:
            import anthropic
        except ImportError:
            return self._fallback.decide(ctx, tech, fund)
        if not default_settings.anthropic_api_key:
            return self._fallback.decide(ctx, tech, fund)
        try:
            client = anthropic.Anthropic(api_key=default_settings.anthropic_api_key)
            resp = client.messages.create(
                model=self.model,
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": self.PROMPT.format(
                        instrument=ctx.instrument,
                        payload=json.dumps(ctx.to_payload(), default=str),
                    ),
                }],
            )
            text = "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text"
            )
            action, confidence, reason = _parse_decision(text)
        except Exception:  # pragma: no cover - network/SDK issues
            return self._fallback.decide(ctx, tech, fund)

        direction = {"long": 1, "short": -1, "flat": 0}.get(action, 0)
        score = _clamp(confidence * direction)
        return Signal(
            direction=direction,
            score=score,
            reason=f"AI(claude): {reason}",
            components={
                "technical": tech.score,
                "fundamental": fund.score,
                "ai_action": action,
                "ai_confidence": confidence,
                "minutes_to_high_impact": ctx.minutes_to_high_impact,
            },
        )


def _parse_decision(text: str) -> tuple[str, float, str]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return "flat", 0.0, "unparseable model output"
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return "flat", 0.0, "invalid json from model"
    action = str(obj.get("action", "flat")).lower()
    if action not in {"long", "short", "flat"}:
        action = "flat"
    try:
        confidence = max(0.0, min(1.0, float(obj.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return action, confidence, str(obj.get("reason", ""))


class HybridDecider(Decider):
    """Free rule decider by default; consult Claude only on the bars that matter.

    Claude is asked for a view ONLY when one of these triggers fires (everything
    else is decided for free by the rule decider):
      * the rule signal is actionable — would open or reverse a position;
      * conviction is borderline (just under the entry threshold) or the
        technical and fundamental pillars disagree;
      * a high-impact event is on the near horizon (caution window).

    When consulted, Claude is a RISK-FIRST GATE with veto power only — it can
    stand the trade down or shrink it, but never amplify it or flip its side:
      * Claude flat            -> stand aside (veto);
      * Claude opposite to rule -> stand aside (don't chase either way);
      * Claude agrees           -> keep the rule's side, size = min(rule, Claude)
                                   so Claude can only reduce conviction.

    Memory: while the rule's view holds steady (same direction, same ~0.1 score
    bucket) and nothing material changes, the previous Claude verdict is reused
    instead of paying for another call. A fresh call is forced when the rule
    flips/changes bucket, the pillars start disagreeing, or a high-impact event
    enters the caution window — i.e. only at the meaningful turning points.
    """

    name = "hybrid"

    def __init__(self, claude: Decider | None = None, rule: Decider | None = None,
                 model: str | None = None, reuse: bool = True) -> None:
        self.rule = rule or RuleDecider()
        self.claude = claude or AnthropicDecider(model)
        self.reuse = reuse
        self._cache_fp: tuple | None = None
        self._cache_cl: Signal | None = None

    @staticmethod
    def _disagree(tech: Signal, fund: Signal) -> bool:
        return abs(fund.score) >= 1e-6 and tech.score != 0 and (tech.score > 0) != (fund.score > 0)

    @staticmethod
    def _near_event(ctx: DecisionContext) -> bool:
        m = ctx.minutes_to_high_impact
        return m is not None and 0 <= m <= ctx.event_caution_min

    def _should_consult(self, ctx: DecisionContext, tech: Signal, fund: Signal,
                        base: Signal) -> bool:
        et = ctx.entry_threshold
        # actionable: rule would open/reverse a position
        if abs(base.score) >= et and base.direction != 0:
            return True
        # borderline conviction just under the entry bar
        if et * 0.6 <= abs(base.score) < et:
            return True
        # technical vs fundamental disagreement
        if self._disagree(tech, fund):
            return True
        # high-impact event on the near horizon (blackout is handled upstream)
        if self._near_event(ctx):
            return True
        return False

    def decide(self, ctx: DecisionContext, tech: Signal, fund: Signal) -> Signal:
        base = self.rule.decide(ctx, tech, fund)
        if not self._should_consult(ctx, tech, fund, base):
            base.components["consulted_claude"] = False
            return base

        # Reuse the cached Claude verdict while the situation is unchanged,
        # forcing a fresh call only at meaningful turning points.
        fp = (base.direction, round(base.score, 1))
        must_refresh = (
            not self.reuse
            or self._cache_cl is None
            or fp != self._cache_fp
            or self._disagree(tech, fund)
            or self._near_event(ctx)
        )
        if must_refresh:
            cl = self.claude.decide(ctx, tech, fund)
            self._cache_cl, self._cache_fp = cl, fp
            cached = False
        else:
            cl = self._cache_cl
            cached = True

        if cl.direction == 0:
            tag = "Claude veto -> stand aside"
            out = Signal.flat(f"hybrid: {tag} | {cl.reason}")
        elif cl.direction != base.direction:
            tag = "Claude disagrees with rule -> stand aside"
            out = Signal.flat(f"hybrid: {tag} | {cl.reason}")
        else:
            size = min(abs(base.score), abs(cl.score))  # Claude may only reduce
            out = Signal(
                direction=base.direction,
                score=size * base.direction,
                reason=f"hybrid: rule+Claude agree (size={size:.2f}) | {cl.reason}",
            )
        out.components = {
            **base.components,
            "consulted_claude": True,
            "claude_cached": cached,
            "rule_score": base.score,
            "claude_dir": cl.direction,
            "claude_score": cl.score,
        }
        return out


def get_decider(mode: str | None = None) -> Decider:
    mode = (mode or default_settings.decision_mode).lower()
    if mode == "rule":
        return RuleDecider()
    if mode == "anthropic":
        return AnthropicDecider()
    if mode == "hybrid":
        return HybridDecider()
    raise ValueError(f"Unknown decision mode: {mode!r}")


class AIDecisionStrategy(Strategy):
    """Event-aware, AI-driven strategy. Plugs into the engine like any Strategy."""

    name = "ai"

    def __init__(
        self,
        cfg: Settings | None = None,
        decision_mode: str | None = None,
        calendar_mode: str | None = None,
        fundamental_mode: str | None = None,
        calendar: EconomicCalendar | None = None,
        decider: Decider | None = None,
        technical: Strategy | None = None,
    ) -> None:
        self.cfg = cfg or default_settings
        # Technical base = the validated trend filter by default (the real edge);
        # the mechanical ensemble loses OOS and is kept only as a legacy option.
        if technical is not None:
            self.technical = technical
        elif (self.cfg.ai_base or "trend").lower() == "trend":
            self.technical = TrendRegimeStrategy(sma=self.cfg.trend_sma)
        else:
            self.technical = TechnicalStrategy()
        # cfg is authoritative when no explicit mode is passed (mirrors calendar).
        self.fundamental = FundamentalStrategy(fundamental_mode or self.cfg.fundamental_mode)
        self._calendar_mode = calendar_mode or self.cfg.calendar_mode
        self.calendar = calendar if calendar is not None else get_calendar(self._calendar_mode)
        self.decider = decider or get_decider(decision_mode)
        self.blackout_min = self.cfg.event_blackout_min
        self.caution_min = self.cfg.event_caution_min
        # exposed for weighting + persistence (mirrors CombinedStrategy)
        self.w_tech = self.cfg.technical_weight
        self.w_fund = self.cfg.fundamental_weight
        self.last_technical: Signal = Signal.flat()
        self.last_fundamental: Signal = Signal.flat()
        self.last_event = None

    def refresh(self, instrument: str) -> None:
        """Live hook: refresh both the news view and the event calendar."""
        try:
            self.fundamental.refresh(instrument)
        except Exception as exc:  # pragma: no cover - network/key issues
            print(f"[ai] fundamental refresh skipped: {exc}")
        try:
            self.calendar = get_calendar(self._calendar_mode, instrument)
        except Exception as exc:  # pragma: no cover
            print(f"[ai] calendar refresh skipped: {exc}")

    @staticmethod
    def _now(df: pd.DataFrame) -> datetime:
        if not len(df):
            return datetime.now(timezone.utc)
        t = df.iloc[-1]["time"]
        t = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

    def generate(self, instrument: str, df: pd.DataFrame) -> Signal:
        tech = self.technical.generate(instrument, df)
        fund = self.fundamental.generate(instrument, df)
        self.last_technical = tech
        self.last_fundamental = fund
        now = self._now(df)

        # HARD RISK CONTROL (backend-independent): stand aside around events.
        ev = self.calendar.imminent_high_impact(instrument, now, self.blackout_min)
        if ev is not None:
            self.last_event = ev
            mins = ev.minutes_until(now)
            when = f"in {mins:.0f}m" if mins >= 0 else f"{-mins:.0f}m ago"
            sig = Signal.flat(
                f"event blackout: {ev.currency} {ev.title} ({when}) — standing aside"
            )
            sig.components = {
                "event_blackout": True,
                "event": ev.title,
                "event_currency": ev.currency,
                "minutes": mins,
                "technical": tech.score,
                "fundamental": fund.score,
            }
            return sig
        self.last_event = None

        nxt = self.calendar.next_high_impact(instrument, now)
        minutes_to_high = nxt.minutes_until(now) if nxt is not None else None
        ctx = DecisionContext(
            instrument=instrument,
            now=now,
            price=float(df.iloc[-1]["close"]) if len(df) else 0.0,
            technical_score=tech.score,
            technical_components=tech.components,
            fundamental_bias=fund.score,
            fundamental_reason=fund.reason,
            upcoming_events=self.calendar.summary(instrument, now),
            minutes_to_high_impact=minutes_to_high,
            w_tech=self.w_tech,
            w_fund=self.w_fund,
            event_caution_min=self.caution_min,
            entry_threshold=self.cfg.entry_threshold,
        )
        return self.decider.decide(ctx, tech, fund)
