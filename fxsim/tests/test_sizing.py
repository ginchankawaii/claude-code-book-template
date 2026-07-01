"""Conviction-scaled leverage helper + engine wiring (docs/RESEARCH.md)."""
import math

import pandas as pd

from app.config import Settings
from app.engine import PaperTradingEngine
from app.models import Signal
from app.sizing import conviction_leverage


# --- pure helper -------------------------------------------------------------
def test_full_cap_when_far_above_sma():
    # price >> sma (many ATRs above) -> full cap
    assert conviction_leverage(150.0, 100.0, 1.0, 5.0, atr_mult=1.5, floor=1.0) == 5.0


def test_floor_at_or_below_sma():
    # price <= sma -> strength 0 -> floor
    assert conviction_leverage(100.0, 100.0, 1.0, 5.0, atr_mult=1.5, floor=1.0) == 1.0
    assert conviction_leverage(99.0, 100.0, 1.0, 5.0, atr_mult=1.5, floor=1.0) == 1.0


def test_ramps_monotonically_between_floor_and_cap():
    xs = [conviction_leverage(100 + d, 100.0, 1.0, 5.0, atr_mult=2.0, floor=1.0)
          for d in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)]
    assert xs[0] == 1.0 and xs[-1] == 5.0
    assert all(b >= a for a, b in zip(xs, xs[1:]))     # non-decreasing
    assert all(1.0 <= v <= 5.0 for v in xs)            # never exceeds cap


def test_never_exceeds_cap_even_with_huge_distance():
    assert conviction_leverage(1e9, 100.0, 0.001, 5.0) == 5.0


def test_degrades_to_cap_on_bad_inputs():
    assert conviction_leverage(100.0, 100.0, 0.0, 5.0) == 5.0        # atr=0
    assert conviction_leverage(100.0, float("nan"), 1.0, 5.0) == 5.0  # nan sma
    assert conviction_leverage(100.0, 100.0, 1.0, 0.0) == 0.0        # cap off


def test_convex_power_stays_below_linear_mid_ramp():
    # p=2 loads up late: below the linear ramp everywhere strictly inside (0,1),
    # equal at the endpoints, never above the cap.
    for d in (0.25, 0.75, 1.0):
        lin = conviction_leverage(100 + d, 100.0, 1.0, 5.0, atr_mult=1.0, power=1.0)
        cvx = conviction_leverage(100 + d, 100.0, 1.0, 5.0, atr_mult=1.0, power=2.0)
        assert cvx <= lin <= 5.0
    # endpoints identical
    assert conviction_leverage(100.0, 100.0, 1.0, 5.0, power=2.0) == 1.0
    assert conviction_leverage(200.0, 100.0, 1.0, 5.0, power=2.0) == 5.0
    # mid-ramp: s=0.5 -> 1 + 4*0.25 = 2.0
    assert conviction_leverage(100.5, 100.0, 1.0, 5.0, atr_mult=1.0, power=2.0) == 2.0


# --- engine wiring -----------------------------------------------------------
def _rising_df(n=60, start=100.0, step=0.2):
    # steadily rising closes so price sits above its own SMA; atr well-defined
    rows = []
    for i in range(n):
        c = start + i * step
        rows.append(dict(time=pd.Timestamp("2020-01-01") + pd.Timedelta(hours=i),
                         open=c, high=c + 0.1, low=c - 0.1, close=c, volume=1.0, atr=0.5))
    return pd.DataFrame(rows)


def test_engine_dyn_leverage_never_exceeds_flat_cap():
    df = _rising_df()
    # dyn vs flat: dyn size must be <= flat size (same cap), never larger
    def open_units(dyn):
        cfg = Settings(initial_balance=100000, risk_per_trade=0.99, max_position_units=10**12,
                       max_leverage=5.0, trend_sma=30, dyn_leverage=dyn)
        eng = PaperTradingEngine(0, "USD_JPY", None, cfg, persist=False)
        eng.step(df, Signal(1, 0.6, "long"))
        return abs(eng.state.position.units)
    assert open_units(True) <= open_units(False)


def test_engine_dyn_leverage_respects_hard_cap():
    df = _rising_df()
    cfg = Settings(initial_balance=100000, risk_per_trade=0.99, max_position_units=10**12,
                   max_leverage=5.0, trend_sma=30, dyn_leverage=True)
    eng = PaperTradingEngine(0, "USD_JPY", None, cfg, persist=False)
    eng.step(df, Signal(1, 0.6, "long"))
    price = df.iloc[-1]["close"]
    assert abs(eng.state.position.units) * price <= 5.0 * eng.balance * 1.001
