#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MindClip DIY — netlist.json から .kicad_pcb / layout.png / layout_top.svg を生成する。

============================================================================
 【重要】この基板は v1.5 では使わない
============================================================================
採用案は **案A-1（ハーネス v1.5・キャリア基板を作らない）** である。
本スクリプトが生成する2枚の基板は、どちらも
`netlist.json` の `V2_SENSE_SATELLITE`（= SCHEMATIC.md §9）に属する
**v2 用の設計データ**であり、SCHEMATIC.md §9.4 の離脱ゲートを通過し、
かつ XIAO スタック総厚の実測が終わるまで発注してはならない。

  - v1.5 を組む人は SCHEMATIC.md §1〜§5 だけを読むこと。
  - 空中配線での分圧追加（案A-2）は禁止（SCHEMATIC.md §0.1）。
    VBUS検出・電池監視が必要になったら、空中配線ではなく本基板に載せる。

生成物:
  mindclip_sense.kicad_pcb    MC-SENSE-A   サテライト基板（推奨・筐体無改造）
  mindclip_carrier.kicad_pcb  MC-CARRIER-A キャリア基板（XIAO直載せ・筐体改造必須）
  gerber/<board>/*.gbr        Gerber RS-274X（銅2層・レジスト2層・ペースト・シルク2層・外形）
  gerber/<board>/*.drl        Excellon ドリル（PTH / NPTH）
  gerber/<board>/*-bom.csv    BOM（JLCPCB 形式。LCSC 品番は未記入＝要記入）
  gerber/<board>/*-cpl.csv    実装座標（JLCPCB 形式）
  layout.png                  部品配置図（寸法注記つき・2面）
  layout_top.svg              実寸(1:1)の配置図

KiCad はこの環境に無いため、S式も Gerber も**同じ内部データ構造から直接**
書き出す。フットプリントは**ファイル内にインライン定義**しているので、
利用者側のライブラリの有無に依存せず開ける。
ライブラリ名は `MindClip:` 名前空間（インライン定義の寸法が KiCad 標準と
一致していなかったため、標準名を名乗るのをやめた。§3 の注記を参照）。

============================================================================
 【重要】実行ログの `[done] independent-DRC errors=0` を「検証済み」と読まない
============================================================================
本スクリプトの `validate_pcb()` は、全銅箔（パッド／トラック／ビア）を幾何
プリミティブに落として異ネット総当たりでクリアランスを見る独立 DRC である
（2026-08-28 に全面拡張。旧版は track↔track / track↔via / track↔pad /
via↔via / via↔pad と、track・via の対外形距離を**一切見ていなかった**）。
しかしこれは **KiCad 本体の DRC でも、製造業者の DFM でもない**。
発注前に必ず KiCad で開いて DRC を通すこと（LAYOUT.md §9.3）。

実行:  python3 gen_pcb.py
"""
import json
import math
import re
import os
import sys
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
NETLIST = os.path.join(HERE, "netlist.json")

# ---------------------------------------------------------------------------
# 0. 筐体寸法の取得（cad/mindclip_case.py を import して実値を使う）
# ---------------------------------------------------------------------------
CASE_FALLBACK = {
    # 2026-08-28 に mindclip_case.py を実行して得た値（check_layout PASS）
    "allday": dict(W=38.0, H=49.4, TOTAL_D=14.6, BODY_D=12.8, IW=34.8, IH=46.2,
                   ID=11.2, WALL=1.6, XIAO_LIFT=1.4, XIAO_STACK_T=7.5,
                   GAP_BX=1.2, M_TOP=0.6,
                   bat=(4.0, 3.2, 34.0, 28.2, 3.0, 11.0),
                   xiao=(15.4, 29.4, 36.4, 47.2, 3.0, 10.5),
                   sw=(4.0, 45.0, 12.7, 48.5, 5.35, 9.05),
                   led=(5.3, 34.4, 8.5, 37.6, 8.8, 12.8), LED_POS=(6.9, 36.0),
                   xiao_stops=((12.4, 31.0, 15.25, 35.0, 1.6, 8.1),
                               (12.4, 40.0, 15.25, 44.0, 1.6, 8.1)),
                   sw_rib=(2.9, 44.6, 3.7, 47.8, 1.6, 8.4),
                   lip_left=(1.75, 1.75, 2.75, 47.65, 10.6, 12.8),
                   USB_CY=38.3, USB_Z0=3.8),
    "slim": dict(W=38.0, H=49.4, TOTAL_D=12.9, BODY_D=11.1, IW=34.8, IH=46.2,
                 ID=9.5, WALL=1.6, XIAO_LIFT=1.4, XIAO_STACK_T=7.5,
                 GAP_BX=1.2, M_TOP=0.6,
                 bat=(4.0, 3.2, 34.0, 28.2, 3.0, 8.0),
                 xiao=(15.4, 29.4, 36.4, 47.2, 3.0, 10.5),
                 sw=(4.0, 45.0, 12.7, 48.5, 4.5, 8.2),
                 led=(5.3, 34.4, 8.5, 37.6, 7.1, 11.1), LED_POS=(6.9, 36.0),
                 xiao_stops=((12.4, 31.0, 15.25, 35.0, 1.6, 8.1),
                             (12.4, 40.0, 15.25, 44.0, 1.6, 8.1)),
                 sw_rib=(2.9, 44.6, 3.7, 47.8, 1.6, 8.4),
                 lip_left=(1.75, 1.75, 2.75, 47.65, 8.9, 11.1),
                 USB_CY=38.3, USB_Z0=3.8),
}


def load_case():
    """cad/mindclip_case.py を両バリアントで import し、実値を返す。
    cadquery が無い等で失敗したら CASE_FALLBACK を使う（警告つき）。"""
    out = {}
    cad = os.path.join(HW, "cad")
    sys.path.insert(0, cad)
    for v in ("allday", "slim"):
        try:
            os.environ["MINDCLIP_VARIANT"] = v
            sys.modules.pop("mindclip_case", None)
            import mindclip_case as M  # noqa
            M.check_layout()
            out[v] = dict(
                W=M.W, H=M.H, TOTAL_D=M.TOTAL_D, BODY_D=M.BODY_D, IW=M.IW,
                IH=M.IH, ID=M.ID, WALL=M.WALL, XIAO_LIFT=M.XIAO_LIFT,
                XIAO_STACK_T=M.XIAO_STACK_T, GAP_BX=M.GAP_BX, M_TOP=M.M_TOP,
                bat=tuple(M.bat), xiao=tuple(M.xiao), sw=tuple(M.sw),
                led=tuple(M.led), LED_POS=tuple(M.LED_POS),
                xiao_stops=tuple(tuple(s) for s in M.xiao_stops),
                sw_rib=tuple(M.sw_rib), lip_left=tuple(M.lip_left),
                USB_CY=M.USB_CY, USB_Z0=M.USB_Z0)
            out[v + "_src"] = "cad/mindclip_case.py (live import, check_layout PASS)"
        except Exception as e:                                  # pragma: no cover
            print(f"[warn] mindclip_case import failed for {v}: {e}")
            out[v] = CASE_FALLBACK[v]
            out[v + "_src"] = "CASE_FALLBACK (hardcoded 2026-08-28 run)"
    sys.path.pop(0)
    return out


# ---------------------------------------------------------------------------
# 1. 製造ルール（JLCPCB 2層・標準プロセス）
# ---------------------------------------------------------------------------
DRC = dict(
    min_track=0.127,        # JLCPCB 絶対最小 5mil
    min_clear=0.127,        # 同 最小間隔
    min_drill=0.30,         # 同 最小穴径
    min_annular=0.13,       # 同 最小アニュラリング
    min_copper_edge=0.30,   # 銅箔〜基板外形（JLCPCB 推奨 0.3）
    min_hole_edge=0.30,     # 穴〜基板外形
    use_track=0.30,         # 本設計の採用線幅（電源）
    use_track_sig=0.25,     # 同（信号）
    use_drill=0.75,         # 本設計の採用穴径（JST PH ピン。KiCad 標準と同値）
    min_silk=0.15,          # JLCPCB シルク最小線幅
    use_via_drill=0.40,     # 本設計の採用ビア穴径
    use_via=0.80,           # 同 ビアランド径
    use_clear=0.25,         # 本設計の設計クリアランス
)

LAYERS = [
    (0, "F.Cu", "signal"), (31, "B.Cu", "signal"),
    (32, "B.Adhes", "user", "B.Adhesive"), (33, "F.Adhes", "user", "F.Adhesive"),
    (34, "B.Paste", "user"), (35, "F.Paste", "user"),
    (36, "B.SilkS", "user", "B.Silkscreen"), (37, "F.SilkS", "user", "F.Silkscreen"),
    (38, "B.Mask", "user"), (39, "F.Mask", "user"),
    (40, "Dwgs.User", "user", "User.Drawings"),
    (41, "Cmts.User", "user", "User.Comments"),
    (42, "Eco1.User", "user", "User.Eco1"), (43, "Eco2.User", "user", "User.Eco2"),
    (44, "Edge.Cuts", "user"), (45, "Margin", "user"),
    (46, "B.CrtYd", "user", "B.Courtyard"), (47, "F.CrtYd", "user", "F.Courtyard"),
    (48, "B.Fab", "user"), (49, "F.Fab", "user"),
]

_uid = [0]


def uuid():
    _uid[0] += 1
    h = hashlib.md5(f"mindclip-{_uid[0]}".encode()).hexdigest()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def f(v):
    return f"{v:.4f}".rstrip("0").rstrip(".") if v != 0 else "0"


# ---------------------------------------------------------------------------
# 2. 座標系
#    筐体座標 (x右 / y上 / 原点=body外形の左下) → KiCad座標 (x右 / y下)
# ---------------------------------------------------------------------------
KX0, KY0 = 30.0, 120.0        # KiCad ページ上のオフセット


def K(x, y):
    return (KX0 + x, KY0 - y)


def KROT(deg):
    """筐体座標での反時計回り角 → KiCad の角度（KiCadはY下だが角度はCCW表記）"""
    return deg % 360


# ---------------------------------------------------------------------------
# 3. フットプリント定義
#    pads: (番号, 種別, 形状, (lx,ly), (sx,sy), drill, ネット名)
#      lx,ly はフットプリント原点からのローカル座標（未回転）
#
#    【ライブラリ名について（2026-08-28 訂正）】
#    以前は KiCad 標準ライブラリ名（Resistor_SMD:R_0805_2012Metric 等）を
#    そのまま名乗っていたが、インライン定義の寸法が標準フットプリントと
#    一致していなかった（パッド位置 ±0.9375 vs 実物 ±0.9125、コートヤード
#    2.90x1.70 vs 実物 3.36x1.90、JST は穴 φ0.90 vs 実物 φ0.75 など）。
#    「標準名を名乗るが中身は別物」は追跡性をむしろ壊すため、
#    **全て `MindClip:` 名前空間に改め、寸法は標準に合わせて訂正**した。
#    各フットプリントの descr に「相当する KiCad 標準フットプリント名」を書く。
#    なお `MountingHole:MountingHole_2.2mm` は KiCad 標準に**実在しない**
#    （正しくは MountingHole_2.2mm_M2）。これも訂正済み。
# ---------------------------------------------------------------------------
SILK_W = 0.15          # JLCPCB シルク最小線幅（0.12 では欠ける）


def fp_0805(ref, val, net1, net2, kind="R"):
    """0805(2012M) チップ。寸法は KiCad 標準 R_0805_2012Metric に一致させた:
       パッド (at ±0.9125 0) size 1.025 x 1.40 / コートヤード 3.36 x 1.90 /
       シルクはパッド間の短い横線2本（±0.735）→ silk-on-pad が原理的に起きない。
       コンデンサは C_0805_2012Metric に合わせ コートヤードのみ 3.40 x 1.96。"""
    cy = (3.40, 1.96) if kind == "C" else (3.36, 1.90)
    std = "Capacitor_SMD:C_0805_2012Metric" if kind == "C" \
        else "Resistor_SMD:R_0805_2012Metric"
    return dict(lib=f"MindClip:{'C' if kind == 'C' else 'R'}_0805_2012Metric_MC",
                std=std, ref=ref, value=val, attr="smd",
                crtyd=cy,
                fab=[((-1.0, -0.625), (1.0, 0.625))],
                silk=[((-0.227, -0.735), (0.227, -0.735)),
                      ((-0.227, 0.735), (0.227, 0.735))],
                pads=[("1", "smd", "rect", (-0.9125, 0.0), (1.025, 1.40), None, net1),
                      ("2", "smd", "rect", (0.9125, 0.0), (1.025, 1.40), None, net2)])


def fp_jst_ph2(ref, net1, net2):
    """JST PH 2.0mm 2P トップエントリ THT (B2B-PH-K-S)。
    穴径 φ0.75 / パッド 1.20 x 1.75 は KiCad 標準
    Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical に一致させた値。
    以前の φ0.90 は 0.5mm角ポストに対してガタが大きすぎた。
    原点はピン列の中央（=フットプリント配置座標がピン中心になる）。
    本体 7.9(X) x 4.5(Y)（B2B-PH-K-S 2P: A=2.0, B=A+5.9=7.9）。
    嵌合高さ 7.5mm と嵌合体の実寸は **assumption**（§11 参照。現物のノギス実測前提）。
    bend_z 2.4mm = AWG28 (外径1.2mm) の最小曲げ半径 2xOD。嵌合体の上に必要な空間。"""
    return dict(lib="MindClip:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical_MC",
                std="Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
                ref=ref, value="JST_PH_2P", attr="through_hole",
                crtyd=(8.40, 5.00), crtyd_off=(0.0, 0.55), body_z=7.5, bend_z=2.4,
                fab=[((-3.95, -1.70), (3.95, 2.80))],
                silk=[((-3.95, -1.70), (3.95, -1.70)), ((-3.95, 2.80), (3.95, 2.80)),
                      ((-3.95, -1.70), (-3.95, 2.80)), ((3.95, -1.70), (3.95, 2.80))],
                pads=[("1", "thru_hole", "rect", (-1.0, 0.0), (1.20, 1.75), 0.75, net1),
                      ("2", "thru_hole", "oval", (1.0, 0.0), (1.20, 1.75), 0.75, net2)])


def fp_testpoint(ref, net, d=1.50):
    return dict(lib="MindClip:TestPoint_Pad_D1.5mm_MC",
                std="TestPoint:TestPoint_Pad_D1.5mm",
                ref=ref, value="TP",
                attr="smd", crtyd=(d + 0.4, d + 0.4), fab=[], silk=[],
                pads=[("1", "smd", "circle", (0.0, 0.0), (d, d), None, net)])


def fp_mount(ref, d=2.20):
    """NPTH。KiCad 標準の該当名は MountingHole_2.2mm_M2（2.2mm 単体は実在しない）。"""
    return dict(lib=f"MindClip:MountingHole_{d:.1f}mm_M2_MC",
                std=f"MountingHole:MountingHole_{d:.1f}mm_M2",
                ref=ref, value=f"MountingHole_{d:.1f}mm", attr="through_hole",
                crtyd=(d + 1.0, d + 1.0), fab=[], silk=[],
                pads=[("", "np_thru_hole", "circle", (0.0, 0.0), (d, d), d, None)])


def fp_xiao(ref, nets):
    """XIAO ESP32S3 (Sense) カステレーション受けランド 2x7 / P2.54 / 列間 17.78mm。
    ★ このフットプリント寸法は assumption。発注前に Seeed 公式 KiCad ライブラリ
      (Seeed-Studio/OPL_Kicad_Library) の XIAO フットプリントと必ず突き合わせること。
      列間 17.78mm(=7x2.54) は外形幅 17.8mm と整合するが実測未検証。
      （案C が使っていた 15.24mm は「7ピンの列方向スパン」であって列間ではない。）"""
    PITCH, ROWSP = 2.54, 17.78
    LAND_W, LAND_L, OUT = 1.60, 1.80, 0.40   # 幅 / 長さ / 外側オフセット
    pads = []
    # 下列(pad 8..14: D7,D8,D9,D10,3V3,GND,5V) / 上列(pad 1..7: D0..D6)
    order_bot = ["D7", "D8", "D9", "D10", "3V3", "GND", "5V"]
    order_top = ["D6", "D5", "D4", "D3", "D2", "D1", "D0"]
    for i, nm in enumerate(order_bot):
        x = (i - 3) * PITCH
        pads.append((nm, "smd", "rect", (x, ROWSP / 2 + OUT), (LAND_W, LAND_L),
                     None, nets.get(nm)))
    for i, nm in enumerate(order_top):
        x = (i - 3) * PITCH
        pads.append((nm, "smd", "rect", (x, -(ROWSP / 2 + OUT)), (LAND_W, LAND_L),
                     None, nets.get(nm)))
    return dict(lib="MindClip:XIAO_ESP32S3_Castellated_2x7_P2.54mm", std=None,
                ref=ref, value="XIAO ESP32S3 Sense", attr="smd",
                crtyd=(21.4, 18.2), body_z=7.5,
                fab=[((-10.5, -8.9), (10.5, 8.9))],
                # シルクはランド内端(±8.39)より内側、かつ基板端の内側へ引く
                silk=[((-10.1, -8.1), (10.1, -8.1)), ((-10.1, 8.1), (10.1, 8.1)),
                      ((-10.1, -8.1), (-10.1, 8.1))],
                pads=pads)


def fp_wirepads_smd(ref, cells, nets, pw=2.0, ph=1.0):
    """AWG28 を直接はんだ付けする SMD ランド（ピンヘッダを挿さない = 追加高さ 0）。
    cells = [(lx, ly), ...] ローカル座標。"""
    pads = [(str(i + 1), "smd", "rect", c, (pw, ph), None, nets[i])
            for i, c in enumerate(cells)]
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    w = max(xs) - min(xs) + pw + 0.4
    h = max(ys) - min(ys) + ph + 0.4
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return dict(lib="MindClip:WireLand_SMD", std=None, ref=ref,
                value=f"WIRE x{len(cells)}",
                attr="smd", crtyd=(w, h), crtyd_off=(cx, cy), fab=[], silk=[],
                pads=pads)


# ---------------------------------------------------------------------------
# 4. 基板定義
# ---------------------------------------------------------------------------
def build_sense_board(case):
    """MC-SENSE-A: 案D のサテライト基板を製造基板化したもの。
    左ポケット床（XIAO の左のデッドスペース）に寝かせる。筐体CAD変更ゼロ。

    配置方針（2026-08-28 レイアウト全面見直し）:
      - 0805 は 2列 x 3行。列 x=3.8 / x=7.4（パッド左端 2.375 で 銅箔-外形 0.375mm 確保）。
        行 y=35.0 / 37.5 / 40.0（行間 2.5mm。コートヤード高 1.96 に対し 0.54mm 余裕）。
      - 右側 x 8.9..12.0 を「縦の配線レーン」として空ける（ビアも置ける幅）。
      - J1 は下端、J2（XIAOへ出る6本のワイヤランド）は上端。
      - J2 の6ランドは **そのままテストポイントを兼ねる**（TP を別に置く余地が無いため）。
    """
    a = case["allday"]
    # 左ポケット床の利用可能域: x = 内壁1.6 .. xiao_stops[0].x0 12.4
    #                          y = 電池上端 28.2 .. sw_rib.y0 44.6
    px0, px1 = a["WALL"], a["xiao_stops"][0][0]
    py0, py1 = a["bat"][3], a["sw_rib"][1]
    CL = 0.4                                     # 筐体ポケットとの片側クリアランス
    bx0, bx1 = px0 + CL, px1 - CL                # 2.0 .. 12.0
    by0, by1 = py0 + CL, py1 - CL                # 28.6 .. 44.2

    N = dict(GND="GND", BATP="BATP", BATN="BATN", VBUS="VBUS",
             VS="VBUS_SENSE", BS="VBAT_SENSE")
    CX = (4.2, 7.0, 9.8)                         # 0805 の3列（90度回転して縦置き）
    RY = (35.6, 39.4)                            # 0805 の2行
    fps = []
    # --- 電池コネクタ（トップエントリ。本体は -y 側＝電池側へ向ける）
    fps.append((("J1"), (7.0, 31.7), 0, fp_jst_ph2("J1", N["BATP"], N["BATN"])))
    # --- 電池電圧分圧（BATP -R4- VBAT_SENSE -R5- GND / C1 バイパス）
    fps.append((("R4"), (CX[0], RY[0]), 90, fp_0805("R4", "220k", N["BATP"], N["BS"])))
    fps.append((("R5"), (CX[1], RY[0]), 90, fp_0805("R5", "220k", N["BS"], N["GND"])))
    fps.append((("C1"), (CX[2], RY[0]), 90, fp_0805("C1", "100nF", N["BS"], N["GND"], "C")))
    # --- VBUS 分圧（VBUS -R2- VBUS_SENSE -R3- GND / C2 バイパス）
    fps.append((("R2"), (CX[0], RY[1]), 90, fp_0805("R2", "220k", N["VBUS"], N["VS"])))
    fps.append((("R3"), (CX[1], RY[1]), 90, fp_0805("R3", "330k", N["VS"], N["GND"])))
    fps.append((("C2"), (CX[2], RY[1]), 90, fp_0805("C2", "100nF", N["VS"], N["GND"], "C")))
    # --- XIAO へ出る6本のワイヤランド（SMD 一列。ヘッダは挿さない = 追加高さ 0）
    #     6ランドは **そのままテストポイントを兼ねる**（TP を別に置く余地が無い）
    cells = [(-3.75, 0.0), (-2.25, 0.0), (-0.75, 0.0),
             (0.75, 0.0), (2.25, 0.0), (3.75, 0.0)]
    nets6 = [N["BATN"], N["BATP"], N["BS"], N["VS"], N["VBUS"], N["GND"]]
    fps.append((("J2"), (7.0, 42.9), 0,
                fp_wirepads_smd("J2", cells, nets6, pw=1.0, ph=1.8)))

    labels = {
        "J1": "BAT (PH2.0)", "J2": "→XIAO / TP", "R2": "220k", "R3": "330k",
        "R4": "220k", "R5": "220k", "C1": "100n", "C2": "100n",
    }
    padlabels = {"J2": ["B-", "B+", "D4", "D0", "5V", "GND"],
                 "J1": ["+", "-"]}
    return dict(
        name="MC-SENSE-A", file="mindclip_sense.kicad_pcb",
        title="MindClip MC-SENSE-A (v2 sense satellite)",
        rect=(bx0, by0, bx1, by1), corner_r=0.8, thickness=0.8,
        fps=fps, labels=labels, padlabels=padlabels,
        z=(a["WALL"], a["WALL"] + 0.8),
        variants=["allday"],
        note="左ポケット床置き。筐体CAD変更ゼロ。slim は J1 嵌合高さの天井余裕不足で非対応。",
    )


def build_carrier_board(case):
    """MC-CARRIER-A: XIAO をカステレーション直はんだで載せるキャリア基板。
    ★ 筐体の作り直しが必要（GAP_BX 1.2→2.1 / M_TOP 0.6→1.8 / XIAO_LIFT 1.4→1.6）。

    2026-08-28 の修正:
      - GAP_BX を 1.8→2.1 に拡げた。1.8 では XIAO ランド列の外端が基板端から
        0.31mm しか無く、JLCPCB の 0.30mm 規格に対し外形ルーティング公差
        ±0.2mm を吸収できなかった（→ 0.61 / 0.51mm を確保）。
      - M_TOP を 0.6→2.0 に。基板外形と筐体上内壁に 0.20mm の逃げを作る
        （従来は基板が内寸を 1.60mm はみ出していたが無警告だった）。
      - MH1/MH2 を x3.4→3.8 に移動（穴縁-外形 0.30 ちょうど → 0.70mm）。
      - R1/J2/J3 を x14.0→13.5 に移動（U1 コートヤードと 0.00mm 接触していた）。
      - J4 を x24.7→24.6 に移動（BAT窓との銅箔クリアランス 0.30 → 0.40mm）。
      - 逆接続保護 FET(Q1/Q2) は **rev.A では載せない**（SCHEMATIC §8.1 参照）。
    """
    a = case["allday"]
    GAP_BX2, M_TOP2 = 2.1, 2.0
    IH2 = 1.6 + 25.0 + GAP_BX2 + 17.8 + M_TOP2          # 48.5
    H2 = IH2 + 2 * a["WALL"]                            # 51.7
    xiao_y0 = a["bat"][3] + GAP_BX2                     # 30.3
    xiao_y1 = xiao_y0 + 17.8                            # 48.1
    xc, yc = (a["xiao"][0] + a["xiao"][2]) / 2, (xiao_y0 + xiao_y1) / 2
    bx0, bx1 = 2.0, a["xiao"][2] - 0.2                  # 2.0 .. 36.2
    by0, by1 = 28.4, a["WALL"] + IH2 - 0.2              # 28.4 .. 49.9

    N = dict(GND="GND", BATP="BATP", BATN="BATN", VBUS="VBUS",
             VS="VBUS_SENSE", BS="VBAT_SENSE", SW="SW_IN",
             LD="LED_DRV", LA="LED_A")
    xn = {"D0": N["VS"], "D1": N["SW"], "D2": None, "D3": N["LD"],
          "D4": N["BS"], "D5": None, "D6": None, "D7": None, "D8": None,
          "D9": None, "D10": None, "3V3": None, "GND": N["GND"], "5V": N["VBUS"]}
    fps = []
    fps.append((("U1"), (xc, yc), 0, fp_xiao("U1", xn)))
    fps.append((("J1"), (10.0, 32.4), 0, fp_jst_ph2("J1", N["BATP"], N["BATN"])))
    fps.append((("R4"), (3.9, 36.4), 0, fp_0805("R4", "220k", N["BATP"], N["BS"])))
    fps.append((("R5"), (7.7, 36.4), 0, fp_0805("R5", "220k", N["BS"], N["GND"])))
    fps.append((("C1"), (3.9, 38.9), 0, fp_0805("C1", "100nF", N["BS"], N["GND"], "C")))
    fps.append((("C2"), (7.7, 38.9), 0, fp_0805("C2", "100nF", N["VS"], N["GND"], "C")))
    fps.append((("R2"), (3.9, 41.4), 0, fp_0805("R2", "220k", N["VBUS"], N["VS"])))
    fps.append((("R3"), (7.7, 41.4), 0, fp_0805("R3", "330k", N["VS"], N["GND"])))
    fps.append((("R1"), (13.5, 36.4), 90, fp_0805("R1", "220R", N["LD"], N["LA"])))
    fps.append((("J3"), (13.5, 40.6), 0,
                fp_wirepads_smd("J3", [(0, 0.9), (0, -0.9)], [N["LA"], N["GND"]])))
    fps.append((("J2"), (13.5, 45.0), 0,
                fp_wirepads_smd("J2", [(0, 0.9), (0, -0.9)], [N["SW"], N["GND"]])))
    # BAT ジャンパランド（B.Cu。窓から XIAO 裏面 BAT パッドへ線1〜2本）
    fps.append((("J4"), (24.6, 38.9), 0,
                fp_wirepads_smd("J4", [(0, 1.0), (0, -1.0)], [N["BATP"], N["BATN"]],
                                pw=1.6, ph=1.4)))
    for i, (x, y, net) in enumerate([(6.5, 48.0, N["GND"]), (8.5, 48.0, N["BATP"]),
                                     (10.5, 48.0, N["VS"]), (12.5, 48.0, N["BS"]),
                                     (10.5, 45.2, N["BATN"])]):
        fps.append(((f"TP{i+1}"), (x, y), 0, fp_testpoint(f"TP{i+1}", net)))
    fps.append((("MH1"), (3.8, 31.2), 0, fp_mount("MH1")))
    fps.append((("MH2"), (3.8, 47.6), 0, fp_mount("MH2")))

    labels = {"U1": "XIAO ESP32S3 Sense", "J1": "BAT (PH2.0)", "R1": "220R",
              "R2": "220k", "R3": "330k", "R4": "220k", "R5": "220k",
              "C1": "100n", "C2": "100n", "J2": "SW", "J3": "LED",
              "J4": "BAT jumper (B.Cu)"}
    padlabels = {"J2": ["SW", "GND"], "J3": ["LED+", "GND"], "J1": ["+", "-"],
                 "J4": ["B+", "B-"]}
    return dict(
        name="MC-CARRIER-A", file="mindclip_carrier.kicad_pcb",
        title="MindClip MC-CARRIER-A (v2 carrier)",
        rect=(bx0, by0, bx1, by1), corner_r=1.5, thickness=0.8,
        fps=fps, labels=labels, padlabels=padlabels,
        cutouts=[(25.8, 32.9, 35.8, 44.9)],     # XIAO 裏面 BAT パッド用アクセス窓
        z=(a["WALL"] + 0.8, a["WALL"] + 1.6),
        variants=["allday", "slim(+0.2mm)"],
        case_mod=dict(GAP_BX=GAP_BX2, M_TOP=M_TOP2, XIAO_LIFT=1.6, IH=IH2, H=H2,
                      IW=a["IW"], WALL=a["WALL"]),
        note="筐体改造必須（body/lid 再印刷）。外形高さ 49.4→51.7mm。",
    )


# ---------------------------------------------------------------------------
# 5. 幾何ヘルパ（フットプリント → 絶対座標）
# ---------------------------------------------------------------------------
def _rot(lx, ly, R):
    """フットプリントローカル(KiCad流 y下) → 筐体座標の相対量 (dx, dy_up)"""
    c, s = math.cos(math.radians(R)), math.sin(math.radians(R))
    return (lx * c + ly * s, lx * s - ly * c)


def abs_pads(board):
    """全パッドの絶対位置（筐体座標）とサイズを返す。"""
    out = []
    for ref, (X, Y), R, fp in board["fps"]:
        for (num, ptype, shape, (lx, ly), (sx, sy), drill, net) in fp["pads"]:
            dx, dy = _rot(lx, ly, R)
            w, h = (sx, sy) if R % 180 == 0 else (sy, sx)
            out.append(dict(ref=ref, pad=num, net=net, type=ptype, shape=shape,
                            x=X + dx, y=Y + dy, w=w, h=h, drill=drill,
                            layers=("F.Cu",) if ptype == "smd" and fp.get("bcu") is None
                            else None, lib=fp["lib"]))
    # J4（BAT ジャンパランド）だけは B.Cu 実装
    for p in out:
        if p["ref"] == "J4":
            p["layers"] = ("B.Cu",)
        elif p["type"] == "np_thru_hole":
            p["layers"] = ()
        elif p["type"] == "thru_hole":
            p["layers"] = ("F.Cu", "B.Cu")
        elif p["layers"] is None:
            p["layers"] = ("F.Cu",)
    return out


def abs_courtyards(board):
    out = []
    for ref, (X, Y), R, fp in board["fps"]:
        cw, ch = fp["crtyd"]
        ox, oy = fp.get("crtyd_off", (0.0, 0.0))
        dx, dy = _rot(ox, oy, R)
        if R % 180 != 0:
            cw, ch = ch, cw
        out.append((ref, X + dx - cw / 2, Y + dy - ch / 2,
                    X + dx + cw / 2, Y + dy + ch / 2))
    return out


def abs_body(board):
    """物理的な本体（fab枠）の絶対 AABB。高さ body_z も返す。"""
    out = []
    for ref, (X, Y), R, fp in board["fps"]:
        if not fp["fab"]:
            continue
        (ax, ay), (bx, by) = fp["fab"][0]
        p1 = _rot(ax, ay, R)
        p2 = _rot(bx, by, R)
        x0, x1 = sorted((X + p1[0], X + p2[0]))
        y0, y1 = sorted((Y + p1[1], Y + p2[1]))
        out.append((ref, x0, y0, x1, y1, fp.get("body_z", 0.6),
                    fp.get("bend_z", 0.0)))
    return out


# ---------------------------------------------------------------------------
# 6. 迷路（maze）ルータ — 0.1mm グリッド / 2層 / ビアあり
#
#    【2026-08-28 全面修正: 異ネット short 16件・クリアランス違反41件の根本原因】
#    旧実装は占有マップが層あたり1枚しかなく、
#      (a) 層変更（ビア打ち）の可否を「反対層の 0.1mm セル1個が空いているか」
#          だけで判定していた。ビアランド φ0.8 の実体を他ネットの銅箔と
#          突き合わせていないので、先に引かれた他ネットのトラックの脇
#          0.400mm にビアが「合法的に」落ちた（必要 0.652mm → 0.125mm 食い込み）。
#      (b) トラックのハローが tw/2 + cl*0.5 = 0.25mm しかなく、
#          DRC dict が自ら宣言する use_clear=0.25 を構造的に満たせなかった。
#    修正: 占有マップを層ごとに **2枚** 持つ。
#      occ_t[L] … 「他ネットのトラック中心線」を禁止するセル
#      occ_v[L] … 「他ネットのビア中心」を禁止するセル
#    障害物（パッド/トラック/ビア/外形/窓）は、その実体の外形に
#      occ_t へ (相手トラック半幅 tw/2) + clearance
#      occ_v へ (相手ビア半径 via/2) + clearance
#    を足して塗る。ビアは occ_v の両層が空いているときだけ打てる。
#    occ_v の塗り範囲は occ_t の真部分集合ではなく上位集合なので、
#    ビア判定は occ_v の2層チェックだけで足りる。
# ---------------------------------------------------------------------------
import heapq
from collections import defaultdict

GRID = 0.1


def rrect_sdf(x, y, x0, y0, x1, y1, r):
    """角R矩形の符号付き距離（負=内側）。内側の余裕は -sdf。"""
    hx, hy = (x1 - x0) / 2.0, (y1 - y0) / 2.0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    qx = abs(x - cx) - hx + r
    qy = abs(y - cy) - hy + r
    return (math.hypot(max(qx, 0.0), max(qy, 0.0))
            + min(max(qx, qy), 0.0) - r)


class Router:
    def __init__(self, board, pads):
        x0, y0, x1, y1 = board["rect"]
        self.x0, self.y0 = x0, y0
        self.nx = int(round((x1 - x0) / GRID)) + 1
        self.ny = int(round((y1 - y0) / GRID)) + 1
        self.occ_t = [bytearray(self.nx * self.ny) for _ in range(2)]
        self.occ_v = [bytearray(self.nx * self.ny) for _ in range(2)]
        self.netid = {}
        self.tw = DRC["use_track_sig"]
        self.cl = DRC["use_clear"]
        self.vr = DRC["use_via"] / 2.0
        self.board = board
        self.pads = pads
        self.tracks = []      # (net, layer, (x,y), (x,y), width)
        self.vias = []        # (net, x, y)
        self._init_obstacles()

    # -- 基本操作 ----------------------------------------------------------
    def nid(self, net):
        if net is None:
            return 254
        if net not in self.netid:
            self.netid[net] = len(self.netid) + 1
        return self.netid[net]

    def idx(self, ix, iy):
        return iy * self.nx + ix

    def _paint(self, mp, layer, x0, y0, x1, y1, nid):
        i0 = max(0, int(math.floor((x0 - self.x0) / GRID)))
        i1 = min(self.nx - 1, int(math.ceil((x1 - self.x0) / GRID)))
        j0 = max(0, int(math.floor((y0 - self.y0) / GRID)))
        j1 = min(self.ny - 1, int(math.ceil((y1 - self.y0) / GRID)))
        arr = mp[layer]
        for j in range(j0, j1 + 1):
            base = j * self.nx
            for i in range(i0, i1 + 1):
                cur = arr[base + i]
                arr[base + i] = nid if (cur == 0 or cur == nid) else 255

    def obstacle(self, layer, x0, y0, x1, y1, nid):
        """銅箔の実体 AABB を占有マップに反映する（層ごと）。"""
        et = self.tw / 2 + self.cl
        ev = self.vr + self.cl
        self._paint(self.occ_t, layer, x0 - et, y0 - et, x1 + et, y1 + et, nid)
        self._paint(self.occ_v, layer, x0 - ev, y0 - ev, x1 + ev, y1 + ev, nid)

    # -- 初期障害物 --------------------------------------------------------
    def _init_obstacles(self):
        bx0, by0, bx1, by1 = self.board["rect"]
        r = self.board["corner_r"]
        et = self.tw / 2 + DRC["min_copper_edge"]
        ev = self.vr + DRC["min_copper_edge"]
        cuts = self.board.get("cutouts", [])
        for j in range(self.ny):
            for i in range(self.nx):
                x = self.x0 + i * GRID
                y = self.y0 + j * GRID
                inside = -rrect_sdf(x, y, bx0, by0, bx1, by1, r)   # 内側の余裕
                for (cx0, cy0, cx1, cy1) in cuts:
                    inside = min(inside, rrect_sdf(x, y, cx0, cy0, cx1, cy1, 1.0))
                k = self.idx(i, j)
                if inside < et:
                    self.occ_t[0][k] = self.occ_t[1][k] = 255
                if inside < ev:
                    self.occ_v[0][k] = self.occ_v[1][k] = 255
        # パッド: まずハローを塗り、そのあとコアを自ネットIDで上書きする
        # （近接パッドのハローが重なってコアが 255 になり到達不能になるのを防ぐ）
        for p in self.pads:
            nid = self.nid(p["net"])
            ex, ey = p["w"] / 2, p["h"] / 2
            if p["type"] == "np_thru_hole":
                for L in range(2):
                    self.obstacle(L, p["x"] - ex, p["y"] - ey,
                                  p["x"] + ex, p["y"] + ey, 255)
                continue
            for L in range(2):
                ln = "F.Cu" if L == 0 else "B.Cu"
                if ln in p["layers"] or p["type"] == "thru_hole":
                    self.obstacle(L, p["x"] - ex, p["y"] - ey,
                                  p["x"] + ex, p["y"] + ey, nid)
        for p in self.pads:
            if p["type"] == "np_thru_hole":
                continue
            nid = self.nid(p["net"])
            ex, ey = p["w"] / 2, p["h"] / 2
            for L in range(2):
                ln = "F.Cu" if L == 0 else "B.Cu"
                if ln in p["layers"] or p["type"] == "thru_hole":
                    for mp in (self.occ_t, self.occ_v):
                        self._paint_force(mp, L, p["x"] - ex, p["y"] - ey,
                                          p["x"] + ex, p["y"] + ey, nid)

    def _paint_force(self, mp, layer, x0, y0, x1, y1, nid):
        """パッドのコア領域を無条件に自ネットIDへ上書き（到達性の確保）。"""
        i0 = max(0, int(math.ceil((x0 - self.x0) / GRID)))
        i1 = min(self.nx - 1, int(math.floor((x1 - self.x0) / GRID)))
        j0 = max(0, int(math.ceil((y0 - self.y0) / GRID)))
        j1 = min(self.ny - 1, int(math.floor((y1 - self.y0) / GRID)))
        arr = mp[layer]
        for j in range(j0, j1 + 1):
            base = j * self.nx
            for i in range(i0, i1 + 1):
                if arr[base + i] != 255 or True:
                    arr[base + i] = nid

    def pad_cells(self, p):
        """パッド中心近傍の到達セル（そのパッドが存在する層）。"""
        cells = []
        for L in range(2):
            ln = "F.Cu" if L == 0 else "B.Cu"
            if ln not in p["layers"]:
                continue
            i = int(round((p["x"] - self.x0) / GRID))
            j = int(round((p["y"] - self.y0) / GRID))
            if 0 <= i < self.nx and 0 <= j < self.ny:
                cells.append((L, i, j))
        return cells

    def route_net(self, net, pads):
        nid = self.nid(net)
        groups = [self.pad_cells(p) for p in pads]
        groups = [g for g in groups if g]
        if len(groups) < 2:
            return True
        connected = set(groups[0])
        rest = groups[1:]
        ok = True
        while rest:
            best = None
            for gi, g in enumerate(rest):
                res = self._bfs(connected, set(g), nid)
                if res and (best is None or res[0] < best[0]):
                    best = (res[0], gi, res[1])
            if best is None:
                ok = False
                break
            _, gi, path = best
            self._commit(path, net, nid)
            connected |= set(path)
            connected |= set(rest[gi])
            rest.pop(gi)
        return ok

    DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
    TURN = 30         # 方向転換のペナルティ（配線を直線的にする）
    VIA = 250

    def _bfs(self, srcs, dsts, nid):
        """状態 = (層, ix, iy, 直前の進行方向)。方向転換にコストを付けて
        階段状の配線を避ける。"""
        INF = float("inf")
        dist = {}
        prev = {}
        pq = []
        seq = [0]
        for s in srcs:
            st = (s[0], s[1], s[2], 4)
            dist[st] = 0
            seq[0] += 1
            heapq.heappush(pq, (0, seq[0], st, None))
        while pq:
            d, _, cur, par = heapq.heappop(pq)
            if cur in prev:
                continue
            prev[cur] = par
            if (cur[0], cur[1], cur[2]) in dsts:
                path = []
                n = cur
                while n is not None:
                    path.append((n[0], n[1], n[2]))
                    n = prev[n]
                out = list(reversed(path))
                ded = [out[0]]
                for q in out[1:]:
                    if q != ded[-1]:
                        ded.append(q)
                return (d, ded)
            L, i, j, pd = cur
            for k, (di, dj) in enumerate(self.DIRS):
                ni, nj = i + di, j + dj
                if not (0 <= ni < self.nx and 0 <= nj < self.ny):
                    continue
                if self.occ_t[L][self.idx(ni, nj)] not in (0, nid):
                    continue
                nxt = (L, ni, nj, k)
                nd = d + 1 + (self.TURN if (pd != 4 and pd != k) else 0)
                if dist.get(nxt, INF) > nd:
                    dist[nxt] = nd
                    seq[0] += 1
                    heapq.heappush(pq, (nd, seq[0], nxt, cur))
            # 層変更（ビア）: ビアランドの実体が両層で成立するときだけ許す
            nl = 1 - L
            k = self.idx(i, j)
            if self.occ_v[0][k] in (0, nid) and self.occ_v[1][k] in (0, nid):
                nxt = (nl, i, j, 4)
                nd = d + self.VIA
                if dist.get(nxt, INF) > nd:
                    dist[nxt] = nd
                    seq[0] += 1
                    heapq.heappush(pq, (nd, seq[0], nxt, cur))
        return None

    def _commit(self, path, net, nid):
        """path = [(layer, ix, iy), ...] 整数グリッド。浮動小数で比較しないこと
        （0.1mm 刻みの丸め誤差で共線判定が壊れ、線分が細切れになる）。"""
        run = [path[0]]
        for k in range(1, len(path)):
            if path[k][0] != path[k - 1][0]:
                self._emit_run(run, net, nid)
                x = self.x0 + path[k][1] * GRID
                y = self.y0 + path[k][2] * GRID
                self.vias.append((net, x, y))
                for L in range(2):
                    self.obstacle(L, x - self.vr, y - self.vr,
                                  x + self.vr, y + self.vr, nid)
                run = [path[k]]
            else:
                run.append(path[k])
        self._emit_run(run, net, nid)

    def _emit_run(self, run, net, nid):
        if len(run) < 2:
            return
        L = run[0][0]
        hw = self.tw / 2
        simp = [run[0]]
        for k in range(1, len(run) - 1):
            a, b, c = run[k - 1], run[k], run[k + 1]
            if (b[1] - a[1], b[2] - a[2]) != (c[1] - b[1], c[2] - b[2]):
                simp.append(b)
        simp.append(run[-1])
        for k in range(len(simp) - 1):
            (_, i1, j1), (_, i2, j2) = simp[k], simp[k + 1]
            x1, y1 = self.x0 + i1 * GRID, self.y0 + j1 * GRID
            x2, y2 = self.x0 + i2 * GRID, self.y0 + j2 * GRID
            self.tracks.append((net, "F.Cu" if L == 0 else "B.Cu",
                                (x1, y1), (x2, y2), self.tw))
            self.obstacle(L, min(x1, x2) - hw, min(y1, y2) - hw,
                          max(x1, x2) + hw, max(y1, y2) + hw, nid)


# ---------------------------------------------------------------------------
# 7. .kicad_pcb ライタ（S式を直接生成。KiCad 7 形式 version 20221018）
# ---------------------------------------------------------------------------
def rounded_outline(x0, y0, x1, y1, r):
    """角R付き矩形を (直線4本, 円弧4本) で返す（筐体座標）。"""
    lines = [((x0 + r, y0), (x1 - r, y0)), ((x1, y0 + r), (x1, y1 - r)),
             ((x1 - r, y1), (x0 + r, y1)), ((x0, y1 - r), (x0, y0 + r))]
    k = r * (1 - math.sqrt(0.5))
    arcs = [((x1 - r, y0), (x1 - k, y0 + k), (x1, y0 + r)),
            ((x1, y1 - r), (x1 - k, y1 - k), (x1 - r, y1)),
            ((x0 + r, y1), (x0 + k, y1 - k), (x0, y1 - r)),
            ((x0, y0 + r), (x0 + k, y0 + k), (x0 + r, y0))]
    return lines, arcs


def write_kicad_pcb(board, pads, router, path, banner):
    nets = [""]
    for p in pads:
        if p["net"] and p["net"] not in nets:
            nets.append(p["net"])
    for t in router.tracks:
        if t[0] not in nets:
            nets.append(t[0])
    nidx = {n: i for i, n in enumerate(nets)}
    _sl, _st, _sd = silk_items(board, pads)
    _refpos = {t[3]: (t[1], t[2]) for t in _st if t[5] == "ref"}

    L = []
    A = L.append
    A('(kicad_pcb (version 20221018) (generator "mindclip_gen_pcb.py")')
    A(f'  (general (thickness {f(board["thickness"])}))')
    A('  (paper "A4")')
    A('  (title_block')
    A(f'    (title "{board["title"]}")')
    A('    (date "2026-08-28")')
    A('    (rev "v2-A")')
    A('    (company "MindClip DIY")')
    A('    (comment 1 "NOT USED IN v1.5 (adopted plan = A-1 harness, no PCB)")')
    A('    (comment 2 "Gated by SCHEMATIC.md section 9.4 - measure XIAO stack first")')
    A('  )')
    A('  (layers')
    for ly in LAYERS:
        if len(ly) == 4:
            A(f'    ({ly[0]} "{ly[1]}" {ly[2]} "{ly[3]}")')
        else:
            A(f'    ({ly[0]} "{ly[1]}" {ly[2]})')
    A('  )')
    A('  (setup')
    A('    (pad_to_mask_clearance 0.05)')
    A('    (pcbplotparams (layerselection 0x00010fc_ffffffff) (plot_on_all_layers_selection 0x0000000_00000000)')
    A('      (disableapertmacros false) (usegerberextensions false) (usegerberattributes true)')
    A('      (usegerberadvancedattributes true) (creategerberjobfile true) (svgprecision 4)')
    A('      (plotframeref false) (viasonmask false) (mode 1) (useauxorigin false)')
    A('      (hpglpennumber 1) (hpglpenspeed 20) (hpglpendiameter 15.000000)')
    A('      (dxfpolygonmode true) (dxfimperialunits true) (dxfusepcbnewfont true)')
    A('      (psnegative false) (psa4output false) (plotreference true) (plotvalue true)')
    A('      (plotinvisibletext false) (sketchpadsonfab false) (subtractmaskfromsilk false)')
    A('      (outputformat 1) (mirror false) (drillshape 1) (scaleselection 1) (outputdirectory "gerber/"))')
    A('  )')
    for i, n in enumerate(nets):
        A(f'  (net {i} "{n}")')

    # --- フットプリント
    for ref, (X, Y), R, fp in board["fps"]:
        kx, ky = K(X, Y)
        A(f'  (footprint "{fp["lib"]}" (layer "F.Cu")')
        A(f'    (tstamp {uuid()})')
        A(f'    (at {f(kx)} {f(ky)}{" " + f(KROT(R)) if R else ""})')
        std = fp.get("std")
        A(f'    (descr "MindClip inline footprint'
          f'{" (dimensions match KiCad " + std + ")" if std else ""}")')
        A(f'    (attr {fp["attr"]})')
        rp = _refpos.get(fp["ref"])
        rlx, rly = inv_rot((rp[0] - X) if rp else 0.0,
                           (rp[1] - Y) if rp else -2.2, R)
        A(f'    (fp_text reference "{fp["ref"]}" (at {f(rlx)} {f(rly)}'
          f'{" " + f(KROT(R)) if R else ""}) '
          f'(layer "F.SilkS"){"" if rp else " hide"} (tstamp {uuid()})')
        A(f'      (effects (font (size 0.7 0.7) (thickness {f(SILK_W)})))')
        A('    )')
        A(f'    (fp_text value "{fp["value"]}" (at 0 2.2{" " + f(KROT(R)) if R else ""}) '
          f'(layer "F.Fab") hide (tstamp {uuid()})')
        A(f'      (effects (font (size 0.7 0.7) (thickness {f(SILK_W)})))')
        A('    )')
        for (a, b) in fp["silk"]:
            A(f'    (fp_line (start {f(a[0])} {f(a[1])}) (end {f(b[0])} {f(b[1])}) '
              f'(stroke (width {f(SILK_W)}) (type solid)) (layer "F.SilkS") '
              f'(tstamp {uuid()}))')
        for ((ax, ay), (bx, by)) in fp["fab"]:
            A(f'    (fp_rect (start {f(ax)} {f(ay)}) (end {f(bx)} {f(by)}) '
              f'(stroke (width 0.1) (type solid)) (fill none) (layer "F.Fab") (tstamp {uuid()}))')
        cw, ch = fp["crtyd"]
        ox, oy = fp.get("crtyd_off", (0.0, 0.0))
        A(f'    (fp_rect (start {f(ox - cw/2)} {f(oy - ch/2)}) (end {f(ox + cw/2)} {f(oy + ch/2)}) '
          f'(stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd") (tstamp {uuid()}))')
        for (num, ptype, shape, (lx, ly), (sx, sy), drill, net) in fp["pads"]:
            if ptype == "np_thru_hole":
                A(f'    (pad "" np_thru_hole circle (at {f(lx)} {f(ly)}) '
                  f'(size {f(sx)} {f(sy)}) (drill {f(drill)}) '
                  f'(layers "F&B.Cu" "*.Mask") (tstamp {uuid()}))')
                continue
            if ptype == "thru_hole":
                lay = '"*.Cu" "*.Mask"'
            elif ref == "J4":
                lay = '"B.Cu" "B.Paste" "B.Mask"'
            else:
                lay = '"F.Cu" "F.Paste" "F.Mask"'
            dr = f' (drill {f(drill)})' if drill else ''
            rr = ' (roundrect_rratio 0.25)' if shape == "roundrect" else ''
            nn = f' (net {nidx[net]} "{net}")' if net else ''
            # ★ KiCad の pad (at x y ANGLE) の ANGLE は **絶対角**。
            #   フットプリント回転を含めて書かないとパッド *形状* が回らず、
            #   銅箔が未回転（例 1.025(X) x 1.40(Y) のまま）で出力される。
            ang = f' {f(KROT(R))}' if R else ''
            A(f'    (pad "{num}" {ptype} {shape} (at {f(lx)} {f(ly)}{ang}) '
              f'(size {f(sx)} {f(sy)}){dr} (layers {lay}){rr}{nn} (tstamp {uuid()}))')
        A('  )')

    # --- 基板外形
    lines, arcs = rounded_outline(*board["rect"], board["corner_r"])
    for (a, b) in lines:
        ka, kb = K(*a), K(*b)
        A(f'  (gr_line (start {f(ka[0])} {f(ka[1])}) (end {f(kb[0])} {f(kb[1])}) '
          f'(stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (tstamp {uuid()}))')
    for (s, m, e) in arcs:
        ks, km, ke = K(*s), K(*m), K(*e)
        A(f'  (gr_arc (start {f(ks[0])} {f(ks[1])}) (mid {f(km[0])} {f(km[1])}) '
          f'(end {f(ke[0])} {f(ke[1])}) (stroke (width 0.1) (type solid)) '
          f'(layer "Edge.Cuts") (tstamp {uuid()}))')
    for (cx0, cy0, cx1, cy1) in board.get("cutouts", []):
        cl, ca = rounded_outline(cx0, cy0, cx1, cy1, 1.0)
        for (a, b) in cl:
            ka, kb = K(*a), K(*b)
            A(f'  (gr_line (start {f(ka[0])} {f(ka[1])}) (end {f(kb[0])} {f(kb[1])}) '
              f'(stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (tstamp {uuid()}))')
        for (s, m, e) in ca:
            ks, km, ke = K(*s), K(*m), K(*e)
            A(f'  (gr_arc (start {f(ks[0])} {f(ks[1])}) (mid {f(km[0])} {f(km[1])}) '
              f'(end {f(ke[0])} {f(ke[1])}) (stroke (width 0.1) (type solid)) '
              f'(layer "Edge.Cuts") (tstamp {uuid()}))')

    # --- シルク文字（パッド名・銘板）。位置は silk_items() が唯一の正で、
    #     Gerber の F_Silkscreen.gbr / B_Silkscreen.gbr と同じ座標を使う。
    bx0, by0, bx1, by1 = board["rect"]
    for (ly, tx, ty, txt, size, kind, owner, rot) in silk_items(board, pads)[1]:
        if kind == "ref":
            continue                       # fp_text reference として既に出している
        kx, ky = K(tx, ty)
        mir = ' (justify mirror)' if ly == "B.SilkS" else ''
        A(f'  (gr_text "{txt}" (at {f(kx)} {f(ky)}) (layer "{ly}") (tstamp {uuid()})')
        A(f'    (effects (font (size {f(size)} {f(size)}) '
          f'(thickness {f(SILK_W)})){mir})')
        A('  )')

    # --- 配線
    for (net, layer, a, b, w) in router.tracks:
        ka, kb = K(*a), K(*b)
        A(f'  (segment (start {f(ka[0])} {f(ka[1])}) (end {f(kb[0])} {f(kb[1])}) '
          f'(width {f(w)}) (layer "{layer}") (net {nidx[net]}) (tstamp {uuid()}))')
    for (net, x, y) in router.vias:
        kx, ky = K(x, y)
        A(f'  (via (at {f(kx)} {f(ky)}) (size {f(DRC["use_via"])}) '
          f'(drill {f(DRC["use_via_drill"])}) (layers "F.Cu" "B.Cu") '
          f'(net {nidx[net]}) (tstamp {uuid()}))')
    A(')')
    txt = "\n".join(L) + "\n"
    with open(path, "w") as fh:
        fh.write(txt)
    return txt, nets


# ---------------------------------------------------------------------------
# 8. 検証 — S式のパース（括弧対応）と DRC
# ---------------------------------------------------------------------------
def sexp_parse(text):
    """S式をネストしたリストにパースする。括弧が対応しなければ例外。"""
    tok, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in "()":
            tok.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n:
                if text[j] == "\\":
                    buf.append(text[j + 1])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            if j >= n:
                raise ValueError("unterminated string")
            tok.append('"' + "".join(buf))
            i = j + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            tok.append(text[i:j])
            i = j
    stack, cur, depth = [], [], 0
    for t in tok:
        if t == "(":
            depth += 1
            stack.append(cur)
            cur = []
        elif t == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced: too many ')'")
            parent = stack.pop()
            parent.append(cur)
            cur = parent
        else:
            cur.append(t)
    if depth != 0:
        raise ValueError(f"unbalanced: {depth} unclosed '('")
    if len(cur) != 1:
        raise ValueError(f"expected 1 top-level form, got {len(cur)}")
    return cur[0]


def find_all(node, key):
    out = []
    if isinstance(node, list):
        if node and node[0] == key:
            out.append(node)
        for c in node:
            out.extend(find_all(c, key))
    return out


# --- 幾何プリミティブ（DRC 用）--------------------------------------------
#   rect : 軸並行矩形          (x0,y0,x1,y1)
#   seg  : 太さのある線分       (x1,y1,x2,y2,hw)   ※円は長さ0の seg で表す
def _pt_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _seg_seg_core(a, b):
    (ax1, ay1, ax2, ay2) = a
    (bx1, by1, bx2, by2) = b

    def cr(ox, oy, px, py, qx, qy):
        return (px - ox) * (qy - oy) - (py - oy) * (qx - ox)
    d1 = cr(bx1, by1, bx2, by2, ax1, ay1)
    d2 = cr(bx1, by1, bx2, by2, ax2, ay2)
    d3 = cr(ax1, ay1, ax2, ay2, bx1, by1)
    d4 = cr(ax1, ay1, ax2, ay2, bx2, by2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(_pt_seg(ax1, ay1, bx1, by1, bx2, by2),
               _pt_seg(ax2, ay2, bx1, by1, bx2, by2),
               _pt_seg(bx1, by1, ax1, ay1, ax2, ay2),
               _pt_seg(bx2, by2, ax1, ay1, ax2, ay2))


def _pt_rect(px, py, r):
    dx = max(r[0] - px, 0.0, px - r[2])
    dy = max(r[1] - py, 0.0, py - r[3])
    return math.hypot(dx, dy)


def _rect_rect(a, b):
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dy)


def _seg_rect_core(sg, r):
    x1, y1, x2, y2 = sg
    if (r[0] <= x1 <= r[2] and r[1] <= y1 <= r[3]) or \
       (r[0] <= x2 <= r[2] and r[1] <= y2 <= r[3]):
        return 0.0
    edges = [(r[0], r[1], r[2], r[1]), (r[2], r[1], r[2], r[3]),
             (r[2], r[3], r[0], r[3]), (r[0], r[3], r[0], r[1])]
    return min(_seg_seg_core((x1, y1, x2, y2), e) for e in edges)


def shp_dist(A, B):
    """2つのプリミティブ間の銅箔エッジ間距離（重なりは 0 ではなく負を返さない）。"""
    if A["t"] == "rect" and B["t"] == "rect":
        return _rect_rect(A["r"], B["r"])
    if A["t"] == "rect" and B["t"] == "seg":
        return max(0.0, _seg_rect_core(B["s"], A["r"]) - B["hw"])
    if A["t"] == "seg" and B["t"] == "rect":
        return max(0.0, _seg_rect_core(A["s"], B["r"]) - A["hw"])
    return max(0.0, _seg_seg_core(A["s"], B["s"]) - A["hw"] - B["hw"])


def shp_inside_margin(A, board):
    """基板外形（角R矩形）の内側余裕。窓(cutout)も考慮して最小値を返す。"""
    bx0, by0, bx1, by1 = board["rect"]
    r = board["corner_r"]
    cuts = board.get("cutouts", [])

    def marg(px, py, off):
        m = -rrect_sdf(px, py, bx0, by0, bx1, by1, r) - off
        for (cx0, cy0, cx1, cy1) in cuts:
            m = min(m, rrect_sdf(px, py, cx0, cy0, cx1, cy1, 1.0) - off)
        return m
    if A["t"] == "rect":
        x0, y0, x1, y1 = A["r"]
        return min(marg(x, y, 0.0)
                   for x in (x0, x1) for y in (y0, y1))
    x1, y1, x2, y2 = A["s"]
    n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.05) + 1)
    return min(marg(x1 + (x2 - x1) * k / (n - 1),
                    y1 + (y2 - y1) * k / (n - 1), A["hw"]) for k in range(n))


def collect_copper(board, pads, router):
    """基板上の全銅箔（パッド / トラック / ビア）をプリミティブ列にする。"""
    out = []
    for p in pads:
        if p["type"] == "np_thru_hole":
            out.append(dict(t="seg", s=(p["x"], p["y"], p["x"], p["y"]),
                            hw=p["drill"] / 2, net=None, layers=("F.Cu", "B.Cu"),
                            name=f"{p['ref']} (NPTH hole)", hole=True))
            continue
        lay = tuple(p["layers"])
        nm = f"{p['ref']}.{p['pad']}"
        if p["shape"] == "rect":
            out.append(dict(t="rect", r=(p["x"] - p["w"] / 2, p["y"] - p["h"] / 2,
                                         p["x"] + p["w"] / 2, p["y"] + p["h"] / 2),
                            net=p["net"], layers=lay, name=nm))
        else:                                    # circle / oval
            hw = min(p["w"], p["h"]) / 2
            ext = max(p["w"], p["h"]) / 2 - hw
            if p["w"] >= p["h"]:
                sg = (p["x"] - ext, p["y"], p["x"] + ext, p["y"])
            else:
                sg = (p["x"], p["y"] - ext, p["x"], p["y"] + ext)
            out.append(dict(t="seg", s=sg, hw=hw, net=p["net"], layers=lay, name=nm))
        if p["drill"]:
            out.append(dict(t="seg", s=(p["x"], p["y"], p["x"], p["y"]),
                            hw=p["drill"] / 2, net=p["net"],
                            layers=("F.Cu", "B.Cu"),
                            name=f"{nm} (drill)", hole=True, hole_only=True))
    for k, (net, layer, a, b, w) in enumerate(router.tracks):
        out.append(dict(t="seg", s=(a[0], a[1], b[0], b[1]), hw=w / 2, net=net,
                        layers=(layer,), name=f"track#{k} {layer} {net}"))
    for k, (net, x, y) in enumerate(router.vias):
        out.append(dict(t="seg", s=(x, y, x, y), hw=DRC["use_via"] / 2, net=net,
                        layers=("F.Cu", "B.Cu"), name=f"via#{k} {net}"))
        out.append(dict(t="seg", s=(x, y, x, y), hw=DRC["use_via_drill"] / 2,
                        net=net, layers=("F.Cu", "B.Cu"),
                        name=f"via#{k} {net} (drill)", hole=True, hole_only=True))
    return out


def validate_pcb(text, board, pads, router, nets):
    """独立ジオメトリ DRC。
    ★ 2026-08-28 拡張: 旧版は 線幅 / 穴径・アニュラリング / pad↔pad /
      pad↔外形 / pad↔窓 / courtyard しか見ておらず、
      **track↔track / track↔via / track↔pad / via↔via / via↔pad**、および
      **track・via と基板外形・窓の関係**が全て死角だった（異ネット衝突41件が
      この死角に入り、それでも errors=0 と表示していた）。
      現版は「基板上の全銅箔」を幾何プリミティブに落として総当たりする。
      角R外形も SDF で扱うので、旧版が原理的に見逃していた角部の違反も出る。
    """
    errs, warns, info = [], [], {}
    tree = sexp_parse(text)                      # ← 括弧対応の検証を兼ねる
    if tree[0] != "kicad_pcb":
        errs.append("top-level form is not kicad_pcb")
    info["paren_balanced"] = True
    info["footprints"] = len(find_all(tree, "footprint"))
    info["pads"] = len(find_all(tree, "pad"))
    info["segments"] = len(find_all(tree, "segment"))
    info["vias"] = len(find_all(tree, "via"))
    info["nets"] = len([c for c in tree if isinstance(c, list) and c and c[0] == "net"])
    info["edge_lines"] = len([g for g in find_all(tree, "gr_line")
                              if any(c == ['layer', '"Edge.Cuts'] for c in g)])
    # --- ネット参照の整合
    declared = set()
    for nd in find_all(tree, "net"):
        if len(nd) == 3 and nd[1].isdigit():
            declared.add(nd[2])
    for p in pads:
        if p["net"] and '"' + p["net"] not in declared:
            errs.append(f"pad net not declared: {p['ref']}.{p['pad']} = {p['net']}")
    # --- 回転フットプリントのパッド角度が S式に出ているか（形状回転の検証）
    for fpn in find_all(tree, "footprint"):
        at = [c for c in fpn if isinstance(c, list) and c and c[0] == "at"]
        rot = float(at[0][3]) if at and len(at[0]) >= 4 else 0.0
        if abs(rot) < 1e-9:
            continue
        for pd in find_all(fpn, "pad"):
            pat = [c for c in pd if isinstance(c, list) and c and c[0] == "at"]
            if pat and len(pat[0]) < 4:
                errs.append(f"pad angle token missing on rotated footprint "
                            f"(rot={rot}): {pd[1]}")
    # --- 線幅・穴径・アニュラリング
    for (net, layer, a, b, w) in router.tracks:
        if w < DRC["min_track"] - 1e-9:
            errs.append(f"track width {w} < min {DRC['min_track']}")
    for p in pads:
        if p["drill"]:
            if p["drill"] < DRC["min_drill"] - 1e-9:
                errs.append(f"drill {p['drill']} < min {DRC['min_drill']} ({p['ref']})")
            ann = (min(p["w"], p["h"]) - p["drill"]) / 2
            if p["type"] != "np_thru_hole" and ann < DRC["min_annular"] - 1e-9:
                errs.append(f"annular {ann:.3f} < min ({p['ref']}.{p['pad']})")
    if DRC["use_via_drill"] < DRC["min_drill"] - 1e-9:
        errs.append("via drill below minimum")
    va = (DRC["use_via"] - DRC["use_via_drill"]) / 2
    if va < DRC["min_annular"] - 1e-9:
        errs.append(f"via annular {va:.3f} < min {DRC['min_annular']}")
    # --- 全銅箔の総当たり（異ネットのみ / 層を共有するときのみ）
    cop = collect_copper(board, pads, router)
    info["copper_prims"] = len(cop)
    seen = set()
    npairs = 0
    for i in range(len(cop)):
        A = cop[i]
        for j in range(i + 1, len(cop)):
            B = cop[j]
            if A.get("hole_only") and B.get("hole_only"):
                continue
            if A["net"] is not None and A["net"] == B["net"]:
                continue
            if not (set(A["layers"]) & set(B["layers"])):
                continue
            npairs += 1
            g = shp_dist(A, B)
            if g < DRC["min_clear"] - 1e-9:
                key = (A["name"], B["name"])
                if key in seen:
                    continue
                seen.add(key)
                errs.append(f"CLEARANCE {g:.4f} < {DRC['min_clear']} : "
                            f"{A['name']} [{'/'.join(A['layers'])}] <-> "
                            f"{B['name']} [{'/'.join(B['layers'])}]"
                            + ("  ★SHORT (0.000)" if g <= 1e-9 else ""))
            elif g < DRC["use_clear"] - 1e-9:
                warns.append(f"clearance {g:.3f} < design {DRC['use_clear']}: "
                             f"{A['name']} <-> {B['name']}")
    info["drc_pairs"] = npairs
    # --- 銅箔・穴と 基板外形／窓（角R を SDF で正しく扱う）
    for A in cop:
        m = shp_inside_margin(A, board)
        lim = DRC["min_hole_edge"] if A.get("hole") else DRC["min_copper_edge"]
        kind = "hole" if A.get("hole") else "copper"
        if m < lim - 1e-9:
            errs.append(f"{kind}-to-edge {m:.4f} < {lim} : {A['name']}")
    # --- コートヤード
    cy = abs_courtyards(board)
    allowed = {frozenset(("U1", "J4"))}     # J4 は XIAO 直下の B.Cu ランド（意図的）
    for i in range(len(cy)):
        for j in range(i + 1, len(cy)):
            a, b = cy[i], cy[j]
            if frozenset((a[0], b[0])) in allowed:
                continue
            if a[1] < b[3] - 1e-9 and b[1] < a[3] - 1e-9 and \
               a[2] < b[4] - 1e-9 and b[2] < a[4] - 1e-9:
                warns.append(f"courtyard overlap: {a[0]} <-> {b[0]}")
    # --- シルクがパッドに乗っていないか（線幅 SILK_W を考慮）
    padnames = {f"{p['ref']}.{p['pad']}" for p in pads}
    padrects = [A for A in cop if not A.get("hole") and "F.Cu" in A["layers"]
                and A["name"] in padnames]
    silk_lines, silk_texts, silk_dropped = silk_items(board, pads)
    info["silk_dropped"] = silk_dropped
    segs = [("silk-line", a, b) for (ly, a, b) in silk_lines if ly == "F.SilkS"]
    for (ly, tx, ty, txt, size, kind, owner, rot) in silk_texts:
        if ly != "F.SilkS":
            continue
        for pl in text_polylines(txt, tx, ty, size):
            for k in range(len(pl) - 1):
                segs.append((f"silk-text '{txt}'", pl[k], pl[k + 1]))
    hit = set()
    for (nm, a, b) in segs:
        sg = dict(t="seg", s=(a[0], a[1], b[0], b[1]), hw=SILK_W / 2,
                  net=None, layers=("F.SilkS",), name=nm)
        for A in padrects:
            if shp_dist(sg, A) <= 1e-9 and (nm, A["name"]) not in hit:
                hit.add((nm, A["name"]))
                warns.append(f"silk on pad: {nm} <-> {A['name']}")
        if shp_inside_margin(sg, board) < 0.0 and ("out", nm) not in hit:
            hit.add(("out", nm))
            warns.append(f"silk outside board outline: {nm}")
    if SILK_W < 0.15 - 1e-9:
        errs.append(f"silk width {SILK_W} < JLCPCB min 0.15")
    return errs, warns, info


def check_case_fit(board, case):
    """筐体との干渉チェック（AABB）。基板外形と背の高い部品の実体で判定する。
    ★ 2026-08-28 追加: 「基板外形が筐体内寸に収まっているか」の検査。
      従来は個別部品との AABB と天井高さしか見ておらず、基板そのものが
      内寸から 1.6mm はみ出していても無警告だった。"""
    msgs = []
    for vname in ("allday", "slim"):
        a = case[vname]
        mod = board.get("case_mod") or {}
        WALL = mod.get("WALL", a["WALL"])
        IW = mod.get("IW", a["IW"])
        IH = mod.get("IH", a["IH"])
        ix0, ix1 = WALL, WALL + IW
        iy0, iy1 = WALL, WALL + IH
        bx0, by0, bx1, by1 = board["rect"]
        cl = min(bx0 - ix0, ix1 - bx1, by0 - iy0, iy1 - by1)
        tag = "（case_mod 適用後の内寸）" if mod else ""
        if cl < 0:
            msgs.append(f"[{vname}] BOARD OUTSIDE CASE: 内寸 x{ix0:.1f}..{ix1:.1f} / "
                        f"y{iy0:.1f}..{iy1:.1f} に対し {-cl:.2f}mm はみ出し{tag}")
        else:
            msgs.append(f"[{vname}] board-in-case clearance = {cl:.2f} mm{tag}")
    for vname in ("allday", "slim"):
        a = case[vname]
        z0, z1 = board["z"]
        ceil = a["BODY_D"]
        bx0, by0, bx1, by1 = board["rect"]
        obstacles = {"battery": a["bat"], "switch": a["sw"], "led_body": a["led"],
                     "sw_rib": a["sw_rib"], "lip_left": a["lip_left"],
                     "xiao_stop0": a["xiao_stops"][0], "xiao_stop1": a["xiao_stops"][1]}
        if board["name"] == "MC-CARRIER-A":
            obstacles.pop("xiao_stop0")
            obstacles.pop("xiao_stop1")
            obstacles.pop("sw_rib")
        def hit(b, o):
            return (b[0] < o[2] - 1e-9 and o[0] < b[2] - 1e-9 and
                    b[1] < o[3] - 1e-9 and o[1] < b[3] - 1e-9 and
                    b[4] < o[5] - 1e-9 and o[4] < b[5] - 1e-9)
        board_box = (bx0, by0, bx1, by1, z0, z1)
        for nm, o in obstacles.items():
            if hit(board_box, o):
                msgs.append(f"[{vname}] BOARD vs {nm}: INTERFERENCE")
        for (ref, x0, y0, x1, y1, bz, ez) in abs_body(board):
            bb = (x0, y0, x1, y1, z1, z1 + bz)
            for nm, o in obstacles.items():
                if hit(bb, o):
                    msgs.append(f"[{vname}] {ref} (h={bz}) vs {nm}: INTERFERENCE")
            if z1 + bz > ceil + 1e-9:
                msgs.append(f"[{vname}] {ref} top z={z1+bz:.2f} > lid inner "
                            f"z={ceil:.2f}: OVER CEILING")
            elif ez:
                need = z1 + bz + ez
                if need > ceil + 1e-9:
                    msgs.append(
                        f"[{vname}] {ref} 嵌合体top z={z1+bz:.2f}+曲げ代{ez:.1f} "
                        f"= {need:.2f} > 天井 {ceil:.2f} → NG。"
                        f"成立には内寸奥行 ID を +{need-ceil:.2f}mm "
                        f"(外形奥行 {a['TOTAL_D']:.1f}→{a['TOTAL_D']+need-ceil:.1f}mm) "
                        f"要する")
                else:
                    msgs.append(
                        f"[{vname}] {ref} 嵌合体top z={z1+bz:.2f}+曲げ代{ez:.1f} "
                        f"= {need:.2f} <= 天井 {ceil:.2f}: OK "
                        f"(余裕 {ceil-need:.2f}mm)")
        msgs.append(f"[{vname}] board z {z0:.2f}..{z1:.2f}, lid inner z={ceil:.2f}, "
                    f"headroom above board = {ceil - z1:.2f} mm")
    return msgs


# ---------------------------------------------------------------------------
# 8b. 製造データ出力（Gerber RS-274X / Excellon / BOM / CPL）
#
#    この環境に KiCad が無いため、.kicad_pcb からプロットするのではなく
#    **.kicad_pcb と同じ内部データ構造から直接** 製造データを書き出す。
#    したがって Gerber と .kicad_pcb は同じ幾何から生成された兄弟であり、
#    §8 の独立ジオメトリ DRC はその共通データに対して掛かっている。
#    ただし **KiCad 本体の DRC / DFM は一度も走っていない**。発注前に
#    KiCad で開いて DRC を通すこと（LAYOUT.md §9.3 の手順）。
#
#    座標系: Gerber は「上から見た図」を全層共通で用いる（業界標準）。
#    本ファイル群は筐体座標（x右 / y上、原点=body外形の左下）をそのまま使う。
#    .kicad_pcb 側は KiCad の y下座標なので Y 符号が反転するが、
#    層間の相対関係は同一なので製造上の意味は変わらない。
#    B.SilkS / B.Cu も鏡像にしない（上面視）。B面の**文字だけ**は鏡像で描く。
# ---------------------------------------------------------------------------
# 6x10 グリッドのストロークフォント（Gerber のシルク文字用）。
# KiCad が無いので文字はここでベクタ化する。英大文字・数字・記号のみ。
GLYPH = {
    " ": [], "A": [[(0, 0), (3, 10), (6, 0)], [(1.2, 4), (4.8, 4)]],
    "B": [[(0, 0), (0, 10), (4, 10), (6, 8.5), (4, 5), (0, 5)],
          [(4, 5), (6, 2.5), (4, 0), (0, 0)]],
    "C": [[(6, 8), (3, 10), (0, 7), (0, 3), (3, 0), (6, 2)]],
    "D": [[(0, 0), (0, 10), (3, 10), (6, 7), (6, 3), (3, 0), (0, 0)]],
    "E": [[(6, 10), (0, 10), (0, 0), (6, 0)], [(0, 5), (4, 5)]],
    "F": [[(6, 10), (0, 10), (0, 0)], [(0, 5), (4, 5)]],
    "G": [[(6, 8), (3, 10), (0, 7), (0, 3), (3, 0), (6, 2), (6, 5), (3, 5)]],
    "H": [[(0, 0), (0, 10)], [(6, 0), (6, 10)], [(0, 5), (6, 5)]],
    "I": [[(1, 10), (5, 10)], [(3, 10), (3, 0)], [(1, 0), (5, 0)]],
    "J": [[(6, 10), (6, 3), (3, 0), (0, 3)]],
    "K": [[(0, 0), (0, 10)], [(6, 10), (0, 4.5)], [(0.5, 5), (6, 0)]],
    "L": [[(0, 10), (0, 0), (6, 0)]],
    "M": [[(0, 0), (0, 10), (3, 5), (6, 10), (6, 0)]],
    "N": [[(0, 0), (0, 10), (6, 0), (6, 10)]],
    "O": [[(0, 3), (3, 0), (6, 3), (6, 7), (3, 10), (0, 7), (0, 3)]],
    "P": [[(0, 0), (0, 10), (4, 10), (6, 8), (4, 5), (0, 5)]],
    "Q": [[(0, 3), (3, 0), (6, 3), (6, 7), (3, 10), (0, 7), (0, 3)],
          [(3.5, 3), (6, 0)]],
    "R": [[(0, 0), (0, 10), (4, 10), (6, 8), (4, 5), (0, 5)], [(3, 5), (6, 0)]],
    "S": [[(6, 8.5), (3, 10), (0, 8), (3, 5), (6, 3), (3, 0), (0, 1.5)]],
    "T": [[(0, 10), (6, 10)], [(3, 10), (3, 0)]],
    "U": [[(0, 10), (0, 3), (3, 0), (6, 3), (6, 10)]],
    "V": [[(0, 10), (3, 0), (6, 10)]],
    "W": [[(0, 10), (1.5, 0), (3, 6), (4.5, 0), (6, 10)]],
    "X": [[(0, 0), (6, 10)], [(0, 10), (6, 0)]],
    "Y": [[(0, 10), (3, 5), (6, 10)], [(3, 5), (3, 0)]],
    "Z": [[(0, 10), (6, 10), (0, 0), (6, 0)]],
    "0": [[(0, 3), (3, 0), (6, 3), (6, 7), (3, 10), (0, 7), (0, 3)],
          [(0, 3), (6, 7)]],
    "1": [[(1, 8), (3, 10), (3, 0)], [(1, 0), (5, 0)]],
    "2": [[(0, 8), (3, 10), (6, 8), (0, 0), (6, 0)]],
    "3": [[(0, 9), (3, 10), (6, 8), (3, 5.5)], [(3, 5.5), (6, 3), (3, 0), (0, 1)]],
    "4": [[(4, 0), (4, 10), (0, 3), (6, 3)]],
    "5": [[(6, 10), (0, 10), (0, 6), (3, 6), (6, 4), (3, 0), (0, 1)]],
    "6": [[(6, 9), (3, 10), (0, 6), (0, 3), (3, 0), (6, 3), (3, 5.5), (0, 4.5)]],
    "7": [[(0, 10), (6, 10), (2, 0)]],
    "8": [[(3, 5), (0, 7), (3, 10), (6, 7), (3, 5), (0, 2.5), (3, 0), (6, 2.5),
           (3, 5)]],
    "9": [[(0, 1), (3, 0), (6, 4), (6, 7), (3, 10), (0, 7), (3, 4.5), (6, 5.5)]],
    "+": [[(3, 2), (3, 8)], [(0, 5), (6, 5)]], "-": [[(0, 5), (6, 5)]],
    ".": [[(2.5, 0), (3.5, 0)]], "/": [[(0, 0), (6, 10)]],
    "(": [[(4, 10), (1, 7), (1, 3), (4, 0)]], ")": [[(2, 10), (5, 7), (5, 3), (2, 0)]],
    ":": [[(3, 2), (3, 2.6)], [(3, 6), (3, 6.6)]], "_": [[(0, 0), (6, 0)]],
}
GLYPH_ADV = 8.0        # 文字送り（6 幅 + 2 空き）を 10 単位系で


def text_polylines(txt, x, y, size, mirror=False, anchor="center"):
    """ストローク文字列を絶対座標のポリライン列にする。size = 文字高さ(mm)。"""
    txt = txt.upper()
    sc = size / 10.0
    w = (len(txt) * GLYPH_ADV - 2.0) * sc
    x0 = x - w / 2 if anchor == "center" else x
    out = []
    cur = x0
    for ch in txt:
        for pl in GLYPH.get(ch, GLYPH["?"] if "?" in GLYPH else []):
            pts = []
            for (gx, gy) in pl:
                px = cur + gx * sc
                if mirror:
                    px = 2 * x - px
                pts.append((px, y - size / 2 + gy * sc))
            out.append(pts)
        cur += GLYPH_ADV * sc
    return out


def inv_rot(dx, dy, R):
    """_rot の逆変換（_rot は対合なので同じ式）。"""
    return _rot(dx, dy, R)


TEXT_CLR = 0.12          # シルク文字とパッド／外形の最小すき間


def text_bbox(txt, x, y, size):
    w = (len(txt) * GLYPH_ADV - 2.0) * size / 10.0
    return (x - w / 2, y - size / 2, x + w / 2, y + size / 2)


def _text_ok(board, padboxes, box, placed=()):
    """文字の外接矩形が 基板内 / どのパッドにも乗らない / 既存の文字と
    重ならない、の全てを満たすか。"""
    bx0, by0, bx1, by1 = board["rect"]
    r = board["corner_r"]
    for (px, py) in ((box[0], box[1]), (box[2], box[1]),
                     (box[0], box[3]), (box[2], box[3])):
        if -rrect_sdf(px, py, bx0, by0, bx1, by1, r) < TEXT_CLR:
            return False
        for (cx0, cy0, cx1, cy1) in board.get("cutouts", []):
            if rrect_sdf(px, py, cx0, cy0, cx1, cy1, 1.0) < TEXT_CLR:
                return False
    for pb in padboxes:
        if _rect_rect(box, pb) < TEXT_CLR - 1e-9:
            return False
    for tb in placed:
        if _rect_rect(box, tb) < 0.12 - 1e-9:
            return False
    return True


def ref_text_pos(board, X, Y, R, fp, padboxes, placed=(), size=0.65):
    """リファレンス指示子の位置。上→下→右→左→中央 の順に、
    「基板内 かつ どのパッドにも乗らない」最初の候補を選ぶ。
    どれも成立しなければ None（＝その部品の指示子はシルクに出さない）。"""
    cw, ch = fp["crtyd"]
    ox, oy = fp.get("crtyd_off", (0.0, 0.0))
    dxc, dyc = _rot(ox, oy, R)
    if R % 180 != 0:
        cw, ch = ch, cw
    cx, cy = X + dxc, Y + dyc
    gap = TEXT_CLR + 0.08
    for sz in (size, 0.55, 0.45):
        tw = (len(fp["ref"]) * GLYPH_ADV - 2.0) * sz / 10.0
        dy = ch / 2 + sz / 2 + gap
        dx = cw / 2 + tw / 2 + gap
        cands = []
        for k in (0.0, 0.35, -0.35, 0.7, -0.7, 1.1, -1.1):
            cands += [(cx + k * tw, cy + dy), (cx + k * tw, cy - dy)]
        for k in (0.0, 0.4, -0.4, 0.8, -0.8):
            cands += [(cx + dx, cy + k * sz * 2), (cx - dx, cy + k * sz * 2)]
        cands.append((cx, cy))
        for (tx, ty) in cands:
            if _text_ok(board, padboxes, text_bbox(fp["ref"], tx, ty, sz),
                        placed):
                return tx, ty, sz
    return None


def silk_items(board, pads):
    """F.SilkS / B.SilkS に載る全要素を筐体座標で返す。
    kicad_pcb ライタ / Gerber ライタ / DRC が同じ関数を使う（差異が出ない）。
    文字は「基板内 かつ パッドに乗らない」位置にしか置かない。
    置けなかった指示子は `dropped` に入れて呼び出し側に返す。"""
    lines, texts, dropped = [], [], []
    bx0, by0, bx1, by1 = board["rect"]
    padboxes = [(p["x"] - p["w"] / 2, p["y"] - p["h"] / 2,
                 p["x"] + p["w"] / 2, p["y"] + p["h"] / 2) for p in pads]
    placed = []
    # パッド名 → リファレンス指示子 の順に置く（パッド名のほうが組立に効く）
    for ref, labels in board["padlabels"].items():
        for ref2, (X, Y), R, fp in board["fps"]:
            if ref2 != ref:
                continue
            for lbl, pd in zip(labels, fp["pads"]):
                dx, dy = _rot(pd[3][0], pd[3][1], R)
                w, h = (pd[4] if R % 180 == 0 else (pd[4][1], pd[4][0]))
                spot = None
                for (tx, ty) in ((X + dx, Y + dy - h / 2 - 0.45),
                                 (X + dx, Y + dy + h / 2 + 0.45),
                                 (X + dx + w / 2 + 0.60, Y + dy),
                                 (X + dx - w / 2 - 0.60, Y + dy)):
                    bb = text_bbox(lbl, tx, ty, 0.55)
                    if _text_ok(board, padboxes, bb, placed):
                        spot = (tx, ty, bb)
                        break
                if spot is None:
                    dropped.append(f"{ref}:{lbl}")
                    continue
                placed.append(spot[2])
                texts.append(("F.SilkS", spot[0], spot[1], lbl, 0.55,
                              "pad", ref, 0))
    for ref, (X, Y), R, fp in board["fps"]:
        for (a, b) in fp["silk"]:
            d1 = _rot(a[0], a[1], R)
            d2 = _rot(b[0], b[1], R)
            lines.append(("F.SilkS", (X + d1[0], Y + d1[1]),
                          (X + d2[0], Y + d2[1])))
        pos = ref_text_pos(board, X, Y, R, fp, padboxes, placed)
        if pos is None:
            dropped.append(fp["ref"])
            continue
        placed.append(text_bbox(fp["ref"], pos[0], pos[1], pos[2]))
        texts.append(("F.SilkS", pos[0], pos[1], fp["ref"], pos[2], "ref", ref, R))
    texts.append(("B.SilkS", (bx0 + bx1) / 2, by0 + 0.9,
                  f"{board['name']} V2 NOT FOR V1.5", 0.60, "board", None, 0))
    return lines, texts, dropped


def gbr_num(v):
    return f"{int(round(v * 1e6)):d}"


class Gerber:
    """最小限の RS-274X ライタ（4.6 形式 / mm / 絶対 / 面積ゼロの線と flash のみ）。"""

    def __init__(self, func, polarity="Positive"):
        self.ap = {}
        self.body = []
        self.func = func
        self.polarity = polarity
        self.cur = None

    def aperture(self, key):
        if key not in self.ap:
            self.ap[key] = 10 + len(self.ap)
        return self.ap[key]

    def _sel(self, key):
        d = self.aperture(key)
        if self.cur != d:
            self.body.append(f"D{d}*")
            self.cur = d
        return d

    def line(self, x1, y1, x2, y2, w):
        self._sel(("C", round(w, 6)))
        self.body.append(f"X{gbr_num(x1)}Y{gbr_num(y1)}D02*")
        self.body.append(f"X{gbr_num(x2)}Y{gbr_num(y2)}D01*")

    def polyline(self, pts, w):
        for i in range(len(pts) - 1):
            self.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], w)

    def flash(self, key, x, y):
        self._sel(key)
        self.body.append(f"X{gbr_num(x)}Y{gbr_num(y)}D03*")

    def dumps(self, title):
        L = ["%FSLAX46Y46*%", "%MOMM*%",
             "%TF.GenerationSoftware,MindClip,gen_pcb.py,2.0*%",
             f"%TF.FileFunction,{self.func}*%",
             f"%TF.FilePolarity,{self.polarity}*%",
             f"G04 {title}*", "%TF.SameCoordinates,Original*%",
             "G01*", "%LPD*%"]
        for key, d in sorted(self.ap.items(), key=lambda kv: kv[1]):
            if key[0] == "C":
                L.append(f"%ADD{d}C,{key[1]:.6f}*%")
            elif key[0] == "R":
                L.append(f"%ADD{d}R,{key[1]:.6f}X{key[2]:.6f}*%")
            elif key[0] == "O":
                L.append(f"%ADD{d}O,{key[1]:.6f}X{key[2]:.6f}*%")
        L += self.body
        L.append("M02*")
        return "\n".join(L) + "\n"


def _pad_ap(p, grow=0.0):
    w, h = p["w"] + grow, p["h"] + grow
    if p["shape"] == "circle":
        return ("C", round(w, 6))
    if p["shape"] == "oval":
        return ("O", round(w, 6), round(h, 6))
    return ("R", round(w, 6), round(h, 6))


def outline_polylines(board):
    """Edge.Cuts を折れ線化する（角Rは16分割。弦誤差 < 0.005mm）。"""
    x0, y0, x1, y1 = board["rect"]
    outs = []

    def rr(x0, y0, x1, y1, r):
        pts = []
        for (cx, cy, a0) in ((x1 - r, y0 + r, -90.0), (x1 - r, y1 - r, 0.0),
                             (x0 + r, y1 - r, 90.0), (x0 + r, y0 + r, 180.0)):
            for k in range(17):
                a = math.radians(a0 + 90.0 * k / 16.0)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        pts.append(pts[0])
        return pts
    outs.append(rr(x0, y0, x1, y1, board["corner_r"]))
    for (cx0, cy0, cx1, cy1) in board.get("cutouts", []):
        outs.append(rr(cx0, cy0, cx1, cy1, 1.0))
    return outs


def write_fabrication(board, pads, router, outdir, stem):
    """Gerber(6層+外形) / Excellon(PTH,NPTH) / BOM / CPL を書き出す。"""
    os.makedirs(outdir, exist_ok=True)
    files = []
    lines, texts, _dropped = silk_items(board, pads)

    for (lname, func, cu) in (("F.Cu", "Copper,L1,Top", "F.Cu"),
                              ("B.Cu", "Copper,L2,Bot", "B.Cu")):
        g = Gerber(func)
        for p in pads:
            if p["type"] == "np_thru_hole" or cu not in p["layers"]:
                continue
            g.flash(_pad_ap(p), p["x"], p["y"])
        for (net, layer, a, b, w) in router.tracks:
            if layer != cu:
                continue
            g.line(a[0], a[1], b[0], b[1], w)
        for (net, x, y) in router.vias:
            g.flash(("C", round(DRC["use_via"], 6)), x, y)
        files.append((f"{stem}-{lname.replace('.', '_')}.gbr",
                      g.dumps(f"{board['name']} {lname}")))

    MASK = 2 * 0.05                       # pad_to_mask_clearance 0.05 / 片側
    for (lname, func, cu) in (("F.Mask", "SolderMask,Top", "F.Cu"),
                              ("B.Mask", "SolderMask,Bot", "B.Cu")):
        g = Gerber(func, "Negative")
        for p in pads:
            if p["type"] == "np_thru_hole" or cu not in p["layers"]:
                continue
            g.flash(_pad_ap(p, MASK), p["x"], p["y"])
        files.append((f"{stem}-{lname.replace('.', '_')}.gbr",
                      g.dumps(f"{board['name']} {lname} (vias tented)")))

    for (lname, func, cu) in (("F.Paste", "Paste,Top", "F.Cu"),
                              ("B.Paste", "Paste,Bot", "B.Cu")):
        g = Gerber(func)
        n = 0
        for p in pads:
            if p["type"] != "smd" or cu not in p["layers"]:
                continue
            g.flash(_pad_ap(p), p["x"], p["y"])
            n += 1
        if n:
            files.append((f"{stem}-{lname.replace('.', '_')}.gbr",
                          g.dumps(f"{board['name']} {lname}")))

    for (lname, func, side) in (("F.Silkscreen", "Legend,Top", "F.SilkS"),
                                ("B.Silkscreen", "Legend,Bot", "B.SilkS")):
        g = Gerber(func)
        n = 0
        for (ly, a, b) in lines:
            if ly != side:
                continue
            g.line(a[0], a[1], b[0], b[1], SILK_W)
            n += 1
        for (ly, x, y, txt, size, kind, owner, rot) in texts:
            if ly != side:
                continue
            for pl in text_polylines(txt, x, y, size, mirror=(side == "B.SilkS")):
                g.polyline(pl, SILK_W)
            n += 1
        if n:
            files.append((f"{stem}-{lname.replace('.', '_')}.gbr",
                          g.dumps(f"{board['name']} {lname}")))

    g = Gerber("Profile,NP")
    for pl in outline_polylines(board):
        g.polyline(pl, 0.10)
    files.append((f"{stem}-Edge_Cuts.gbr", g.dumps(f"{board['name']} outline")))

    # --- Excellon
    def excellon(holes, plated):
        tools = sorted({round(d, 3) for (d, _, _) in holes})
        L = ["M48", "; MindClip gen_pcb.py Excellon",
             "; FORMAT={-:-/ absolute / metric / decimal}",
             f"; TYPE={'PTH' if plated else 'NPTH'}",
             "FMAT,2", "METRIC,TZ"]
        for i, d in enumerate(tools):
            L.append(f"T{i+1}C{d:.3f}")
        L += ["%", "G90", "G05"]
        for i, d in enumerate(tools):
            L.append(f"T{i+1}")
            for (dd, x, y) in holes:
                if abs(dd - d) < 1e-6:
                    L.append(f"X{x:.3f}Y{y:.3f}")
        L += ["T0", "M30"]
        return "\n".join(L) + "\n"

    pth = [(p["drill"], p["x"], p["y"]) for p in pads
           if p["drill"] and p["type"] == "thru_hole"]
    pth += [(DRC["use_via_drill"], x, y) for (_, x, y) in router.vias]
    npth = [(p["drill"], p["x"], p["y"]) for p in pads
            if p["type"] == "np_thru_hole"]
    if pth:
        files.append((f"{stem}-PTH.drl", excellon(pth, True)))
    if npth:
        files.append((f"{stem}-NPTH.drl", excellon(npth, False)))

    # --- BOM / CPL（JLCPCB SMT 形式。LCSC 品番は未指定＝要記入）
    bom = {}
    for ref, (X, Y), R, fp in board["fps"]:
        if fp["attr"] == "through_hole" and fp["ref"].startswith("MH"):
            continue
        if fp["ref"].startswith("TP") or fp["ref"] in ("U1",):
            continue
        key = (fp["value"], fp["lib"])
        bom.setdefault(key, []).append(fp["ref"])
    b = ["Comment,Designator,Footprint,LCSC Part #"]
    for (val, lib), refs in sorted(bom.items()):
        b.append(f'"{val}","{",".join(sorted(refs))}","{lib}",')
    b.append("# LCSC Part # は未指定。JLCPCB の SMT 実装を使う場合は発注前に記入すること。")
    b.append("# 本プロジェクトの既定は手はんだ（0805 まで）なので実装サービスは任意。")
    files.append((f"{stem}-bom.csv", "\n".join(b) + "\n"))

    c = ["Designator,Mid X,Mid Y,Layer,Rotation"]
    for ref, (X, Y), R, fp in board["fps"]:
        if fp["ref"].startswith("MH"):
            continue
        layer = "bottom" if fp["ref"] == "J4" else "top"
        c.append(f"{fp['ref']},{X:.4f},{Y:.4f},{layer},{KROT(R):.1f}")
    c.append("# 座標系は Gerber と同一（筐体座標 x右/y上）。原点は body 外形の左下。")
    files.append((f"{stem}-cpl.csv", "\n".join(c) + "\n"))

    for name, txt in files:
        with open(os.path.join(outdir, name), "w") as fh:
            fh.write(txt)
    return [n for n, _ in files]


def verify_fabrication(outdir, stem, board, pads, router):
    """書き出した製造データを **読み直して** 中身を数え、生成元と突き合わせる。
    Gerber を書きっぱなしにしないための最低限の自己検査。"""
    errs = []
    exp_flash = {
        "F_Cu": sum(1 for p in pads if p["type"] != "np_thru_hole"
                    and "F.Cu" in p["layers"]) + len(router.vias),
        "B_Cu": sum(1 for p in pads if p["type"] != "np_thru_hole"
                    and "B.Cu" in p["layers"]) + len(router.vias),
    }
    exp_draw = {
        "F_Cu": sum(1 for t in router.tracks if t[1] == "F.Cu"),
        "B_Cu": sum(1 for t in router.tracks if t[1] == "B.Cu"),
    }
    for key in ("F_Cu", "B_Cu"):
        fn = os.path.join(outdir, f"{stem}-{key}.gbr")
        txt = open(fn).read()
        if not txt.startswith("%FSLAX46Y46*%"):
            errs.append(f"{key}: 座標フォーマット指定が先頭に無い")
        if not txt.rstrip().endswith("M02*"):
            errs.append(f"{key}: M02* で終わっていない")
        defined = set(re.findall(r"%ADD(\d+)[CRO],", txt))
        used = set(re.findall(r"^D(\d+)\*$", txt, re.M))
        if used - defined:
            errs.append(f"{key}: 未定義アパーチャ D{sorted(used - defined)}")
        want = set()
        for p in pads:
            if p["type"] != "np_thru_hole" and key.replace("_", ".") in p["layers"]:
                want.add((round(p["x"], 4), round(p["y"], 4)))
        for (_, vx, vy) in router.vias:
            want.add((round(vx, 4), round(vy, 4)))
        got = {(round(int(m.group(1)) / 1e6, 4), round(int(m.group(2)) / 1e6, 4))
               for m in re.finditer(r"X(-?\d+)Y(-?\d+)D03\*", txt)}
        if got != want:
            errs.append(f"{key}: flash 座標が生成元と不一致 "
                        f"(欠 {sorted(want - got)[:3]} / 余 {sorted(got - want)[:3]})")
        nf = len(re.findall(r"D03\*", txt))
        nd = len(re.findall(r"D01\*", txt))
        if nf != exp_flash[key]:
            errs.append(f"{key}: flash {nf} != 期待 {exp_flash[key]}")
        if nd != exp_draw[key]:
            errs.append(f"{key}: draw {nd} != 期待 {exp_draw[key]}")
        for m in re.finditer(r"X(-?\d+)Y(-?\d+)D0[123]\*", txt):
            if abs(int(m.group(1))) > 10 ** 9 or abs(int(m.group(2))) > 10 ** 9:
                errs.append(f"{key}: 座標が異常 {m.group(0)}")
                break
    pth = [p for p in pads if p["drill"] and p["type"] == "thru_hole"]
    fn = os.path.join(outdir, f"{stem}-PTH.drl")
    if os.path.exists(fn):
        txt = open(fn).read()
        n = len(re.findall(r"^X-?[\d.]+Y-?[\d.]+$", txt, re.M))
        if n != len(pth) + len(router.vias):
            errs.append(f"PTH.drl: 穴数 {n} != 期待 {len(pth) + len(router.vias)}")
        if "M48" not in txt or "M30" not in txt:
            errs.append("PTH.drl: M48/M30 が無い")
    for suffix, need in (("bom.csv", "Comment,Designator"),
                         ("cpl.csv", "Designator,Mid X,Mid Y,Layer,Rotation")):
        txt = open(os.path.join(outdir, f"{stem}-{suffix}")).read()
        if not txt.startswith(need):
            errs.append(f"{suffix}: ヘッダが違う")
    return errs


# ---------------------------------------------------------------------------
# 9. 作図（同じデータ構造から PNG と SVG を出す）
# ---------------------------------------------------------------------------
LBL_OFF = {"U1": (-6.0, 7.0), "J2": (0.0, 3.0), "J3": (0.0, 2.1),
           "J4": (-3.6, 0.0), "J1": (0.0, -3.4)}

COL = dict(edge="#111111", fcu="#c02020", bcu="#2050c0", pad="#c8a020",
           padb="#5080d0", crtyd="#b060c0", silk="#f0f0f0", dim="#3a7d44",
           body="#888888")


def draw_board(ax, board, pads, router, case, show_dims=True):
    import matplotlib.patches as mp
    bx0, by0, bx1, by1 = board["rect"]
    r = board["corner_r"]
    ax.add_patch(mp.FancyBboxPatch((bx0 + r, by0 + r), bx1 - bx0 - 2 * r,
                                   by1 - by0 - 2 * r,
                                   boxstyle=mp.BoxStyle("Round", pad=r),
                                   fc="#1f6f3f", ec=COL["edge"], lw=1.6, zorder=1))
    for (cx0, cy0, cx1, cy1) in board.get("cutouts", []):
        ax.add_patch(mp.Rectangle((cx0, cy0), cx1 - cx0, cy1 - cy0, fc="white",
                                  ec=COL["edge"], lw=1.2, hatch="//", zorder=2))
        ax.text((cx0 + cx1) / 2, (cy0 + cy1) / 2,
                f"BAT pad\naccess window\n{cx1-cx0:.1f} x {cy1-cy0:.1f}",
                ha="center", va="center", fontsize=6, zorder=3)
    for (net, layer, a, b, w) in router.tracks:
        ax.plot([a[0], b[0]], [a[1], b[1]],
                color=COL["fcu"] if layer == "F.Cu" else COL["bcu"],
                lw=max(0.8, w * 3.2), solid_capstyle="round", zorder=3,
                alpha=0.95 if layer == "F.Cu" else 0.75)
    for (net, x, y) in router.vias:
        ax.add_patch(mp.Circle((x, y), DRC["use_via"] / 2, fc="#e0e0e0",
                               ec="#404040", lw=0.4, zorder=4))
    for (ref, x0, y0, x1, y1) in abs_courtyards(board):
        ax.add_patch(mp.Rectangle((x0, y0), x1 - x0, y1 - y0, fc="none",
                                  ec=COL["crtyd"], lw=0.5, ls=":", zorder=5))
    for p in pads:
        c = COL["padb"] if "B.Cu" in p["layers"] and "F.Cu" not in p["layers"] \
            else COL["pad"]
        if p["type"] == "np_thru_hole":
            ax.add_patch(mp.Circle((p["x"], p["y"]), p["w"] / 2, fc="white",
                                   ec=COL["edge"], lw=0.8, zorder=6))
            continue
        ax.add_patch(mp.Rectangle((p["x"] - p["w"] / 2, p["y"] - p["h"] / 2),
                                  p["w"], p["h"], fc=c, ec="#8a6b10", lw=0.3,
                                  zorder=6))
        if p["drill"]:
            ax.add_patch(mp.Circle((p["x"], p["y"]), p["drill"] / 2, fc="white",
                                   ec="none", zorder=7))
    off = {"U1": (-6.0, 7.0), "J2": (0.0, 3.0), "J3": (0.0, 2.1),
           "J4": (-3.6, 0.0), "J1": (0.0, -3.4)}
    for ref, (X, Y), R, fp in board["fps"]:
        lbl = board["labels"].get(ref, "")
        ox, oy = off.get(ref, (0.0, 0.0))
        ax.text(X + ox, Y + oy, ref, ha="center", va="center", fontsize=6.5,
                color="white", zorder=10,
                bbox=dict(fc="#000000cc", ec="none", pad=0.6))
        if lbl:
            ax.text(X + ox, Y + oy - 1.0, lbl, ha="center", va="top",
                    fontsize=5.0, color="#f2f2f2", zorder=10)
    for ref, labels in board["padlabels"].items():
        for ref2, (X, Y), R, fp in board["fps"]:
            if ref2 != ref:
                continue
            for lbl, pd in zip(labels, fp["pads"]):
                dx, dy = _rot(pd[3][0], pd[3][1], R)
                ax.text(X + dx, Y + dy, lbl, ha="center", va="center",
                        fontsize=4.3, color="#2b2b2b", zorder=11,
                        fontweight="bold")
    if show_dims:
        d = 2.2
        ax.annotate("", (bx0, by0 - d), (bx1, by0 - d),
                    arrowprops=dict(arrowstyle="<->", color=COL["dim"], lw=0.9))
        ax.text((bx0 + bx1) / 2, by0 - d - 0.4, f"{bx1-bx0:.1f} mm",
                ha="center", va="top", color=COL["dim"], fontsize=7)
        ax.annotate("", (bx1 + d, by0), (bx1 + d, by1),
                    arrowprops=dict(arrowstyle="<->", color=COL["dim"], lw=0.9))
        ax.text(bx1 + d + 0.3, (by0 + by1) / 2, f"{by1-by0:.1f} mm",
                ha="left", va="center", color=COL["dim"], fontsize=7, rotation=90)
    ax.set_aspect("equal")
    span_y = 30.0                       # 両パネルで mm スケールを揃える
    cyv = (by0 + by1) / 2
    ax.set_xlim(bx0 - 6.5, bx1 + 6.5)
    ax.set_ylim(cyv - span_y / 2, cyv + span_y / 2)
    ax.set_facecolor("#f7f7f4")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def render_png(boards, case, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for fam in ("IPAGothic", "IPAPGothic", "Noto Sans CJK JP", "DejaVu Sans"):
        try:
            import matplotlib.font_manager as fm
            fm.findfont(fm.FontProperties(family=fam), fallback_to_default=False)
            matplotlib.rcParams["font.family"] = [fam, "DejaVu Sans"]
            break
        except Exception:
            continue
    matplotlib.rcParams["axes.unicode_minus"] = False
    fig = plt.figure(figsize=(15.5, 9.2), dpi=150)
    wr = [(b["rect"][2] - b["rect"][0]) + 13.0 for (b, _, _) in boards]
    gs = fig.add_gridspec(1, 3, width_ratios=wr + [sum(wr) * 0.9], wspace=0.10)
    for k, (b, pads, rt) in enumerate(boards):
        ax = fig.add_subplot(gs[0, k])
        draw_board(ax, b, pads, rt, case)
        bx0, by0, bx1, by1 = b["rect"]
        ax.set_title(f"{b['name']}\n{bx1-bx0:.1f} x {by1-by0:.1f} x "
                     f"{b['thickness']:.1f} mm  2層 FR-4", fontsize=9)
    ax = fig.add_subplot(gs[0, 2])
    ax.axis("off")
    a = case["allday"]
    lines = [
        "MindClip DIY — PCB LAYOUT (v2 / 発注ゲート未通過)",
        "",
        "■ v1.5 はこの基板を使わない",
        "  採用案 = 案A-1（ハーネス・基板なし・はんだ10点）",
        "  本図は SCHEMATIC.md §9 の v2 用データ。",
        "  §9.4 の離脱ゲート通過＋スタック厚実測まで発注禁止。",
        "",
        "■ 筐体からの寸法決定（cad/mindclip_case.py 実行値）",
        f"  外形(allday) {a['W']:.1f} x {a['H']:.1f} x {a['TOTAL_D']:.1f} mm",
        f"  内寸 IW {a['IW']:.1f} / IH {a['IH']:.1f} / ID {a['ID']:.1f}",
        f"  左ポケット床 x {a['WALL']:.1f}..{a['xiao_stops'][0][0]:.1f} /"
        f" y {a['bat'][3]:.1f}..{a['sw_rib'][1]:.1f}",
        f"  リッド内面 z = {a['BODY_D']:.1f}（allday）/ "
        f"{case['slim']['BODY_D']:.1f}（slim）",
        "",
        "■ 層構成（両基板共通）",
        "  2層 FR-4 / 厚 0.8mm / 銅 1oz(35um)",
        "  外層のみ配線・内層なし / レジスト緑 / HASL(有鉛なし)",
        f"  線幅 {DRC['use_track_sig']:.2f}mm / クリアランス "
        f"{DRC['use_clear']:.2f}mm",
        f"  ビア φ{DRC['use_via']:.1f}/穴 φ{DRC['use_via_drill']:.1f}mm",
        f"  THT穴 φ{DRC['use_drill']:.2f}mm（JST PH ピン）"
        f" / シルク線幅 {DRC['min_silk']:.2f}mm",
        "",
        "■ 凡例",
        "  赤 = F.Cu 配線   青 = B.Cu 配線",
        "  黄 = F.Cu パッド 水色 = B.Cu パッド",
        "  紫点線 = コートヤード  白丸 = 穴",
        "",
        "■ MC-SENSE-A（推奨）",
        "  左ポケット床置き。筐体CAD変更ゼロ・追加高さ0.00mm。",
        "  allday 専用（slim は J1 嵌合高さの天井余裕不足）。",
        "  J2 の6ランドはテストポイントを兼ねる。",
        "",
        "■ MC-CARRIER-A（参考）",
        "  XIAO をカステレーション直はんだ。筐体改造必須:",
        "  GAP_BX 1.2→2.1 / M_TOP 0.6→2.0 / XIAO_LIFT 1.4→1.6",
        "  外形高さ 49.4 → 51.7 mm（body/lid 再印刷）",
        "  ★ XIAO フットプリントと BAT窓位置は未実測 assumption",
        "  ★ 逆接続保護 FET(Q1/Q2) は rev.A では未搭載",
        "",
        "■ 製造データ（gerber/ 以下）",
        "  Gerber RS-274X + Excellon + BOM/CPL を出力済み。",
        "  ただし KiCad 本体の DRC / 製造業者 DFM は未実行。",
        "  発注前に LAYOUT.md §9.3 の手順で必ず DRC を通すこと。",
    ]
    ax.text(0.0, 1.0, "\n".join(lines), va="top", ha="left", fontsize=7.6,
            linespacing=1.35, transform=ax.transAxes)
    fig.suptitle("MindClip DIY — PCB 部品配置図 (layout.png) / generated by gen_pcb.py",
                 fontsize=12, y=0.985)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_svg(boards, path):
    """実寸(1:1, 1mm = 1 user unit = 96/25.4 px 指定)の配置図。"""
    pad = 8.0
    gap = 15.0
    widths, heights = [], []
    for (b, _, _) in boards:
        x0, y0, x1, y1 = b["rect"]
        widths.append(x1 - x0)
        heights.append(y1 - y0)
    W = sum(widths) + gap * (len(boards) - 1) + 2 * pad
    H = max(heights) + 2 * pad + 9
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
         f'viewBox="0 0 {W:.3f} {H:.3f}" version="1.1">',
         '<style>text{font-family:monospace}</style>',
         f'<rect width="{W:.3f}" height="{H:.3f}" fill="#ffffff"/>']
    ox = pad
    for (b, pads, rt) in boards:
        x0, y0, x1, y1 = b["rect"]
        bw, bh = x1 - x0, y1 - y0

        def T(x, y):
            return (ox + (x - x0), pad + 9 + (y1 - y))
        s.append(f'<g id="{b["name"]}">')
        s.append(f'<text x="{ox:.2f}" y="{pad+2.4:.2f}" font-size="1.6" '
                 f'font-weight="bold">{b["name"]}</text>')
        s.append(f'<text x="{ox:.2f}" y="{pad+4.4:.2f}" font-size="1.0">'
                 f'{bw:.1f}x{bh:.1f}x{b["thickness"]:.1f}mm 2L FR-4</text>')
        s.append(f'<text x="{ox:.2f}" y="{pad+6.0:.2f}" font-size="1.0">'
                 f'PRINT 100% (1:1)</text>')
        r = b["corner_r"]
        px, py = T(x0, y1)
        s.append(f'<rect x="{px:.3f}" y="{py:.3f}" width="{bw:.3f}" '
                 f'height="{bh:.3f}" rx="{r}" ry="{r}" fill="#1f6f3f" '
                 f'stroke="#111" stroke-width="0.15"/>')
        for (cx0, cy0, cx1, cy1) in b.get("cutouts", []):
            qx, qy = T(cx0, cy1)
            s.append(f'<rect x="{qx:.3f}" y="{qy:.3f}" width="{cx1-cx0:.3f}" '
                     f'height="{cy1-cy0:.3f}" rx="1" fill="#ffffff" '
                     f'stroke="#111" stroke-width="0.12"/>')
        for (net, layer, a, bb, w) in rt.tracks:
            ax_, ay_ = T(*a)
            bx_, by_ = T(*bb)
            s.append(f'<line x1="{ax_:.3f}" y1="{ay_:.3f}" x2="{bx_:.3f}" '
                     f'y2="{by_:.3f}" stroke="'
                     f'{"#c02020" if layer=="F.Cu" else "#2050c0"}" '
                     f'stroke-width="{w}" stroke-linecap="round" '
                     f'opacity="{0.95 if layer=="F.Cu" else 0.7}"/>')
        for (net, x, y) in rt.vias:
            vx, vy = T(x, y)
            s.append(f'<circle cx="{vx:.3f}" cy="{vy:.3f}" '
                     f'r="{DRC["use_via"]/2}" fill="#e8e8e8" stroke="#444" '
                     f'stroke-width="0.08"/>')
        for p in pads:
            qx, qy = T(p["x"] - p["w"] / 2, p["y"] + p["h"] / 2)
            if p["type"] == "np_thru_hole":
                cx_, cy_ = T(p["x"], p["y"])
                s.append(f'<circle cx="{cx_:.3f}" cy="{cy_:.3f}" '
                         f'r="{p["w"]/2}" fill="#ffffff" stroke="#111" '
                         f'stroke-width="0.12"/>')
                continue
            col = "#5080d0" if ("B.Cu" in p["layers"] and
                                "F.Cu" not in p["layers"]) else "#c8a020"
            s.append(f'<rect x="{qx:.3f}" y="{qy:.3f}" width="{p["w"]:.3f}" '
                     f'height="{p["h"]:.3f}" fill="{col}" stroke="#8a6b10" '
                     f'stroke-width="0.06"/>')
            if p["drill"]:
                cx_, cy_ = T(p["x"], p["y"])
                s.append(f'<circle cx="{cx_:.3f}" cy="{cy_:.3f}" '
                         f'r="{p["drill"]/2}" fill="#ffffff"/>')
        for ref, (X, Y), R, fp in b["fps"]:
            lox, loy = LBL_OFF.get(ref, (0.0, 0.0))
            tx, ty = T(X + lox, Y + loy)
            s.append(f'<text x="{tx:.3f}" y="{ty+0.35:.3f}" font-size="1.0" '
                     f'text-anchor="middle" fill="#ffffff" '
                     f'stroke="#00000066" stroke-width="0.15" '
                     f'paint-order="stroke">{ref}</text>')
        for ref, labels in b["padlabels"].items():
            for ref2, (X, Y), R, fp in b["fps"]:
                if ref2 != ref:
                    continue
                for lbl, pd in zip(labels, fp["pads"]):
                    dx, dy = _rot(pd[3][0], pd[3][1], R)
                    tx, ty = T(X + dx, Y + dy - 0.22)
                    s.append(f'<text x="{tx:.3f}" y="{ty:.3f}" font-size="0.62" '
                             f'text-anchor="middle" fill="#2b2b2b">{lbl}</text>')
        s.append('</g>')
        ox += bw + gap
    s.append('</svg>')
    with open(path, "w") as fh:
        fh.write("\n".join(s) + "\n")


# ---------------------------------------------------------------------------
# 10. main
# ---------------------------------------------------------------------------
def netlist_crosscheck(board, pads):
    """netlist.json の V2_SENSE_SATELLITE / A1_HARNESS_V15 と突き合わせる。"""
    nl = json.load(open(NETLIST))
    want = defaultdict(set)
    for n in nl["nets"]:
        for c in n["connections"]:
            want[n["name"]].add(c)
    have = defaultdict(set)
    for p in pads:
        if p["net"]:
            have[p["net"]].add(f"{p['ref']}.{p['pad']}")
    msgs = []
    for net, conns in sorted(want.items()):
        on_board = {c for c in conns if c.split(".")[0] in
                    {r for r, _, _, _ in board["fps"]}}
        got = have.get(net, set())
        missing = on_board - got - {"U1.BATP", "U1.BATN"}
        if missing:
            msgs.append(f"  {net}: 基板に無い接続 {sorted(missing)}")
    return msgs


def main():
    case = load_case()
    print(f"[case] allday src = {case['allday_src']}")
    a = case["allday"]
    print(f"[case] allday outer {a['W']}x{a['H']}x{a['TOTAL_D']} / "
          f"IW {a['IW']} IH {a['IH']} ID {a['ID']} / lid inner z {a['BODY_D']}")
    print(f"[case] slim   ID {case['slim']['ID']} / lid inner z "
          f"{case['slim']['BODY_D']}")

    results = []
    total_err = 0
    total_warn = 0
    for builder in (build_sense_board, build_carrier_board):
        b = builder(case)
        pads = abs_pads(b)
        rt = Router(b, pads)
        nets = defaultdict(list)
        for p in pads:
            if p["net"]:
                nets[p["net"]].append(p)
        order = sorted(nets, key=lambda n: len(nets[n]))
        unrouted = []
        for n in order:
            if not rt.route_net(n, nets[n]):
                unrouted.append(n)
        path = os.path.join(HERE, b["file"])
        txt, netnames = write_kicad_pcb(b, pads, rt, path, b["name"])
        errs, warns, info = validate_pcb(txt, b, pads, rt, netnames)
        fit = check_case_fit(b, case)
        xc = netlist_crosscheck(b, pads)
        bx0, by0, bx1, by1 = b["rect"]
        print(f"\n=== {b['name']}  ({b['file']}) ===")
        print(f"  outline      : {bx1-bx0:.2f} x {by1-by0:.2f} x "
              f"{b['thickness']:.2f} mm, corner R{b['corner_r']:.1f}")
        print(f"  placement    : x {bx0:.2f}..{bx1:.2f} / y {by0:.2f}..{by1:.2f} "
              f"/ z {b['z'][0]:.2f}..{b['z'][1]:.2f} (筐体座標)")
        print(f"  sexp         : balanced={info['paren_balanced']} "
              f"footprints={info['footprints']} pads={info['pads']} "
              f"nets={info['nets']} segments={info['segments']} "
              f"vias={info['vias']} edge_lines={info['edge_lines']}")
        print(f"  routing      : {'ALL NETS ROUTED' if not unrouted else 'UNROUTED: ' + str(unrouted)}")
        for m in fit:
            print(f"  fit          : {m}")
        if xc:
            print("  netlist xcheck:")
            for m in xc:
                print(m)
        else:
            print("  netlist xcheck: OK (netlist.json の該当接続は全て基板上にある)")
        print(f"  drc          : {info['copper_prims']} copper primitives, "
              f"{info['drc_pairs']} 異ネットペアを総当たり "
              f"(track/via/pad の全組合せ + 角R外形 + 窓)")
        for w in warns:
            print(f"  [warn] {w}")
        for e in errs:
            print(f"  [ERROR] {e}")
        if info.get("silk_dropped"):
            print(f"  silk dropped : {', '.join(info['silk_dropped'])}"
                  f"  ← パッドに乗る/基板外に出るため文字を置かなかった箇所"
                  f"（layout_top.svg を 1:1 で印刷して実装ガイドにすること）")
        outdir = os.path.join(HERE, "gerber", b["name"].lower())
        stem = b["file"].replace(".kicad_pcb", "")
        made = write_fabrication(b, pads, rt, outdir, stem)
        vf = verify_fabrication(outdir, stem, b, pads, rt)
        for e in vf:
            print(f"  [ERROR] fab: {e}")
        errs = errs + vf
        print(f"  fab data     : gerber/{b['name'].lower()}/ に {len(made)} ファイル"
              f"（読み直し検査 {'OK' if not vf else 'NG'}）")
        print(f"                 {' '.join(made)}")
        total_err += len(errs) + len(unrouted)
        total_warn += len(warns)
        results.append((b, pads, rt))

    render_png(results, case, os.path.join(HERE, "layout.png"))
    print("\n[render] layout.png")
    render_svg(results, os.path.join(HERE, "layout_top.svg"))
    print("[render] layout_top.svg")
    import xml.dom.minidom as md
    md.parse(os.path.join(HERE, "layout_top.svg"))
    print("[verify] layout_top.svg is well-formed XML")
    print("\n" + "=" * 74)
    print(f"[done] independent-DRC errors={total_err}  warnings={total_warn}")
    print("=" * 74)
    print("""\
★ この行を「検証済み」と読まないこと。ここで通ったのは
   (1) S式の括弧対応 / ネット参照の整合
   (2) 線幅・穴径・アニュラリング
   (3) **全銅箔（パッド／トラック／ビア）の異ネット総当たりクリアランス**
   (4) 銅箔・穴 と 基板外形（角R を SDF で厳密に）／窓 の距離
   (5) 回転フットプリントのパッド絶対角トークンの有無
   (6) コートヤード重なり・シルクのパッド乗り／外形はみ出し
   (7) 基板外形が筐体内寸に収まっているか
  だけである。**KiCad 本体の DRC も、製造業者の DFM も一度も走っていない。**
  発注前に必ず LAYOUT.md §9.3 の手順で KiCad に読み込み、JLCPCB ルール
  （線幅/間隔 0.127 / 穴 0.30 / アニュラリング 0.13）で DRC を通すこと。
  そもそも v1.5（採用案 A-1）ではこの基板を作らない。SCHEMATIC.md §9.4 の
  離脱ゲートと XIAO スタック厚の実測が済むまで発注してはならない。""")
    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
