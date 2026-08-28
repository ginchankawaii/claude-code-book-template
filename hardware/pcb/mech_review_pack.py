# [mechanical 審査用] 案A/B/C/D が筐体に入るかの検算スクリプト (自動生成 2026-08-28)
#   cad/mindclip_case.py を実際に評価して数値を出す。既存ファイルは一切変更しない。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""左ポケットの実効自由体積(ボクセル実測)に対し、各案が入れる物の体積が収まるかを検算。
   電線外径は ELECTRICAL.md §5.3 の実装要求値 AWG28 = 外径約1.2mm を使う。"""
import math
AWG28_OD = 1.2                       # ELECTRICAL.md §5.3 明記値
A_W = math.pi*(AWG28_OD/2)**2        # 1.131 mm2/mm
PACK = (0.50, 0.70)                  # 束ねた電線の実効充填率 (assumption)
# eval_pocket.py のボクセル実測値
POCKET = {"allday": {"full": 2.15, "under_bat": 1.84},
          "slim":   {"full": 1.79, "under_bat": 1.24}}
def wire(mm): return A_W*mm
RIGID = {}   # 剛体 (充填率100%)
FLEX  = {}   # 電線・熱収縮 (充填率を掛ける)
RIGID["A-1"] = {"JST嵌合体(寝かせ) 11x5.8x4.5": 11*5.8*4.5, "LED本体 φ3x5": math.pi*1.5**2*5}
FLEX ["A-1"] = {"LED余長 2x60mm": wire(120), "SW配線 2x50mm": wire(100),
                "JSTピグテール 2x40mm": wire(80), "熱収縮/ホットボンド": 80}
RIGID["A-2"] = dict(RIGID["A-1"]); RIGID["A-2"].update({"1/6W抵抗x4(寝かせ)":4*3.2*1.8*1.8,"0.1uF":60})
FLEX ["A-2"] = dict(FLEX["A-1"]);  FLEX ["A-2"].update({"追加信号線 4x40mm":wire(160)})
RIGID["D"]   = {"蛇の目基板 10.2x15.9x1.0":10.2*15.9*1.0,
                "J1(トップ型PH)+立上り 7.8x4.5x7.5":7.8*4.5*7.5, "LED本体 φ3x5": math.pi*1.5**2*5}
FLEX ["D"]   = {"LED余長 2x60mm":wire(120),"SW配線 2x50mm":wire(100),
                "基板→XIAO 6本x35mm":wire(210),"熱収縮":60}
RIGID["B"]   = {}   # 全部キャリア基板上 → 左ポケットは空く
FLEX ["B"]   = {"LED余長 2x60mm":wire(120),"SW配線 2x50mm":wire(100),"熱収縮":40,
                "LED本体 φ3x5": math.pi*1.5**2*5}
print(f"AWG28 外径 {AWG28_OD}mm → 断面 {A_W:.3f} mm2/本 (ELECTRICAL.md §5.3)")
print()
for key in ("A-1","A-2","D","B"):
    r=sum(RIGID[key].values()); f=sum(FLEX[key].values())
    print(f"■ 案{key}: 剛体 {r:6.1f} mm3 / 可撓 {f:6.1f} mm3")
    for k,v in sorted({**RIGID[key],**FLEX[key]}.items(),key=lambda kv:-kv[1]):
        print(f"     {k:34s} {v:7.1f} mm3")
    for var in ("allday","slim"):
        for rule,cap in POCKET[var].items():
            need_lo = (r + f/PACK[1])/1000.0   # 充填率70% (最良)
            need_hi = (r + f/PACK[0])/1000.0   # 充填率50% (最悪)
            uu = "ポケット全体" if rule=="full" else "MECH§7『電池上面より下』"
            ok_lo, ok_hi = need_lo<=cap, need_hi<=cap
            v = "OK" if ok_hi else ("要押し込み(条件付き)" if ok_lo else "**入らない**")
            print(f"     [{var:6s}/{uu:22s} 容量{cap:.2f}cm3] 所要 {need_lo:.2f}〜{need_hi:.2f} cm3 "
                  f"= 占有率 {need_lo/cap*100:3.0f}〜{need_hi/cap*100:3.0f}%  → {v}")
    print()
print("※ 充填率50〜70% = 束ねた電線が実際に占める空間 (assumption。裸導体断面ではなく")
print("   曲げ半径と余長のたるみを含む実効値。50%は雑に押し込んだ場合、70%は丁寧に折り畳んだ場合)")
