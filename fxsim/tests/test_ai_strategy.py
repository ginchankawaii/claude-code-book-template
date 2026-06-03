from datetime import datetime, timedelta, timezone

import pandas as pd

from app.config import Settings
from app.events import EconomicCalendar, EconomicEvent
from app.indicators import candles_to_df, enrich
from app.models import Signal
from app.providers.sample import SampleProvider
from app.strategies.ai import (
    AIDecisionStrategy,
    Decider,
    DecisionContext,
    HybridDecider,
    RuleDecider,
)


class _FakeClaude(Decider):
    """Records calls and returns a fixed signal — no API."""

    def __init__(self, sig):
        self.sig = sig
        self.calls = 0

    def decide(self, ctx, tech, fund):
        self.calls += 1
        return self.sig


def _df(now=None, bars=120):
    candles = SampleProvider(seed=5).history("USD_JPY", "M15", bars)
    df = enrich(candles_to_df(candles))
    if now is not None:
        # rebase the timestamps so the last bar sits at `now`
        shift = now - df.iloc[-1]["time"]
        df["time"] = df["time"] + shift
    return df


def _ctx(minutes_to_high=None, tech=0.4, fund=0.4):
    return DecisionContext(
        instrument="USD_JPY", now=datetime.now(timezone.utc), price=150.0,
        technical_score=tech, technical_components={}, fundamental_bias=fund,
        fundamental_reason="", upcoming_events=[],
        minutes_to_high_impact=minutes_to_high, w_tech=0.6, w_fund=0.4,
        event_caution_min=360.0,
    )


# --- RuleDecider unit behaviour ------------------------------------------- #
def test_rule_decider_blends_aligned():
    sig = RuleDecider().decide(_ctx(tech=0.5, fund=0.5),
                               Signal(1, 0.5), Signal(1, 0.5))
    assert sig.direction == 1 and sig.score > 0


def test_rule_decider_halves_on_disagreement():
    agree = RuleDecider().decide(_ctx(tech=0.6, fund=0.6), Signal(1, 0.6), Signal(1, 0.6))
    disagree = RuleDecider().decide(_ctx(tech=0.6, fund=-0.6), Signal(1, 0.6), Signal(-1, -0.6))
    # disagreement should pull conviction toward zero vs the aligned case
    assert abs(disagree.score) < abs(agree.score)


def test_rule_decider_trims_before_event():
    far = RuleDecider().decide(_ctx(tech=0.6, fund=0.6, minutes_to_high=None),
                               Signal(1, 0.6), Signal(1, 0.6))
    near = RuleDecider().decide(_ctx(tech=0.6, fund=0.6, minutes_to_high=120),
                                Signal(1, 0.6), Signal(1, 0.6))
    assert abs(near.score) < abs(far.score)


# --- AIDecisionStrategy event blackout ------------------------------------ #
def test_blackout_forces_flat_near_high_impact_event():
    now = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    cal = EconomicCalendar([EconomicEvent(now + timedelta(minutes=20), "USD", "CPI", "high")])
    cfg = Settings(fundamental_mode="stub", event_blackout_min=60)
    strat = AIDecisionStrategy(cfg=cfg, fundamental_mode="stub",
                               calendar=cal, decider=RuleDecider())
    sig = strat.generate("USD_JPY", _df(now=now))
    assert sig.direction == 0
    assert sig.components.get("event_blackout") is True


def test_no_blackout_when_event_is_far():
    now = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    cal = EconomicCalendar([EconomicEvent(now + timedelta(hours=10), "USD", "CPI", "high")])
    cfg = Settings(fundamental_mode="stub", event_blackout_min=60)
    strat = AIDecisionStrategy(cfg=cfg, fundamental_mode="stub",
                               calendar=cal, decider=RuleDecider())
    sig = strat.generate("USD_JPY", _df(now=now))
    assert not sig.components.get("event_blackout")


# --- HybridDecider: consult triggers + veto gate -------------------------- #
def _hctx(score_inputs, minutes=None):
    tech, fund = score_inputs
    return _ctx(minutes_to_high=minutes, tech=tech, fund=fund)


def test_hybrid_skips_claude_on_quiet_bar():
    # weak aligned conviction, no event, no disagreement -> rule decides for free
    fake = _FakeClaude(Signal.flat("should not be called"))
    h = HybridDecider(claude=fake)
    ctx = _ctx(tech=0.05, fund=0.05); ctx.entry_threshold = 0.20
    out = h.decide(ctx, Signal(1, 0.05), Signal(1, 0.05))
    assert fake.calls == 0
    assert out.components["consulted_claude"] is False


def test_hybrid_consults_claude_on_actionable_signal():
    fake = _FakeClaude(Signal(1, 0.9, "agree"))
    h = HybridDecider(claude=fake)
    ctx = _ctx(tech=0.6, fund=0.6); ctx.entry_threshold = 0.20
    out = h.decide(ctx, Signal(1, 0.6), Signal(1, 0.6))
    assert fake.calls == 1 and out.components["consulted_claude"] is True


def test_hybrid_claude_veto_forces_flat():
    fake = _FakeClaude(Signal.flat("too risky"))
    h = HybridDecider(claude=fake)
    ctx = _ctx(tech=0.6, fund=0.6); ctx.entry_threshold = 0.20
    out = h.decide(ctx, Signal(1, 0.6), Signal(1, 0.6))
    assert out.direction == 0 and out.score == 0.0


def test_hybrid_claude_opposite_stands_aside():
    fake = _FakeClaude(Signal(-1, -0.8, "I'd short"))
    h = HybridDecider(claude=fake)
    ctx = _ctx(tech=0.6, fund=0.6); ctx.entry_threshold = 0.20
    out = h.decide(ctx, Signal(1, 0.6), Signal(1, 0.6))
    assert out.direction == 0  # never flips to Claude's side


def test_hybrid_claude_can_only_shrink_not_amplify():
    rule_score = 0.30
    # Claude agrees but with lower confidence -> size is the smaller of the two
    fake = _FakeClaude(Signal(1, 0.12, "agree, low conviction"))
    h = HybridDecider(claude=fake)
    ctx = _ctx(tech=rule_score, fund=rule_score); ctx.entry_threshold = 0.20
    base = RuleDecider().decide(ctx, Signal(1, rule_score), Signal(1, rule_score))
    out = h.decide(ctx, Signal(1, rule_score), Signal(1, rule_score))
    assert out.direction == 1
    assert abs(out.score) <= abs(base.score)        # never amplified
    assert abs(out.score) == min(abs(base.score), 0.12)

    # and a very confident Claude still cannot push above the rule's size
    fake2 = _FakeClaude(Signal(1, 0.99, "very confident"))
    h2 = HybridDecider(claude=fake2)
    out2 = h2.decide(ctx, Signal(1, rule_score), Signal(1, rule_score))
    assert abs(out2.score) == abs(base.score)


# --- HybridDecider memory: reuse the verdict while the view holds ---------- #
def _consult(h, tech, fund, minutes=None, et=0.20):
    ctx = _ctx(tech=tech, fund=fund, minutes_to_high=minutes)
    ctx.entry_threshold = et
    import math
    sign = lambda x: 0 if x == 0 else int(math.copysign(1, x))
    return h.decide(ctx, Signal(sign(tech), tech), Signal(sign(fund), fund))


def test_hybrid_reuses_verdict_while_steady():
    fake = _FakeClaude(Signal(1, 0.9, "agree"))
    h = HybridDecider(claude=fake)
    out1 = _consult(h, 0.30, 0.30)   # first actionable bar -> real call
    out2 = _consult(h, 0.31, 0.31)   # same dir, same 0.3 bucket -> reuse
    out3 = _consult(h, 0.29, 0.29)   # rounds to 0.3 too -> reuse
    assert fake.calls == 1
    assert out2.components["claude_cached"] is True
    assert out3.components["claude_cached"] is True
    assert out1.direction == out2.direction == 1


def test_hybrid_refreshes_on_bucket_or_direction_change():
    fake = _FakeClaude(Signal(1, 0.9, "agree"))
    h = HybridDecider(claude=fake)
    _consult(h, 0.30, 0.30)          # call #1 (bucket 0.3)
    _consult(h, 0.50, 0.50)          # bucket 0.5 -> call #2
    _consult(h, -0.50, -0.50)        # direction flip -> call #3
    assert fake.calls == 3


def test_hybrid_refreshes_when_event_enters_window():
    fake = _FakeClaude(Signal(1, 0.9, "agree"))
    h = HybridDecider(claude=fake)
    _consult(h, 0.30, 0.30)              # call #1
    _consult(h, 0.30, 0.30)              # steady -> reuse
    _consult(h, 0.30, 0.30, minutes=90)  # event in caution window -> fresh call
    assert fake.calls == 2


def test_ai_strategy_is_deterministic():
    now = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    cal = EconomicCalendar([])
    cfg = Settings(fundamental_mode="stub")
    mk = lambda: AIDecisionStrategy(cfg=cfg, fundamental_mode="stub",
                                    calendar=cal, decider=RuleDecider())
    df = _df(now=now)
    a = mk().generate("USD_JPY", df)
    b = mk().generate("USD_JPY", df)
    assert a.score == b.score and a.direction == b.direction
