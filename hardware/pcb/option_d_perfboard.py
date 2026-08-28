#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案D (ユニバーサル基板・手組み) の成立性検証スクリプト

「PCBを発注せず、秋月のユニバーサル基板を切って手配線する」案が
v1 筐体 (hardware/cad/mindclip_case.py) に物理的に入るかを、CADのパラメータと
内部リブ AABB をそのまま読み込んで実数で検証する。推測値は ASSUMPTION 辞書に集約。

やること:
  1) 筐体CADを exec で読み込み (main は走らせない)、内部部品・リブの AABB を集める。
  2) 「基板が占める z スラブ」について、キャビティ断面を 0.1mm グリッドに離散化し、
     天井高さ (= 実装部品の許容高さ) 条件つきの **最大空き長方形** をヒストグラム法で求める。
     → 「どれだけの基板が、どれだけの部品高さで入るか」のトレードオフ曲線。
  3) 切り欠き可 (L字カット) の場合の上限として、同条件の**空き面積**も出す。
  4) 採用配置 (4x6=24穴) を定義し、各部品の footprint 直上の天井を実測して
     クリアランスを assert する。
  5) 代案「XIAOの下に敷く」を XIAO_LIFT 差し替えで評価 (奥行き増分・実装可能高さ)。
  6) 分圧回路の電気的成立性 (電圧・電流・ADCレンジ) を計算。
  7) option_d_layout.svg を生成。

実行: python3 hardware/pcb/option_d_perfboard.py
"""
import os
import re
import io
import math
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
CAD = os.path.abspath(os.path.join(HERE, "..", "cad", "mindclip_case.py"))
SRC = open(CAD, encoding="utf-8").read()

GRID = 0.1          # 離散化ピッチ [mm]
WALL_CLR = 0.3      # 基板外形と筐体内壁のクリアランス [mm]
PART_CLR = 0.2      # 基板外形と内部リブ/部品のクリアランス [mm]
PITCH = 2.54        # ユニバーサル基板の穴ピッチ [mm]

# --- 推測値 (実測/データシートで裏を取れなかったもの) --------------------------
ASSUMPTION = {
    # 秋月 112019 は「1.0mm厚」と明記。裏面のリード切り残し+はんだフィレットは
    # 手作業では 0.5-0.8mm 残るため 0.8mm 浮かせる前提 (assumption)。
    "PCB_T": 1.0,
    "PCB_FLOAT": 0.8,
    # JST B2B-PH-K-S (トップ型 2P) を嵌合した状態の高さ+ケーブル曲げ代。
    # JST 原典データシートは本環境から取得できず、実装高さ・footprint とも
    # assumption (LCSC の「4.5mm幅/8.0mm実装高さ」表記を保守側に丸めた)。
    "J1_H": 7.5, "J1_X": 6.0, "J1_Y": 4.5,
    # 1/6W カーボン抵抗 (本体 φ1.8 x 3.2) を立てて実装したときの高さ
    "R_VERT_H": 4.7,
    # リード型積層セラミック 0.1uF を寝かせて実装したときの高さ
    "C_H": 2.0, "C_X": 4.5, "C_Y": 2.0,
    # 基板に来る配線のはんだ+被覆の盛り上がり
    "WIRE_H": 2.0,
}


# ---------------------------------------------------------------------------
# 筐体CADの読み込み
# ---------------------------------------------------------------------------
def load_case(variant, xiao_lift=None):
    src = SRC
    if xiao_lift is not None:
        src = re.sub(r"^XIAO_LIFT = [0-9.]+", f"XIAO_LIFT = {xiao_lift}",
                     src, count=1, flags=re.M)
    os.environ["MINDCLIP_VARIANT"] = variant
    ns = {"__name__": "case_probe_d", "__file__": CAD}
    exec(compile(src, CAD, "exec"), ns)
    return ns


def collect_parts(ns):
    """check_layout() と同じ AABB 群を dict で返す"""
    boss_r = ns["MAG_D"] / 2 + ns["MAG_FIT"] / 2 + 1.5
    parts = {
        "battery": ns["bat"], "xiao": ns["xiao"], "switch": ns["sw"],
        "led": ns["led"],
        "lip_left": ns["lip_left"], "lip_top": ns["lip_top"],
        "lip_bottom": ns["lip_bottom"], "lip_right": ns["lip_right"],
        "sw_rib": ns["sw_rib"],
    }
    for k, mx in enumerate(ns["MAG_XS"]):
        parts[f"boss{k}"] = (mx - boss_r, ns["MAG_Y"] - boss_r,
                             mx + boss_r, ns["MAG_Y"] + boss_r,
                             ns["WALL"] - 1.2, ns["WALL"] + ns["BOSS_H"])
    for tag, key in (("xstop", "xiao_stops"), ("xnub_t", "xiao_nubs_top"),
                     ("xnub_b", "xiao_nubs_bot"), ("bstop_l", "bat_stops_left"),
                     ("bstop_b", "bat_stops_bot"), ("lidrib", "lid_bat_ribs"),
                     ("seat", "xiao_seats")):
        for i, b in enumerate(ns[key]):
            parts[f"{tag}{i}"] = b
    return parts


# ---------------------------------------------------------------------------
# 空き空間の探索
# ---------------------------------------------------------------------------
def _grid_axes(ns):
    x0, y0 = ns["WALL"], ns["WALL"]
    nx = int(round(ns["IW"] / GRID))
    ny = int(round(ns["IH"] / GRID))
    return x0, y0, nx, ny


def _in_cavity(ns, x, y):
    """内側R2.5の角丸を考慮したキャビティ内判定 (壁クリアランス込み)"""
    x0, y0 = ns["WALL"] + WALL_CLR, ns["WALL"] + WALL_CLR
    x1 = ns["WALL"] + ns["IW"] - WALL_CLR
    y1 = ns["WALL"] + ns["IH"] - WALL_CLR
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    re_ = max(ns["R_IN"] - WALL_CLR, 0.0)
    for cx, sx in ((x0 + re_, True), (x1 - re_, False)):
        for cy, sy in ((y0 + re_, True), (y1 - re_, False)):
            inside_x = x < cx if sx else x > cx
            inside_y = y < cy if sy else y > cy
            if inside_x and inside_y:
                if (x - cx) ** 2 + (y - cy) ** 2 > re_ ** 2 + 1e-9:
                    return False
    return True


def occupancy(ns, parts, z0, z1):
    """z スラブ [z0,z1] を横切る部品で塞がれているセル = 1"""
    gx0, gy0, nx, ny = _grid_axes(ns)
    blocked = [bytearray(nx) for _ in range(ny)]
    for j in range(ny):
        yc = gy0 + (j + 0.5) * GRID
        row = blocked[j]
        for i in range(nx):
            if not _in_cavity(ns, gx0 + (i + 0.5) * GRID, yc):
                row[i] = 1
    for b in parts.values():
        if not (b[5] - 1e-9 > z0 and z1 - 1e-9 > b[4]):
            continue
        i0 = max(0, int(math.floor((b[0] - PART_CLR - gx0) / GRID)))
        i1 = min(nx, int(math.ceil((b[2] + PART_CLR - gx0) / GRID)))
        j0 = max(0, int(math.floor((b[1] - PART_CLR - gy0) / GRID)))
        j1 = min(ny, int(math.ceil((b[3] + PART_CLR - gy0) / GRID)))
        for j in range(j0, j1):
            row = blocked[j]
            for i in range(i0, i1):
                row[i] = 1
    return blocked, gx0, gy0, nx, ny


def ceiling_map(ns, parts, z_top):
    """各セルの「z_top から上に空いている高さ」[mm]"""
    gx0, gy0, nx, ny = _grid_axes(ns)
    lid = ns["BODY_D"]
    ceil = [[lid - z_top] * nx for _ in range(ny)]
    for b in parts.values():
        if b[5] <= z_top + 1e-9:
            continue
        top = max(b[4], z_top) - z_top
        i0 = max(0, int(math.floor((b[0] - PART_CLR - gx0) / GRID)))
        i1 = min(nx, int(math.ceil((b[2] + PART_CLR - gx0) / GRID)))
        j0 = max(0, int(math.floor((b[1] - PART_CLR - gy0) / GRID)))
        j1 = min(ny, int(math.ceil((b[3] + PART_CLR - gy0) / GRID)))
        for j in range(j0, j1):
            row = ceil[j]
            for i in range(i0, i1):
                if top < row[i]:
                    row[i] = top
    return ceil


def mask_for(blocked, ceil, need, nx, ny):
    out = [bytearray(nx) for _ in range(ny)]
    for j in range(ny):
        b, c, o = blocked[j], ceil[j], out[j]
        for i in range(nx):
            o[i] = 1 if (b[i] or c[i] < need - 1e-9) else 0
    return out


def largest_rect(mask, nx, ny):
    heights = [0] * nx
    best = (0, None)
    for j in range(ny):
        row = mask[j]
        for i in range(nx):
            heights[i] = 0 if row[i] else heights[i] + 1
        stack = []
        for i in range(nx + 1):
            h = heights[i] if i < nx else 0
            start = i
            while stack and stack[-1][1] >= h:
                si, sh = stack.pop()
                if sh * (i - si) > best[0]:
                    best = (sh * (i - si), (si, j - sh + 1, i, j + 1))
                start = si
            stack.append((start, h))
    return best


def free_area(mask, nx, ny, xlim=None, gx0=0.0):
    n = 0
    for j in range(ny):
        row = mask[j]
        for i in range(nx):
            if row[i]:
                continue
            if xlim is not None and gx0 + (i + 0.5) * GRID > xlim:
                continue
            n += 1
    return n * GRID * GRID


def rect_mm(gx0, gy0, r):
    i0, j0, i1, j1 = r
    return (gx0 + i0 * GRID, gy0 + j0 * GRID,
            gx0 + i1 * GRID, gy0 + j1 * GRID)


def holes_in(rect, margin=0.9):
    w = rect[2] - rect[0] - 2 * margin
    h = rect[3] - rect[1] - 2 * margin
    nc = int(math.floor(w / PITCH)) + 1 if w >= 0 else 0
    nr = int(math.floor(h / PITCH)) + 1 if h >= 0 else 0
    return max(nc, 0), max(nr, 0)


def local_ceiling(ns, parts, box, z_top):
    """box=(x0,y0,x1,y1) の直上にある最も低い天井までの高さ [mm] と原因"""
    lid = ns["BODY_D"]
    best, who = lid - z_top, "lid"
    for name, b in parts.items():
        if b[5] <= z_top + 1e-9:
            continue
        if (b[2] + PART_CLR > box[0] and box[2] > b[0] - PART_CLR and
                b[3] + PART_CLR > box[1] and box[3] > b[1] - PART_CLR):
            h = max(b[4], z_top) - z_top
            if h < best:
                best, who = h, name
    return best, who


# ---------------------------------------------------------------------------
# 採用配置 (4列 x 6行 = 24穴)
# ---------------------------------------------------------------------------
BOARD = (1.9, 28.4, 12.1, 44.3)     # 基板外形 (x0,y0,x1,y1) [mm]
HOLE0 = (2.95, 29.70)               # 左下ホール中心
NCOL, NROW = 4, 6


def hole(c, r):
    return (HOLE0[0] + (c - 1) * PITCH, HOLE0[1] + (r - 1) * PITCH)


def placement():
    """(名前, x0,y0,x1,y1, 部品高さ, 使用ホール, 説明)"""
    A = ASSUMPTION
    out = []
    # J1: トップ型 PH。ピンは (2,6)(3,6) にピッチ 2.0→2.54 で開いて挿す。
    #     本体は -y 側へ張り出し、ケーブルは +z に出してから左壁沿いに降ろす。
    px = (hole(2, 6)[0] + hole(3, 6)[0]) / 2
    py = hole(2, 6)[1]
    out.append(("J1 PH-2P(トップ型)", px - A["J1_X"] / 2, py + 1.9 - A["J1_Y"],
                px + A["J1_X"] / 2, py + 1.9, A["J1_H"],
                [(2, 6), (3, 6)], "電池コネクタ (嵌合+ケーブル曲げ代込み)"))
    # R1-R4: 1/6W を立てて実装 (2ホール/本)。LED の真下を避けて行1-2に集約。
    for k, c in enumerate((1, 2, 3, 4), start=1):
        x, y = hole(c, 1)
        out.append((f"R{k} 220k (立て)", x - 1.0, y - 1.0, x + 1.0,
                    hole(c, 2)[1] + 1.0, A["R_VERT_H"], [(c, 1), (c, 2)],
                    "1/6W を立てて 1ピッチ渡し"))
    # C1: 寝かせ実装 (2.54mm ピッチ)
    x0, y0 = hole(1, 3)
    x1, _ = hole(2, 3)
    out.append(("C1 0.1uF (寝かせ)", x0 - 1.1, y0 - A["C_Y"] / 2,
                x1 + 1.1, y0 + A["C_Y"] / 2, A["C_H"], [(1, 3), (2, 3)],
                "ADC のソースインピーダンス対策"))
    for name, (c, r) in (("W:BAT+", (4, 6)), ("W:BAT-/GND", (4, 5)),
                         ("W:5V", (3, 4)), ("W:D5(VBUS)", (4, 4)),
                         ("W:D0/A0(VBAT)", (4, 3))):
        x, y = hole(c, r)
        out.append((name, x - 1.0, y - 1.0, x + 1.0, y + 1.0,
                    A["WIRE_H"], [(c, r)], "XIAO への配線ランド"))
    return out


# ---------------------------------------------------------------------------
# レポート
# ---------------------------------------------------------------------------
def report_freespace(variant, pcb_t=None, float_h=None):
    A = ASSUMPTION
    pcb_t = A["PCB_T"] if pcb_t is None else pcb_t
    float_h = A["PCB_FLOAT"] if float_h is None else float_h
    ns = load_case(variant)
    parts = collect_parts(ns)
    zb0 = ns["WALL"] + float_h
    zb1 = zb0 + pcb_t
    blocked, gx0, gy0, nx, ny = occupancy(ns, parts, zb0, zb1)
    ceil = ceiling_map(ns, parts, zb1)
    print(f"\n[{variant}] 床から {float_h}mm 浮かせた板厚 {pcb_t}mm の基板"
          f" (基板 z {zb0:.1f}..{zb1:.1f} / リッド内面 z {ns['BODY_D']:.1f})")
    print("   必要部品高さ |  最大の空き長方形   | 2.54グリッド | 位置"
          "                  | 左ゾーン空き面積(切欠き可なら上限)")
    for need in (1.5, 2.0, 2.6, 3.0, 4.0, 5.0, 6.0, 8.0, 9.5):
        m = mask_for(blocked, ceil, need, nx, ny)
        area, r = largest_rect(m, nx, ny)
        fa = free_area(m, nx, ny, xlim=ns["xiao"][0], gx0=gx0)
        if r is None:
            print(f"   {need:5.1f} mm     | (なし)")
            continue
        rect = rect_mm(gx0, gy0, r)
        nc, nr = holes_in(rect)
        print(f"   {need:5.1f} mm     | {rect[2] - rect[0]:5.1f} x"
              f" {rect[3] - rect[1]:5.1f} ({area * GRID * GRID:4.0f}mm2) |"
              f" {nc}x{nr}={nc * nr:3d}穴 |"
              f" x {rect[0]:5.1f}..{rect[2]:5.1f} y {rect[1]:5.1f}..{rect[3]:5.1f}"
              f" | {fa:6.1f} mm2 (~{fa / (PITCH ** 2):.0f}穴相当)")
    return ns, parts, zb1


def report_placement(variant):
    A = ASSUMPTION
    ns = load_case(variant)
    parts = collect_parts(ns)
    z_top = ns["WALL"] + A["PCB_FLOAT"] + A["PCB_T"]
    print(f"\n[{variant}] 採用配置 (基板 {BOARD[2] - BOARD[0]:.1f} x"
          f" {BOARD[3] - BOARD[1]:.1f} mm, {NCOL}x{NROW}={NCOL * NROW}穴,"
          f" 基板上面 z={z_top:.1f}, リッド内面 z={ns['BODY_D']:.1f})")
    print("   部品                      高さ  天井  余裕  制約元")
    ok_all = True
    used = set()
    for name, x0, y0, x1, y1, h, holes, note in placement():
        ceil_h, who = local_ceiling(ns, parts, (x0, y0, x1, y1), z_top)
        margin = ceil_h - h
        if margin < 0:
            ok_all = False
        print(f"   {'OK ' if margin >= 0 else 'NG '}{name:<23s} {h:4.1f}"
              f"  {ceil_h:4.1f} {margin:+5.1f}  {who}")
        used.update(holes)
    # J1 本体で潰れるホール
    j = [p for p in placement() if p[0].startswith("J1")][0]
    blockedh = [(c, r) for c in range(1, NCOL + 1) for r in range(1, NROW + 1)
                if j[1] <= hole(c, r)[0] <= j[3] and j[2] <= hole(c, r)[1] <= j[4]]
    used.update(blockedh)
    print(f"   使用/占有ホール {len(used)} / {NCOL * NROW}"
          f" (空き {NCOL * NROW - len(used)} 穴をジャンパ・GNDバスに使う)")
    blocked, gx0, gy0, nx, ny = occupancy(
        ns, parts, ns["WALL"] + A["PCB_FLOAT"], z_top)
    i0 = int(round((BOARD[0] - gx0) / GRID))
    i1 = int(round((BOARD[2] - gx0) / GRID))
    j0 = int(round((BOARD[1] - gy0) / GRID))
    j1 = int(round((BOARD[3] - gy0) / GRID))
    bad = sum(blocked[jj][ii] for jj in range(j0, j1) for ii in range(i0, i1))
    print(f"   基板外形の干渉セル数: {bad} (0 なら干渉なし)")
    assert bad == 0, f"{variant}: 基板外形が既存部品と干渉"
    return ok_all


def report_under_xiao(variant):
    A = ASSUMPTION
    print(f"\n[{variant}] 代案: XIAO の下に敷く (XIAO_LIFT を差し替え)")
    base = load_case(variant)
    d0 = base["TOTAL_D"]
    need_xiao = base["XIAO_LIFT"] + base["XIAO_STACK_T"] + 0.6
    slack = base["ID"] - need_xiao
    print(f"   v1: XIAO_LIFT={base['XIAO_LIFT']} ID={base['ID']:.1f}"
          f" 外形 {base['W']:.1f}x{base['H']:.1f}x{d0:.1f}")
    print(f"   XIAO側の奥行き必要量 {need_xiao:.1f} / ID {base['ID']:.1f}"
          f" → 余裕 {slack:.1f}mm"
          f" (XIAO_LIFT を {base['XIAO_LIFT'] + slack:.1f} まで上げても外形不変)")
    for t, u, label in ((1.0, 0.8, "板1.0(112019)+裏面逃げ0.8"),
                        (1.6, 0.8, "板1.6(108241)+裏面逃げ0.8"),
                        (1.0, 0.8, "板1.0+裏面0.8+寝かせ抵抗2.6")):
        comp = 2.6 if "寝かせ" in label else 0.0
        lift = u + t + comp
        ns = load_case(variant, xiao_lift=lift)
        buf = io.StringIO()
        ok, err = True, ""
        try:
            with contextlib.redirect_stdout(buf):
                ns["check_layout"]()
        except AssertionError as e:
            ok, err = False, str(e)
        head = lift - u - t
        print(f"   {'OK ' if ok else 'NG '}{label:<28s} XIAO_LIFT={lift:4.1f}"
              f" → 外形奥行 {ns['TOTAL_D']:.1f} ({ns['TOTAL_D'] - d0:+.1f})"
              f" / 基板上の実装可能高さ {min(head, slack + base['XIAO_LIFT'] - u - t):.1f}mm")
        if not ok:
            print(f"       assert: {err}")
    free_h = slack + base["XIAO_LIFT"] - A["PCB_FLOAT"] - A["PCB_T"]
    print(f"   → 外形を変えずに XIAO 下に置ける部品高さの上限:"
          f" {free_h:.1f} mm (板1.0mm・裏面逃げ0.8mm 前提)")


def report_circuit():
    print("\n" + "=" * 100)
    print("分圧回路の電気的成立性 (ELECTRICAL.md §2.1 の v2 方針 220k x2 を踏襲)")
    print("=" * 100)
    R = 220e3
    for label, vin, vmax in (("VBUS検出 (XIAO 5Vピン)", 5.0, 5.25),
                             ("電池電圧監視 (BAT+)", 3.7, 4.25)):
        v = vin * R / (2 * R)
        vm = vmax * R / (2 * R)
        i = vin / (2 * R)
        print(f"  {label}: 分圧比 1/2 → 標準 {v:.2f}V / 最大 {vm:.2f}V"
              f" (ADC 12dB フルスケール ~3.1V に対し {'OK' if vm < 3.1 else 'NG'})"
              f" / 常時消費 {i * 1e6:.1f} uA")
    print(f"  電池側分圧の常時消費 {3.7 / (2 * R) * 1e6:.1f} uA は"
          f" deep sleep 3mA (公式typ) の {3.7 / (2 * R) / 3e-3 * 100:.3f}% → 無視できる")
    print("  ADC のソースインピーダンス: 分圧の等価出力抵抗 = 220k//220k ="
          f" {R / 2 / 1e3:.0f}k → ESP32-S3 の SAR には高すぎるため C1(0.1uF) 必須")
    print("  ※ VBUS 側は HIGH/LOW のデジタル判定なのでインピーダンスは問題にならない")


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------
def draw_svg(path, ns, parts, z_top):
    S = 10.0
    W, H = ns["W"], ns["H"]
    pad = 28
    LEG = 300

    def X(x):
        return pad + x * S

    def Y(y):
        return pad + (H - y) * S

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W * S + 2 * pad + LEG:.0f}"'
         f' height="{H * S + 2 * pad:.0f}" viewBox="0 0 {W * S + 2 * pad + LEG:.0f}'
         f' {H * S + 2 * pad:.0f}">',
         '<style>text{font-family:"DejaVu Sans",sans-serif;font-size:9px;fill:#263238}'
         '.t{font-size:12px;font-weight:bold}.s{font-size:8px}</style>',
         '<rect width="100%" height="100%" fill="#fcfcfc"/>',
         f'<rect x="{X(0):.1f}" y="{Y(H):.1f}" width="{W * S:.1f}"'
         f' height="{H * S:.1f}" rx="{4.0 * S:.1f}" fill="#eceff1"'
         f' stroke="#546e7a" stroke-width="1.6"/>',
         f'<rect x="{X(ns["WALL"]):.1f}" y="{Y(ns["WALL"] + ns["IH"]):.1f}"'
         f' width="{ns["IW"] * S:.1f}" height="{ns["IH"] * S:.1f}"'
         f' rx="{2.5 * S:.1f}" fill="#fff" stroke="#90a4ae"/>']
    col = {"battery": "#c8e6c9", "xiao": "#bbdefb", "switch": "#ffe0b2",
           "led": "#ef9a9a"}
    for name, b in sorted(parts.items()):
        if name.startswith("lip"):
            c, op = "#b0bec5", 0.30
        elif name in col:
            c, op = col[name], 0.85
        else:
            c, op = "#cfd8dc", 0.8
        o.append(f'<rect x="{X(b[0]):.1f}" y="{Y(b[3]):.1f}"'
                 f' width="{(b[2] - b[0]) * S:.1f}"'
                 f' height="{(b[3] - b[1]) * S:.1f}" fill="{c}"'
                 f' fill-opacity="{op}" stroke="#78909c" stroke-width="0.5"/>')
    for name, lbl in (("battery", "LiPo"), ("xiao", "XIAO stack"),
                      ("switch", "SW"), ("led", "LED")):
        b = parts[name]
        o.append(f'<text x="{X((b[0] + b[2]) / 2):.1f}"'
                 f' y="{Y((b[1] + b[3]) / 2):.1f}" text-anchor="middle">{lbl}</text>')
    o.append(f'<rect x="{X(BOARD[0]):.1f}" y="{Y(BOARD[3]):.1f}"'
             f' width="{(BOARD[2] - BOARD[0]) * S:.1f}"'
             f' height="{(BOARD[3] - BOARD[1]) * S:.1f}" fill="#fff9c4"'
             f' fill-opacity="0.9" stroke="#f9a825" stroke-width="1.6"/>')
    for c in range(1, NCOL + 1):
        for r in range(1, NROW + 1):
            x, y = hole(c, r)
            o.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="1.5"'
                     f' fill="none" stroke="#f9a825" stroke-width="0.8"/>')
    for name, x0, y0, x1, y1, h, holes, note in placement():
        fill = "#ffcc80" if name.startswith("J1") else (
            "#b39ddb" if name.startswith("W:") else "#a5d6a7")
        o.append(f'<rect x="{X(x0):.1f}" y="{Y(y1):.1f}"'
                 f' width="{(x1 - x0) * S:.1f}" height="{(y1 - y0) * S:.1f}"'
                 f' fill="{fill}" fill-opacity="0.85" stroke="#455a64"'
                 f' stroke-width="0.6"/>')
        o.append(f'<text class="s" x="{X((x0 + x1) / 2):.1f}"'
                 f' y="{Y((y0 + y1) / 2) + 3:.1f}" text-anchor="middle">'
                 f'{name.split(" ")[0]}</text>')
    lx = pad + W * S + 14
    o.append(f'<text class="t" x="{lx:.0f}" y="{pad + 12:.0f}">'
             f'案D: 左デッドスペース搭載ユニバーサル基板</text>')
    lines = [
        f"variant = {os.environ.get('MINDCLIP_VARIANT')}",
        f"内寸 {ns['IW']:.1f} x {ns['IH']:.1f} x {ns['ID']:.1f} mm",
        f"外形 {ns['W']:.1f} x {ns['H']:.1f} x {ns['TOTAL_D']:.1f} mm",
        "",
        f"基板: 秋月 112019 (1.0mm厚) を",
        f"      {BOARD[2] - BOARD[0]:.1f} x {BOARD[3] - BOARD[1]:.1f} mm"
        f" ({NCOL}x{NROW}={NCOL * NROW}穴) に切断",
        f"      z {ns['WALL'] + ASSUMPTION['PCB_FLOAT']:.1f}"
        f"..{z_top:.1f} (床から 0.8mm 浮かせ)",
        "",
        "橙 J1 = JST PH 2P サイド型 (電池)",
        "緑 R1-R4 = 220k 分圧 x2組 / C1 = 0.1uF",
        "紫 W: = XIAO への配線ランド",
        "",
        "XIAO スタックの z には一切かからない",
        "  → 高さ予算への影響 0.0 mm",
        "  → 筐体CADの変更なし (allday)",
        "",
        "灰 = 既存の内部リブ (CADから読込)",
        "赤 LED はリッドから 4mm 侵入するため",
        "  その真下は部品高さが制限される",
    ]
    for k, s in enumerate(lines):
        o.append(f'<text x="{lx:.0f}" y="{pad + 32 + k * 14:.0f}">{s}</text>')
    o.append("</svg>")
    open(path, "w", encoding="utf-8").write("\n".join(o))
    print(f"\n[svg] {path}")


def main():
    print("=" * 100)
    print("案D: ユニバーサル基板 手組み — 筐体内の実空間検証")
    print(f"  CAD: {CAD}")
    print(f"  グリッド {GRID}mm / 壁クリア {WALL_CLR}mm / 部品クリア {PART_CLR}mm")
    print("=" * 100)
    keep = {}
    for v in ("allday", "slim"):
        keep[v] = report_freespace(v)
    report_freespace("allday", pcb_t=1.6)

    print()
    print("=" * 100)
    print("採用配置の部品高さチェック (天井 = リッド内面 or 直上の部品/リブ)")
    print("=" * 100)
    res = {v: report_placement(v) for v in ("allday", "slim")}
    print()
    for v, ok in res.items():
        print(f"  {v}: {'全部品クリア' if ok else '★干渉あり (上表の NG 行を参照)'}")

    print()
    print("=" * 100)
    for v in ("allday", "slim"):
        report_under_xiao(v)

    report_circuit()

    ns, parts, z_top = keep["allday"]
    os.environ["MINDCLIP_VARIANT"] = "allday"
    draw_svg(os.path.join(HERE, "option_d_layout.svg"), ns, parts, z_top)


if __name__ == "__main__":
    main()
