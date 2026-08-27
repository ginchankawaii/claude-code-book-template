#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MindClip DIY — クリップ型音声ロガー筐体 パラメトリックCADモデル (CadQuery 2.8)

バリアント (環境変数 MINDCLIP_VARIANT):
  - allday (既定) : LiPo 802530 (800mAh)。外形 37.2 x 49.4 x 14.6 mm
  - slim          : LiPo 502530 (500mAh)。外形 37.2 x 49.4 x 12.9 mm
  出力は ../stl/<variant>/ と ../renders/<variant>/ に分かれる。

パーツ構成:
  - body      : 本体ケース (XIAO ESP32S3 Sense スタック + LiPo + スライドスイッチ
                + LED を収容。磁石2個の圧入ポケット、マイク開口(上面)、USB-C開口(右側面)、
                スイッチレバースロット(上面)、LED窓(正面リッド側) )
  - lid       : 前面フタ (スナップフィット。lip(スカート)+バンプ4個、工具不要で開閉)
  - backplate : 服の内側に入れる薄い裏板 (磁石2個圧入、肌側は完全フラット)

設計上の重要ポイント (レビュー反映):
  - XIAO は基板4隅のコーナーシート (h=XIAO_LIFT=1.4) の上に載せ、基板裏面の
    BAT+/- はんだ盛り + AWG28 リード + カプトンテープ + スルーホール裏フィレット
    (実測 1.0〜1.5mm 突出, ELECTRICAL.md §5.3) の逃げ空間を床との間に確保する。
  - XIAO 左端にストップリブ、上下に当てナブを配置し、USB-C 挿入力 (5〜20N) を
    リブ→筐体壁で受ける (基板が内側へ逃げない)。両面テープ固定は必須手順。
  - 電池は右詰めで配置し、左端 (リード出射端: 502530 のタブは 25mm 幅の端面から出る)
    に 2.4mm のリード曲げチャネルを確保。x/y 位置決めリブ + リッド側押さえリブで拘束。
  - v1.3: 電池厚をバリアント化したのに伴い、電池と右リッド lip が干渉したため内寸幅を
    32.6 → 34.0 に拡大。内部リブ座標を xiao[0] / CX 基準の相対値に改め、寸法変更で
    リブ同士が衝突しないようにした。内寸奥行きは「XIAOスタック」と「磁石ボス+電池+
    押さえリブ逃げ」の厚い方から自動計算する。

座標系 (body 基準):
  X = 幅方向 (装着時の左右) / Y = 高さ方向 (Y+ が上 = マイク側) / Z = 奥行き
  z=0 が背面(服に当たる面)、z+ が正面(リッド側)

実行:
  python3 mindclip_case.py
  → ../stl/*.stl と ../renders/*.png を生成し、干渉チェック(assert)と
    watertight 検証結果をログ出力する。

寸法出典:
  - XIAO ESP32S3 基板 21.0 x 17.8 mm : Seeed 公式値 (Web検証済み)
  - Sense拡張ボード込みスタック総厚 7.5 mm (カメラ除く) : **assumption** (Web未検証)
  - PDMマイク位置 : 拡張ボード上、正面向き : **assumption** → 上面開口+前面キャビティで導音
  - LiPo 502530 : 30 x 25 x 5.0 mm (公称)
  - SS-12D00 : 本体 8.7 x 3.7 mm (Web検証済み)、高さ3.5 mm・レバー突出2 mm : **assumption**
  - ネオジム磁石 φ6 x 2 mm x 4個
"""
import os
import sys
import math

import cadquery as cq

# ---------------------------------------------------------------------------
# パラメータ
# ---------------------------------------------------------------------------
WALL = 1.6          # 標準壁厚 (側面・背面・上下面)
LID_T = 1.8         # リッド板厚
CLR = 0.15          # リッド lip の片側クリアランス (FDM 公差 0.2-0.3 を吸収)

# --- バリアント選択 ---------------------------------------------------------
# Seeed 公式スペックの実測値 (録音+SD書込 3.8V/54.4mA平均) を電力予算の基準にすると、
# 500mAh では約8時間しか持たず「起床〜就寝」を走り切れない (ELECTRICAL.md §2.2)。
# そのため既定は 800mAh の allday。電池は同フットプリント(30x25)で厚みだけ違うため、
# 筐体奥行きの増加は +0.8mm に留まる (奥行きを支配するのは XIAO スタックのため)。
#   allday (既定): LiPo 802530 800mAh — 最悪ケース54.4mAでも約12.5時間、省電力込みで18h+
#   slim         : LiPo 502530 500mAh — 約8時間。薄さ優先・短時間運用向け
# 切替: MINDCLIP_VARIANT=slim python3 mindclip_case.py
VARIANT = os.environ.get("MINDCLIP_VARIANT", "allday").strip().lower()
if VARIANT not in ("allday", "slim"):
    raise SystemExit(f"MINDCLIP_VARIANT は allday / slim のいずれか (指定値: {VARIANT})")

# --- 収容部品 (バウンディングボックス, 公称値) ---
if VARIANT == "slim":
    BAT_W, BAT_H, BAT_T = 30.0, 25.0, 5.0      # LiPo 502530 (500mAh)
    BAT_LABEL, BAT_MAH = "LiPo 502530 (500mAh)", 500
else:
    BAT_W, BAT_H, BAT_T = 30.0, 25.0, 8.0      # LiPo 802530 (800mAh)
    BAT_LABEL, BAT_MAH = "LiPo 802530 (800mAh)", 800
XIAO_W, XIAO_H = 21.0, 17.8                     # XIAO ESP32S3 基板
XIAO_STACK_T = 7.5                              # Sense拡張ボード込み総厚 (assumption)
USB_PROTRUDE = 1.3                              # USB-C の基板端からの突出
SW_L, SW_W, SW_H = 8.7, 3.7, 3.5                # SS-12D00 本体
SW_LEVER = 2.0                                  # レバー突出
LED_D = 3.0                                     # 3mm LED
MAG_D, MAG_T = 6.0, 2.0                         # ネオジム磁石 φ6 x 2
MAG_FIT = 0.2                                   # 圧入ポケット径方向余裕 (φ6.2)
MAG_WEB = 0.8                                   # 磁石ポケット残し肉厚 (磁力を通す)
MAG_PITCH = 18.0                                # 磁石2個の中心間距離

# --- 内寸の組み立て ---
# 内寸幅: 左のリード曲げチャネル(2.4) + 電池(30) + 右のリッドlip逃げ。
# allday(8mm厚)では電池上面がリッドlipの降下域まで届くため、電池右端と右lip内面の間に
# 0.4mm以上の隙間が要る (旧値32.6では右lipと干渉し check_layout が失敗した)。
IW = 34.0
XIAO_LIFT = 1.4                                 # XIAO基板下面リフト (裏面はんだ+AWG28+
                                                #   カプトンの突出 1.0-1.5mm の逃げ空間)
BOSS_H = 1.4                                    # 磁石ボスの内面からの突出 (電池はこの上に載る)
# 内寸奥行き = 「XIAOスタック」と「磁石ボス+電池」の厚い方 + リッド内面クリアランス。
# XIAO側: リフト1.4 + スタック7.5 + 余裕0.6 = 9.5
# 電池側: ボス1.4 + BAT_T + リブ逃げ1.8 (押さえリブのギャップ1.0 + リブ肉厚0.8)
ID = round(max(XIAO_LIFT + XIAO_STACK_T + 0.6, BOSS_H + BAT_T + 1.8), 2)
M_BOT = 1.6                                     # バッテリー下マージン
GAP_BX = 1.2                                    # バッテリー上端〜XIAO下端 (配線通し)
M_TOP = 0.6                                     # XIAO上端マージン
IH = M_BOT + BAT_H + GAP_BX + XIAO_H + M_TOP    # 内寸高さ = 46.2

# --- 外形 ---
W = IW + 2 * WALL                               # 35.8
H = IH + 2 * WALL                               # 49.4
BODY_D = WALL + ID                              # 11.1 (body 単体奥行き)
TOTAL_D = BODY_D + LID_T                        # 12.9 (組立時奥行き)
R_OUT = 4.0                                     # 外形コーナーR
R_IN = 2.5                                      # 内寸コーナーR

# --- 内部レイアウト (絶対座標, body基準) ---
CX = W / 2.0                                    # 17.9
# バッテリー: 下段・背面側・右詰め (磁石ボスの上に載る → 重心をクランプ側に寄せる)
#   502530 のリード/タブは長さ30mm方向の端面 (25mm幅の面) から出る → 左端面から出射し、
#   左側の BAT_LEAD_CH チャネルを上へ回して XIAO 裏面の BAT パッドへ配線する。
BAT_LEAD_CH = 2.4                             # 左側リード曲げチャネル幅 (AWG28 x2)
bat = (WALL + BAT_LEAD_CH, WALL + M_BOT,        # x0,y0  (4.0, 3.2)
       WALL + BAT_LEAD_CH + BAT_W, WALL + M_BOT + BAT_H,   # x1,y1 (34.0, 28.2)
       WALL + BOSS_H, WALL + BOSS_H + BAT_T)    # z0,z1  (3.0 .. 8.0)
# XIAO スタック: 上段・右詰め (USB-C を右側面へフラッシュ)。
#   コーナーシート4個 (h=XIAO_LIFT) の上に載せ、裏面はんだの逃げ空間を確保。
xiao = (WALL + IW - XIAO_W, bat[3] + GAP_BX,
        WALL + IW, bat[3] + GAP_BX + XIAO_H,
        WALL + XIAO_LIFT, WALL + XIAO_LIFT + XIAO_STACK_T)  # z 3.0 .. 10.5
# 磁石: バッテリー背後の背面壁ボス内 (筐体中心 CX 基準 → backplate と共通)
MAG_Y = (bat[1] + bat[3]) / 2.0                 # 15.7 (バッテリー中心)
MAG_XS = (CX - MAG_PITCH / 2, CX + MAG_PITCH / 2)
# スイッチ: 上面左 (XIAO の左の空間)。上壁の浅い凹みにはめて接着
SW_RECESS = 0.7                                 # 上壁内面の位置決め凹み深さ
_swz0 = WALL + (ID - SW_W) / 2.0                # 4.5
sw = (4.0, WALL + IH - (SW_H - SW_RECESS), 4.0 + SW_L, WALL + IH + SW_RECESS,
      _swz0, _swz0 + SW_W)                      # z 4.5 .. 8.2
# LED: 正面リッドの窓。左上ゾーン (スイッチの下、XIAOの左)
LED_POS = (6.9, 36.0)                           # 窓中心 (x, y)
led = (LED_POS[0] - 1.6, LED_POS[1] - 1.6, LED_POS[0] + 1.6, LED_POS[1] + 1.6,
       BODY_D - 4.0, BODY_D)                    # 内側へ 4mm 侵入と見なす
# USB-C 開口: 右側面、XIAO 中央 (z は XIAO_LIFT に追従)
USB_CY = (xiao[1] + xiao[3]) / 2.0              # 38.3
USB_OPEN_W, USB_OPEN_H = 10.5, 4.8              # y方向 x z方向
USB_Z0 = 2.4 + XIAO_LIFT                        # 3.8
USB_CB_W, USB_CB_H, USB_CB_D = 13.0, 8.0, 0.8   # プラグ逃がし座ぐり (オーバーモールド対応)
# マイク開口: 上面。Sense拡張ボード上面 (z=10.5) 近傍の高さに合わせる
MIC_Z = xiao[5] - 0.9                           # 9.6 (開口 z 8.85..10.35)
# --- 内部リブ類 (AABB) ---
# XIAO コーナーシート (基板4隅の座面。ピン列カステレーション x16.1-31.3 を回避)
#   v1.3: 座標を xiao[0] 基準の相対値に変更 (IW を変えると絶対値がずれ、
#   シートとストップリブが干渉したため)。カステレーション帯は基板左端から
#   2.9〜18.1mm なので、その外側にリブを置く。
_CAST_L = xiao[0] + 2.9                         # カステレーション帯 左端
_CAST_R = xiao[0] + 18.1                        # 同 右端
xiao_seats = [
    (xiao[0], 29.5, xiao[0] + 2.5, 32.0, WALL, WALL + XIAO_LIFT),
    (xiao[2] - 2.6, 29.5, xiao[2], 32.0, WALL, WALL + XIAO_LIFT),
    (xiao[0], 44.6, xiao[0] + 2.5, 47.1, WALL, WALL + XIAO_LIFT),
    (xiao[2] - 2.6, 44.6, xiao[2], 47.1, WALL, WALL + XIAO_LIFT),
]
# XIAO 左端ストップリブ (USB-C挿入反力を受ける。中央はアンテナ/U.FL通し用に開放)
xiao_stops = [
    (xiao[0] - 3.0, 31.0, xiao[0] - 0.15, 35.0, WALL, 8.1),
    (xiao[0] - 3.0, 40.0, xiao[0] - 0.15, 44.0, WALL, 8.1),
]
# XIAO 上下の当てナブ (y方向拘束。カステレーション帯の外側)
xiao_nubs_top = [
    (xiao[0] + 0.3, xiao[3] + 0.15, _CAST_L - 0.3, WALL + IH, WALL, 7.0),
    (_CAST_R + 0.3, xiao[3] + 0.15, _CAST_R + 2.3, WALL + IH, WALL, 7.0),
]
# 電池上端ストップ兼 XIAO 下端ナブ (配線ギャップ内、リード経路は左側を開放)
xiao_nubs_bot = [
    (xiao[0] + 0.3, bat[3] + 0.15, _CAST_L - 0.3, xiao[1] - 0.15, WALL, 7.0),
    (_CAST_R + 0.3, bat[3] + 0.15, _CAST_R + 2.3, xiao[1] - 0.15, WALL, 7.0),
]
# 電池 左端ストップリブ (リード出射端。中央 y9-22 はリード曲げ用に開放)
bat_stops_left = [
    (WALL, 5.0, bat[0] - 0.2, 9.0, WALL, 7.0),
    (WALL, 22.0, bat[0] - 0.2, 26.0, WALL, 7.0),
]
# 電池 下端ストップリブ (y方向拘束)
bat_stops_bot = [
    (8.0, WALL, 12.0, bat[1] - 0.15, WALL, 7.0),
    (24.0, WALL, 28.0, bat[1] - 0.15, WALL, 7.0),
]
# スイッチ左端の挟みリブ (右端は XIAO ストップリブが兼ねる)
sw_rib = (2.9, 44.6, 3.7, WALL + IH, WALL, 8.4)
# リッド側 電池押さえリブ (z方向ラトル防止。低密度の薄スポンジ併用)
#   v1.2: リブ下面 8.7→9.0 (電池上面ギャップ 0.7→1.0)。電池下の両面テープ厚
#   (+0.15〜0.5) を考慮し、1mm スポンジの過圧縮 (45〜60%) による常時リッド
#   押し開け荷重を回避する。
#   v1.3: リブ下面を電池上面から 1.0mm 上に自動追従させる (バリアントで電池厚が
#   変わるため固定値 9.0 は allday で電池と干渉した)。
_BAT_TOP = WALL + BOSS_H + BAT_T                # allday 11.0 / slim 8.0
_RIB_Z0 = _BAT_TOP + 1.0
lid_bat_ribs = [
    (8.0, 7.5, 28.0, 8.7, _RIB_Z0, BODY_D),
    (8.0, 20.5, 28.0, 21.7, _RIB_Z0, BODY_D),
]
# リッド lip (スカート) セグメント AABB (干渉チェック用)
#   LIP_D=2.2 → lip 帯は z 8.9..11.1 で電池上面 (公称8.0 / 厚め個体8.3) より上
LIP_D = 2.2                                     # lip の挿入深さ
lip_left = (WALL + CLR, WALL + CLR, WALL + CLR + 1.0, WALL + IH - CLR,
            BODY_D - LIP_D, BODY_D)
lip_top = (WALL + CLR, WALL + IH - CLR - 1.0, 12.5, WALL + IH - CLR,
           BODY_D - LIP_D, BODY_D)              # 上辺左コーナーの保持スタブ
lip_bottom = (WALL + CLR, WALL + CLR, WALL + IW - CLR, WALL + CLR + 1.0,
              BODY_D - LIP_D, BODY_D)
lip_right = (WALL + IW - CLR - 1.0, WALL + CLR, WALL + IW - CLR, 26.6,
             BODY_D - LIP_D, BODY_D)
SNAP_PROTRUDE = 0.3                             # スナップリッジ突出 (0.5→0.3 に低減)
# v1.2: リッジ円筒を小径化して lip 深さ帯 (z8.9..11.1) 内に収める。
#   旧 r1.2/軸z9.6 はリッジ下端が lip 下端より 0.5mm 下 (z8.4) に張り出し、
#   lip 内面も 1.1mm 超えていた。r0.7/軸z9.8 でリッジ帯は z9.1..10.5、
#   lip 内面超えは 0.1mm、電池左端まで 1.15mm を確保。
SNAP_R_RIDGE = 0.7                              # リッジ円筒半径
SNAP_R_GROOVE = SNAP_R_RIDGE + 0.15             # 受け溝円筒半径 0.85
SNAP_AX = WALL + CLR + SNAP_R_RIDGE - SNAP_PROTRUDE   # 軸オフセット 2.15 (左/下辺)
SNAP_AXR = W - SNAP_AX                          # 右辺用 33.65
SNAP_AZ = BODY_D - 1.3                          # 軸 z=9.8
SNAP_SY = (14.0, 34.0)                          # 左辺スナップ y 中心
SNAP_SX = (CX - 6.5, CX + 6.5)                  # 下辺スナップ x 中心 (v1.3: CX基準の
                                                #   相対値。固定値だと W 変更で中央の
                                                #   こじ開けノッチと重なった)
SNAP_SYR = 17.0                                 # 右辺スナップ y 中心 (v1.2 追加:
                                                #   右lip y<26.6 に保持が無かった)

HW_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# バリアントごとに出力先を分ける (slim を焼いても allday の STL を潰さない)
STL_DIR = os.path.join(HW_DIR, "stl", VARIANT)
REN_DIR = os.path.join(HW_DIR, "renders", VARIANT)


# ---------------------------------------------------------------------------
# 干渉チェック (バウンディングボックス)
# ---------------------------------------------------------------------------
def _overlap1(a0, a1, b0, b1, tol=1e-6):
    return (a1 - tol > b0) and (b1 - tol > a0)


def boxes_intersect(a, b, tol=1e-6):
    """a,b = (x0,y0,x1,y1,z0,z1)"""
    return (_overlap1(a[0], a[2], b[0], b[2], tol)
            and _overlap1(a[1], a[3], b[1], b[3], tol)
            and _overlap1(a[4], a[5], b[4], b[5], tol))


def check_layout():
    boss_r = MAG_D / 2 + MAG_FIT / 2 + 1.5      # ボス外半径 4.7
    bosses = [(mx - boss_r, MAG_Y - boss_r, mx + boss_r, MAG_Y + boss_r,
               WALL - 1.2, WALL + BOSS_H) for mx in MAG_XS]
    parts = {
        "battery": bat, "xiao": xiao, "switch": sw, "led": led,
        "lip_left": lip_left, "lip_top": lip_top,
        "lip_bottom": lip_bottom, "lip_right": lip_right,
        "boss_L": bosses[0], "boss_R": bosses[1],
        "sw_rib": sw_rib,
    }
    for i, b in enumerate(xiao_seats):
        parts[f"seat{i}"] = b
    for i, b in enumerate(xiao_stops):
        parts[f"xstop{i}"] = b
    for i, b in enumerate(xiao_nubs_top):
        parts[f"xnub_t{i}"] = b
    for i, b in enumerate(xiao_nubs_bot):
        parts[f"xnub_b{i}"] = b
    for i, b in enumerate(bat_stops_left):
        parts[f"bstop_l{i}"] = b
    for i, b in enumerate(bat_stops_bot):
        parts[f"bstop_b{i}"] = b
    for i, b in enumerate(lid_bat_ribs):
        parts[f"lidrib{i}"] = b
    # 意図的に接触/内包している組み合わせは除外
    allowed = {frozenset(p) for p in [
        ("battery", "boss_L"), ("battery", "boss_R"),   # ボス上面=バッテリー底 (接触)
        ("lip_left", "lip_bottom"), ("lip_bottom", "lip_right"),  # コーナー共有
        ("lip_left", "lip_top"),                                  # コーナー共有
    ]}
    names = list(parts)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if frozenset((a, b)) in allowed:
                continue
            assert not boxes_intersect(parts[a], parts[b]), \
                f"INTERFERENCE: {a} <-> {b}"
    # 収容チェック (キャビティ内)
    cav = (WALL, WALL, WALL + IW, WALL + IH, WALL, BODY_D)
    for name in ("battery", "xiao"):
        p = parts[name]
        assert (p[0] >= cav[0] - 1e-6 and p[2] <= cav[2] + 1e-6 and
                p[1] >= cav[1] - 1e-6 and p[3] <= cav[3] + 1e-6 and
                p[4] >= cav[4] - 1e-6 and p[5] <= cav[5] + 1e-6), \
            f"{name} outside cavity"
    # スイッチは上壁凹みに SW_RECESS だけ食い込む設計
    assert sw[3] <= WALL + IH + SW_RECESS + 1e-6, "switch recess overrun"
    assert WALL - SW_RECESS >= 0.8, "top wall too thin at switch recess"
    # 磁石ウェブ (背面残し肉厚)
    pocket_bottom_z = WALL + BOSS_H - (MAG_T + 0.2)   # 3.0 - 2.2 = 0.8
    assert abs(pocket_bottom_z - MAG_WEB) < 1e-6, "magnet web != 0.8mm"
    # ボス上面 = バッテリー底 (支持)
    assert abs((WALL + BOSS_H) - bat[4]) < 1e-6, "battery not resting on bosses"
    # XIAO 裏面はんだ逃げ: 基板下面と床の間に 1.2mm 以上
    assert xiao[4] - WALL >= 1.2 - 1e-6, "no solder/wire relief under XIAO"
    # XIAO とリッド内面のクリアランス
    assert BODY_D - xiao[5] >= 0.5 - 1e-6, "XIAO stack too close to lid"
    # XIAO 横方向拘束: 左ストップリブの面が基板左端に 0.1-0.3mm で対向
    assert 0.1 <= xiao[0] - xiao_stops[0][2] <= 0.3, "XIAO left stop gap wrong"
    # lip 帯と電池の非干渉 (厚め個体 5.3mm でも 0.4mm 以上のz隙間)
    assert (BODY_D - LIP_D) - (bat[4] + 5.3) >= 0.4 - 1e-6, \
        "lid lip overlaps battery (thick cell)"
    # 左 lip 内面と電池のたわみ代 (スナップ嵌合に 0.35mm 必要 → 0.5mm 以上確保)
    assert bat[0] - lip_left[2] >= 0.5 - 1e-6, "no snap deflection room at battery"
    # 電池リード曲げチャネル (左端面出射、AWG28 x2)
    assert bat[0] - WALL >= 2.2 - 1e-6, "battery lead channel too narrow"
    # USB-C: 基板端が右内壁面 → コネクタ突出1.3 < 壁1.6 (面一以内)
    assert USB_PROTRUDE <= WALL, "USB-C protrudes beyond outer wall"
    # --- スナップ機構 (v1.2) ---
    # リッジ円筒が lip 深さ帯 (z BODY_D-LIP_D .. BODY_D) に収まる
    assert SNAP_AZ - SNAP_R_RIDGE >= (BODY_D - LIP_D) - 1e-6, \
        "snap ridge extends below lip band"
    # 受け溝の上に保持肉が残る (前面から 0.4mm 以上)
    assert BODY_D - (SNAP_AZ + SNAP_R_GROOVE) >= 0.4 - 1e-6, \
        "snap groove breaks through front face"
    # リッジ内側端 (lip内面超え分) と電池左端のクリアランス
    assert bat[0] - (SNAP_AX + SNAP_R_RIDGE) >= 1.0 - 1e-6, \
        "snap ridge too close to battery"
    # こじ開けノッチと下辺スナップ受け溝の x 方向非重複
    for sx in SNAP_SX:
        assert not _overlap1(CX - 2.0, CX + 2.0, sx - 3.5, sx + 3.5), \
            "pry notch overlaps bottom snap groove"
    # 右辺スナップは右 lip の残存域 (y<26.6) 内
    assert SNAP_SYR + 3.5 <= lip_right[3] - 1e-6, "right snap outside right lip"
    print("[layout] all interference checks passed")
    print(f"[layout] outer: {W:.1f} x {H:.1f} x {TOTAL_D:.1f} mm (W x H x D, lid込み)")


# ---------------------------------------------------------------------------
# 形状ヘルパ
# ---------------------------------------------------------------------------
def bbox_solid(b):
    return cq.Solid.makeBox(b[2] - b[0], b[3] - b[1], b[5] - b[4],
                            cq.Vector(b[0], b[1], b[4]))


def rounded_slab(w, h, r, t, cx, cy, z0):
    return (cq.Workplane("XY", origin=(cx, cy, z0))
            .rect(w, h).extrude(t).edges("|Z").fillet(r))


# ---------------------------------------------------------------------------
# body
# ---------------------------------------------------------------------------
def build_body():
    body = rounded_slab(W, H, R_OUT, BODY_D, CX, H / 2, 0)
    body = body.edges("<Z").fillet(1.0)                     # 背面(服側)の当たりを丸める
    # キャビティ
    cavity = rounded_slab(IW, IH, R_IN, ID + 1.0, CX, H / 2, WALL)
    body = body.cut(cavity)
    # 磁石ボス (背面壁から内側へ突出、バッテリーの座面を兼ねる)
    boss_r = MAG_D / 2 + MAG_FIT / 2 + 1.5
    for mx in MAG_XS:
        body = body.union(cq.Workplane(
            obj=cq.Solid.makeCylinder(boss_r, BOSS_H + 1.0,
                                      cq.Vector(mx, MAG_Y, WALL - 1.0))))
    # バッテリー支持リブ (ボスと同じ高さ)
    for ry in (5.0, 25.2):
        body = body.union(cq.Workplane(
            obj=bbox_solid((6.0, ry, 29.8, ry + 1.2, WALL - 0.4, WALL + BOSS_H))))
    # 内部リブ類 (XIAOコーナーシート / 左ストップ / 上下ナブ / 電池ストップ / スイッチ挟み)
    for rb in (xiao_seats + xiao_stops + xiao_nubs_top + xiao_nubs_bot
               + bat_stops_left + bat_stops_bot + [sw_rib]):
        body = body.union(cq.Workplane(obj=bbox_solid(rb)))
    # 磁石圧入ポケット (φ6.2 x 深さ2.2、背面に 0.8mm ウェブを残す)
    for mx in MAG_XS:
        body = body.cut(cq.Workplane(
            obj=cq.Solid.makeCylinder(MAG_D / 2 + MAG_FIT / 2, MAG_T + 0.2 + 0.5,
                                      cq.Vector(mx, MAG_Y, MAG_WEB))))
    # USB-C 開口 (右側面) + 外側のプラグ逃がし座ぐり
    # 座ぐり 13 x 8 x 深さ0.8: 市販ケーブルのオーバーモールド (幅10-12/厚6-7) を受け、
    # プラグシェル露出 ~6.5mm でレセプタクル面 (外面-0.3mm) に確実に届かせる
    usb_zc = USB_Z0 + USB_OPEN_H / 2.0
    body = body.cut(cq.Workplane(obj=bbox_solid(
        (W - USB_CB_D, USB_CY - USB_CB_W / 2, W + 0.5, USB_CY + USB_CB_W / 2,
         usb_zc - USB_CB_H / 2, usb_zc + USB_CB_H / 2))))
    body = body.cut(cq.Workplane(obj=bbox_solid(
        (WALL + IW - 0.5, USB_CY - USB_OPEN_W / 2, W + 0.5, USB_CY + USB_OPEN_W / 2,
         USB_Z0, USB_Z0 + USB_OPEN_H))))
    # スイッチ位置決め凹み (上壁内面) + レバースロット (上面貫通)
    body = body.cut(cq.Workplane(obj=bbox_solid(
        (sw[0] - 0.2, WALL + IH, sw[2] + 0.2, WALL + IH + SW_RECESS,
         sw[4] - 0.2, sw[5] + 0.2))))
    sw_cx = (sw[0] + sw[2]) / 2
    sw_cz = (sw[4] + sw[5]) / 2
    body = body.cut(cq.Workplane(obj=bbox_solid(
        (sw_cx - 2.5, WALL + IH + SW_RECESS - 0.1, sw_cx + 2.5, H + 0.5,
         sw_cz - 1.1, sw_cz + 1.1))))                      # スロット 5.0 x 2.2
    # マイク開口 (上面、XIAO 上方に φ1.5 x 3。Sense拡張ボード上面高さに合わせる)
    for hx in (22.0, 25.5, 29.0):
        body = body.cut(cq.Workplane(
            obj=cq.Solid.makeCylinder(0.75, WALL + 1.0,
                                      cq.Vector(hx, WALL + IH - 0.2, MIC_Z),
                                      cq.Vector(0, 1, 0))))
    # スナップ受け溝 (内壁面の浅い水平溝、深さ~0.3。リッド側リッジと嵌合)
    for sy in SNAP_SY:
        body = body.cut(cq.Workplane(
            obj=cq.Solid.makeCylinder(SNAP_R_GROOVE, 7.0,
                                      cq.Vector(SNAP_AX, sy - 3.5, SNAP_AZ),
                                      cq.Vector(0, 1, 0))))
    for sx in SNAP_SX:
        body = body.cut(cq.Workplane(
            obj=cq.Solid.makeCylinder(SNAP_R_GROOVE, 7.0,
                                      cq.Vector(sx - 3.5, SNAP_AX, SNAP_AZ),
                                      cq.Vector(1, 0, 0))))
    # 右辺スナップ受け溝 (v1.2 追加。右上コーナーの口開き対策)
    body = body.cut(cq.Workplane(
        obj=cq.Solid.makeCylinder(SNAP_R_GROOVE, 7.0,
                                  cq.Vector(SNAP_AXR, SNAP_SYR - 3.5, SNAP_AZ),
                                  cq.Vector(0, 1, 0))))
    # こじ開けノッチ (底面前縁、爪を掛ける)
    #   v1.2: 幅 8→4 (CX±2)。下辺スナップ受け溝 (x8.5-15.5 / 20.5-27.5) との
    #   x 方向重複で壁残りが ~0.5mm になるのを解消。
    body = body.cut(cq.Workplane(obj=bbox_solid(
        (CX - 2.0, -0.1, CX + 2.0, 0.8, BODY_D - 1.2, BODY_D + 0.5))))
    return body


# ---------------------------------------------------------------------------
# lid (スナップフィット)
# ---------------------------------------------------------------------------
def build_lid():
    plate = rounded_slab(W, H, R_OUT, LID_T, CX, H / 2, BODY_D)
    plate = plate.edges(">Z").fillet(0.8)
    # lip (スカート): 内寸より CLR 小さいリング、厚さ1.0、深さ LIP_D
    lo_w, lo_h = IW - 2 * CLR, IH - 2 * CLR
    outer = rounded_slab(lo_w, lo_h, R_IN - CLR, -LIP_D, CX, H / 2, BODY_D)
    inner = rounded_slab(lo_w - 2.0, lo_h - 2.0, max(R_IN - CLR - 1.0, 0.6), -LIP_D - 1.0,
                         CX, H / 2, BODY_D + 0.5)
    ring = outer.cut(inner)
    # lip の切り欠き: 上辺の x>12.5 (XIAO上端との干渉回避。左コーナーはスタブとして残し
    # 上辺の保持を確保) と右側上部 (XIAO/USB)
    # ※ plate と結合する前に ring 単体から切る (共面カットによる非多様体化を防ぐ)
    ring = ring.cut(cq.Workplane(obj=bbox_solid(
        (12.5, 43.0, W - 0.5, H - 0.5, BODY_D - LIP_D - 0.5, BODY_D + 0.5))))
    ring = ring.cut(cq.Workplane(obj=bbox_solid(
        (WALL + IW - CLR - 1.6, 26.6, WALL + IW, H - 0.5,
         BODY_D - LIP_D - 0.5, BODY_D + 0.5))))
    lid = plate.union(ring)
    # 電池押さえリブ (リッド内面から降ろし、電池上面 (公称) と 0.7mm ギャップ。
    # 1mm 薄スポンジを介して電池の z ラトルを抑える)
    for rb in lid_bat_ribs:
        lid = lid.union(cq.Workplane(obj=bbox_solid(rb)))
    # スナップリッジ (lip 外面から 0.3mm 突出する丸棒状の凸。溝と嵌合)
    for sy in SNAP_SY:
        lid = lid.union(cq.Workplane(
            obj=cq.Solid.makeCylinder(SNAP_R_RIDGE, 6.0,
                                      cq.Vector(SNAP_AX, sy - 3.0, SNAP_AZ),
                                      cq.Vector(0, 1, 0))))
    for sx in SNAP_SX:
        lid = lid.union(cq.Workplane(
            obj=cq.Solid.makeCylinder(SNAP_R_RIDGE, 6.0,
                                      cq.Vector(sx - 3.0, SNAP_AX, SNAP_AZ),
                                      cq.Vector(1, 0, 0))))
    # 右辺スナップリッジ (v1.2 追加)
    lid = lid.union(cq.Workplane(
        obj=cq.Solid.makeCylinder(SNAP_R_RIDGE, 6.0,
                                  cq.Vector(SNAP_AXR, SNAP_SYR - 3.0, SNAP_AZ),
                                  cq.Vector(0, 1, 0))))
    # LED 窓 (φ3.2 貫通。LEDは内側から挿してドームを覗かせる)
    lid = lid.cut(cq.Workplane(
        obj=cq.Solid.makeCylinder(LED_D / 2 + 0.1, LID_T + 1.0,
                                  cq.Vector(LED_POS[0], LED_POS[1], BODY_D - 0.5))))
    return lid


# ---------------------------------------------------------------------------
# backplate (裏板)
# ---------------------------------------------------------------------------
BP_W, BP_H, BP_T = 32.0, 26.0, 3.0


def build_backplate():
    bp = rounded_slab(BP_W, BP_H, 5.0, BP_T, 0, 0, 0)
    bp = bp.edges("<Z").fillet(1.0)     # 肌側: フラット + 縁を大きく丸める
    bp = bp.edges(">Z").fillet(0.6)     # 布側
    # 磁石ポケット (布側から圧入、肌側に 0.8mm ウェブ → 肌側は完全フラット)
    for mx in (-MAG_PITCH / 2, MAG_PITCH / 2):
        bp = bp.cut(cq.Workplane(
            obj=cq.Solid.makeCylinder(MAG_D / 2 + MAG_FIT / 2, MAG_T + 0.2 + 0.5,
                                      cq.Vector(mx, 0, MAG_WEB))))
    return bp


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
def export_all():
    os.makedirs(STL_DIR, exist_ok=True)
    os.makedirs(REN_DIR, exist_ok=True)
    check_layout()

    print("[build] body ...")
    body = build_body()
    print("[build] lid ...")
    lid = build_lid()
    print("[build] backplate ...")
    backplate = build_backplate()

    paths = {}
    for name, wp in (("body", body), ("lid", lid), ("backplate", backplate)):
        p = os.path.join(STL_DIR, f"mindclip_{name}.stl")
        cq.exporters.export(wp, p, tolerance=0.05, angularTolerance=0.2)
        paths[name] = p
        print(f"[export] {p}")
    return paths


def verify_and_render(paths):
    import numpy as np
    import trimesh
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from matplotlib.collections import PolyCollection

    PETG_RHO = 1.27e-3  # g/mm^3
    meshes = {}
    total_print_mass = 0.0
    for name, p in paths.items():
        m = trimesh.load_mesh(p)
        meshes[name] = m
        mass = m.volume * PETG_RHO
        total_print_mass += mass
        print(f"[verify] {name}: watertight={m.is_watertight}  "
              f"volume={m.volume/1000.0:.2f} cm3  mass(PETG)={mass:.1f} g  "
              f"tris={len(m.faces)}")
        assert m.is_watertight, f"{name} STL is not watertight"
    comp_mass = 10.0 + 5.0 + 4 * 0.44 + 1.0   # 電池+XIAOスタック+磁石+SW/LED/配線
    print(f"[verify] total printed mass ~{total_print_mass:.1f} g, "
          f"device total ~{total_print_mass + comp_mass:.1f} g (est.)")

    def shade(mesh, base, light=(0.45, 0.35, 0.82)):
        ln = np.array(light) / np.linalg.norm(light)
        d = np.clip(mesh.face_normals @ ln, 0, 1)
        k = (0.45 + 0.55 * d)[:, None]
        c = np.array(base)[None, :3] * k
        return np.clip(np.hstack([c, np.full((len(c), 1), 1.0)]), 0, 1)

    def draw_scene(ax, items, lw=0.05):
        """items = [(mesh, color, alpha), ...] を1つの深度ソート済み
        Poly3DCollection として描画する (パーツ間の前後関係を正しく表示)"""
        polys, colors = [], []
        for mesh, color, alpha in items:
            mesh = mesh.copy()
            try:  # 大きい三角形を分割して painter's sort の破綻を抑える
                mesh = mesh.subdivide_to_size(5.0, max_iter=6)
            except BaseException:
                pass
            fc = shade(mesh, color)
            fc[:, 3] = alpha
            polys.append(mesh.vertices[mesh.faces])
            colors.append(fc)
        col = Poly3DCollection(np.concatenate(polys),
                               facecolors=np.concatenate(colors),
                               edgecolors=(0, 0, 0, 0.05), linewidths=lw,
                               zsort="average")
        ax.add_collection3d(col)

    def finish(ax, pts, elev=18, azim=-60, zoom=1.0):
        lo = pts.min(axis=0)
        hi = pts.max(axis=0)
        c = (lo + hi) / 2
        r = (hi - lo).max() / 2 / zoom
        ax.set_xlim(c[0] - r, c[0] + r)
        ax.set_ylim(c[1] - r, c[1] + r)
        ax.set_zlim(c[2] - r, c[2] + r)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()

    C_BODY = (0.30, 0.45, 0.62)
    C_LID = (0.42, 0.60, 0.75)
    C_BP = (0.55, 0.55, 0.58)
    C_BAT = (0.85, 0.72, 0.25)
    C_XIAO = (0.25, 0.60, 0.35)
    C_SW = (0.80, 0.35, 0.30)
    C_LED = (0.90, 0.20, 0.20)
    C_MAG = (0.35, 0.35, 0.38)

    def tf(dx=0, dy=0, dz=0):
        T = np.eye(4)
        T[:3, 3] = [dx, dy, dz]
        return T

    def boxmesh(b):
        m = trimesh.creation.box(extents=[b[2] - b[0], b[3] - b[1], b[5] - b[4]])
        m.apply_transform(tf((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, (b[4] + b[5]) / 2))
        return m

    def magmesh(x, y, z):
        m = trimesh.creation.cylinder(radius=MAG_D / 2, height=MAG_T, sections=32)
        m.apply_transform(tf(x, y, z))
        return m

    body_m, lid_m, bp_m = meshes["body"], meshes["lid"], meshes["backplate"]
    # backplate を装着位置へ (布厚 0.4mm を挟んで背面側、ポケット面を本体へ向ける)
    bp_asm = bp_m.copy()
    bp_asm.apply_transform(tf(CX, MAG_Y, -BP_T - 0.4))

    # ---- assembled.png ----
    # 装着姿勢で表示: モデルの Y(上) をプロットの Z(上) に回転
    RUP = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1.0]])
    fig = plt.figure(figsize=(9, 8), dpi=140)
    ax = fig.add_subplot(111, projection="3d")
    ups = []
    for m in (body_m, lid_m, bp_asm):
        mu = m.copy()
        mu.apply_transform(RUP)
        ups.append(mu)
    draw_scene(ax, [(ups[0], C_BODY, 1.0), (ups[1], C_LID, 1.0),
                    (ups[2], C_BP, 1.0)])
    pts = np.vstack([u.vertices for u in ups])
    finish(ax, pts, elev=14, azim=-62, zoom=1.05)
    ax.set_title("MindClip DIY — assembled (worn state)\n"
                 f"body {W:.1f} x {H:.1f} x {TOTAL_D:.1f} mm + backplate "
                 f"{BP_W:.0f} x {BP_H:.0f} x {BP_T:.0f} mm (fabric gap 0.4)",
                 fontsize=10)
    fig.savefig(os.path.join(REN_DIR, "assembled.png"), bbox_inches="tight")
    plt.close(fig)
    print("[render] assembled.png")

    # ---- exploded.png ----
    fig = plt.figure(figsize=(9, 9), dpi=140)
    ax = fig.add_subplot(111, projection="3d")
    lid_e = lid_m.copy(); lid_e.apply_transform(tf(dz=26))
    bp_e = bp_asm.copy(); bp_e.apply_transform(tf(dz=-22))
    mags = [magmesh(mx, MAG_Y, -9) for mx in MAG_XS] + \
           [magmesh(mx, MAG_Y, -31) for mx in MAG_XS]
    draw_scene(ax, [(body_m, C_BODY, 1.0), (lid_e, C_LID, 1.0),
                    (bp_e, C_BP, 1.0)] + [(mm, C_MAG, 1.0) for mm in mags])
    labels = [
        ("lid (snap-fit)", (W + 4, H - 6, 26 + BODY_D)),
        ("body", (W + 4, H / 2, BODY_D / 2)),
        ("magnets φ6x2 (x2, press-fit)", (CX + 12, MAG_Y - 4, -9)),
        ("backplate (inside garment)", (CX + 14, MAG_Y + 6, -23)),
        ("magnets φ6x2 (x2, press-fit)", (CX + 12, MAG_Y - 8, -33)),
    ]
    for txt, (x, y, z) in labels:
        ax.text(x, y, z, txt, fontsize=9)
    pts = np.vstack([body_m.vertices, lid_e.vertices, bp_e.vertices])
    finish(ax, pts, elev=14, azim=-58, zoom=0.95)
    ax.set_title("MindClip DIY — exploded view", fontsize=11)
    fig.savefig(os.path.join(REN_DIR, "exploded.png"), bbox_inches="tight")
    plt.close(fig)
    print("[render] exploded.png")

    # ---- views.png (3面図 + 寸法) ----
    asm = trimesh.util.concatenate([body_m, lid_m])
    views = [
        ("Front (XY)", (0, 1), (2,), "front"),
        ("Side (ZY)", (2, 1), (0,), "side"),
        ("Top (XZ)", (0, 2), (1,), "top"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(14, 6), dpi=140)
    for ax2, (title, ij, _k, kind) in zip(axes, views):
        i, j = ij
        tris = asm.vertices[asm.faces][:, :, [i, j]]
        pc = PolyCollection(tris, facecolors=(0.55, 0.68, 0.80),
                            edgecolors=(0.1, 0.15, 0.2, 0.10), linewidths=0.1)
        ax2.add_collection(pc)
        lo = asm.vertices[:, [i, j]].min(axis=0)
        hi = asm.vertices[:, [i, j]].max(axis=0)
        pad = 8
        ax2.set_xlim(lo[0] - pad, hi[0] + pad)
        ax2.set_ylim(lo[1] - pad, hi[1] + pad)
        ax2.set_aspect("equal")
        ax2.set_title(title, fontsize=10)
        ax2.axis("off")

        def dim_h(y, x0, x1, text):
            ax2.annotate("", xy=(x0, y), xytext=(x1, y),
                         arrowprops=dict(arrowstyle="<->", lw=0.8))
            ax2.text((x0 + x1) / 2, y + 1.0, text, ha="center", fontsize=8)

        def dim_v(x, y0, y1, text):
            ax2.annotate("", xy=(x, y0), xytext=(x, y1),
                         arrowprops=dict(arrowstyle="<->", lw=0.8))
            ax2.text(x + 1.0, (y0 + y1) / 2, text, va="center", fontsize=8,
                     rotation=90)

        if kind == "front":
            dim_h(lo[1] - 4, 0, W, f"{W:.1f}")
            dim_v(hi[0] + 4, 0, H, f"{H:.1f}")
        elif kind == "side":
            dim_h(lo[1] - 4, 0, TOTAL_D, f"{TOTAL_D:.1f}")
            dim_v(hi[0] + 4, 0, H, f"{H:.1f}")
        else:
            dim_h(lo[1] - 4, 0, W, f"{W:.1f}")
            dim_v(hi[0] + 4, 0, TOTAL_D, f"{TOTAL_D:.1f}")
    fig.suptitle("MindClip DIY — orthographic views (mm) / mic port & switch on top,"
                 " USB-C on right side", fontsize=11)
    fig.savefig(os.path.join(REN_DIR, "views.png"), bbox_inches="tight")
    plt.close(fig)
    print("[render] views.png")

    # ---- internal.png (蓋なし内部レイアウト) ----
    fig = plt.figure(figsize=(9, 9), dpi=140)
    ax = fig.add_subplot(111, projection="3d")
    comp = [
        (f"{BAT_LABEL} ({BAT_W:.0f}x{BAT_H:.0f}x{BAT_T:.0f})", bat, C_BAT),
        ("XIAO ESP32S3 Sense stack", xiao, C_XIAO),
        ("slide switch SS-12D00", sw, C_SW),
    ]
    ledm = trimesh.creation.cylinder(radius=1.5, height=4.0, sections=24)
    ledm.apply_transform(tf(LED_POS[0], LED_POS[1], BODY_D - 2.0))
    items = [(body_m, C_BODY, 0.45)]
    items += [(boxmesh(b), c, 1.0) for _t, b, c in comp]
    items += [(ledm, C_LED, 1.0)]
    items += [(magmesh(mx, MAG_Y, MAG_WEB + MAG_T / 2), C_MAG, 1.0)
              for mx in MAG_XS]
    draw_scene(ax, items)
    ann = [
        (f"{BAT_LABEL}\n({BAT_W:.0f}x{BAT_H:.0f}x{BAT_T:.0f})", (CX, bat[1] + 6, 14)),
        ("XIAO ESP32S3 Sense stack\n(USB-C -> right wall)", (W + 4, USB_CY, 14)),
        ("slide switch SS-12D00", (sw[0] - 2, H + 4, 10)),
        ("3mm LED (front window)", (-14, LED_POS[1] - 3, 12)),
        ("magnets under battery\n(bosses in back wall)", (CX, MAG_Y - 3, -8)),
        ("mic ports (top wall)", (W + 4, H + 3, 6)),
    ]
    for txt, (x, y, z) in ann:
        ax.text(x, y, z, txt, fontsize=8, ha="center")
    pts = np.vstack([body_m.vertices])
    finish(ax, pts, elev=58, azim=-80, zoom=0.85)
    ax.set_title("MindClip DIY — internal layout (lid removed)", fontsize=11)
    fig.savefig(os.path.join(REN_DIR, "internal.png"), bbox_inches="tight")
    plt.close(fig)
    print("[render] internal.png")


if __name__ == "__main__":
    paths = export_all()
    verify_and_render(paths)
    print("[done] all outputs generated")
