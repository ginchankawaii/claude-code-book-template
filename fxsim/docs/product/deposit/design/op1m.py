"""Scratch: does the rule behave differently at a 1,000,000 JPY balance than at 272,000?
Same replay as docs/product/ai_value/design/rp.py (0.01-lot granularity = 1000 units)."""
import sys, time, json
import numpy as np
import rp

LENS = list(range(2000, 2801, 100))
out = {}
t0 = time.time()
for cad in ("close", "closedbar"):
    for bal in (272_000.0, 1_000_000.0, 100_000_000.0):
        rows = []
        for n in LENS:
            r = rp.replay(cad, 5, n, bal, 1000)
            rows.append((n, r["cagr"], r["mdd"], r["trades"]))
        c = np.array([x[1] for x in rows]); d = np.array([x[2] for x in rows])
        out[f"{cad}|{int(bal)}"] = rows
        print(f"{cad:9s} bal0={int(bal):>11,d}  mean CAGR {c.mean():5.2f}  (min {c.min():5.2f} max {c.max():5.2f})"
              f"  mean maxDD {d.mean():5.1f}  worst maxDD {d.max():5.1f}"
              f"  | SMA2400: {rows[4][1]:5.2f}% / {rows[4][2]:4.1f}% / {rows[4][3]} trades   [{time.time()-t0:.0f}s]", flush=True)
json.dump(out, open(sys.argv[1], "w"))
