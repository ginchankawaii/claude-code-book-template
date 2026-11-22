import sys, pathlib
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim/tests")
from test_ea_protocol import FakeEA
from app import bridge
base = pathlib.Path(sys.argv[1])
# 1) the brain's normal standing order: 0.09 lots, SEQ, EXP, SL — already executed
ea = FakeEA(lots=0.09, exec_seq=1763000000)
bridge.write_signal("LONG", 0.09, base=base, expires_at=10_000, sl=158.0, seq=1763000000)
ea.tick(base, now=100); print("brain order     ->", ea.lots, ea.sl, ea.actions)
# 2) a foreign process (any program of the same Windows user, another terminal's EA,
#    a restored/synced copy) overwrites one line: bigger, higher SEQ, no EXP, no SL
(base / bridge.SIGNAL_FILE).write_text("LONG 2.00 SEQ 9999999999\n")
ea.tick(base, now=100); print("foreign bigger  ->", ea.lots, "sl", ea.sl, ea.actions[-1])
# 3) flat book + hand-written unsequenced line, no stop, never expires
ea2 = FakeEA(lots=0.0, exec_seq=1763000000)
(base / bridge.SIGNAL_FILE).write_text("LONG 2.00\n")
ea2.tick(base, now=10**12); print("foreign no-seq  ->", ea2.lots, "sl", ea2.sl, ea2.actions)
# 4) close-only attack
ea3 = FakeEA(lots=0.09, exec_seq=1763000000)
(base / bridge.SIGNAL_FILE).write_text("FLAT 0\n")
ea3.tick(base, now=100); print("foreign FLAT    ->", ea3.lots, ea3.actions)
