"""The live MT5 book must act on the SAME entry/exit thresholds as the backtest
engine, not merely on the signal's sign — otherwise the AI base can open weak,
fundamental-driven longs live that the backtest would never take.
"""
from app.config import Settings
from app.mt5_live import MT5LiveTrader


def _trader(want_long=False, entry=0.20, exit=0.08):
    # bypass __init__ (no DB / broker / network) — we only exercise the gate
    t = MT5LiveTrader.__new__(MT5LiveTrader)
    t.cfg = Settings(entry_threshold=entry, exit_threshold=exit)
    t._want_long = want_long
    return t


def test_flat_opens_only_above_entry_threshold():
    t = _trader(want_long=False)
    assert t._want_long_after(1, 0.60) is True    # strong long -> open
    assert t._want_long_after(1, 0.15) is False   # below entry -> stay flat
    assert t._want_long_after(0, 0.00) is False    # no signal -> flat


def test_long_holds_until_signal_fades_below_exit():
    t = _trader(want_long=True)
    assert t._want_long_after(1, 0.10) is True    # >= exit -> hold (hysteresis)
    assert t._want_long_after(1, 0.05) is False   # < exit -> close
    assert t._want_long_after(0, 0.50) is False    # turned flat -> close
    assert t._want_long_after(-1, 0.90) is False   # short signal -> close (never short)
