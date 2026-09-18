"""The EA's order-execution contract, as a model of SteadyBridge.mq5.

steady_signal.txt is a STANDING target that the EA re-executes on every timer
tick (30s) with no memory of having acted. Round-4 gave the broker a REAL stop
that closes the position server-side — and the two together were a critical
defect: the instant the stop filled, the still-standing "LONG <lots>" line made
the very next tick re-buy the same size, with no decision, no trend check and
(its stop now being through the market) no stop at all. The operator's own
manual closes were undone the same way, within 30 seconds.

The fix is the SEQ token: the EA may ALWAYS reduce or close, but may only OPEN
or INCREASE on an order it has not executed.

HONEST LIMIT: MQL5 cannot be executed here. `_ea_tick` below is a transcription
of ProcessSignal's decision logic (mt5_ea/SteadyBridge.mq5), so these tests pin
the CONTRACT and catch a regression in the Python half that feeds it; they do
not prove the compiled EA matches. The transcription is checked by review, and
the live check is the operator seeing no re-entry after a stop-out.
"""
from app import bridge


class FakeEA:
    """ProcessSignal(), transcribed. `lots` is the broker's actual book."""

    def __init__(self, lots=0.0, exec_seq=0, bid=160.0):
        self.lots = lots               # what the broker holds
        self.exec_seq = exec_seq       # persisted in a terminal GlobalVariable
        self.exec_key = ""
        self.sl = 0.0
        self.bid = bid                 # ValidLongSL: a stop must sit below the bid
        self.actions: list[str] = []

    def _valid_sl(self, sl):
        return sl if (sl > 0 and sl < self.bid - 0.001) else 0.0

    def _is_new_order(self, seq, key):
        return seq > self.exec_seq if seq else key != self.exec_key   # r6: strictly greater

    def _commit(self, seq, key):
        self.exec_key = key
        if seq:
            self.exec_seq = seq
            self.exec_seq_on_disk = seq          # r6d: GlobalVariablesFlush()

    def restart(self):
        """Clean terminal restart: in-memory state is lost, the GlobalVariable is not."""
        self.exec_key = ""

    def crash(self):
        """Power loss / BSOD: only what was FLUSHED to disk survives."""
        self.exec_key = ""
        self.exec_seq = getattr(self, "exec_seq_on_disk", 0)

    def tick(self, base, now=0):
        sig = bridge.read_signal(base=base)
        if not sig:
            return
        seq, sl_px = sig["seq"] or 0, sig["sl"] or 0.0
        key = f"{sig['action']} {sig['lots']:.3f} SL {sl_px:.5f}"
        if sig["expires_at"] and now > sig["expires_at"]:
            if self.lots:
                self.lots = 0.0
                self.actions.append("expire-closeall")
            return
        target = sig["lots"] if sig["action"] == "LONG" else 0.0
        if self.lots > 0 and self._valid_sl(sl_px) > 0:   # ApplyStopLoss
            self.sl = sl_px
        if target == 0.0:                          # closing is never gated
            if self.lots:
                self.lots = 0.0
                self.actions.append("closeall")
            return
        if self.lots == 0.0:
            if not self._is_new_order(seq, key):
                self.actions.append("held-flat")
                return
            if sl_px > 0 and self._valid_sl(sl_px) <= 0:      # r6e: never open stop-less
                self.actions.append("refused-stop-through-market")
                return
            self.lots, self.sl = target, sl_px
            self.actions.append(f"buy {target:.2f}")
            self._commit(seq, key)
            return
        diff = target - self.lots
        band = max(0.10, self.lots * 0.20)
        if self.lots < 0.10:
            band = 0.0
        step = 0.01
        # r6b ADOPT RULE: "at target" is half a lot step, INDEPENDENT of the
        # deadband — with band=0 under 0.10 lots the r6 rule was dead code at
        # every size a sub-300k-yen account can hold.
        if abs(diff) < step * 0.5 or abs(diff) < band:
            if self._is_new_order(seq, key):
                self._commit(seq, key)
                self.actions.append(f"adopt {seq}")
            return
        if diff > 0:
            if not self._is_new_order(seq, key):
                self.actions.append("held-partial")
                return
            self.lots = target
            self.actions.append(f"add {diff:.2f}")
            self._commit(seq, key)
        else:
            self.lots = target
            self.actions.append(f"reduce {-diff:.2f}")


def _heartbeat(base, lots, seq, sl=158.0, exp=10_000):
    bridge.write_signal("LONG", lots, base=base, expires_at=exp, sl=sl, seq=seq)


# --- the critical one -------------------------------------------------------

def test_broker_stop_fill_is_not_re_bought(tmp_path):
    ea = FakeEA()
    _heartbeat(tmp_path, 0.17, seq=1000)
    ea.tick(tmp_path)
    assert ea.lots == 0.17 and ea.actions == ["buy 0.17"]

    ea.lots = 0.0                       # the broker SL fills, server-side
    for _ in range(20):                 # 10 minutes of heartbeats, one poll
        _heartbeat(tmp_path, 0.17, seq=1000)
        ea.tick(tmp_path)
    assert ea.lots == 0.0, "the stopped-out long was re-bought by a heartbeat"
    assert ea.actions == ["buy 0.17"] + ["held-flat"] * 20


def test_manual_close_stays_closed(tmp_path):
    # The operator flattens from MT5 mobile while away. It must stay flat.
    ea = FakeEA()
    _heartbeat(tmp_path, 0.30, seq=2000)
    ea.tick(tmp_path)
    ea.lots = 0.0
    for _ in range(10):
        _heartbeat(tmp_path, 0.30, seq=2000)
        ea.tick(tmp_path)
    assert ea.lots == 0.0


def test_partial_close_is_not_refilled(tmp_path):
    ea = FakeEA()
    _heartbeat(tmp_path, 1.20, seq=3000)
    ea.tick(tmp_path)
    assert ea.lots == 1.20
    ea.lots = 0.40                      # partial fill / manual trim
    for _ in range(10):
        _heartbeat(tmp_path, 1.20, seq=3000)
        ea.tick(tmp_path)
    assert ea.lots == 0.40, "the heartbeat re-bought the part that was closed"


def test_terminal_restart_does_not_resurrect_a_closed_position(tmp_path):
    # The executed SEQ lives in a GlobalVariable precisely so that restarting
    # MT5 does not re-open a position closed while it was down.
    ea = FakeEA()
    _heartbeat(tmp_path, 0.17, seq=4000)
    ea.tick(tmp_path)
    ea.lots = 0.0
    ea.restart()
    _heartbeat(tmp_path, 0.17, seq=4000)
    ea.tick(tmp_path)
    assert ea.lots == 0.0


# --- the EA must still do its job -------------------------------------------

def test_a_new_decision_still_opens(tmp_path):
    ea = FakeEA()
    _heartbeat(tmp_path, 0.17, seq=5000)
    ea.tick(tmp_path)
    ea.lots = 0.0                                    # stopped out
    _heartbeat(tmp_path, 0.17, seq=5000)
    ea.tick(tmp_path)
    assert ea.lots == 0.0
    _heartbeat(tmp_path, 0.20, seq=5001)             # the brain decides again
    ea.tick(tmp_path)
    assert ea.lots == 0.20, "a genuinely new order was refused"


def test_flat_always_closes_even_on_a_repeated_seq(tmp_path):
    ea = FakeEA(lots=0.17, exec_seq=6000)
    bridge.write_signal("FLAT", 0.0, base=tmp_path, expires_at=10_000, seq=6000)
    ea.tick(tmp_path)
    assert ea.lots == 0.0 and "closeall" in ea.actions


def test_expiry_failsafe_still_flattens(tmp_path):
    ea = FakeEA(lots=0.17, exec_seq=7000)
    _heartbeat(tmp_path, 0.17, seq=7000, exp=100)
    ea.tick(tmp_path, now=101)
    assert ea.lots == 0.0 and "expire-closeall" in ea.actions


def test_reducing_is_never_gated(tmp_path):
    ea = FakeEA(lots=1.20, exec_seq=8000)
    _heartbeat(tmp_path, 0.30, seq=8000)             # same seq, smaller target
    ea.tick(tmp_path)
    assert ea.lots == 0.30, "a de-risking resize was blocked by the seq gate"


def test_unsequenced_signal_falls_back_to_content(tmp_path):
    # Hand-written signal files and pre-round-5 brains carry no SEQ; the EA
    # then compares the order content with EXP stripped, so a heartbeat still
    # cannot re-open, while an edited file can.
    ea = FakeEA()
    bridge.write_signal("LONG", 0.17, base=tmp_path, expires_at=10_000, sl=158.0)
    ea.tick(tmp_path)
    assert ea.lots == 0.17
    ea.lots = 0.0
    for exp in range(10_001, 10_011):                # EXP changes every beat
        bridge.write_signal("LONG", 0.17, base=tmp_path, expires_at=exp, sl=158.0)
        ea.tick(tmp_path)
    assert ea.lots == 0.0, "a changing EXP alone read as a new order"
    bridge.write_signal("LONG", 0.25, base=tmp_path, expires_at=10_020, sl=158.0)
    ea.tick(tmp_path)
    assert ea.lots == 0.25


# --- round-6: the bootstrap hole (an ADOPTED position's id was never "executed")

def test_adopted_position_is_not_re_bought_after_external_close(tmp_path):
    # Restart with a LONG in the DB but no id on the bridge: the brain adopts
    # the open book under a freshly minted id. The EA never placed that id, so
    # before r6 it stayed "new" forever and the first external close was
    # re-bought within 30s with no decision and no stop.
    ea = FakeEA(lots=0.24, exec_seq=1700000000)      # position from an old order
    _heartbeat(tmp_path, 0.24, seq=1800000000)       # brain's adopted-book heartbeat
    ea.tick(tmp_path)
    assert ea.lots == 0.24 and ea.actions == ["adopt 1800000000"]
    ea.lots = 0.0                                    # broker SL fills
    for _ in range(10):
        _heartbeat(tmp_path, 0.24, seq=1800000000)
        ea.tick(tmp_path)
    assert ea.lots == 0.0, "adopted order was re-bought after the stop filled"


def test_adopt_survives_terminal_restart(tmp_path):
    ea = FakeEA(lots=0.24, exec_seq=0)
    _heartbeat(tmp_path, 0.24, seq=1800000000)
    ea.tick(tmp_path)                                # adopt -> persisted
    ea.lots = 0.0
    ea.restart()
    _heartbeat(tmp_path, 0.24, seq=1800000000)
    ea.tick(tmp_path)
    assert ea.lots == 0.0


def test_lower_or_equal_id_never_opens(tmp_path):
    # Ids only ever increase. A LOWER id is a stale writer or a restored old
    # signal file and must not re-open; only a strictly greater one may.
    ea = FakeEA(lots=0.0, exec_seq=1800000000)
    for seq in (1799999999, 1800000000):
        _heartbeat(tmp_path, 0.17, seq=seq)
        ea.tick(tmp_path)
        assert ea.lots == 0.0
    _heartbeat(tmp_path, 0.17, seq=1800000001)
    ea.tick(tmp_path)
    assert ea.lots == 0.17


# --- round-6b: the r6 fix was verified at 0.24 lots; the owner holds 0.09 ---

import pytest


@pytest.mark.parametrize("lots", [0.01, 0.05, 0.09, 0.099, 0.10, 0.24])
def test_adopt_rule_works_at_every_size_the_account_can_hold(tmp_path, lots):
    ea = FakeEA(lots=lots, exec_seq=1700000000)
    _heartbeat(tmp_path, lots, seq=1800000000)
    ea.tick(tmp_path)
    assert ea.exec_seq == 1800000000, f"adopt rule did not fire at {lots} lots"
    ea.lots = 0.0                                    # broker SL fills
    for _ in range(5):
        _heartbeat(tmp_path, lots, seq=1800000000)
        ea.tick(tmp_path)
    assert ea.lots == 0.0, f"re-bought after the stop at {lots} lots"


def test_hard_crash_after_an_entry_does_not_lose_the_executed_id(tmp_path):
    # Globals reach disk on a clean shutdown; without an explicit flush a power
    # loss right after an entry restarted with the PREVIOUS id and re-bought a
    # stop that filled while the PC was down (round-6c).
    ea = FakeEA(lots=0.0, exec_seq=1700000000)
    ea.exec_seq_on_disk = 1700000000
    _heartbeat(tmp_path, 0.09, seq=1800000000)
    ea.tick(tmp_path)
    assert ea.lots == 0.09
    ea.lots = 0.0                                    # broker SL fills during the outage
    ea.crash()
    _heartbeat(tmp_path, 0.09, seq=1800000000)       # the standing line, still live
    ea.tick(tmp_path)
    assert ea.lots == 0.0, "re-bought after a crash: the executed id was not flushed"


def test_entry_whose_stop_is_already_through_the_market_is_refused(tmp_path):
    # Opening it would create a position with NO broker stop whose exit
    # condition is already true; the brain re-decides on its next gate tick.
    ea = FakeEA(lots=0.0, exec_seq=0, bid=149.0)
    _heartbeat(tmp_path, 0.09, seq=1800000000, sl=149.5)     # stop above bid
    ea.tick(tmp_path)
    assert ea.lots == 0.0 and ea.actions == ["refused-stop-through-market"]
    assert ea.exec_seq == 0                                    # id stays unexecuted
    ea.bid = 150.2                                             # market recovers
    _heartbeat(tmp_path, 0.09, seq=1800000000, sl=149.5)
    ea.tick(tmp_path)
    assert ea.lots == 0.09 and ea.sl == 149.5
