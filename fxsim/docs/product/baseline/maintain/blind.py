import os, sys, io, contextlib
os.environ["MT5_COMMON_FILES"] = sys.argv[1]
os.environ["FXSIM_DB"] = sys.argv[1] + "/t.db"
from pathlib import Path
from app import bridge
import scripts.run_ai_bridge as R
d = Path(sys.argv[1])
# what a not-logged-in r6e-status EA writes: balance 0, equity 0, empty book
(d / "steady_status.csv").write_text("balance,equity,position_lots,exec_seq,ea_time,build\n0.00,0.00,0.000,1790000000,1790000100,r6e-status\n")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    probe = R._trend_gate("USD_JPY", "H1", 2400, "data/USD_JPY_H1.csv")
print("status parsed:", bridge.read_status())
print("probe:", probe, "| lines printed by the probe:", repr(buf.getvalue()))
