from datetime import datetime, timedelta, timezone

import pandas as pd

from app.config import Settings
from app.events import EconomicCalendar, EconomicEvent
from app.indicators import candles_to_df, enrich
from app.models import Signal
from app.providers.sample import SampleProvider
from app.strategies.ai import AIDecisionStrategy, DecisionContext, RuleDecider


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
