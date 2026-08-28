#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MindClip DIY — 案B: XIAO キャリア基板 (MC-CARRIER-A) の
レイアウト定義・筐体との干渉検証・ネットリスト/レイアウト図の生成

    python3 hardware/pcb/carrier_board.py

出力:
    hardware/pcb/netlist.txt          … ネットリスト (KiCad/EasyEDA 入力用の人手写し元)
    hardware/pcb/carrier_layout.svg   … 実寸レイアウト図 (部品配置・寸法)
    hardware/pcb/stackup.svg          … 断面図 (高さ予算)

座標系は筐体CAD (hardware/cad/mindclip_case.py) の body 基準と同じ:
    X = 幅 (右が +, USB-C 側) / Y = 高さ (上がマイク側) / Z = 奥行き (0=背面, +=リッド側)

前提となる筐体パラメータ変更 (height_budget.py で検証済み):
    XIAO_LIFT 1.4 → 1.8 (= PCB_LIFT 0.8 + 基板厚 1.0)
    GAP_BX    1.2 → 1.8 (XIAO 下辺のキャステレーション・ランド用)
    M_TOP     0.6 → 1.7 (XIAO 上辺のキャステレーション・ランド用)
    → 内寸高さ IH 46.2 → 47.9 / 外形高さ H 49.4 → 51.1 mm
"""
import os
import re
import io
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
CAD = os.path.abspath(os.path.join(HERE, "..", "cad", "mindclip_case.py"))

# --- 基板パラメータ ---------------------------------------------------------
PCB_T = 1.0          # 基板厚 (JLCPCB 2層は 0.8/1.0/1.2/1.6 が同一価格帯)
PCB_LIFT = 0.8       # 基板下面と筐体床の隙間 (THT 足のはんだフィレット逃げ)
GAP_BX = 1.8         # 電池上端〜XIAO 下端 (ランド用に 1.2 から拡大)
M_TOP = 1.7          # XIAO 上端〜上壁内面 (ランド用に 0.6 から拡大)
EDGE_CLR = 0.3       # 基板外形と筐体内壁のクリアランス (片側)
LAND_OUT = 1.0       # キャステレーション・ランドが XIAO 外形から出る長さ
LAND_IN = 1.0        # 同 XIAO 直下に潜る長さ
LAND_W = 1.1         # ランド幅
PITCH = 2.54
NPIN = 7

# 部品の実装高さ (mm)。* = assumption
COMP_H = {
    "J1 JST B2B-PH-K-S": 6.0,      # データシート値 (Web検証済み)
    "J1 + PHR-2 嵌合代": 7.0,       # *assumption (+1.0)
    "Q1/Q2 AO3401A SOT-23": 1.1,   # *assumption (SOT-23 一般値)
    "R/C 0805(2012)": 0.6,         # *assumption
    "XIAO Sense スタック": 7.5,     # *assumption (MECHANICAL.md §8)
}


def load_case(variant, xiao_lift, gap_bx, m_top):
    src = open(CAD, encoding="utf-8").read()
    src = re.sub(r"^XIAO_LIFT = [0-9.]+", f"XIAO_LIFT = {xiao_lift}", src, 1, re.M)
    src = re.sub(r"^GAP_BX = [0-9.]+", f"GAP_BX = {gap_bx}", src, 1, re.M)
    src = re.sub(r"^M_TOP = [0-9.]+", f"M_TOP = {m_top}", src, 1, re.M)
    os.environ["MINDCLIP_VARIANT"] = variant
    ns = {"__name__": "case_probe", "__file__": CAD}
    exec(compile(src, CAD, "exec"), ns)
    return ns


# ---------------------------------------------------------------------------
# レイアウト
# ---------------------------------------------------------------------------
def build_layout(ns):
    """筐体名前空間 ns からキャリア基板のジオメトリを組み立てる"""
    WALL, IW, IH = ns["WALL"], ns["IW"], ns["IH"]
    xiao, bat = ns["xiao"], ns["bat"]
    z0 = WALL + PCB_LIFT                     # 基板下面
    z1 = z0 + PCB_T                          # 基板上面 (= XIAO 基板下面)

    # 基板外形: 電池上端より上、内壁から EDGE_CLR
    bx0 = WALL + EDGE_CLR
    bx1 = WALL + IW - EDGE_CLR
    by0 = bat[3] + 0.4                       # 電池上端 +0.4
    by1 = WALL + IH - EDGE_CLR
    board = (bx0, by0, bx1, by1, z0, z1)

    # XIAO 直下の窓 (BAT+ ジャンパ線とはんだ盛りの逃げ)。
    # 左端を XIAO 外形より左に出し、線を横方向に引き出せるようにする。
    win = (xiao[0] - 0.4, xiao[1] + 3.8, xiao[0] + 11.6,
           xiao[1] + 13.8, z0, z1)

    # キャステレーション・ランド (下段=電源列 5V/GND/3V3/D10/D9/D8/D7,
    #                             上段=信号列 D0..D6)。x は XIAO 中心基準。
    cx = (xiao[0] + xiao[2]) / 2.0
    xs = [cx + (i - (NPIN - 1) / 2.0) * PITCH for i in range(NPIN)]
    # ピン並び: USB-C を +x に向けたとき、下辺が 5V(+x端)…D7、上辺が D0(+x端)…D6
    bot_names = ["5V", "GND", "3V3", "D10", "D9", "D8", "D7"]
    top_names = ["D0", "D1", "D2", "D3", "D4", "D5", "D6"]
    lands = []
    for name, x in zip(bot_names, reversed(xs)):      # +x 端が 5V
        lands.append((name, x, xiao[1], "bottom"))
    for name, x in zip(top_names, reversed(xs)):      # +x 端が D0
        lands.append((name, x, xiao[3], "top"))

    def land_box(x, yedge, side):
        if side == "bottom":
            return (x - LAND_W / 2, yedge - LAND_OUT, x + LAND_W / 2,
                    yedge + LAND_IN, z1, z1 + 0.035)
        return (x - LAND_W / 2, yedge - LAND_IN, x + LAND_W / 2,
                yedge + LAND_OUT, z1, z1 + 0.035)

    # 部品配置 (x0,y0,x1,y1 は基板上のフットプリント外形)
    parts = {
        # 電池コネクタ: 左下 = 電池リード出射側 (左端チャネル) に最短
        "J1": ("JST B2B-PH-K-S 2P", (2.4, by0 + 0.6, 8.4, by0 + 5.1), 6.0),
        # 逆接続保護 P-ch MOSFET (背中合わせ 2 個)
        "Q1": ("AO3401A SOT-23", (9.4, by0 + 0.6, 12.4, by0 + 3.0), 1.1),
        "Q2": ("AO3401A SOT-23", (9.4, by0 + 3.6, 12.4, by0 + 6.0), 1.1),
        # 分圧・LED 抵抗・ADC 安定化コンデンサ (0805)
        "R1": ("220R 0805 (LED)", (2.4, by0 + 8.0, 4.4, by0 + 9.3), 0.6),
        "R2": ("220k 0805 (VBUS hi)", (5.0, by0 + 8.0, 7.0, by0 + 9.3), 0.6),
        "R3": ("330k 0805 (VBUS lo)", (7.6, by0 + 8.0, 9.6, by0 + 9.3), 0.6),
        "R4": ("220k 0805 (VBAT hi)", (2.4, by0 + 10.2, 4.4, by0 + 11.5), 0.6),
        "R5": ("220k 0805 (VBAT lo)", (5.0, by0 + 10.2, 7.0, by0 + 11.5), 0.6),
        "C1": ("100n 0805 (VBAT)", (7.6, by0 + 10.2, 9.6, by0 + 11.5), 0.6),
        "C2": ("100n 0805 (VBUS)", (10.2, by0 + 10.2, 12.2, by0 + 11.5), 0.6),
        # 手はんだ用スルーホール (線を挿してはんだ付け)
        "TP1": ("BAT+ ジャンパ (XIAO裏 BAT+ へ)", (12.6, by0 + 7.4, 14.6, by0 + 9.4), 0.0),
        "J2": ("スイッチ 2P THT (D1/GND)", (12.6, by0 + 15.0, 14.6, by0 + 17.6), 0.0),
        "J3": ("LED 2P THT (LED+/GND)", (2.4, by0 + 12.8, 4.4, by0 + 15.4), 0.0),
        # 筐体位置決めボス用穴 φ2.1
        "H1": ("位置決め穴 φ2.1", (2.2, by1 - 3.0, 4.3, by1 - 0.9), 0.0),
        "H2": ("位置決め穴 φ2.1", (12.6, by0 + 0.9, 14.7, by0 + 3.0), 0.0),
    }
    return dict(board=board, win=win, lands=lands, land_box=land_box,
                parts=parts, z0=z0, z1=z1, xs=xs,
                bot_names=bot_names, top_names=top_names)


# ---------------------------------------------------------------------------
# 検証
# ---------------------------------------------------------------------------
def _ov(a0, a1, b0, b1, tol=1e-6):
    return (a1 - tol > b0) and (b1 - tol > a0)


def hits(a, b):
    return (_ov(a[0], a[2], b[0], b[2]) and _ov(a[1], a[3], b[1], b[3])
            and _ov(a[4], a[5], b[4], b[5]))


def verify(variant):
    ns = load_case(variant, PCB_LIFT + PCB_T, GAP_BX, M_TOP)
    L = build_layout(ns)
    board, win = L["board"], L["win"]
    WALL, IW, IH, BODY_D = ns["WALL"], ns["IW"], ns["IH"], ns["BODY_D"]
    fails, warns, notes = [], [], []

    print(f"\n{'=' * 92}\n[{variant}] 筐体 {ns['W']:.1f} x {ns['H']:.1f} x "
          f"{ns['TOTAL_D']:.1f} mm / 内寸 {IW:.1f} x {IH:.1f} x {ns['ID']:.1f}")
    print(f"{'=' * 92}")
    print(f"  キャリア基板 外形 {board[2] - board[0]:.1f} x {board[3] - board[1]:.1f} mm "
          f"(面積 {(board[2] - board[0]) * (board[3] - board[1]):.0f} mm2), "
          f"厚 {PCB_T} mm, z {board[4]:.1f}..{board[5]:.1f}")

    # 1. キャビティ内に収まるか
    cav = (WALL, WALL, WALL + IW, WALL + IH, WALL, BODY_D)
    if not (board[0] >= cav[0] and board[2] <= cav[2]
            and board[1] >= cav[1] and board[3] <= cav[3]):
        fails.append("キャリア基板がキャビティ外形をはみ出す")

    # 2. 電池・リッド lip・リッド押さえリブとの干渉
    for name in ("bat", "lip_left", "lip_top", "lip_bottom", "lip_right"):
        if hits(board, ns[name]):
            fails.append(f"キャリア基板 <-> {name} が干渉")
    for i, rb in enumerate(ns["lid_bat_ribs"]):
        if hits(board, rb):
            fails.append(f"キャリア基板 <-> lid_bat_ribs[{i}] が干渉")

    # 3. 既存の内部リブとの干渉 (= 筐体側で作り直しが必要なリブの洗い出し)
    rib_groups = {
        "xiao_seats": ns["xiao_seats"], "xiao_stops": ns["xiao_stops"],
        "xiao_nubs_top": ns["xiao_nubs_top"], "xiao_nubs_bot": ns["xiao_nubs_bot"],
        "bat_stops_left": ns["bat_stops_left"], "bat_stops_bot": ns["bat_stops_bot"],
        "sw_rib": [ns["sw_rib"]],
    }
    clash = []
    for gname, boxes in rib_groups.items():
        for i, rb in enumerate(boxes):
            if hits(board, rb) or hits(win, rb):
                clash.append(f"{gname}[{i}]")
    if clash:
        notes.append("キャリア基板と当たるため撤去/改修が必要な内部リブ: "
                     + ", ".join(clash))

    # 4. XIAO が基板上に載るか (基板上面 = XIAO 基板下面)
    if abs(ns["xiao"][4] - L["z1"]) > 1e-6:
        fails.append(f"XIAO 下面 z={ns['xiao'][4]} が基板上面 z={L['z1']} と一致しない")

    # 5. キャステレーション・ランドが基板内に収まるか
    for name, x, ye, side in L["lands"]:
        lb = L["land_box"](x, ye, side)
        m_out = (board[3] - lb[3]) if side == "top" else (lb[1] - board[1])
        if lb[0] < board[0] or lb[2] > board[2] or lb[1] < board[1] or lb[3] > board[3]:
            fails.append(f"ランド {name} ({side}) が基板外形からはみ出す")
        elif m_out < 0.2:
            fails.append(f"ランド {name} ({side}) の銅箔〜基板端 {m_out:.2f}mm "
                         f"< 0.2mm (JLCPCB 最小)")
        elif m_out < 0.3:
            warns.append(f"ランド {name} ({side}) の銅箔〜基板端 {m_out:.2f}mm (余裕僅少)")

    # 6. 窓が XIAO の下に収まり、左に抜けているか
    if not (win[0] < ns["xiao"][0]):
        fails.append("BAT ジャンパ窓が XIAO 左端より内側にあり、線を横に引き出せない")
    if win[3] > ns["xiao"][3] - LAND_IN or win[1] < ns["xiao"][1] + LAND_IN:
        fails.append("BAT ジャンパ窓がキャステレーション・ランド帯に食い込む")
    notes.append(f"BAT ジャンパ窓 {win[2] - win[0]:.1f} x {win[3] - win[1]:.1f} mm "
                 f"(XIAO 裏 BAT パッド位置は assumption。実測後に位置決定)")

    # 7. 部品高さ vs リッド内面
    head = BODY_D - L["z1"]
    print(f"  キャリア上面 z={L['z1']:.1f} / リッド内面 z={BODY_D:.1f} "
          f"→ 実装可能高さ {head:.1f} mm")
    for label, h in COMP_H.items():
        mark = "OK" if h <= head else "NG"
        if h > head:
            fails.append(f"{label} (H{h}) が実装可能高さ {head:.1f}mm を超える")
        elif head - h < 1.0:
            warns.append(f"{label} (H{h}) の上余裕 {head - h:.2f}mm (配線曲げ代が苦しい)")
        print(f"    {mark}  {label:<24s} H{h:<5} 余裕 {head - h:+.2f} mm")

    # 8. 部品同士の重なり
    pn = list(L["parts"])
    for i in range(len(pn)):
        for j in range(i + 1, len(pn)):
            a = L["parts"][pn[i]][1]
            b = L["parts"][pn[j]][1]
            if _ov(a[0], a[2], b[0], b[2]) and _ov(a[1], a[3], b[1], b[3]):
                fails.append(f"部品 {pn[i]} と {pn[j]} が重なる")
    # 部品が基板内 / 窓を避けているか
    for k, (desc, fp, h) in L["parts"].items():
        if not (fp[0] >= board[0] and fp[2] <= board[2]
                and fp[1] >= board[1] and fp[3] <= board[3]):
            fails.append(f"部品 {k} が基板外形をはみ出す")
        if _ov(fp[0], fp[2], win[0], win[2]) and _ov(fp[1], fp[3], win[1], win[3]):
            fails.append(f"部品 {k} が BAT ジャンパ窓と重なる")
        for lname, lx, lye, lside in L["lands"]:
            lb = L["land_box"](lx, lye, lside)
            if _ov(fp[0], fp[2], lb[0], lb[2]) and _ov(fp[1], fp[3], lb[1], lb[3]):
                fails.append(f"部品 {k} がキャステレーション・ランド {lname} と重なる")
        # XIAO 直下に部品を置いていないか (XIAO 下は 0 クリアランス)
        if _ov(fp[0], fp[2], ns["xiao"][0], ns["xiao"][2]) and \
                _ov(fp[1], fp[3], ns["xiao"][1], ns["xiao"][3]) and h > 0:
            fails.append(f"部品 {k} が XIAO 直下にあり、XIAO を持ち上げてしまう")

    # 9. 電池リード〜J1 の到達性
    j1 = L["parts"]["J1"][1]
    lead_run = (j1[1] - ns["bat"][3]) + (j1[0] - WALL) + (L["z1"] + 6.0 - ns["bat"][4])
    notes.append(f"電池リード経路長の目安 {lead_run:.0f} mm "
                 f"(左端チャネル→立上げ→J1)。市販セルのリード 30〜50mm で足りる")

    for f in fails:
        print(f"  ★NG  {f}")
    for w in warns:
        print(f"  ！WARN {w}")
    for n in notes:
        print(f"  ・{n}")
    print(f"  → 判定: {'PASS' if not fails else 'FAIL'} "
          f"(NG {len(fails)} / WARN {len(warns)})")
    return ns, L, fails


# ---------------------------------------------------------------------------
# ネットリスト
# ---------------------------------------------------------------------------
NETLIST = """\
MindClip DIY — キャリア基板 MC-CARRIER-A  ネットリスト (rev.0 / 案B 評価用)
=========================================================================
KiCad / EasyEDA へ手入力するための一次資料。Gerber はこのリポジトリには無い
(本作業環境に KiCad が無いため。実制作時は本表から回路図を起こすこと)。

■ 部品
  U1  XIAO ESP32S3 Sense   キャステレーション 2x7 / 2.54mm / 列間 17.78mm
                           (基板上面へ直はんだ。ピンヘッダは使わない)
  J1  JST B2B-PH-K-S 2P    電池コネクタ (トップ型 / H6.0mm)  秋月 112802
  Q1,Q2 AO3401A (SOT-23)   P-ch MOSFET / 逆接続保護 (背中合わせ)  LCSC C15127
  R1  220R  0805           LED 電流制限 (ELECTRICAL.md §1.2 と同値)
  R2  220k  0805 / R3 330k 0805   VBUS(5V) 分圧 → 3.00V
  R4  220k  0805 / R5 220k 0805   VBAT 分圧 → Vbat/2 (1.5〜2.1V)
  C1,C2 100nF 0805         ADC 入力の電荷供給 (分圧のインピーダンス対策)
  TP1 φ1.0 スルーホール      BAT+ ジャンパ (XIAO 裏面 BAT+ パッドへ AWG30)
  J2  2P THT 2.54          スライドスイッチ用 (D1 / GND)
  J3  2P THT 2.54          LED 用 (LED_A / GND)

■ ネット
  GND        U1.GND, J1.2, Q1.G, Q2.G, R3.2, R5.2, C1.2, C2.2, J2.2, J3.2
             ※ XIAO の BAT- は内部で GND と同電位である前提 (要テスター確認)。
                成立すれば BAT- 側のジャンパ線は不要 → 線は BAT+ の1本だけ。
  VBAT_CELL  J1.1, Q1.D                      (セル正極。保護前)
  VBAT_MID   Q1.S, Q2.S                      (背中合わせ FET の共通ソース)
  VBAT_SYS   Q2.D, TP1, R4.1                 (保護後。XIAO BAT+ へジャンパ)
  VBUS       U1.5V, R2.1                     (XIAO の 5V ピン = USB VBUS 直結)
  VBUS_SENSE R2.2, R3.1, C2.1, U1.D0         (GPIO1 / RTC / デジタル入力で使用)
  VBAT_SENSE R4.2, R5.1, C1.1, U1.D4         (GPIO5 / ADC1_CH4)
  SW_IN      U1.D1, J2.1                     (GPIO2 / 内部プルアップ / ON=GND)
  LED_DRV    U1.D3, R1.1                     (GPIO4)
  LED_A      R1.2, J3.1

■ 未接続 (ランドのみ・機械保持用に半田付けしてよい)
  U1.3V3, U1.D10, U1.D9, U1.D8, U1.D7, U1.D2, U1.D5, U1.D6
  ※ D8/D9/D10 = GPIO7/8/9 は Sense 拡張ボードの microSD SPI。回路的に一切
     引き回さないこと (スタブでも触らない方が安全)。

■ 計算根拠
  VBUS 分圧 : 5.00V x 330k/(220k+330k) = 3.00V   (VIH=0.75x3.3=2.48V に対し +0.52V)
              USB 5.25V でも 3.15V < 3.3V。消費 9.1uA (USB 挿入時のみ)
  VBAT 分圧 : 4.20V x 220k/440k = 2.10V / 3.00V → 1.50V
              ADC1 12dB の精度確保域 150〜2450mV に収まる。常時 9.5uA
              → 680mAh に対し 0.001C 未満 (約340日で1%)。ELECTRICAL.md §2.1
                の v2 申し送り「220k x2・約9uA」と同値
  LED       : (3.3-2.0)/220 = 5.9mA (ELECTRICAL.md §1.2 と同じ)
  逆接続保護 : AO3401A x2 背中合わせ。正常時 Vgs=-Vbat で両方 ON。
              セル逆挿し時は両方 OFF + ボディダイオードが逆直列 → 双方向阻止。
              ★1個だけでは「逆挿しセルへの充電」を止められない (ボディダイオードが
                充電方向に導通する) ため必ず2個使うこと。
              オン抵抗 2x50mOhm = 0.1Ohm → WiFi 300mA バーストで 30mV 降下。
"""


def write_netlist():
    p = os.path.join(HERE, "netlist.txt")
    open(p, "w", encoding="utf-8").write(NETLIST)
    print(f"[write] {p}")


# ---------------------------------------------------------------------------
# SVG 出力
# ---------------------------------------------------------------------------
def svg_layout(ns, L, variant):
    S = 9.0                    # mm → px
    MX, MY = 34, 34
    W, H = ns["W"], ns["H"]
    ww, hh = W * S + 2 * MX, H * S + 2 * MY

    def X(x):
        return MX + x * S

    def Y(y):
        return MY + (H - y) * S      # y 反転 (上が +y)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{ww:.0f}" '
         f'height="{hh:.0f}" viewBox="0 0 {ww:.0f} {hh:.0f}">',
         '<style>text{font-family:IPAGothic,"Hiragino Sans","Yu Gothic",'
         'Meiryo,"Noto Sans JP",sans-serif}'
         '.t{font-size:8px;fill:#222}.s{font-size:6.5px;fill:#444}'
         '.h{font-size:12px;fill:#111}.d{font-size:7px;fill:#06c}</style>',
         f'<rect width="{ww:.0f}" height="{hh:.0f}" fill="#fff"/>']

    def rect(b, fill, stroke, sw=1.0, dash=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        o.append(f'<rect x="{X(b[0]):.1f}" y="{Y(b[3]):.1f}" '
                 f'width="{(b[2] - b[0]) * S:.1f}" height="{(b[3] - b[1]) * S:.1f}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def txt(x, y, s, cls="t", anchor="middle"):
        o.append(f'<text x="{X(x):.1f}" y="{Y(y):.1f}" class="{cls}" '
                 f'text-anchor="{anchor}">{s}</text>')

    # 筐体外形・キャビティ
    rect((0, 0, W, H, 0, 1), "#f7f7f7", "#999", 1.2)
    cav = (ns["WALL"], ns["WALL"], ns["WALL"] + ns["IW"], ns["WALL"] + ns["IH"])
    rect(cav + (0, 1), "#fff", "#bbb", 1.0, "4 3")
    # 電池
    rect(ns["bat"], "#fdf0d5", "#e0a800", 1.0)
    txt((ns["bat"][0] + ns["bat"][2]) / 2, ns["bat"][1] + 12,
        f"LiPo {ns['BAT_W']:.0f}x{ns['BAT_H']:.0f}x{ns['BAT_T']:.0f} ({variant})")
    txt((ns["bat"][0] + ns["bat"][2]) / 2, ns["bat"][1] + 9,
        "キャリア基板はここには重ねられない (電池上面 z%.1f)" % ns["bat"][5], "s")

    # キャリア基板
    b = L["board"]
    rect(b, "#e8f4e8", "#2a7", 1.6)
    # 窓
    rect(L["win"], "#fff", "#2a7", 1.2, "3 2")
    txt((L["win"][0] + L["win"][2]) / 2, L["win"][1] + 1.2,
        "BAT+ジャンパ窓 %.0fx%.0f" % (L["win"][2] - L["win"][0],
                                   L["win"][3] - L["win"][1]), "s")
    # XIAO
    x = ns["xiao"]
    rect(x, "none", "#c33", 1.4, "5 3")
    txt((x[0] + x[2]) / 2, x[3] - 3.0, "XIAO ESP32S3 Sense", "t")
    txt((x[0] + x[2]) / 2, x[3] - 5.4, "(キャリア基板上面へ直はんだ)", "s")
    txt(x[2] + 0.5, (x[1] + x[3]) / 2 - 6, "USB-C →", "s", "end")

    # ランド
    for name, lx, ye, side in L["lands"]:
        lb = L["land_box"](lx, ye, side)
        rect(lb, "#f2c200", "#a80", 0.6)
        ty = lb[3] + 0.7 if side == "top" else lb[1] - 1.6
        o.append(f'<text x="{X(lx):.1f}" y="{Y(ty):.1f}" class="s" '
                 f'text-anchor="middle" transform="rotate(-90 {X(lx):.1f} '
                 f'{Y(ty):.1f})">{name}</text>')

    # 部品
    for k, (desc, fp, h) in L["parts"].items():
        col = "#cfe3ff" if h > 0 else "#ffe0e0"
        rect(fp + (0, 1), col, "#369" if h > 0 else "#c66", 0.8)
        txt((fp[0] + fp[2]) / 2, (fp[1] + fp[3]) / 2 - 0.5, k, "s")
    # 凡例
    ly = 27.0
    for i, (k, (desc, fp, h)) in enumerate(sorted(L["parts"].items())):
        o.append(f'<text x="{X(-32.0):.1f}" y="{Y(ly - i * 1.9):.1f}" class="s" '
                 f'text-anchor="start">{k}: {desc}'
                 + (f"  H{h}" if h else "") + '</text>')

    o.append(f'<text x="{X(0):.1f}" y="{Y(H + 3.0):.1f}" class="h" '
             f'text-anchor="start">MC-CARRIER-A — キャリア基板レイアウト '
             f'({variant}) 実寸 {b[2] - b[0]:.1f} x {b[3] - b[1]:.1f} x {PCB_T}t mm'
             f'</text>')
    o.append(f'<text x="{X(0):.1f}" y="{Y(H + 0.8):.1f}" class="d" '
             f'text-anchor="start">筐体内寸 {ns["IW"]:.1f} x {ns["IH"]:.1f} '
             f'/ 外形 {W:.1f} x {H:.1f} x {ns["TOTAL_D"]:.1f} mm '
             f'(GAP_BX={GAP_BX} M_TOP={M_TOP} に拡大した前提)</text>')
    o.append("</svg>")
    p = os.path.join(HERE, f"carrier_layout_{variant}.svg")
    open(p, "w", encoding="utf-8").write("\n".join(o))
    print(f"[write] {p}")


def svg_stackup(cases):
    """z 方向のスタック断面 (v1 と 案B の比較)"""
    S = 26.0
    rowh = 150
    ww = 980
    hh = 120 + rowh * len(cases)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{ww}" height="{hh}" '
         f'viewBox="0 0 {ww} {hh}">',
         '<style>text{font-family:IPAGothic,"Hiragino Sans","Yu Gothic",'
         'Meiryo,"Noto Sans JP",sans-serif}'
         '.t{font-size:11px;fill:#222}.s{font-size:9px;fill:#555}'
         '.h{font-size:15px;fill:#111}</style>',
         f'<rect width="{ww}" height="{hh}" fill="#fff"/>',
         '<text x="20" y="30" class="h">MindClip — 奥行き(Z)スタック比較 '
         '/ 数値は hardware/pcb/height_budget.py の出力</text>']
    for i, (title, layers, total) in enumerate(cases):
        y0 = 70 + i * rowh
        o.append(f'<text x="20" y="{y0}" class="t">{title}</text>')
        x = 40
        for name, t, col in layers:
            w = t * S
            o.append(f'<rect x="{x:.1f}" y="{y0 + 12}" width="{w:.1f}" height="46" '
                     f'fill="{col}" stroke="#333" stroke-width="0.8"/>')
            o.append(f'<text x="{x + w / 2:.1f}" y="{y0 + 40}" class="s" '
                     f'text-anchor="middle" transform="rotate(-0)">{t}</text>')
            o.append(f'<text x="{x + w / 2:.1f}" y="{y0 + 78}" class="s" '
                     f'text-anchor="middle" transform="rotate(20 {x + w / 2:.1f} '
                     f'{y0 + 78})">{name}</text>')
            x += w
        o.append(f'<text x="{x + 14:.1f}" y="{y0 + 40}" class="t" '
                 f'text-anchor="start">→ 外形奥行き {total}</text>')
    o.append("</svg>")
    p = os.path.join(HERE, "stackup.svg")
    open(p, "w", encoding="utf-8").write("\n".join(o))
    print(f"[write] {p}")


def main():
    allfail = 0
    for variant in ("allday", "slim"):
        ns, L, fails = verify(variant)
        allfail += len(fails)
        svg_layout(ns, L, variant)
    write_netlist()

    C1, C2 = "#dfe8f5", "#f6dede"
    C3, C4 = "#e8f4e8", "#f0f0f0"
    svg_stackup([
        ("v1 (基板なし) allday", [("背面壁", 1.6, C4), ("裏面はんだ逃げ", 1.4, C2),
                              ("XIAOスタック", 7.5, C1), ("電池側で決まる余裕", 2.3, C4),
                              ("リッド", 1.8, C4)], "14.6 mm"),
        ("案B PCB1.0 allday", [("背面壁", 1.6, C4), ("基板下逃げ", 0.8, C2),
                             ("キャリア基板", 1.0, C3), ("XIAOスタック", 7.5, C1),
                             ("余裕", 1.9, C4), ("リッド", 1.8, C4)], "14.6 mm (変化なし)"),
        ("v1 (基板なし) slim", [("背面壁", 1.6, C4), ("裏面はんだ逃げ", 1.4, C2),
                            ("XIAOスタック", 7.5, C1), ("余裕", 0.6, C4),
                            ("リッド", 1.8, C4)], "12.9 mm"),
        ("案B PCB1.0 slim", [("背面壁", 1.6, C4), ("基板下逃げ", 0.8, C2),
                           ("キャリア基板", 1.0, C3), ("XIAOスタック", 7.5, C1),
                           ("余裕", 0.6, C4), ("リッド", 1.8, C4)], "13.3 mm (+0.4)"),
        ("案B PCB1.6 slim", [("背面壁", 1.6, C4), ("基板下逃げ", 0.8, C2),
                           ("キャリア基板", 1.6, C3), ("XIAOスタック", 7.5, C1),
                           ("余裕", 0.6, C4), ("リッド", 1.8, C4)], "13.9 mm (+1.0)"),
    ])
    print(f"\n総合: {'PASS' if allfail == 0 else f'FAIL ({allfail} 件)'}")
    return 0 if allfail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
