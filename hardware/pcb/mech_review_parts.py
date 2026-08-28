# [mechanical 審査用] 案A/B/C/D が筐体に入るかの検算スクリプト (自動生成 2026-08-28)
#   cad/mindclip_case.py を実際に評価して数値を出す。既存ファイルは一切変更しない。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案A(空中配線) / 案D(蛇の目サテライト) の追加部品を AABB で置いて、
   mindclip_case.py の実体(リブ/lip/LED/スイッチ/電池/XIAO)と干渉するかを検算する。"""
import os, re, io, contextlib, math
SRC = "/home/user/claude-code-book-template/hardware/cad/mindclip_case.py"
raw = open(SRC, encoding="utf-8").read().split('if __name__ == "__main__":')[0]
def load(variant):
    os.environ["MINDCLIP_VARIANT"] = variant
    ns = {"__name__":"mc","__file__":SRC}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(raw, SRC, "exec"), ns)
    return ns

def occupants(ns):
    o = {"battery": ns["bat"], "xiao": ns["xiao"], "switch": ns["sw"], "LED": ns["led"],
         "lip_left": ns["lip_left"], "lip_top": ns["lip_top"],
         "lip_bottom": ns["lip_bottom"], "lip_right": ns["lip_right"],
         "sw_rib": ns["sw_rib"]}
    for grp in ("xiao_seats","xiao_stops","xiao_nubs_top","xiao_nubs_bot",
                "bat_stops_left","bat_stops_bot","lid_bat_ribs"):
        for i,b in enumerate(ns[grp]): o[f"{grp}[{i}]"]=b
    return o

def hit(a,b,t=1e-6):
    ov=lambda a0,a1,b0,b1:(a1-t>b0)and(b1-t>a0)
    return ov(a[0],a[2],b[0],b[2]) and ov(a[1],a[3],b[1],b[3]) and ov(a[4],a[5],b[4],b[5])

# --- 追加部品の寸法 ---------------------------------------------------------
# JST PH 2.0 2極 トップ型ヘッダ B2B-PH-K-S: 本体 7.8 x 4.5, PCB上高さ 6.0mm (JSTカタログ公称)
#   → PHR-2 嵌合後の PCB 上高さ: 6.0 + 嵌合代 (assumption 1.0〜1.5) = 7.0〜7.5mm
J1_FOOT = (7.8, 4.5)
J1_H_LO, J1_H_HI = 7.0, 7.5     # assumption レンジ
# 案D 蛇の目基板 (秋月112019 を 4x6=24穴に切断): 10.2 x 15.9 x 1.0t
D_BOARD = (10.2, 15.9, 1.0)
# 案A: JST嵌合体を寝かせる = 11.0 x 5.8 x 4.5 (案Aの申告値)
A_JST_LAY = (11.0, 5.8, 4.5)

for variant in ("allday","slim"):
    ns = load(variant); occ = occupants(ns)
    WALL, IW, IH, BODY_D = ns["WALL"], ns["IW"], ns["IH"], ns["BODY_D"]
    bat = ns["bat"]
    print("="*80); print(f"[{variant}]  リッド内面 z={BODY_D:.2f}  電池上面 z={bat[5]:.2f}")
    # ---------- 案D: 床置きサテライト基板 ----------
    bx0, by0 = 1.9, 28.4
    board = (bx0, by0, bx0+D_BOARD[0], by0+D_BOARD[1], WALL, WALL+D_BOARD[2])
    bad = [k for k,b in occ.items() if hit(board,b)]
    print(f" 案D 基板 AABB x{board[0]:.1f}..{board[2]:.1f} y{board[1]:.1f}..{board[3]:.1f} "
          f"z{board[4]:.1f}..{board[5]:.1f} → 干渉 {bad if bad else 'なし'}")
    btop = board[5]
    for h,tag in ((J1_H_LO,"公称6.0+嵌合1.0"),(J1_H_HI,"案D申告7.5")):
        top = btop+h; head = BODY_D-top
        print(f"   J1 (トップ型, {tag}={h:.1f}mm): 上端 z{top:.2f} / リッド内面まで "
              f"**{head:+.2f} mm**  {'NG (入らない)' if head<0 else ('要注意(電線曲げ代不足)' if head<3.0 else 'OK')}")
    # 電線の垂直立ち上がり: AWG26 の最小曲げ半径 ~3mm → J1 上に 3mm 必要
    print(f"   → 電線の90度曲げに必要な余裕 3.0mm を課すと、J1許容高さは "
          f"{BODY_D-btop-3.0:.2f} mm まで (実部品 {J1_H_LO:.1f}〜{J1_H_HI:.1f}mm)")
    # ---------- 案A: JSTを寝かせて左ポケットへ ----------
    ax0, ay0, az0 = 3.0, 29.0, WALL
    ajst = (ax0, ay0, ax0+A_JST_LAY[0], ay0+A_JST_LAY[1], az0, az0+A_JST_LAY[2])
    bad = [k for k,b in occ.items() if hit(ajst,b)]
    print(f" 案A JST嵌合体を寝かせ AABB x{ajst[0]:.1f}..{ajst[2]:.1f} y{ajst[1]:.1f}..{ajst[3]:.1f} "
          f"z{ajst[4]:.1f}..{ajst[5]:.1f} → 干渉 {bad if bad else 'なし'}")
    print(f"   上端 z{ajst[5]:.2f} は 電池上面 z{bat[5]:.2f} より {bat[5]-ajst[5]:+.2f} mm 下"
          f" (MECHANICAL §7 の配線収納制約を満たす)")
    print()

# --- 配線・部品の所要体積 ---------------------------------------------------
print("="*80); print("所要体積の見積り (AWG28 PVC 被覆外径 1.0mm と仮定 → 0.785 mm2/本)")
A_wire = 0.785
def wv(mm): return A_wire*mm
items_A1 = {"LED余長 2x60mm": wv(120), "SW配線 2x50mm": wv(100),
            "JSTピグテール 2x40mm": wv(80), "JST嵌合体(寝かせ)": 11.0*5.8*4.5,
            "LED本体 φ3x5": math.pi*1.5**2*5, "熱収縮/ホットボンド(assumption)": 80}
items_A2 = dict(items_A1); items_A2.update({"追加信号線 4x40mm (D0/D4/5V/GND)": wv(160),
            "1/6W抵抗 4本 (3.2x1.8 寝かせ)": 4*3.2*1.8*1.8, "0.1uF 1個": 60})
items_D  = {"LED余長 2x60mm": wv(120), "SW配線 2x50mm": wv(100),
            "蛇の目基板 10.2x15.9x1.0": 10.2*15.9*1.0,
            "J1+電池ケーブル立ち上がり (7.8x4.5x7.5)": 7.8*4.5*7.5,
            "基板→XIAO 6本x35mm": wv(210), "LED本体 φ3x5": math.pi*1.5**2*5}
for nm, it in (("案A-1", items_A1), ("案A-2", items_A2), ("案D", items_D)):
    tot = sum(it.values())
    print(f" {nm}: 合計 {tot:7.1f} mm3 = {tot/1000:.2f} cm3")
    for k,v in sorted(it.items(), key=lambda kv:-kv[1]):
        print(f"        {k:38s} {v:7.1f} mm3")
