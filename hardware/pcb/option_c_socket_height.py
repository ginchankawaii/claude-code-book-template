#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案C (キャリア基板 + ピンソケットで XIAO を着脱可能にする) の高さ検証スクリプト

問い: 「XIAO をソケットに載せると筐体に入るのか。入らないなら何mm厚くなるのか」
方法: 筐体CAD (hardware/cad/mindclip_case.py) をパラメータ差し替えで読み込み直し、
      干渉チェック (check_layout) を各構成で実行して外形寸法を実数で出す。

モデル化:
    XIAO 基板下面の高さ = 床 + STANDOFF + PCB_T + GAP_B2B
      STANDOFF : キャリア基板下面〜床 (ソケットのスルーホール足を切り詰めた残り)
      PCB_T    : キャリア基板厚
      GAP_B2B  : キャリア基板上面〜XIAO 基板下面 (= コネクタの嵌合高さ)
    これは筐体CADの XIAO_LIFT (現行 1.4 = 裏面はんだ逃げ) を
        XIAO_LIFT' = STANDOFF + PCB_T + GAP_B2B
    に置き換えるのと等価。XIAO 裏面のはんだ盛り・BAT リードの逃げは
    GAP_B2B (>= 3.9mm) がそのまま担うので 1.4mm の逃げは不要になる。

    GAP_B2B の内訳 (実部品の寸法。出典は OPTION_C_socket_carrier.md §2):
      標準ピンヘッダー ハウジング 2.5mm + 低メスソケット ハウジング 3.6mm = 6.1mm
      細ピンヘッダー   ハウジング 2.0mm + 丸ピンソケット   (assumption 3.0)  = 5.0mm
      裸ピン (樹脂なし)              + 低メスソケット 3.6mm + フィレット0.3 = 3.9mm

実行:
    python3 hardware/pcb/option_c_socket_height.py
"""
import contextlib
import io
import os
import re
import sys

CAD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cad",
                                   "mindclip_case.py"))
SRC = open(CAD, encoding="utf-8").read()


def load_case(variant, xiao_lift=None, iw=None):
    """mindclip_case.py をパラメータ差し替えで読み込む (__main__ は走らせない)"""
    src = SRC
    if xiao_lift is not None:
        src = re.sub(r"^XIAO_LIFT = [0-9.]+", f"XIAO_LIFT = {xiao_lift}",
                     src, count=1, flags=re.M)
    if iw is not None:
        src = re.sub(r"^IW = [0-9.]+", f"IW = {iw}", src, count=1, flags=re.M)
    os.environ["MINDCLIP_VARIANT"] = variant
    ns = {"__name__": "option_c_probe", "__file__": CAD}
    exec(compile(src, CAD, "exec"), ns)
    return ns


def probe(label, variant, standoff, pcb_t, gap, iw=None, note=""):
    lift = None if standoff is None else round(standoff + pcb_t + gap, 2)
    ns = load_case(variant, xiao_lift=lift, iw=iw)
    buf = io.StringIO()
    ok, err = True, ""
    try:
        with contextlib.redirect_stdout(buf):
            ns["check_layout"]()
    except AssertionError as e:
        ok, err = False, str(e)
    return dict(label=label, variant=variant, lift=ns["XIAO_LIFT"],
                ID=ns["ID"], W=ns["W"], H=ns["H"], D=ns["TOTAL_D"],
                ok=ok, err=err, note=note)


#: (ラベル, standoff, PCB厚, 基板間ギャップ, 注記)
CASES = [
    ("v1 現行 (直はんだ・キャリア無し)", None, None, None,
     "基準: XIAO_LIFT=1.4"),
    ("C-a  標準ピンヘッダ+低メス / PCB1.6", 0.6, 1.6, 6.1,
     "秋月 100167 (H2.5) + 103138 (H3.6)"),
    ("C-a' 標準ピンヘッダ+低メス / PCB1.0", 0.6, 1.0, 6.1,
     "PCB を 1.0mm 指定にして節約"),
    ("C-b  細ピンヘッダ+丸ピンソケット",    0.6, 1.0, 5.0,
     "秋月 106631 (H2.0) + 丸ピン (H3.0=assumption)"),
    ("C-c  裸ピン+低メス (上級者向け)",     0.6, 1.0, 3.9,
     "樹脂を使わず 0.64mm 角ピンを直はんだ"),
    ("C-d  裸ピン+低メス / PCB0.8 / 台座0.3", 0.3, 0.8, 3.9,
     "案Cの理論下限"),
]


def main():
    rows = []
    for variant in ("allday", "slim"):
        for label, so, t, g, note in CASES:
            rows.append(probe(label, variant, so, t, g, note=note))

    base = {r["variant"]: r["D"] for r in rows if r["lift"] == 1.4}
    print("=" * 96)
    print("案C: キャリア基板 + ピンソケットにしたときの筐体外形 (CAD の check_layout 実行結果)")
    print("=" * 96)
    hdr = (f"{'構成':<38}{'variant':<8}{'lift':>6}{'内寸ID':>8}"
           f"{'外形D':>8}{'Δ':>7}  判定")
    print(hdr)
    print("-" * 96)
    for r in rows:
        d = r["D"] - base[r["variant"]]
        print(f"{r['label']:<38}{r['variant']:<8}{r['lift']:6.2f}{r['ID']:8.2f}"
              f"{r['D']:8.2f}{d:+7.2f}  {'OK' if r['ok'] else 'NG'}")
        if not r["ok"]:
            print(f"    !! {r['err']}")
    print("-" * 96)

    # 副作用1: 案Cでは XIAO 側が内寸奥行きを支配するので slim / allday の差が消える
    a = [r for r in rows if r["variant"] == "allday" and r["lift"] != 1.4]
    s = [r for r in rows if r["variant"] == "slim" and r["lift"] != 1.4]
    same = all(abs(x["D"] - y["D"]) < 1e-6 for x, y in zip(a, s))
    print(f"[副作用] キャリア導入後 allday と slim の外形奥行きが同一か: {same}")
    print("         -> True の場合、slim バリアント (薄さが唯一の存在理由) は意味を失う。")

    # 副作用2: 内寸奥行きが増えると電池上面がリッド lip 帯から z 方向に逃げるので
    #          v1.4 で 34.0->34.8 に広げた内寸幅を元に戻せる (幅は 2.2mm 縮む)
    narrow = probe("C-a' + 内寸幅 32.6 に縮小", "allday", 0.6, 1.0, 6.1, iw=32.6)
    print(f"[副作用] {narrow['label']}: 外形 {narrow['W']:.1f} x {narrow['H']:.1f} "
          f"x {narrow['D']:.1f} mm  判定 {'OK' if narrow['ok'] else 'NG'}")
    print("         -> 奥行きが増える代わりに幅は 38.0->35.8mm に戻せる (トレードオフ)。")

    # USB-C 挿入反力がソケットを引き剥がすモーメントの概算
    r = [x for x in rows if x["label"].startswith("C-a'")
         and x["variant"] == "allday"][0]
    ns = load_case("allday", xiao_lift=r["lift"])
    z_board = ns["WALL"] + ns["XIAO_LIFT"]                    # XIAO 基板下面
    z_usb = ns["USB_Z0"] + ns["USB_OPEN_H"] / 2.0             # USB-C 開口中心
    z_socket_mid = (ns["WALL"] + 0.3 + 1.0 + z_board) / 2.0   # ソケット嵌合中心
    arm = z_usb - z_socket_mid
    span = 15.24                                              # ピン列 7P スパン
    for F in (5.0, 20.0):
        couple = F * arm / span
        print(f"[リスク] USB-C 挿入力 {F:4.1f}N -> てこ腕 {arm:.2f}mm, "
              f"片列7ピンを引き抜く力 {couple:5.2f}N "
              f"(7ピンの保持力は 3.5~14N=assumption)")


if __name__ == "__main__":
    sys.exit(main())
