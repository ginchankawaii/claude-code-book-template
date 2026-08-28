# [mechanical 審査用] 案A/B/C/D が筐体に入るかの検算スクリプト (自動生成 2026-08-28)
#   cad/mindclip_case.py を実際に評価して数値を出す。既存ファイルは一切変更しない。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""左ポケット(XIAO左のデッドスペース)の実効自由体積をボクセルで実測し、
   案A(空中配線+JST)/案D(蛇の目サテライト)が本当に入るかを検算する。"""
import os, re, io, contextlib, numpy as np
SRC = "/home/user/claude-code-book-template/hardware/cad/mindclip_case.py"
raw = open(SRC, encoding="utf-8").read().split('if __name__ == "__main__":')[0]

def load(variant, overrides=None):
    os.environ["MINDCLIP_VARIANT"] = variant
    src = raw
    for k, v in (overrides or {}).items():
        src = re.sub(r"^(%s\s*=\s*)([^\n#]*)" % re.escape(k),
                     lambda m: m.group(1)+v, src, count=1, flags=re.M)
    ns = {"__name__": "mc", "__file__": SRC}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(src, SRC, "exec"), ns)
    return ns

STEP = 0.1  # mm ボクセル
for variant in ("allday", "slim"):
    ns = load(variant)
    W, IW, IH, WALL, BODY_D = ns["W"], ns["IW"], ns["IH"], ns["WALL"], ns["BODY_D"]
    xiao, bat, sw, led = ns["xiao"], ns["bat"], ns["sw"], ns["led"]
    # 左ポケット = キャビティのうち x<XIAO左ストップリブ左端, y>電池上端, z=床..リッド内面
    px0, px1 = WALL, ns["xiao_stops"][0][0]
    py0, py1 = bat[3], WALL + IH
    pz0, pz1 = WALL, BODY_D
    xs = np.arange(px0 + STEP/2, px1, STEP)
    ys = np.arange(py0 + STEP/2, py1, STEP)
    zs = np.arange(pz0 + STEP/2, pz1, STEP)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    free = np.ones(X.shape, bool)
    # 既存の占有物 (mindclip_case.py が持つ AABB をそのまま使う)
    occ = {"lip_left": ns["lip_left"], "lip_top": ns["lip_top"],
           "lip_bottom": ns["lip_bottom"], "sw_rib": ns["sw_rib"],
           "switch": sw, "LED本体": led}
    for i, b in enumerate(ns["xiao_stops"]):  occ[f"xstop{i}"] = b
    for i, b in enumerate(ns["bat_stops_left"]): occ[f"bstop_l{i}"] = b
    for i, b in enumerate(ns["xiao_nubs_top"]):  occ[f"xnub_t{i}"] = b
    for i, b in enumerate(ns["xiao_nubs_bot"]):  occ[f"xnub_b{i}"] = b
    detail = {}
    for name, b in occ.items():
        m = ((X>b[0])&(X<b[2])&(Y>b[1])&(Y<b[3])&(Z>b[4])&(Z<b[5]))
        detail[name] = m.sum()*STEP**3/1000.0
        free &= ~m
    # 内側コーナーR2.5 の削り (キャビティ左上/左下コーナー)
    for (cx, cy) in [(WALL+2.5, WALL+IH-2.5), (WALL+2.5, WALL+2.5)]:
        out = ((X<cx)&(Y>cy) if cy>WALL+IH/2 else (X<cx)&(Y<cy))
        rr = (X-cx)**2 + (Y-cy)**2 > 2.5**2
        free &= ~(out & rr)
    raw_v = xs.size*ys.size*zs.size*STEP**3/1000.0
    print(f"[{variant}] 左ポケット素の体積 {raw_v:.2f} cm3 "
          f"(x{px0:.1f}..{px1:.1f} y{py0:.1f}..{py1:.1f} z{pz0:.1f}..{pz1:.1f})")
    for k, v in sorted(detail.items(), key=lambda kv:-kv[1]):
        if v > 0.001: print(f"          -{k:10s} {v:.3f} cm3")
    fv = free.sum()*STEP**3/1000.0
    print(f"          => 実効自由体積 **{fv:.2f} cm3**")
    # z 制限つき自由体積 (MECHANICAL §7: リード・余長は電池上面より下 に収める)
    zlim = bat[5]
    fz = (free & (Z < zlim)).sum()*STEP**3/1000.0
    print(f"          => うち『電池上面 z<{zlim:.1f} 以下』に収めねばならない分 **{fz:.2f} cm3** "
          f"(MECHANICAL §7 の配線収納制約)")
    print()
