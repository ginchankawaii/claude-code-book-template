"""Sampled hand mutation of the order path, run on a scratch COPY of fxsim.

Each mutant = (id, file, old, new, what it breaks). `old` must occur exactly once.
For every mutant: apply, run the whole test suite with -x, restore, record
KILLED (a test failed) or SURVIVED (274 passed).
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(sys.argv[1])
PY = sys.argv[2]
B = "scripts/run_ai_bridge.py"

MUTANTS = [
    ("M01", B, 'closed = candles[:-1] if src == "ea" else candles', 'closed = candles',
     "decide on the FORMING bar again (the Round-2..9 defect)"),
    ("M02", B, 'if status is None or (status.get("equity") or 0) <= 0:\n        return None\n    loaded = _load_bars(instrument, granularity, sma_n, history_csv)\n    if loaded is None:\n        return None\n    feed, closed = loaded\n    price = float(feed[-1].close)',
     'if status is None:\n        return None\n    loaded = _load_bars(instrument, granularity, sma_n, history_csv)\n    if loaded is None:\n        return None\n    feed, closed = loaded\n    price = float(feed[-1].close)',
     "probe trusts a status row with equity 0 (EA not logged in: book reads empty)"),
    ("M03", B, 'stop_price = round(price - max(1.5 * atr_now, 5 * pip), 3)',
     'stop_price = round(price - max(2.5 * atr_now, 5 * pip), 3)', "stop distance 1.5 ATR -> 2.5 ATR"),
    ("M04", B, 'out_seq = int(seq) if (action == "LONG" and not fresh and seq) else _next_seq(seq)',
     'out_seq = _next_seq(seq)', "a HOLD decision mints a new order id (licenses the EA to re-buy)"),
    ("M05", B, 'bridge.write_signal(action, lots, sl=stop_price if action == "LONG" else None,\n                            seq=out_seq, expires_at=expires_at)',
     'bridge.write_signal(action, lots, sl=None,\n                            seq=out_seq, expires_at=expires_at)',
     "decision line carries no broker stop"),
    ("M06", B, 'seq=out_seq, expires_at=expires_at)', 'seq=out_seq, expires_at=None)',
     "decision line carries no EXP (time-unbounded order)"),
    ("M07", B, 'blind_grace_s = max(3 * args.poll, 60)', 'blind_grace_s = max(3000 * args.poll, 60)',
     "blind brain never withholds the heartbeat (fail-safe unreachable)"),
    ("M08", B, 'if intent == "LONG" and seen_long and pos < FLAT_EPS:\n                    print(f"[ai] book closed EXTERNALLY',
     'if False and intent == "LONG" and seen_long and pos < FLAT_EPS:\n                    print(f"[ai] book closed EXTERNALLY',
     "external close (broker SL fill) is never reconciled"),
    ("M09", B, 'elif pos > 0 and stop_price is not None and price <= stop_price:',
     'elif pos > 0 and stop_price is not None and price <= stop_price - 50:', "python-side stop never fires"),
    ("M10", B, 'last_gate = _time.time()          # brief pause before re-entry\n                    reentry_bar = st.get("_bar_t")',
     'last_gate = _time.time()          # brief pause before re-entry\n                    reentry_bar = None',
     "no re-entry block after a python stop (I12)"),
    ("M11", B, 'wants_exit = (not trend_up) and pos > 0', 'wants_exit = False',
     "trend-down no longer triggers a gate exit (waits for the 20h daily slot)"),
    ("M12", B, 'prev_stop=stop_price, seq=max(order_seq, ea_exec_seq),', 'prev_stop=stop_price, seq=order_seq,',
     "new order id not stepped over the EA's executed id"),
    ("M13", B, "expires_at=(int(_time.time() + clock_skew) + ttl_s) if ttl_s > 0 else None,",
     "expires_at=(int(_time.time()) + ttl_s) if ttl_s > 0 else None,",
     "heartbeat EXP written in the container clock, not the EA's"),
    ("M14", B, 'if blind_s > blind_grace_s:', 'if False:', "stop-liveness withholding removed"),
    ("M15", B, 'hb_ok = False        # not provably the single writer: stop attesting', 'hb_ok = True',
     "keeps heartbeating after losing the lock"),
    ("M16", B, "and (intent == \"FLAT\" or intent_lots >= FLAT_EPS)):", "and True):",
     "heartbeats 'LONG 0.00' (EA reads close-everything)"),
    ("M17", B, 'sl=stop_price if intent == "LONG" else None,\n                                    seq=order_seq)',
     'sl=None,\n                                    seq=order_seq)', "heartbeat drops the broker stop"),
    ("M18", B, 'if frozen_status or torn_row or (ea_now is not None and sk is None):', 'if False:',
     "frozen/torn EA status is trusted by the loop"),
    ("M19", B, 'if pos < intent_lots - FLAT_EPS:', 'if False:', "external shrink not adopted (heartbeat keeps the old target)"),
    ("M20", B, 'skip_scheduled = probe is None', 'skip_scheduled = False', "blind poll still runs scheduled decisions"),
    ("M21", B, 'if age_h > limit_h:', 'if False:', "stale bars accepted"),
    ("M22", B, 'if jump > MAX_BAR_JUMP_PCT:', 'if False:', "implausible bar accepted"),
    ("M23", B, 'return max(int(prev) + 1, int(floor) + 1, int(_time.time()))', 'return int(prev) + 1',
     "order ids not wall-clock monotone across restarts"),
    ("M24", B, 'if pos > 0 and stop_price is not None and stop_price >= price * 1.03:', 'if False:',
     "implausible restored stop not discarded"),
    ("M25", B, 'if intent == "LONG" and not seen_long and pos < FLAT_EPS and not trend_up:', 'if False:',
     "unfilled order not cancelled when the trend turns"),
    ("M26", B, 'order_seq = _next_seq(order_seq, ea_exec_seq)\n                        bridge.write_signal("FLAT", 0.0, seq=order_seq)',
     'order_seq = _next_seq(order_seq, ea_exec_seq)\n                        bridge.write_signal("LONG", intent_lots, seq=order_seq)',
     "stop hit writes a new LONG order instead of FLAT"),
    ("M27", B, 'settle_pending = intent == "LONG" and not order_seq', 'settle_pending = False',
     "restored id-less LONG never settled against the book"),
    ("M28", B, 'last_decision = min(last_decision, _time.time())', 'pass',
     "restored decision clock may sit in the future"),
    ("M29", B, 'if intent == "FLAT" and pos > 0:\n                    # Ordered closed',
     'if False:\n                    # Ordered closed', "FLAT-pending no longer blocks decisions (hold re-adopts)"),
    ("M30", B, 'trend_up = sig_close > ma\n', 'trend_up = price > ma\n', "decision signal from the live price, not the closed bar"),
    ("M31", "app/bridge.py", 'if seq:\n        line += f" SEQ {int(seq)}"', 'if False:\n        line += f" SEQ {int(seq)}"',
     "signal file never carries SEQ"),
    ("M32", "app/bridge.py", 'if len(row) >= 6 and row[5]:', 'if len(row) >= 4:',
     "status all-or-nothing parse relaxed (torn ea_time trusted)"),
    ("M33", "app/ai_trader.py", 'lots = math.floor(lots / min_lot + 1e-9) * min_lot', 'lots = round(lots / min_lot) * min_lot',
     "size rounds to nearest instead of truncating (can exceed the cap)"),
    ("M34", "app/sizing.py", 'return lo + (cap - lo) * strength', 'return cap', "ramp disabled: always full cap"),
    ("M35", B, 'eff_leverage = cfg.max_leverage\n', 'eff_leverage = cfg.max_leverage * 2\n', "hold/FLAT path leverage doubled (I2 probe)"),
    ("M36", B, 'if reentry_bar is not None:\n        last_gate = min(last_exit, _time.time())',
     'reentry_bar = None\n    if reentry_bar is not None:\n        last_gate = min(last_exit, _time.time())',
     "re-entry block not restored after restart"),
]


def run_tests():
    t = time.time()
    p = subprocess.run([PY, "-m", "pytest", "tests", "-q", "-x", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    tail = [ln for ln in p.stdout.splitlines() if ln.strip()][-1] if p.stdout.strip() else ""
    failed = [ln for ln in p.stdout.splitlines() if ln.startswith("FAILED") or ln.startswith("ERROR")]
    return p.returncode, tail, failed[:1], time.time() - t


def main():
    only = set(sys.argv[3:])
    results = []
    for mid, rel, old, new, what in MUTANTS:
        if only and mid not in only:
            continue
        path = ROOT / rel
        src = path.read_text()
        n = src.count(old)
        if n != 1:
            print(f"{mid} SKIP (pattern occurs {n}x) {what}", flush=True)
            continue
        path.write_text(src.replace(old, new))
        try:
            rc, tail, failed, dt = run_tests()
        finally:
            path.write_text(src)
        verdict = "SURVIVED" if rc == 0 else "KILLED"
        killer = failed[0].split(" - ")[0].replace("FAILED ", "") if failed else ""
        print(f"{mid} {verdict:8s} {dt:5.0f}s | {what} | {killer or tail}", flush=True)
        results.append((mid, verdict))
    k = sum(1 for _, v in results if v == "KILLED")
    print(f"TOTAL {len(results)} mutants: {k} killed, {len(results) - k} survived", flush=True)


if __name__ == "__main__":
    main()
