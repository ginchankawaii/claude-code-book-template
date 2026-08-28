# [mechanical 審査用] 案A/B/C/D が筐体に入るかの検算スクリプト (自動生成 2026-08-28)
#   cad/mindclip_case.py を実際に評価して数値を出す。既存ファイルは一切変更しない。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装着性(襟元)の定量評価: 布面からの重心オフセット z_cog と、
   磁石クランプの転倒(浮き上がり)余裕・滑り余裕を各案の外形で計算する。"""
import os, glob, trimesh, math
SP=os.path.dirname(os.path.abspath(__file__))
G=9.80665
# 磁石: N35 φ6x2 を2ペア、ギャップ計 2.1mm。MECHANICAL §6 の概算 2.0〜2.5 N/ペア を採用
F_MAG_LO, F_MAG_HI = 2.0*2, 2.5*2      # N (2ペア合計)
MU = 0.35                              # PETG-綿 の静止摩擦 (assumption)
BP_H = 26.0                            # backplate の Y 寸法 → 有効支圧域
D_LEVER = BP_H/2.0                     # 磁石列から支圧域下端まで = 13.0 mm
# 中身の質量 (g) と z 重心 (mm, 布面 z=0 基準)
def contents(ns_bat_z0, bat_t, xiao_z0, xiao_t, mag_z):
    return [("LiPo802530", 14.0, ns_bat_z0+bat_t/2),      # README §9.9: 実物13〜15g
            ("XIAOスタック+SD", 5.0, xiao_z0+xiao_t/2),
            ("磁石x2(本体側)", 0.9, mag_z),
            ("SW/LED/配線",   1.0, 6.0)]
CASES = {
 "v1現行 (= 案A / 案D)":      ("v1現行", 14.6, 3.0, 8.0, 3.0, 7.5, 1.8, 0.0),
 "案B (キャリア基板 1.0t)":     ("案B",    14.6, 3.0, 8.0, 3.4, 7.5, 1.8, 1.5),
 "案C (ピンソケット)":          ("案C",    19.2, 3.0, 8.0, 9.3, 7.5, 1.8, 2.0),
}
print(f"{'案':26s} {'外形D':>7s} {'質量(装着側)':>11s} {'z_cog':>7s} {'転倒モーメント':>12s} "
      f"{'転倒余裕':>9s} {'滑り余裕':>9s}")
print("-"*92)
for label,(tag,TOTD,bz,bt,xz,xt,magz,extra_g) in CASES.items():
    d=os.path.join(SP,"massout",tag,"allday")
    parts=[]
    for nm in ("body","lid"):
        m=trimesh.load(os.path.join(d,nm+".stl"))
        parts.append((nm, m.volume/1000.0*1.27, m.center_mass[2]))
    parts += contents(bz,bt,xz,xt,magz)
    parts += [("案固有の追加部品", extra_g, TOTD/2)] if extra_g else []
    M=sum(p[1] for p in parts)
    zc=sum(p[1]*p[2] for p in parts)/M
    Wn=M/1000.0*G                                  # N
    M_over=Wn*zc                                   # N*mm
    M_lo, M_hi = F_MAG_LO*D_LEVER, F_MAG_HI*D_LEVER
    slip=(MU*F_MAG_LO)/Wn
    print(f"{label:26s} {TOTD:6.1f}mm {M:9.1f} g {zc:6.2f}mm {M_over:9.2f} N*mm "
          f"{M_lo/M_over:7.1f}x  {slip:7.1f}x")
print()
print(f"※ 転倒余裕 = 磁石が布から浮き始めるモーメント (F_mag {F_MAG_LO:.1f}N x 支圧レバー {D_LEVER:.1f}mm "
      f"= {F_MAG_LO*D_LEVER:.1f} N*mm) ÷ 自重の転倒モーメント。")
print(f"※ 滑り余裕 = 摩擦保持力 (mu={MU} x {F_MAG_LO:.1f}N = {MU*F_MAG_LO*1000/G:.0f} gf) ÷ 装着側自重。")
print("※ いずれも『布は剛体』という仮定。実際の『お辞儀』は布の変形で起きるため、")
print("   この余裕倍率は上限であり、体感の悪化は z_cog (突き出し量) にほぼ比例する。")
