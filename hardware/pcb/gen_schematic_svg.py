#!/usr/bin/env python3
"""schematic.svg を生成する。

  python3 hardware/pcb/gen_schematic_svg.py

SCHEMATIC.md / netlist.json と同じネット名・同じ数値を使う（分圧の値は netlist.json から読む）。
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
NL = json.load(open(os.path.join(HERE, "netlist.json"), encoding="utf-8"))

W, H = 1480, 1290
FONT = ("'Noto Sans JP','Noto Sans CJK JP','Source Han Sans JP','Hiragino Sans',"
        "'Yu Gothic',Meiryo,IPAPGothic,IPAGothic,sans-serif")
MONO = "'DejaVu Sans Mono',Menlo,Consolas,monospace"

C_INK, C_SUB, C_BOX = "#1a1a1a", "#5f6b73", "#37474f"
C_FILL, C_RED, C_BLUE, C_ORG = "#ffffff", "#d62828", "#1565c0", "#e07b00"
C_PUR, C_TEAL, C_PANEL, C_GREY = "#6a1b9a", "#00796b", "#fafafa", "#9aa4ab"

out = []
A = out.append


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=13, fill=C_INK, anchor="start", weight="normal", font=FONT):
    A(f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" fill="{fill}" '
      f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')


def rect(x, y, w, h, fill=C_FILL, stroke=C_BOX, sw=1.6, rx=0, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
      f'stroke="{stroke}" stroke-width="{sw}"{d}/>')


def poly(pts, stroke=C_INK, sw=2.2, dash=None, fill="none"):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    p = " ".join(f"{x},{y}" for x, y in pts)
    A(f'<polyline points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" '
      f'stroke-linejoin="round" stroke-linecap="round"{d}/>')


def line(x1, y1, x2, y2, stroke=C_INK, sw=2.2, dash=None):
    poly([(x1, y1), (x2, y2)], stroke, sw, dash)


def dot(x, y, r=4.6, fill=C_INK):
    A(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"/>')


def cross(x, y, color=C_GREY, r=6):
    line(x - r, y - r, x + r, y + r, color, 2.4)
    line(x + r, y - r, x - r, y + r, color, 2.4)


def netlabel(x, y, name, color=C_INK, anchor="middle"):
    w = 9.2 * len(name) + 14
    x0 = {"middle": x - w / 2, "start": x, "end": x - w}[anchor]
    A(f'<rect x="{x0}" y="{y-12}" width="{w}" height="20" rx="4" fill="#ffffff" '
      f'stroke="{color}" stroke-width="1.2"/>')
    text(x0 + w / 2, y + 3, name, 12.5, color, "middle", "bold", MONO)
    return w


def gnd(x, y, color=C_INK, label=True):
    line(x, y, x, y + 12, color)
    for i, hw in enumerate((13, 8.5, 4)):
        line(x - hw, y + 12 + i * 5, x + hw, y + 12 + i * 5, color, 2.4)
    if label:
        text(x, y + 42, "GND", 11.5, color, "middle", "bold", MONO)


def res_h(x, y, w, h, label, val, color=C_INK):
    rect(x, y - h / 2, w, h, "#ffffff", color, 1.8, 2)
    text(x + w / 2, y - h / 2 - 9, label, 12, color, "middle", "bold", MONO)
    text(x + w / 2, y + h / 2 + 16, val, 12.5, C_INK, "middle", "bold")


def res_v(x, y, w, h, label, val, color=C_INK):
    rect(x - w / 2, y, w, h, "#ffffff", color, 1.8, 2)
    text(x - w / 2 - 10, y + h / 2 - 3, label, 12, color, "end", "bold", MONO)
    text(x - w / 2 - 10, y + h / 2 + 14, val, 12.5, C_INK, "end", "bold")


def cap_v(x, y, label, val, color=C_INK):
    line(x, y, x, y + 14, color)
    line(x - 15, y + 14, x + 15, y + 14, color, 3)
    line(x - 15, y + 22, x + 15, y + 22, color, 3)
    line(x, y + 22, x, y + 36, color)
    text(x + 21, y + 16, label, 12, color, "start", "bold", MONO)
    text(x + 21, y + 32, val, 12.5, C_INK, "start", "bold")


def port(x, y, label, color, direction="right"):
    w = 7.6 * len(label) + 30
    if direction == "right":
        pts = [(x, y - 14), (x + w - 14, y - 14), (x + w, y), (x + w - 14, y + 14), (x, y + 14)]
        tx = x + 12
    else:
        pts = [(x, y), (x + 14, y - 14), (x + w, y - 14), (x + w, y + 14), (x + 14, y + 14)]
        tx = x + 22
    A('<polygon points="' + " ".join(f"{a},{b}" for a, b in pts) +
      f'" fill="#ffffff" stroke="{color}" stroke-width="1.8"/>')
    text(tx, y + 4, label, 12.5, color, "start", "bold", MONO)
    return w


# ============================================================== 枠・タイトル
A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
A(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>')

rect(24, 20, W - 48, 74, "#ffffff", C_BOX, 2, 6)
text(44, 52, "MindClip DIY  回路図", 25, C_INK, "start", "bold")
text(300, 52, "rev.1 — 採用: 案A-1 ハーネス v1.5（キャリア基板を作らない）", 15, C_SUB)
text(44, 79, "Seeed XIAO ESP32S3 Sense ＋ LiPo(PCM内蔵) ＋ スライドスイッチ ＋ 録音中LED　／　"
             "はんだ10点・空中3端子スプライス0箇所・追加高さ0.00mm・筐体CAD変更なし", 13, C_SUB)
text(W - 44, 44, "hardware/pcb/SCHEMATIC.md", 12, C_SUB, "end", "normal", MONO)
text(W - 44, 63, "hardware/pcb/netlist.json", 12, C_SUB, "end", "normal", MONO)
text(W - 44, 82, "rev.1  2026-08-28", 12, C_SUB, "end", "normal", MONO)

# ============================================================== 主回路パネル
MX0, MY0, MX1, MY1 = 24, 108, 912, 762
rect(MX0, MY0, MX1 - MX0, MY1 - MY0, "#ffffff", C_GREY, 1.4, 6)
text(MX0 + 16, MY0 + 26, "v1.5（案A-1）実装する回路 — この6ネットだけを作る", 15, C_INK, "start", "bold")

# ---- U1 -------------------------------------------------------------------
UX0, UY0, UX1, UY1 = 520, 210, 812, 544
rect(UX0, UY0, UX1 - UX0, UY1 - UY0, "#f7f9fa", C_BOX, 2.2, 4)
text((UX0 + UX1) / 2, UY0 + 30, "U1", 17, C_INK, "middle", "bold", MONO)
text((UX0 + UX1) / 2, UY0 + 52, "XIAO ESP32S3 Sense", 14.5, C_INK, "middle", "bold")
text((UX0 + UX1) / 2, UY0 + 70, "(Sense拡張ボード装着／カメラ取外し)", 11.5, C_SUB, "middle")

PY_D0, PY_D1, PY_D3, PY_D4, PY_GND = 320, 365, 410, 455, 505


def upin_l(y, name, gpio, color, dashed=False):
    line(UX0, y, 470, y, color, 2.2, "6 4" if dashed else None)
    dot(UX0, y, 3.6, color)
    text(UX0 + 12, y - 5, name, 12.5, C_INK, "start", "bold", MONO)
    if gpio:
        text(UX0 + 12, y + 11, gpio, 10.5, C_SUB, "start", "normal", MONO)


upin_l(PY_D0, "D0", "GPIO1 / ADC1_CH0", C_TEAL, True)
upin_l(PY_D1, "D1", "GPIO2", C_BLUE)
upin_l(PY_D3, "D3", "GPIO4", C_ORG)
upin_l(PY_D4, "D4", "GPIO5 / ADC1_CH4", C_TEAL, True)
upin_l(PY_GND, "GND", "", C_INK)
text(462, PY_D0 - 12, "[v2]", 10.5, C_TEAL, "end", "bold", MONO)
text(462, PY_D4 - 12, "[v2]", 10.5, C_TEAL, "end", "bold", MONO)

# 右側: 5V と NC 群
line(UX1, PY_D0, 866, PY_D0, C_PUR, 2.2, "6 4")
dot(UX1, PY_D0, 3.6, C_PUR)
text(UX1 - 12, PY_D0 - 5, "5V", 12.5, C_INK, "end", "bold", MONO)
text(UX1 - 12, PY_D0 + 11, "= USB VBUS 直結", 10.5, C_SUB, "end", "normal", MONO)
text(870, PY_D0 - 8, "[v2]", 10.5, C_PUR, "start", "bold", MONO)

line(UX1, PY_D4, 852, PY_D4, C_GREY, 1.8, "5 4")
dot(UX1, PY_D4, 3.6, C_GREY)
cross(858, PY_D4)
text(UX1 - 12, PY_D4 - 12, "3V3 / D2 / D5 / D6 / D7", 11.5, C_SUB, "end", "bold", MONO)
text(UX1 - 12, PY_D4 + 4, "D8 / D9 / D10", 11.5, C_SUB, "end", "bold", MONO)
text(858, PY_D4 + 26, "NC", 11.5, C_SUB, "middle", "bold", MONO)

# 裏面 BAT パッド
for x, nm, col in ((600, "BAT+", C_RED), (688, "BAT−", C_INK)):
    line(x, UY1, x, 592, col)
    dot(x, UY1, 3.6, col)
    text(x, UY1 - 12, nm, 12.5, C_INK, "middle", "bold", MONO)
text(644, UY1 - 32, "裏面パッド（−がUSB-C側）", 10.5, C_SUB, "middle")

# USB-C
rect(596, 150, 130, 40, "#cfd8dc", "#546e7a", 1.6, 8)
text(661, 175, "USB-C", 14, "#37474f", "middle", "bold")
line(661, 190, 661, UY0, "#546e7a", 2.4)
text(736, 166, "充電 50mA固定", 11, C_SUB)
text(736, 182, "書込み・VBUS供給源", 11, C_SUB)

# ---- SW1 ------------------------------------------------------------------
SX0, SY0, SX1, SY1 = 176, 282, 352, 394
rect(SX0, SY0, SX1 - SX0, SY1 - SY0, "#ffffff", C_BOX, 1.8, 4)
text((SX0 + SX1) / 2, SY0 + 20, "SW1  SS-12D00G3", 12.5, C_INK, "middle", "bold", MONO)
text((SX0 + SX1) / 2, SY0 + 35, "スライドスイッチ 1回路2接点", 10.5, C_SUB, "middle")
T1 = (232, 352)
T3 = (232, 382)
TC = (328, PY_D1)
for (px, py), lab in ((T1, "1"), (T3, "3 = NC（切り落とし可）")):
    dot(px, py, 4.2)
    text(px + 10, py + 4, lab, 10.5, C_SUB, "start", "bold", MONO)
dot(TC[0], TC[1], 4.2)
text(TC[0] + 2, TC[1] - 15, "2 中央/コモン", 10.5, C_SUB, "middle", "bold", MONO)
line(TC[0], TC[1], T1[0] + 4, T1[1] + 2, C_INK, 3.0)     # ブレード（ON位置）
line(T1[0], T1[1], SX0, T1[1], C_INK)                    # 端子1のリード（左へ）
line(T3[0], T3[1], SX0, T3[1], C_GREY, 1.8, "5 4")       # 端子3（NC）
cross(SX0 - 12, T3[1])
line(TC[0], TC[1], SX1, TC[1], C_BLUE)                   # コモンのリード（右へ）
text((SX0 + SX1) / 2, SY1 + 14, "ON = コモンが端子1に接続 = LOW = 録音", 11, C_INK, "middle", "bold")

# SW_IN
poly([(SX1, PY_D1), (470, PY_D1)], C_BLUE)
netlabel(430, PY_D1 - 14, "SW_IN", C_BLUE)
text(408, 246, "内部プルアップ 45kΩ", 11, C_BLUE, "middle", "bold")
text(408, 262, "ON:73µA / OFF:0µA", 10.5, C_SUB, "middle")
poly([(408, 270), (408, PY_D1)], C_BLUE, 1.2, "4 3")

# ---- LED + R1 -------------------------------------------------------------
LEDY = 452
poly([(258, LEDY - 16), (258, LEDY + 16), (232, LEDY), (258, LEDY - 16)], C_ORG, 2.2, None, "#ffe0b2")
line(230, LEDY - 16, 230, LEDY + 16, C_ORG, 3.0)
line(214, LEDY, 230, LEDY, C_INK)
line(258, LEDY, 300, LEDY, C_ORG)
for dx, dy in ((0, 0), (10, 6)):
    ya, yb_ = LEDY - 18 - dy, LEDY - 28 - dy
    poly([(248 + dx, ya), (262 + dx, yb_)], C_ORG, 1.8)
    poly([(256 + dx, yb_), (262 + dx, yb_), (262 + dx, yb_ + 6)], C_ORG, 1.8)
text(212, LEDY - 14, "K", 11.5, C_SUB, "middle", "bold", MONO)
text(272, LEDY - 14, "A", 11.5, C_SUB, "middle", "bold", MONO)
rect(300, LEDY - 15, 92, 30, "#ffffff", C_INK, 1.8, 2)
text(346, LEDY - 24, "R1  220Ω 1/4W", 12, C_INK, "middle", "bold", MONO)
line(392, LEDY, 430, LEDY, C_ORG)
poly([(430, LEDY), (430, PY_D3), (470, PY_D3)], C_ORG)
netlabel(279, LEDY + 34, "LED_A", C_ORG)
netlabel(452, PY_D3 - 14, "LED_DRV", C_ORG)
text(96, 522, "D1 = 赤LED 3mm OSR5JA3Z74A（Vf≈2.0V）", 11, C_INK, "start", "bold")
text(96, 538, "I=(3.3−2.0)/220=5.91mA・PWM10〜20%で微灯（平均0.6〜1.2mA）", 10.5, C_SUB, "start")

# ---- GND デイジーチェーン ---------------------------------------------------
J = (150, T1[1])
poly([(470, PY_GND), (90, PY_GND), (90, J[1]), (SX0, J[1])], C_INK)   # U1.GND → SW1.1
poly([(J[0], J[1]), (J[0], LEDY), (214, LEDY)], C_INK)                # SW1.1 → LED.K
dot(J[0], J[1], 5.2)
netlabel(420, PY_GND, "GND", C_INK)
rect(38, 296, 104, 40, "#fff3e0", "#ef6c00", 1.2, 4)
text(90, 312, "J07 = 2導体接合", 10.5, "#ef6c00", "middle", "bold")
text(90, 328, "黒2本を撚って1点で", 10.5, "#ef6c00", "middle", "bold")
poly([(142, 330), (J[0] - 6, J[1] - 4)], "#ef6c00", 1.2, "4 3")
text(96, 554, "GND はデイジーチェーン（空中3端子スプライスを廃止）", 10.5, C_SUB, "start")

# ---- 電池 + J1 -------------------------------------------------------------
BY = 626
rect(46, BY - 30, 168, 88, "#ffffff", C_BOX, 1.8, 4)
text(130, BY - 10, "BT1  LiPo", 12.5, C_INK, "middle", "bold", MONO)
text(130, BY + 6, "802530 800mAh (allday)", 10.5, C_SUB, "middle")
text(130, BY + 20, "502530 500mAh (slim)", 10.5, C_SUB, "middle")
text(130, BY + 40, "PCM内蔵 必須（連続500mA/瞬時1A）", 10.5, C_RED, "middle", "bold")
for dx, hh, sw in ((0, 17, 3.0), (10, 9, 3.0)):
    line(236 + dx, BY - hh, 236 + dx, BY + hh, C_INK, sw)
line(214, BY, 236, BY, C_RED)
line(246, BY, 268, BY, C_INK)
text(236, BY - 26, "+", 15, C_RED, "middle", "bold")
text(248, BY - 26, "−", 15, C_INK, "middle", "bold")
line(214, BY, 214, BY - 30, C_RED)
line(268, BY, 268, BY + 30, C_INK)
poly([(214, BY - 30), (300, BY - 30)], C_RED)
poly([(268, BY + 30), (300, BY + 30)], C_INK)

rect(300, BY - 46, 96, 92, "#ffffff", C_RED, 1.8, 4)
line(348, BY - 46, 348, BY + 46, C_RED, 1.4, "5 4")
text(348, BY - 58, "J1  JST-PH2.0 2P", 12.5, C_INK, "middle", "bold", MONO)
text(348, BY + 64, "極性キー付・圧着工具不要・2A定格", 10.5, C_SUB, "middle")
for yy, lab, col in ((BY - 30, "1 +", C_RED), (BY + 30, "2 −", C_INK)):
    dot(326, yy, 3.6, col)
    dot(370, yy, 3.6, col)
    line(326, yy, 370, yy, col, 1.6, "3 3")
    text(348, yy - 8, lab, 11.5, col, "middle", "bold", MONO)
poly([(396, BY - 30), (600, BY - 30), (600, 592)], C_RED)
poly([(396, BY + 30), (688, BY + 30), (688, 592)], C_INK)
netlabel(470, BY - 30, "BATP", C_RED)
netlabel(500, BY + 30, "BATN", C_INK)
text(348, BY + 82, "※ BATN は XIAO 内部で GND と同電位である前提（未検証・§5.4② で要確認）",
     10.5, C_RED, "middle", "bold")

rect(38, BY + 94, 620, 58, "#ffebee", C_RED, 1.4, 4)
text(48, BY + 112, "【必須】嵌合前テスタ: ①+↔BAT+導通 ②−↔GNDピン導通 ③+↔−が非短絡",
     11.5, C_RED, "start", "bold")
text(48, BY + 127,
     "④ プラグを『キー面基準』で固定し、どちらの“コンタクト位置”が+かを DCV で測る",
     11.0, C_RED, "start", "bold")
text(48, BY + 141,
     "   → それが J1 pin1(BATP) と嵌合すること。線の色も『どちらのリードが+か』も見ない（§5.4）",
     10.2, C_RED, "start")

# ---- 内蔵ブロック注記（U1 の外に出す） ---------------------------------------
rect(700, 600, 198, 104, "#eceff1", "#b0bec5", 1.2, 4)
text(712, 618, "U1 内蔵（配線不要）", 11.5, C_SUB, "start", "bold")
for i, s in enumerate(["充電IC BQ25101 … 50mA固定",
                       "PDMマイク CLK=GPIO42 DATA=41",
                       "microSD SCK7 MISO8 MOSI9",
                       "microSD CS=GPIO21（内蔵LED共用）",
                       "→ 外付けLEDが必要な電気的根拠"]):
    text(712, 635 + i * 14, s, 9.8, C_INK, "start", "normal", MONO)
poly([(780, 600), (780, 560), (700, 560)], "#b0bec5", 1.2, "4 3")

# ============================================================== ネット一覧
TX0, TY0, TX1, TY1 = 928, 108, 1456, 762
rect(TX0, TY0, TX1 - TX0, TY1 - TY0, C_PANEL, C_GREY, 1.4, 6)
text(TX0 + 16, TY0 + 26, "ネット一覧", 15, C_INK, "start", "bold")
text(TX0 + 112, TY0 + 26, "（netlist.json と1対1）", 11.5, C_SUB)
y = TY0 + 44
line(TX0 + 14, y, TX1 - 14, y, C_GREY, 1.2)
y += 26
for nm, col, conn, role in [
    ("GND", C_INK, "U1.GND — SW1.1 — D1.K", "共通GND（デイジーチェーン）"),
    ("BATP", C_RED, "U1.BATP — J1.1 — BT1.P", "電池正極 3.0–4.2V"),
    ("BATN", C_INK, "U1.BATN — J1.2 — BT1.N", "電池負極（GNDと同電位の前提）"),
    ("SW_IN", C_BLUE, "U1.D1 — SW1.2", "録音ON/OFF・内部プルアップ"),
    ("LED_DRV", C_ORG, "U1.D3 — R1.1", "LED駆動（PWM）"),
    ("LED_A", C_ORG, "R1.2 — D1.A", "電流制限後のアノード"),
]:
    netlabel(TX0 + 20, y, nm, col, "start")
    text(TX0 + 132, y + 4, conn, 11.5, C_INK, "start", "normal", MONO)
    text(TX0 + 132, y + 20, role, 10.5, C_SUB)
    y += 38
line(TX0 + 14, y - 8, TX1 - 14, y - 8, C_GREY, 1.2)
y += 14
text(TX0 + 20, y, "[v2 / 非実装] サテライト基板に載せる", 12, C_TEAL, "start", "bold")
y += 24
for nm, col, conn, role in [
    ("VBUS", C_PUR, "U1.5V — R2.1", "USB VBUS 4.40–5.25V"),
    ("VBUS_SENSE", C_TEAL, "R2.2 — R3.1 — C2.1 — U1.D0", "USB挿入検出（0.600倍）"),
    ("VBAT_SENSE", C_TEAL, "R4.2 — R5.1 — C1.1 — U1.D4", "電池電圧監視（0.500倍）"),
]:
    netlabel(TX0 + 20, y, nm, col, "start")
    text(TX0 + 32, y + 22, conn, 11.5, C_SUB, "start", "normal", MONO)
    text(TX0 + 32, y + 38, role, 10.5, C_SUB)
    y += 56
line(TX0 + 14, y - 10, TX1 - 14, y - 10, C_GREY, 1.2)
y += 12
text(TX0 + 20, y, "未接続 (NC)", 12.5, C_INK, "start", "bold")
text(TX0 + 20, y + 19, "U1.3V3 / U1.D2 / U1.D5 / U1.D6 / U1.D7", 11.5, C_SUB, "start", "normal", MONO)
text(TX0 + 20, y + 35, "U1.D8 / U1.D9 / U1.D10 / SW1.3", 11.5, C_SUB, "start", "normal", MONO)
text(TX0 + 20, y + 55, "D8/D9/D10 = GPIO7/8/9 は microSD SPI 使用中", 11, C_RED, "start", "bold")
text(TX0 + 20, y + 71, "D2 = GPIO3 はストラッピングピン（恒久使用禁止）", 11, C_RED, "start", "bold")
text(TX0 + 20, y + 87, "GPIO41/42(マイク)・GPIO21(SD CS)は外部ピンに出ていない", 11, C_SUB, "start")
y += 116
rect(TX0 + 16, y - 16, TX1 - TX0 - 32, 46, "#ffffff", C_BOX, 1.4, 4)
text(TX0 + 30, y + 2, "はんだ 10点 ／ 3端子空中スプライス 0箇所", 12.5, C_INK, "start", "bold", MONO)
text(TX0 + 30, y + 20, "v1 は11点・スプライス1箇所。A-2(不採用)は17〜19点・3箇所", 10.5, C_SUB)

# ============================================================== v2 パネル
VX0, VY0, VX1, VY1 = 24, 778, 1456, 1218
rect(VX0, VY0, VX1 - VX0, VY1 - VY0, C_PANEL, C_GREY, 2.0, 8, "10 6")
text(VX0 + 20, VY0 + 30, "[v2 / 非実装] VBUS検出 ＋ 電池電圧監視", 16, C_INK, "start", "bold")
text(VX0 + 372, VY0 + 30, "実装先は「案D サテライト基板（秋月112019 / 10.2×15.9mm・追加高さ0.00mm）」。"
                          "空中配線（案A-2）での実装は禁止。", 12, C_SUB)
rect(VX1 - 216, VY0 + 12, 196, 30, "#ffebee", C_RED, 1.6, 4)
text(VX1 - 118, VY0 + 33, "v1.5 では実装しない", 13.5, C_RED, "middle", "bold")

d_vbus = next(n for n in NL["nets"] if n["name"] == "VBUS_SENSE")["divider"]
d_vbat = next(n for n in NL["nets"] if n["name"] == "VBAT_SENSE")["divider"]


def divider(x0, yb, in_port, netname, rtop, rtop_v, rbot, rbot_v, capref, outport, notes, color):
    w = port(x0, yb, in_port, color)
    rx = x0 + w + 50
    line(x0 + w, yb, rx, yb, color)
    res_h(rx, yb, 92, 28, rtop, rtop_v, color)
    nx = rx + 92 + 66
    line(rx + 92, yb, nx, yb, color)
    dot(nx, yb, 4.6, color)
    line(nx, yb, nx + 40, yb, color)
    netlabel(nx + 2, yb - 24, netname, C_TEAL, "start")
    port(nx + 40, yb, outport, C_TEAL)
    line(nx, yb, nx, yb + 34, color)
    res_v(nx, yb + 34, 28, 84, rbot, rbot_v, color)
    line(nx, yb + 118, nx, yb + 132, color)
    gnd(nx, yb + 132)
    line(nx, yb + 22, nx + 104, yb + 22, color)
    dot(nx, yb + 22, 4.6, color)
    cap_v(nx + 104, yb + 22, capref, "0.1µF", color)
    line(nx + 104, yb + 58, nx + 104, yb + 132, color)
    gnd(nx + 104, yb + 132)
    for i, s in enumerate(notes):
        text(x0 + 2, yb + 206 + i * 19, s, 11.5, C_INK if i == 0 else C_SUB,
             "start", "bold" if i == 0 else "normal")


divider(VX0 + 40, VY0 + 122, "U1.5V (VBUS)", "VBUS_SENSE", "R2", "220k", "R3", "330k", "C2",
        "→ U1.D0 (GPIO1 / ADC1_CH0)",
        [f"分圧比 {d_vbus['ratio']:.3f}（E24全探索で最良グループ）／ Rth {d_vbus['thevenin_ohm']//1000}kΩ ／ τ={d_vbus['tau_ms']}ms",
         "4.40V→2.640V ／ 5.00V→3.000V ／ 5.25V→3.150V　(VIH=2.475V・設計上限3.30V・絶対最大3.6V)",
         f"±5%最悪 {d_vbus['worst_case_tol5pct']['low_at_4.40V']:.3f}V（余裕+58mV）→ ±1%品なら "
         f"{d_vbus['worst_case_tol1pct']['low_at_4.40V']:.3f}V（+144mV）",
         "判定はADC（閾値2.00V）を主系にしデジタルVIHに依存しない。EXT1 ANY_HIGH は従系",
         f"消費 {d_vbus['current_ua']['at_5.00V']}µA … USB挿入中のみ。電池からは流れない",
         "220k/220k(1:1) は 4.40V で 2.090V となり VIH を割るため不可（案C/案Dの誤り）"],
        C_PUR)

divider(VX0 + 752, VY0 + 122, "BATP (電池+)", "VBAT_SENSE", "R4", "220k", "R5", "220k", "C1",
        "→ U1.D4 (GPIO5 / ADC1_CH4)",
        [f"分圧比 {d_vbat['ratio']:.3f} ／ Rth {d_vbat['thevenin_ohm']//1000}kΩ ／ τ={d_vbat['tau_ms']}ms"
         "（100ms待って初回読み捨て）",
         "3.00V→1.500V ／ 3.70V→1.850V ／ 4.20V→2.100V　(ADC1 12dB 推奨0–3100mV の中央)",
         f"常時消費 {d_vbat['current_ua']['at_4.20V']}µA = {d_vbat['battery_impact']['mah_per_day']}mAh/日 "
         f"= allday 680mAh の 0.034%/日（無視可）",
         "±5%抵抗だと電池換算±210mV → ±1%品にするか、ファーム1点校正（NVS保存）",
         "USB挿入中は BAT+ が充電出力に引かれる → SOC推定は VBUS=LOW のときのみ有効",
         "警告3.40V／停止3.20V（セルPCMのUVLO 2.4–3.0V に到達する前にソフトで倒す）"],
        C_TEAL)

# ============================================================== 凡例・脚注
lx = VX0 + 20
text(lx, H - 54, "凡例:", 12, C_INK, "start", "bold")
lx += 48
for col, lab in ((C_RED, "BAT+/電源"), (C_INK, "GND"), (C_BLUE, "スイッチ(D1)"),
                 (C_ORG, "LED(D3)"), (C_PUR, "VBUS(5V)"), (C_TEAL, "センス/ADC [v2]")):
    line(lx, H - 58, lx + 30, H - 58, col, 3.2)
    text(lx + 36, H - 54, lab, 11.5, C_INK)
    lx += 36 + 11.5 * len(lab) + 26
text(VX0 + 20, H - 26,
     "数値の再現: python3 hardware/pcb/calc_circuit.py ／ ネットリスト整合検査: python3 hardware/pcb/validate_netlist.py",
     11.5, C_SUB, "start", "normal", MONO)
text(VX1 - 20, H - 26, "A-2（空中配線でのVBUS検出・電池監視追加）は不採用。§0.1 参照。",
     11.5, C_RED, "end", "bold")
A("</svg>")

path = os.path.join(HERE, "schematic.svg")
open(path, "w", encoding="utf-8").write("\n".join(out))
print("wrote", path, os.path.getsize(path), "bytes")
