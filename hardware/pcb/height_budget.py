#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案B (キャリア基板) の高さ予算検証スクリプト

hardware/cad/mindclip_case.py を「パラメータだけ差し替えて」読み込み直し、
キャリア基板を挟んだときの内寸奥行き ID / 外形奥行き TOTAL_D / 外形高さ H を
実数で出す。干渉チェック (check_layout) も各ケースで実行する。

キャリア基板を入れると XIAO 基板下面の高さは
    床 + PCB_LIFT (基板下のはんだ足逃げ) + PCB_T (基板厚)
になる。これは筐体CADの XIAO_LIFT (現行 1.4 = 裏面はんだ逃げ) を
    XIAO_LIFT' = PCB_LIFT + PCB_T
に置き換えるのと等価なので、その値を注入して再計算する。
(XIAO裏面 BAT パッドのはんだ盛りはキャリア基板側の窓 12x8mm に落とし込むので、
 1.4mm の逃げ空間は不要になる。窓の下は PCB_LIFT で確保する。)

さらに、キャステレーション用ランドを XIAO の長辺2列の外側に置く必要があるため
    GAP_BX (電池上端〜XIAO下端) と M_TOP (XIAO上端〜上壁)  ※採用値 1.8 / 1.7
を広げる案も同時に評価する。

実行: python3 hardware/pcb/height_budget.py
"""
import os
import re
import sys
import io
import contextlib

CAD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cad",
                                   "mindclip_case.py"))
SRC = open(CAD, encoding="utf-8").read()


def load_case(variant, xiao_lift=None, gap_bx=None, m_top=None):
    """mindclip_case.py をパラメータ差し替えで読み込む (main は走らせない)"""
    src = SRC
    if xiao_lift is not None:
        src = re.sub(r"^XIAO_LIFT = [0-9.]+", f"XIAO_LIFT = {xiao_lift}",
                     src, count=1, flags=re.M)
    if gap_bx is not None:
        src = re.sub(r"^GAP_BX = [0-9.]+", f"GAP_BX = {gap_bx}",
                     src, count=1, flags=re.M)
    if m_top is not None:
        src = re.sub(r"^M_TOP = [0-9.]+", f"M_TOP = {m_top}",
                     src, count=1, flags=re.M)
    os.environ["MINDCLIP_VARIANT"] = variant
    ns = {"__name__": "case_probe", "__file__": CAD}
    exec(compile(src, CAD, "exec"), ns)
    return ns


#: キャリア基板を入れると不要になる (= 基板シェルフ+位置決めボスに置換される) 内部リブ。
#: これらは筐体CADで y 座標が定数直書きのため、IH を変えると互いに衝突する。
#: (xiao_stops / sw_rib は USB 挿入反力とスイッチ保持で残すためここには入れない)
OBSOLETE_RIBS = ("xiao_seats", "xiao_nubs_top", "xiao_nubs_bot")


def probe(label, variant, xiao_lift=None, gap_bx=None, m_top=None,
          drop_ribs=False):
    ns = load_case(variant, xiao_lift, gap_bx, m_top)
    if drop_ribs:
        # キャリア基板がこれらの役割を引き継ぐ想定で外す
        for name in OBSOLETE_RIBS:
            ns[name] = [] if isinstance(ns[name], list) else \
                (-9e3, -9e3, -8.9e3, -8.9e3, -9e3, -8.9e3)
    buf = io.StringIO()
    ok, err = True, ""
    try:
        with contextlib.redirect_stdout(buf):
            ns["check_layout"]()
    except AssertionError as e:
        ok, err = False, str(e)
    return {
        "label": label, "variant": variant,
        "XIAO_LIFT": ns["XIAO_LIFT"], "GAP_BX": ns["GAP_BX"],
        "M_TOP": ns["M_TOP"],
        "ID_xiao_side": round(ns["XIAO_LIFT"] + ns["XIAO_STACK_T"] + 0.6, 2),
        "ID_bat_side": round(ns["BOSS_H"] + ns["BAT_T"] + 1.8, 2),
        "ID": ns["ID"], "IH": round(ns["IH"], 2),
        "W": round(ns["W"], 2), "H": round(ns["H"], 2),
        "BODY_D": round(ns["BODY_D"], 2), "TOTAL_D": round(ns["TOTAL_D"], 2),
        "lid_inner_z": round(ns["BODY_D"], 2),
        "xiao_top_z": round(ns["xiao"][5], 2),
        "ok": ok, "err": err,
    }


# --- 評価するスタック構成 -----------------------------------------------------
# PCB_LIFT: キャリア基板下面と床の隙間。JST/スイッチ/LED のスルーホール足を
#           面一に切ってもはんだフィレットで 0.5-0.6mm は出るため 0.8mm を確保。
PCB_LIFT = 0.8
CASES = [
    ("v1 (基板なし・現行)",            None),
    ("案B / PCB 0.8mm",                PCB_LIFT + 0.8),
    ("案B / PCB 1.0mm (推奨)",          PCB_LIFT + 1.0),
    ("案B / PCB 1.6mm (JLC既定)",       PCB_LIFT + 1.6),
    ("案B2 / 落とし込み(同一面)",        1.4),   # XIAO をカット穴に落として同一面化
]


def fmt(r):
    flag = "OK " if r["ok"] else "NG "
    return (f"  {flag}{r['label']:<26s} XIAO_LIFT={r['XIAO_LIFT']:<4} "
            f"ID(XIAO側)={r['ID_xiao_side']:<5} ID(電池側)={r['ID_bat_side']:<5} "
            f"→ ID={r['ID']:<5} 外形 {r['W']:.1f}x{r['H']:.1f}x{r['TOTAL_D']:.1f}"
            + ("" if r["ok"] else f"\n      assert: {r['err']}"))


def main():
    print("=" * 96)
    print("1) 奥行き(Z)予算 — キャリア基板を XIAO の下に挟んだ場合")
    print("   ID = max(XIAO側, 電池側)。XIAO側 = 基板下逃げ + PCB厚 + スタック7.5 + リッド余裕0.6")
    print("=" * 96)
    base = {}
    rows = []
    for variant in ("allday", "slim"):
        print(f"\n[{variant}]")
        for label, lift in CASES:
            r = probe(label, variant, xiao_lift=lift)
            rows.append(r)
            if label.startswith("v1"):
                base[variant] = r
            print(fmt(r))
        b = base[variant]
        for r in rows:
            if r["variant"] != variant or r is b:
                continue
            d = r["TOTAL_D"] - b["TOTAL_D"]
            print(f"      → 奥行き差 {d:+.1f} mm (v1 {b['TOTAL_D']:.1f} → {r['TOTAL_D']:.1f})")

    print()
    print("=" * 96)
    print("2) 高さ(Y)予算 — キャステレーション用ランドを XIAO 長辺の外に置けるか")
    print("   現行: XIAO上端〜上壁 M_TOP=0.6mm / 電池上端〜XIAO下端 GAP_BX=1.2mm")
    print("   キャリアのランドは基板端から 0.3mm 内側、ランド長は XIAO 外形から 1.0mm 必要")
    print("   → 片側 1.3mm 必要")
    print("=" * 96)
    need = 1.3
    for variant in ("allday", "slim"):
        print(f"\n[{variant}]")
        v1 = probe("v1", variant)
        top_v, bot_v = v1["M_TOP"], v1["GAP_BX"]
        top_msg = "足りる" if top_v >= need else f"★不足 {need - top_v:.1f}mm"
        bot_msg = "足りる" if bot_v >= need else f"★不足 {need - bot_v:.1f}mm"
        print(f"  v1: 上側余裕 {top_v:.1f}mm (必要 {need}) {top_msg}")
        print(f"      下側余裕 {bot_v:.1f}mm (必要 {need}) {bot_msg}")
        for lbl, gb, mt in (("最小拡大", 1.7, 1.3), ("推奨拡大(採用値)", 1.8, 1.7)):
            r = probe(f"案B {lbl}", variant, xiao_lift=PCB_LIFT + 1.0,
                      gap_bx=gb, m_top=mt)
            print(f"  {'OK ' if r['ok'] else 'NG '}{lbl}: GAP_BX={gb} M_TOP={mt} "
                  f"→ IH={r['IH']:.1f} 外形 {r['W']:.1f}x{r['H']:.1f}x{r['TOTAL_D']:.1f} "
                  f"(高さ {r['H'] - v1['H']:+.1f}mm)")
            if not r["ok"]:
                print(f"      assert: {r['err']}")
                r2 = probe(f"案B {lbl}", variant, xiao_lift=PCB_LIFT + 1.0,
                           gap_bx=gb, m_top=mt, drop_ribs=True)
                print(f"      → 旧内部リブ ({', '.join(OBSOLETE_RIBS)}) を"
                      f"キャリア基板シェルフに置換すると: "
                      f"{'OK (干渉なし)' if r2['ok'] else 'NG ' + r2['err']}")

    print()
    print("=" * 96)
    print("3) キャリア基板上に載る部品の高さ余裕 (推奨構成: PCB 1.0mm, PCB_LIFT 0.8)")
    print("=" * 96)
    for variant in ("allday", "slim"):
        r = probe("B", variant, xiao_lift=PCB_LIFT + 1.0, gap_bx=1.8, m_top=1.7)
        ns = load_case(variant, PCB_LIFT + 1.0, 1.8, 1.7)
        pcb_top = ns["WALL"] + PCB_LIFT + 1.0
        head = ns["BODY_D"] - pcb_top
        print(f"\n[{variant}] キャリア上面 z={pcb_top:.1f} / リッド内面 z={ns['BODY_D']:.1f} "
              f"→ 実装可能高さ {head:.1f} mm")
        for name, h in (("JST B2B-PH-K-S (H6.0)", 6.0),
                        ("  + PHR-2 嵌合代 (assumption +1.0)", 7.0),
                        ("0805 チップ抵抗 (H0.6)", 0.6),
                        ("AO3401A SOT-23 (H1.1)", 1.1),
                        ("XIAO スタック (7.5)", 7.5)):
            print(f"    {'OK' if h <= head else '★NG'}  {name:<36s} 余裕 {head - h:+.1f} mm")

    print()
    print("=" * 96)
    print("結論サマリ")
    print("=" * 96)
    for variant in ("allday", "slim"):
        b = probe("v1", variant)
        r10 = probe("B1.0", variant, xiao_lift=PCB_LIFT + 1.0)
        r16 = probe("B1.6", variant, xiao_lift=PCB_LIFT + 1.6)
        ry = probe("B1.0+Y拡大", variant, xiao_lift=PCB_LIFT + 1.0,
                   gap_bx=1.8, m_top=1.7)
        print(f"[{variant}] v1={b['W']:.1f}x{b['H']:.1f}x{b['TOTAL_D']:.1f}  "
              f"PCB1.0mm→{r10['TOTAL_D']:.1f} (奥行 {r10['TOTAL_D'] - b['TOTAL_D']:+.1f})  "
              f"PCB1.6mm→{r16['TOTAL_D']:.1f} ({r16['TOTAL_D'] - b['TOTAL_D']:+.1f})  "
              f"ランド確保のY拡大込み→{ry['W']:.1f}x{ry['H']:.1f}x{ry['TOTAL_D']:.1f} "
              f"(高さ {ry['H'] - b['H']:+.1f})")


if __name__ == "__main__":
    main()
