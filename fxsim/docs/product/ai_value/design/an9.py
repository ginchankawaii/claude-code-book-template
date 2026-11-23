import pandas as pd, numpy as np
d = pd.read_csv("placebo_nine.csv"); BE = 300*12/270000*100
for X, g in d.groupby("X"):
    m = g.groupby("d")[["dA","dB","ddA","ddB","hit"]].mean()
    print(f"--- X={X}h, nine-length MEAN per draw ({len(m)} draws); baseline entries inside windows per length-draw {g.hit.mean():.1f}")
    for c in ("dA","dB"):
        s = m[c]
        print(f"  {c}: mean {s.mean():+.2f}pp sd {s.std():.2f} p5 {s.quantile(.05):+.2f} p50 {s.median():+.2f} p95 {s.quantile(.95):+.2f} min {s.min():+.2f} max {s.max():+.2f} P(>0)={np.mean(s>0):.2f} P(>BE {BE:.2f})={np.mean(s>BE):.2f}")
    print(f"  maxDD change (mean of nine): A {m.ddA.mean():+.1f}, B {m.ddB.mean():+.1f}")
    # single-length sd by length
    print("  per-length sd of dA:", g.groupby("L").dA.std().round(2).to_dict())
    print("  per-length mean of dA:", g.groupby("L").dA.mean().round(2).to_dict())
    print("  per-length mean of dB:", g.groupby("L").dB.mean().round(2).to_dict())
    # best-of-K selection under the null: K candidate windows definitions -> max over K independent draws of the nine-mean
    rng = np.random.default_rng(0); a = m.dA.to_numpy()
    for K in (1,3,6,12):
        mx = np.array([rng.choice(a, K, replace=False).max() for _ in range(5000)])
        print(f"   best-of-{K} placebo (A, nine-mean): mean {mx.mean():+.2f} p95 {np.quantile(mx,.95):+.2f}; P(best>0) {np.mean(mx>0):.2f}")
