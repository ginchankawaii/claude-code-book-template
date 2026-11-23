import math
P0, T = 270_000, 1_000_000
print("break-even pp/yr:")
for m in (300, 3500, 5000, 7000):
    for p in (270_000, 1_000_000):
        print(f"  {m} JPY/month, equity {p:,}: {m*12/p*100:.2f}%  (after 20.315% tax on gains, cost not deducted: {m*12/p*100/(1-0.20315):.2f}%)")
print("equity at which cost = given uplift: 300/mo & 0.5pp ->", 3600/0.005, " 300/mo & 1pp ->", 3600/0.01, "; 3500/mo & 1pp ->", 42000/0.01)
print("years 270k -> 1M, no deposits:")
for r in (0.09, 0.04, 0.02, 0.15):
    print(f"  {r*100:.0f}%: {math.log(T/P0)/math.log(1+r):.1f} years")
def months(r, dep):
    bal, m = P0, 0; rm = (1+r)**(1/12)-1
    while bal < T and m < 2000:
        bal = bal*(1+rm) + dep; m += 1
    return m
for dep in (20_000, 10_000):
    for r in (0.09, 0.04, 0.0):
        m = months(r, dep); print(f"  +{dep:,}/month at {r*100:.0f}%: {m} months = {m/12:.2f} years (deposits {dep*m:,} = {dep*m/(T-P0)*100:.0f}% of the 730k gap)")
# after 9% with -20.315% tax each year
for r in (0.09, 0.04):
    ra = r*(1-0.20315); print(f"  {r*100:.0f}% pre-tax = {ra*100:.2f}% after tax: {math.log(T/P0)/math.log(1+ra):.1f} years")
# what 300 JPY/month buys (USDJPY 155)
usd = 300/155
print(f"300 JPY = {usd:.2f} USD/month at 155: web searches alone {usd/0.01:.0f}/month; ")
for name,(pi,po) in {"haiku-5-5":(0.10,0.50),"sonnet-4-6":(3,15),"opus-5-5":(4,20),"opus-4-8":(5,25)}.items():
    for (tin,tout,ws,label) in ((8000,1200,4,"diagnose_live assumption"),(60000,2000,6,"6 searches, ~10k tokens of results each")):
        c = tin/1e6*pi + tout/1e6*po + ws*0.01
        print(f"  {name:11s} {label:42s}: {c:.3f} USD/call = {c*155:.1f} JPY; calls per 300 JPY: {usd/c:.0f}; 20 entry calls/yr = {20*c*155:.0f} JPY/yr; daily+refresh(2.2/day) = {2.2*30*c*155:,.0f} JPY/month")
print("ratios: sonnet/haiku", 3/0.10, "opus5.5/haiku", 4/0.10)
