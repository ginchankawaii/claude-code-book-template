#!/usr/bin/env python3
"""SCHEMATIC.md の全数値を再生成する計算スクリプト。

  python3 hardware/pcb/calc_circuit.py

出力される値は SCHEMATIC.md §3/§4/§6/§7 の表と1対1で対応する。
ネットリスト側の整合検査は validate_netlist.py を使うこと。
"""
VDD = 3.3
VIH = 0.75*VDD
VIL = 0.25*VDD
print(f"VDD={VDD} VIH={VIH:.3f} VIL={VIL:.3f} abs_max=VDD+0.3={VDD+0.3:.1f}")

def div(vin, r1, r2, t1=0.0, t2=0.0):
    """r1=上側(電源側) r2=下側(GND側) 出力=vin*r2/(r1+r2). t=公差(比率)"""
    return vin * (r2*(1+t2)) / (r1*(1+t1) + r2*(1+t2))

print("\n=== VBUS検出 220k/330k ===")
R1,R2 = 220e3, 330e3
for tol,name in [(0.05,"±5%"),(0.01,"±1%")]:
    for v,label in [(4.40,"USB下限"),(4.75,""),(5.00,"公称"),(5.25,"USB上限")]:
        nom  = div(v,R1,R2)
        lo   = div(v,R1,R2, +tol, -tol)   # 最悪(低)
        hi   = div(v,R1,R2, -tol, +tol)   # 最悪(高)
        print(f" {name} VBUS={v:.2f}V  nom={nom:.3f}  worst_low={lo:.3f} (VIH余裕 {(lo-VIH)*1000:+.0f}mV)  worst_high={hi:.3f} ({'OK' if hi<=3.30 else 'NG'})")
    print()
for v in (5.00,5.25):
    print(f"  消費電流 @VBUS={v}: {v/(R1+R2)*1e6:.2f} uA  (USB挿入中のみ / 電池からは流れない)")
print(f"  Thevenin R = {R1*R2/(R1+R2)/1e3:.0f} kOhm ; 0.1uF で tau = {R1*R2/(R1+R2)*0.1e-6*1e3:.1f} ms, 7tau={7*R1*R2/(R1+R2)*0.1e-6*1e3:.0f} ms")

print("\n=== E24 全探索: VBUS分圧として成立する組合せ (±5%) ===")
E24=[1.0,1.1,1.2,1.3,1.5,1.6,1.8,2.0,2.2,2.4,2.7,3.0,3.3,3.6,3.9,4.3,4.7,5.1,5.6,6.2,6.8,7.5,8.2,9.1]
vals=[e*10**d for d in (4,5) for e in E24]  # 10k..910k
sols=[]
for r1 in vals:
    for r2 in vals:
        if (r1+r2) < 5.00/12e-6:  continue           # 常時消費 <= 12uA @5.0V
        if (r1+r2) > 5.00/4e-6:   continue           # 高すぎ(>1.25MOhm)はノイズ的に不利
        lo = div(4.40,r1,r2,+0.05,-0.05)
        hi = div(5.25,r1,r2,-0.05,+0.05)
        if lo >= VIH and hi <= 3.30:
            sols.append((r1/1e3,r2/1e3,lo,hi,(r1*r2/(r1+r2))/1e3, 5.0/(r1+r2)*1e6))
for s in sorted(sols, key=lambda s:-s[2]):
    print(f"  R1={s[0]:6.0f}k R2={s[1]:6.0f}k  worst_low@4.40V={s[2]:.3f}V  worst_high@5.25V={s[3]:.3f}V  Rth={s[4]:.0f}k  I={s[5]:.1f}uA")
print(f"  解の数 = {len(sols)}")
print("  参考: 1:1 (220k/220k) の最悪値 ->", f"{div(4.40,220e3,220e3,+0.05,-0.05):.3f}V @4.40V,", f"{div(5.00,220e3,220e3,+0.05,-0.05):.3f}V @5.00V  (VIH={VIH:.3f} を割る)")
print("  参考: 180k/220k        ->", f"{div(4.40,180e3,220e3,+0.05,-0.05):.3f}V @4.40V")

print("\n=== 電池電圧監視 220k/220k ===")
R3=R4=220e3
for v in (3.00,3.40,3.70,4.20):
    print(f"  Vbat={v:.2f}V -> {div(v,R3,R4):.3f}V   (ADC 12dB 推奨上限 3.1V 以内: {'OK' if div(v,R3,R4)<=3.1 else 'NG'})")
for tol,name in [(0.05,"±5%"),(0.01,"±1%")]:
    lo=div(4.20,R3,R4,+tol,-tol); hi=div(4.20,R3,R4,-tol,+tol)
    # 逆算誤差(電池電圧に換算)
    print(f"  {name}抵抗: Vbat=4.20V のとき出力 {lo:.4f}〜{hi:.4f}V -> 電池電圧換算 {2*lo:.3f}〜{2*hi:.3f}V (誤差 {(2*hi-4.2)*1000:+.0f}/{(2*lo-4.2)*1000:+.0f} mV)")
for v in (3.70,4.20):
    i=v/(R3+R4)
    print(f"  常時消費 @Vbat={v}V: {i*1e6:.2f} uA = {i*1e3*24:.3f} mAh/day = {i*1e3*8760:.1f} mAh/year")
i42=4.2/(R3+R4)
for cap,name in [(680,"allday実効680mAh"),(425,"slim実効425mAh")]:
    print(f"    {name}: 1日あたり {i42*1e3*24/cap*100:.4f}% / 1年で {i42*1e3*8760/cap*100:.1f}% / 単独放電なら {cap/(i42*1e3)/24/365:.1f} 年")
print(f"  deep sleep 3mA に対する比: {i42/3e-3*100:.3f} %")
print(f"  Thevenin R = {R3*R4/(R3+R4)/1e3:.0f} kOhm ; 0.1uF -> tau={R3*R4/(R3+R4)*0.1e-6*1e3:.1f} ms, 7tau={7*R3*R4/(R3+R4)*0.1e-6*1e3:.0f} ms")
lsb=3100/4095
print(f"  ADC 12bit/12dB: 1LSB={lsb:.3f} mV (分圧後) = {2*lsb:.3f} mV (電池換算)")

print("\n=== LED 電流制限 ===")
for vf in (1.9,2.0,2.1,2.2):
    i=(3.3-vf)/220
    print(f"  Vf={vf}V -> I={i*1e3:.2f} mA, R損失={i*i*220*1e3:.1f} mW, LED損失={vf*i*1e3:.1f} mW")
i=(3.3-2.0)/220
print(f"  PWM duty 10/20% の平均: {i*1e3*0.1:.2f} / {i*1e3*0.2:.2f} mA")
print(f"  GPIO 定格 40mA に対する比: {i*1e3/40*100:.0f} %")

print("\n=== スイッチ内部プルアップ ===")
for rpu in (45e3,):
    print(f"  Rpu={rpu/1e3:.0f}k -> ON(=GND短絡)時 {3.3/rpu*1e6:.0f} uA / OFF時 0 uA")
    print(f"  録音時平均28mA に対する比: {3.3/rpu/28e-3*100:.2f} %")
    print(f"  0.1uF デバウンス併用時 tau = {rpu*0.1e-6*1e3:.1f} ms")

print("\n=== A-1 の消費電流総括 (v1.5 実装分のみ) ===")
print("  追加の常時消費: 0 uA (分圧なし)。SWプルアップ 73uA は録音中のみ。")
