#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MindClip DIY — クリップ型音声ロガー筐体 パラメトリックCADモデル (CadQuery 2.8)

バリアント (環境変数 MINDCLIP_VARIANT):
  - allday (既定) : LiPo 802530 (680mAh, 実測 32.0x25.0x8.0)。外形 40.0 x 49.4 x 14.6 mm
  - slim          : LiPo 502530 (500mAh)。外形 40.0 x 49.4 x 13.6 mm

基板オプション (環境変数 MINDCLIP_PCB, v1.5 で追加):
  - none (既定) : 基板なし = 採用案 A-1 (ハーネス)。**いま実行できるのはこの構成だけ**
                  (allday/none と slim/none の 2 構成)。SCHEMATIC.md §5.5 が確定した
                  JST 嵌合体の置き場所を harness_jst、ピグテールの継ぎ足し (AWG28 への
                  継ぎ目 2 か所) を harness_splice として毎回検算する。
  - sense       : MC-SENSE-A (10.0 x 15.6 x 0.8t) を左ポケット床に置く v2 検討用。
                  v1.8 の実測スイッチ (本体高さ 4.0) でポケットが不足するため、
                  **読み込み時にメッセージを出して終了する** (基板の再設計待ち)。
  - carrier     : MC-CARRIER-A (34.2 x 21.0 x 0.8t) に XIAO を直はんだする v2 検討用。
                  v1.8 で内寸幅が 36.8 になり XIAO が 2.0mm 右へ動いたのに、基板は
                  左アンカーのまま (XIAO フットプリント右端 x36.4) で食い違うため、
                  **読み込み時にメッセージを出して終了する** (基板外形の再生成待ち)。

  出力は ../stl/<tag>/ と ../renders/<tag>/ (tag = variant または variant_pcb)。

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
  - v1.5 rev2: 「箱にならない部品」を AABB でモデル化した (sw_terms = スライドスイッチの
    端子3本+はんだ+φ3熱収縮 / led_leads = 90度に曲げた LED リード+220Ω+継ぎ目)。
    これに伴い JST 嵌合体を左内壁密着・y28.6..39.6 へ、LED 窓を x6.9 → 9.8 へ
    移した (旧配置はスイッチ端子と slim で 0.00mm、LED リードとは 1.0〜2.0mm の実干渉)。
    LED 窓は φ3.2 → φ3.4 (FDM の穴縮み 0.1〜0.3mm に対する救済。MECHANICAL.md §5)。
  - v1.3: 電池厚をバリアント化したのに伴い、電池と右リッド lip が干渉したため内寸幅を
    32.6 → 34.0 に拡大。内部リブ座標を xiao[0] / CX 基準の相対値に改め、寸法変更で
    リブ同士が衝突しないようにした。内寸奥行きは「XIAOスタック」と「磁石ボス+電池+
    押さえリブ逃げ」の厚い方から自動計算する。

座標系 (body 基準):
  X = 幅方向 (装着時の左右) / Y = 高さ方向 (Y+ が上 = マイク側) / Z = 奥行き
  z=0 が背面(服に当たる面)、z+ が正面(リッド側)

実行:
  python3 mindclip_case.py                       # allday / 基板なし (採用構成)
  MINDCLIP_VARIANT=slim python3 mindclip_case.py # slim / 基板なし
  (MINDCLIP_PCB=sense / carrier は現在どちらもメッセージを出して終了する)
  → ../stl/*.stl と ../renders/*.png を生成し、干渉チェック(assert)と
    watertight 検証結果をログ出力する。

寸法出典:
  - XIAO ESP32S3 基板 21.0 x 17.8 mm : Seeed 公式値 (Web検証済み)
  - Sense拡張ボード込みスタック総厚 8.2 mm (カメラ除く) : v1.8 実測 (MEASUREMENTS.md M1)
  - USB-C 中心 : スタック下面から 2.9 mm : v1.8 実測 (M2)
  - PDMマイク位置 : 拡張ボード上、正面向き : **assumption** → 上面開口+前面キャビティで導音。
    穴の x は MIC_X_ON_BOARD (基板左端からの距離) で持つ。**基板上の実位置は未実測 (M9)**
  - XIAO 基板のコーナー R : XIAO_CORNER_R = 1.9 : **assumption / 要実測**
  - LiPo 502530 : 30 x 25 x 5.0 mm (公称)
  - LiPo 802530 : 32.0 x 25.0 x 8.0 mm / 11 g (採用品 HXJNLDC。v1.8 実測 M3。
    電池側コネクタは 1.25mm ピッチ 2P)
  - SS-12D00G3 : 本体 8.7 x 3.7 mm (Web検証済み)、本体高さ 4.0 mm・レバー突出 3.0 mm
    (v1.8 実測 M6)。レバーの幅 (スライド方向) SW_LEVER_W = 2.0 : **assumption / 要実測**
  - LED OSR5JA3Z74A : ツバ φ3.4 x 0.5、ツバ上面〜ドーム先端 4.5 mm (v1.8 実測 M8)
  - JST 嵌合体 (ピグテール + 電池プラグ) : 5.8 x 11.0 x 4.5 : **assumption / 要実測 (M4)**
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
LIP_D = 2.2         # lip (スカート) の挿入深さ。内寸奥行きの計算にも使うため先頭で定義

# --- バリアント選択 ---------------------------------------------------------
# Seeed 公式スペックの実測値 (録音+SD書込 3.8V/54.4mA平均) を電力予算の基準にすると、
# 500mAh では約8時間しか持たず「起床〜就寝」を走り切れない (ELECTRICAL.md §2.2)。
# そのため既定は 802530 の allday。採用品 (HXJNLDC B0D4V9NZSH) の実容量は 680mAh
# (802530 に 800mAh は物理的に入らない。bom.md のエネルギー密度検算参照)。
#   allday (既定): LiPo 802530 680mAh — 最悪ケース54.4mAで約10.6時間、28mAゲート達成で20.6h
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
    # v1.6: 採用品 HXJNLDC 802530 (Amazon B0D4V9NZSH)。メーカー仕様表 (商品画像) は
    # long 31 × width 25 × high 8 mm。公称型番の 30.0 でなく実仕様 31.0 を正とする
    # (BAT_TOL の安全代を食わないため)。
    # v1.8: 実測 32.0 × 25.0 × 8.0 (MEASUREMENTS.md M3。テープ・保護基板の端を含む全長)。
    BAT_W, BAT_H, BAT_T = 32.0, 25.0, 8.0      # LiPo 802530 (680mAh, 実測32mm)
    BAT_LABEL, BAT_MAH = "LiPo 802530 (680mAh)", 680
XIAO_W, XIAO_H = 21.0, 17.8                     # XIAO ESP32S3 基板
XIAO_CORNER_R = 1.9                             # 基板コーナー R : **assumption / 要実測**
                                                #   (右上コーナーの逃げは R=0 の角ばった基板でも
                                                #    入るように切ってある。check_xiao_fit 参照)
XIAO_STACK_T = 8.2                              # Sense拡張ボード込み総厚 (v1.8 実測 M1。旧仮定 7.5)
USB_PROTRUDE = 1.3                              # USB-C の基板端からの突出
SW_L, SW_W, SW_H = 8.7, 3.7, 4.0                # SS-12D00 本体 (高さ v1.8 実測 M6。旧仮定 3.5)
SW_LEVER = 3.0                                  # レバー突出 (SS-12D00**G3** = レバー 3mm。v1.8 実測 M6)
SW_LEVER_W = 2.0                                # レバーの幅 (スライド方向) : **assumption / 要実測 (M6)**
SW_TRAVEL = 2.0                                 # レバーのスライド量 (SS-12D00 公称)
SW_SLOT_L, SW_SLOT_W = 5.0, 2.2                 # 上面のレバースロット (スライド方向 x 厚み方向)
LED_D = 3.0                                     # 3mm LED
MAG_D, MAG_T = 6.0, 2.0                         # ネオジム磁石 φ6 x 2
MAG_FIT = 0.2                                   # 圧入ポケット径方向余裕 (φ6.2)
MAG_WEB = 0.8                                   # 磁石ポケット残し肉厚 (磁力を通す)
MAG_PITCH = 18.0                                # 磁石2個の中心間距離

# --- 基板オプション (v1.5, 環境変数 MINDCLIP_PCB) ---------------------------
# v1.5 の採用構成は「案A-1 = 基板を作らない」(pcb/LAYOUT.md §0)。既定値 none は
# v1.4 と完全に同一形状で、基板を入れる場合だけ筐体側のフィーチャが増える。
#   none    (既定) : 基板なし。JST ピグテール (電池側プラグと同じ 1.25mm ピッチ 2P) +
#                    空中配線 (はんだ12点 = 従来の10点 + ピグテールを AWG28 へ継ぐ2点)。
#                    §5.5 で確定した JST 嵌合体の置き場所を harness_jst、継ぎ目2か所の
#                    置き場所を harness_splice として検算する。
#   sense   : MC-SENSE-A (10.0 x 15.6 x 0.8t) を左ポケット床に寝かせる v2 検討用。
#             実測スイッチでポケットが不足するため、下の sense ブロックで終了する。
#   carrier : MC-CARRIER-A (34.2 x 21.0 x 0.8t) に XIAO をカステレーション直はんだする
#             v2 検討用。基板外形が IW 36.8 に追従していないため、ここで終了する。
# いま実行できるのは allday/none と slim/none の 2 構成だけ。
PCB = os.environ.get("MINDCLIP_PCB", "none").strip().lower()
if PCB not in ("none", "sense", "carrier"):
    raise SystemExit(f"MINDCLIP_PCB は none / sense / carrier のいずれか (指定値: {PCB})")
if PCB == "carrier":
    # 内寸幅を 36.8 に広げた結果、右詰めの XIAO は筐体側で x17.4..38.4 に居るが、
    # MC-CARRIER-A (34.2 x 21.0) は左アンカーの固定外形で、基板上の XIAO フットプリントは
    # x15.4..36.4 のまま。このまま STL を出すと「CAD 上の XIAO」と「基板が置く XIAO」が 2.0mm
    # 食い違い、USB-C レセプタクルが座ぐりの約 1.5mm 奥に引っ込む筐体が出来てしまう。
    # 誤解を招く STL を出さないよう、sense と同じく読み込み時に止める (下の carrier 用の
    # コードは v2 で基板を作り直すときの出発点として残してある)。
    raise SystemExit(
        "MINDCLIP_PCB=carrier: MC-CARRIER-A (34.2x21.0) の基板外形・XIAO フットプリントが "
        "v1.8 の内寸幅 IW=36.8 に追従していません (XIAO は筐体側 x17.4〜38.4、基板側 x15.4〜36.4 で "
        "2.0mm ずれ、USB-C が座ぐりの奥に約1.5mm 引っ込みます)。"
        "基板外形とフットプリントを IW 36.8 用に作り直してから使ってください (v2 で再設計)。"
        "いま実行できる構成は allday/none と slim/none の 2 つです")
PCB_T = 0.8            # 基板厚 (JLCPCB 標準厚。pcb/LAYOUT.md §3)
PCB_CLR = 0.40         # 基板外形とポケット壁の片側クリアランス
                       #   FDM ポケットは 0.1〜0.3mm 小さく出る (§5) + PCB外形公差 ±0.2mm
J1_BODY_Z = 7.5        # 基板実装 JST (v2 検討時は PH2.0) トップエントリの嵌合体高さ : assumption
                       #   ※ v1 の電池プラグは 1.25mm ピッチ。v2 で基板を作るときはコネクタ選定からやり直す
J1_BEND_Z = 2.4        # 嵌合体上に要る電線曲げ代 = AWG28 (φ1.2) の最小曲げ半径 2xOD
J1_PIN_Z = 0.8         # THT ピン + はんだフィレットの基板裏突出 : assumption
PCB_SHELF = 0.8 if PCB == "carrier" else 0.0    # 基板下の逃げ (キャリアのみ)
PCB_Z0 = WALL + PCB_SHELF                       # 基板下面 z
PCB_Z1 = PCB_Z0 + PCB_T                         # 基板上面 z
PCB_GUIDE_GAP = 0.25   # 抜け止め爪の下面と基板上面のすきま (FDM 公差の吸収)
PCB_LEDGE_OVH = 0.6    # 抜け止め爪の張り出し量

# --- 内寸の組み立て ---
# 内寸幅: 左のリード曲げチャネル(2.4) + 電池(30) + 右のリッドlip逃げ。
# allday(8mm厚)では電池上面がリッドlipの降下域まで届くため、電池右端と右lip内面の間に
# 0.4mm以上の隙間が要る (旧値32.6では右lipと干渉し check_layout が失敗した)。
# v1.4: 34.0 では電池右端と右lip内面の隙間が 0.45mm しかなく、LiPo の寸法公差
# (±0.5mm) と保護回路(PCM)端の膨らみで干渉し得た。左側と同じ 1.25mm を確保する
# 34.8 に拡大 (下の BAT_TOL assert で恒久的に担保する)。
IW = 36.8   # v1.8: 電池実測 32.0mm に合わせ 35.8→36.8 (電池両脇の隙間は従来と同一)
BAT_TOL = 1.0                                   # 電池の寸法公差+PCM膨らみの許容代
# XIAO基板下面リフト。none/sense は裏面はんだ+AWG28+カプトンの突出 (1.0-1.5mm) の
# 逃げ空間、carrier では「シェルフ0.8 + キャリア基板0.8」がそのままリフトになる。
XIAO_LIFT = (PCB_SHELF + PCB_T) if PCB == "carrier" else 1.4
BOSS_H = 1.4                                    # 磁石ボスの内面からの突出 (電池はこの上に載る)
# 内寸奥行き = 「XIAOスタック」「磁石ボス+電池」「基板上の J1 嵌合体+曲げ代」の最大 +
#              リッド内面クリアランス。
# XIAO側: リフト1.4 + スタック8.2 + 余裕0.6 = 10.2
# 電池側: ボス1.4 + BAT_T + リブ逃げ1.8 (押さえリブのギャップ1.0 + リブ肉厚0.8)
# 基板側: (基板上面 + 嵌合体7.5 + 曲げ代2.4) - WALL   ← pcb/LAYOUT.md §4.2 と同じ式
_J1_TOP = PCB_Z1 + J1_BODY_Z                    # J1 嵌合体の上端 z
ID_PCB = 0.0
if PCB != "none":
    ID_PCB = _J1_TOP + J1_BEND_Z - WALL
    if PCB == "sense":
        # sense の J1 は左 lip (x1.75..2.75) のすぐ横 (x2.80) に立つ。基板の位置公差
        # (ポケット遊び ±0.2mm) で x が食い違い得るため、非干渉は z 方向で担保する。
        # → 嵌合体上端が lip 帯の下端より 0.3mm 以上下にあること。
        ID_PCB = max(ID_PCB, _J1_TOP + LIP_D + 0.3 - WALL)
ID = round(max(XIAO_LIFT + XIAO_STACK_T + 0.6, BOSS_H + BAT_T + 1.8, ID_PCB), 2)
M_BOT = 1.6                                     # バッテリー下マージン
# carrier ではカステレーション受けランドを XIAO の長辺の外に出す必要があるため、
# 上下のマージンを広げる (pcb/LAYOUT.md §1.2)。内寸高さ 46.2 -> 48.0、外形 49.4 -> 51.2。
GAP_BX = 1.8 if PCB == "carrier" else 1.2       # バッテリー上端〜XIAO下端 (配線通し)
M_TOP = 1.8 if PCB == "carrier" else 0.6        # XIAO上端マージン
IH = M_BOT + BAT_H + GAP_BX + XIAO_H + M_TOP    # 内寸高さ = 46.2 (carrier: 48.0)

# --- 外形 ---
W = IW + 2 * WALL                               # 40.0
H = IH + 2 * WALL                               # 49.4
BODY_D = WALL + ID                              # allday 12.8 / slim 11.8 (body 単体奥行き)
TOTAL_D = BODY_D + LID_T                        # allday 14.6 / slim 13.6 (組立時奥行き)
R_OUT = 4.0                                     # 外形コーナーR
R_IN = 2.5                                      # 内寸コーナーR

# --- 内部レイアウト (絶対座標, body基準) ---
CX = W / 2.0                                    # 20.0
# バッテリー: 下段・背面側・右詰め (磁石ボスの上に載る → 重心をクランプ側に寄せる)
#   502530 のリード/タブは長さ30mm方向の端面 (25mm幅の面) から出る → 左端面から出射し、
#   左側の BAT_LEAD_CH チャネルを上へ回して XIAO 裏面の BAT パッドへ配線する。
BAT_LEAD_CH = 2.4                             # 左側リード曲げチャネル幅 (AWG28 x2)
bat = (WALL + BAT_LEAD_CH, WALL + M_BOT,        # x0,y0  (4.0, 3.2)
       WALL + BAT_LEAD_CH + BAT_W, WALL + M_BOT + BAT_H,   # x1,y1 (allday 36.0 / slim 34.0, 28.2)
       WALL + BOSS_H, WALL + BOSS_H + BAT_T)    # z0,z1  (3.0 .. allday 11.0 / slim 8.0)
# XIAO スタック: 上段・右詰め (USB-C を右側面へフラッシュ)。
#   コーナーシート4個 (h=XIAO_LIFT) の上に載せ、裏面はんだの逃げ空間を確保。
xiao = (WALL + IW - XIAO_W, bat[3] + GAP_BX,
        WALL + IW, bat[3] + GAP_BX + XIAO_H,
        WALL + XIAO_LIFT, WALL + XIAO_LIFT + XIAO_STACK_T)  # x17.4..38.4 / y29.4..47.2 / z3.0..11.2
# 磁石: バッテリー背後の背面壁ボス内 (筐体中心 CX 基準 → backplate と共通)
MAG_Y = (bat[1] + bat[3]) / 2.0                 # 15.7 (バッテリー中心)
MAG_XS = (CX - MAG_PITCH / 2, CX + MAG_PITCH / 2)
# スイッチ: 上面左 (XIAO の左の空間)。上壁の浅い凹みにはめて接着
SW_RECESS = 0.7                                 # 上壁内面の位置決め凹み深さ
_swz0 = WALL + (ID - SW_W) / 2.0                # allday 5.35 / slim 4.85
sw = (4.0, WALL + IH - (SW_H - SW_RECESS), 4.0 + SW_L, WALL + IH + SW_RECESS,
      _swz0, _swz0 + SW_W)                      # x4.0..12.7 / y44.5..48.5 / z allday 5.35..9.05
# 上壁内面の位置決め凹み (build_body で cut する。スイッチの x / z はこの凹みが決める)
sw_recess_pocket = (sw[0] - 0.2, WALL + IH, sw[2] + 0.2, WALL + IH + SW_RECESS,
                    sw[4] - 0.2, sw[5] + 0.2)
# スイッチ端子 (v1.5 rev2 で追加)。旧 CAD は本体 8.7x3.7x3.5 の箱しか持たず、
#   -y 側に出る3本の端子と、そこに付くはんだ継ぎ目 + 熱収縮 (φ3) を一切モデル化して
#   いなかった。このため左ポケットの部品を y42 まで上げても check_layout は素通りした。
#   SS-12D00 の端子は本体の -y 面から 2.54mm ピッチで3本出る (本体中心振り分け)。
#   使うのは SCHEMATIC.md §1.4 のとおり 中央 (SW1.2 / 青) と **左端** (SW1.1 / 黒2本)。
#   右端 (XIAO 側) は根元から切り落とす: 残すと φ3 熱収縮の包絡が x12.5 まで広がり、
#   スイッチ右端の挟みリブ (sw_ribs[1], x13.0..) まで 0.5mm しか残らず、v1.8 で追加した
#   継ぎ目・電線の通り道 (x11.8..14.4 の帯) も塞ぐ (README 手順4)。
SW_TERM_L = 3.5                                 # 端子長 (assumption。流通品は 3.0〜3.5)
SW_TERM_PITCH = 2.54                            # 端子ピッチ
SW_JOINT_R = 1.6                                # はんだ継ぎ目 + φ3 熱収縮チューブの半径
_sw_cx = (sw[0] + sw[2]) / 2.0                  # 端子列の中心 x = 8.35
_sw_cz = (sw[4] + sw[5]) / 2.0                  # 端子の z 中心 (本体中央)
sw_terms = (_sw_cx - SW_TERM_PITCH - SW_JOINT_R, sw[1] - SW_TERM_L - 1.0,
            _sw_cx + SW_JOINT_R, sw[1],
            _sw_cz - SW_JOINT_R, _sw_cz + SW_JOINT_R)   # x4.21..9.95 / y40.0..44.5
# --- JST 嵌合体の置き場所 (採用構成 = 基板なし A-1) -------------------------
#   電池側プラグは 1.25mm ピッチ 2P (実測)。ピグテールはそれと嵌合する同系統品。
#   嵌合体の外形 HARNESS_JST_XYZ は旧 2.0mm 品を想定した assumption のままで、
#   購入済みの 1.25mm ピグテールが届いたら M4 で測って書き換える (それまで据え置き)。
#   SCHEMATIC.md §5.5。長辺 11.0mm は必ず Y方向 (X方向だと xiao_stops[0] に 1.5mm 食い込む)。
#   v1.5 rev2 で座標を変更した (旧: x3.0..8.8 / y31.0..42.0):
#     - x を左内壁 (WALL=1.6) に密着させた。ホットボンドで左内壁へ点付けする以上
#       1.4mm 浮かせる意味がなく、LED リード帯との x 隙間を稼げる。
#     - y1 を 42.0 → 39.6 に下げた。旧位置は SS-12D00 の端子 (上記 sw_terms,
#       現在 y40.0..44.5) と slim で分離距離 0.00mm、はんだ継ぎ目 + 熱収縮を入れると
#       -1.35mm の実干渉だった (旧 CAD は端子を持っていなかったので素通りしていた)。
HARNESS_JST_XYZ = (5.8, 11.0, 4.5)              # 嵌合体 X x Y x Z (assumption / 要実測)
HARNESS_JST_X0 = WALL                           # 左内壁に密着 (点付け面)
HARNESS_JST_Y0 = round(bat[3] + 0.4, 6)         # 電池上端から 0.4mm
harness_jst_x1 = HARNESS_JST_X0 + HARNESS_JST_XYZ[0]        # 7.4 (LED の x 基準)
harness_jst = (HARNESS_JST_X0, HARNESS_JST_Y0,
               harness_jst_x1, HARNESS_JST_Y0 + HARNESS_JST_XYZ[1],
               WALL, WALL + HARNESS_JST_XYZ[2]) if PCB == "none" else None
# --- ピグテールの継ぎ目 (v1.8 で標準手順化) ---------------------------------
#   購入したピグテールの電線 (AWG26 級、被覆外径 1.3mm 超の可能性) は XIAO の下
#   (リフト 1.4mm、通せる外径は 1.3mm まで) を通せないかもしれない。そこで標準手順として
#   ピグテールの線をコネクタ根元から約 10mm / 約 15mm で切り、細い AWG28 を継ぎ足す
#   (README 手順5)。継ぎ目は「はんだ + φ3 熱収縮」で φ2.5 x 長さ 10mm 程度の硬い塊になる。
#   置き場所: コネクタの口 (y39.6 側) から出た線を折り返し、**JST 嵌合体の真上**に 2 本
#   並べて寝かせる (Y方向)。ここは嵌合体上面 z6.1 からフタ内面まで allday 6.7 / slim 5.7mm
#   空いており、スイッチ端子 (y40.0〜)・LED (x8.1〜)・電池 (y〜28.2)・フタの lip (z 高い側) の
#   どれとも 0.3mm 以上離れる (check_layout の soft-part ループで全部品と総当たり)。
#   継ぎ目を置いてはいけない場所: XIAO の下 (基板が浮く) と、ストップリブの切れ目
#   (x14.4..17.25 / y35..40 = 電線が XIAO の下へ入る唯一の通り道)。
SPLICE_D, SPLICE_L = 2.5, 10.0                  # 継ぎ目 1 本の外径 x 長さ (熱収縮後)
harness_splice = ((harness_jst[0] + 0.3, harness_jst[1] + 0.3,
                   harness_jst[0] + 0.3 + 2 * SPLICE_D, harness_jst[3] - 0.3,
                   harness_jst[5] + 0.3, harness_jst[5] + 0.3 + SPLICE_D)
                  if harness_jst is not None else None)
# LED: 正面リッドの窓。左上ゾーン (スイッチの下、XIAOの左)
#   v1.5: 絶対値直書き (6.9, 36.0) をやめ相対値にした
#   (M_TOP/GAP_BX/電池厚を変えたときに窓だけ追従せず干渉する潜在バグの解消)。
#   v1.5 rev2: 基準を「リード曲げチャネル」から「JST 嵌合体の右端」に変更し、
#   x を 6.9 → 9.8 へ 2.9mm 右へ動かした。旧位置 (本体 x5.3..8.5) は JST 嵌合体の
#   真上で、90度に曲げた LED リード (本体下面から LED_LEAD_DROP 下がる = allday z5.8 /
#   slim z4.1) が JST 上端 z6.1 と slim で 1.0〜2.0mm 干渉していた (allday でも
#   3mm 曲げで 0.3mm)。左ポケットの y 方向では LED帯 (3.2mm) の上下どちらにも
#   嵌合体の 11.0mm が入らないため、**平面で逃げられる方向は x しかない**。
#   carrier では基板上の J1 嵌合体 (z3.2..10.7) が y34.8 まで来るため、窓を +1.0mm 上げる。
LED_WIN_FIT = 0.4                               # LED窓の径方向はめあい代 (φ3.0 → φ3.4)
#   FDM の穴は 0.1〜0.3mm 小さく出る (§5)。旧 φ3.2 では実効 2.9〜3.1mm となり
#   φ3.0 の LED が入らない個体が出る (磁石ポケットの MAG_FIT と同じ救済策)。
LED_LEAD_DROP = 3.0                             # 曲げた LED リードが本体下面から下がる量
LED_CLR_X = 0.8                                 # JST 嵌合体と LED リード帯の x 隙間
LED_WIN_R = LED_D / 2 + LED_WIN_FIT / 2         # 窓半径 1.7 (LED 本体は φ3.0)
LED_POS = (harness_jst_x1 + LED_CLR_X + (LED_D / 2 + 0.1),
           bat[3] + (8.8 if PCB == "carrier" else 7.8))     # (9.8, 36.0)
# v1.7: LED を沈めてリッド外面とほぼ面一にする (目立たない・襟や布に引っ掛からない)。
#   標準の 3mm 砲弾型はツバをリッド内面に当てるとドームが約 2.7mm 突出していた (README §9.4)。
#   リッド内面からスリーブを降ろし、ツバの座を LED_RECESS だけ下げてドーム先端を外面の
#   LED_SINK 内側に置く。沈めた分だけ LED 本体と 90度曲げのリード帯も深くなるため、
#   リード帯の下端が床 (WALL) から 0.3mm 以上残る範囲で沈め量を打ち切る
#   (slim は奥行きが浅く満額は入らない → ドームが少しだけ残る)。
#   副次効果: 穴の奥に光源があるので、正面以外の角度からは光がほぼ見えなくなる。
LED_PROTRUDE_STD = 2.7      # 標準3mm LED のドーム突出量 (ツバをリッド内面に当てた場合)
LED_SINK = 0.2              # 面一化後にドーム先端を外面から沈める量
LED_FLANGE_R, LED_FLANGE_T = 1.7, 0.5           # ツバ φ3.4 x 0.5 (OSR5JA3Z74A, v1.8 実測 M8)
#   実測のツバ φ3.4 は窓 (φ3.4) と同径で、ツバではスリーブ下端に止まらない個体がある。
#   組立は「フタを伏せ、ドーム先端が机に当たるまで押し込む」方式 (README 手順10-2) なので、
#   実際の LED はここでモデル化した位置 (ツバ上面 = スリーブ下端、ドーム先端が外面の
#   LED_SINK=0.2mm 内側) より最大 0.2mm フタ側 (z+) に付く。つまり led / led_flange /
#   led_leads の z は**リード帯が最も床・JST 側へ下がる最悪ケース**で、干渉検査は安全側。
_LED_LEAD_BOTTOM_STD = BODY_D - 4.0 - LED_LEAD_DROP
#   基板構成 (sense/carrier, v2・発注禁止の検討用) は LED の真下に J1 / 0805 部品が来るため
#   沈められない (沈めると led_flange<->pcb_j1 / led_leads<->pcb_smd_vbus が干渉する)。
#   v2 を実際に作る段階で基板側レイアウトと一緒に再検討する。
LED_RECESS = (round(max(0.0, min(LED_PROTRUDE_STD + LED_SINK,
                                 _LED_LEAD_BOTTOM_STD - WALL - 0.3)), 2)
              if PCB == "none" else 0.0)
LED_DOME_PROTRUDE = round(LED_PROTRUDE_STD - LED_RECESS, 2)   # 負 = 外面より内側
LED_SLEEVE_R = LED_WIN_R + 0.8                  # スリーブ外半径 2.5 (肉厚0.8 = 0.4ノズル2周)
led = (LED_POS[0] - 1.6, LED_POS[1] - 1.6, LED_POS[0] + 1.6, LED_POS[1] + 1.6,
       BODY_D - 4.0 - LED_RECESS, BODY_D)       # 本体 φ3.0 + 0.1、リッド内面から下
led_flange = (LED_POS[0] - LED_FLANGE_R, LED_POS[1] - LED_FLANGE_R,
              LED_POS[0] + LED_FLANGE_R, LED_POS[1] + LED_FLANGE_R,
              BODY_D - LED_RECESS - LED_FLANGE_T, BODY_D - LED_RECESS)
led_sleeve = ((LED_POS[0] - LED_SLEEVE_R, LED_POS[1] - LED_SLEEVE_R,
               LED_POS[0] + LED_SLEEVE_R, LED_POS[1] + LED_SLEEVE_R,
               BODY_D - LED_RECESS, BODY_D) if LED_RECESS > 0 else None)
# LED のリード帯 (90度に曲げたリード + 220Ω + はんだ継ぎ目 + 熱収縮の包絡)
#   none    : リードは -y (電池側) へ曲げ、電池上端 +0.4mm の線まで下ろしてよい。
#   sense/carrier: 基板上の J1・実装部品があるため -y へは下ろせない (LED の帯だけ)。
led_leads = (led[0], (bat[3] + 0.4) if PCB == "none" else led[1],
             led[2] + 0.4, led[3], led[4] - LED_LEAD_DROP, led[4])
# USB-C 開口: 右側面、XIAO 中央 (z は XIAO_LIFT に追従)
USB_CY = (xiao[1] + xiao[3]) / 2.0              # 38.3
USB_OPEN_W, USB_OPEN_H = 10.5, 4.8              # y方向 x z方向
# v1.8: USB-C 開口の中心を「スタック下面 (BAT パッド面) から 2.9mm」に置く (実測 M2: A4.50 − B3.20/2)。
USB_CENTER_ABOVE_STACK = 2.9
USB_Z0 = WALL + XIAO_LIFT + USB_CENTER_ABOVE_STACK - USB_OPEN_H / 2.0   # 3.5 (開口 z3.5..8.3)
USB_CB_W, USB_CB_H, USB_CB_D = 13.0, 8.0, 0.8   # プラグ逃がし座ぐり (オーバーモールド対応)
# マイク開口: 上面。Sense拡張ボード上面 (z=11.2) 近傍の高さに合わせる
MIC_Z = xiao[5] - 0.9                           # 10.3 (開口 z 9.55..11.05)
MIC_HOLE_R = 0.75                               # φ1.5
# 穴の x は XIAO 基板の左端 (USB と反対側の端 = xiao[0]) からの距離で持つ。
#   旧版は絶対値 22.0 / 25.5 / 29.0 の直書きで、設計時 (IW 34.8、XIAO x15.4..36.4) には
#   基板の長さ方向の中央 (10.5) ±3.5 の少し手前 = 左端から 6.6 / 10.1 / 13.6 だった。
#   IW を 36.8 に広げて XIAO が 2.0mm 右へ動いても穴だけ取り残されていたため相対値に改めた
#   (穴は +2.0mm 動いて x24.0 / 27.5 / 31.0)。
#   **拡張ボード上のマイクの実位置は未実測** (MEASUREMENTS.md M9)。測ったら中央の値を
#   実測値に書き換える (3 穴は ±3.5mm の振り分け)。
MIC_X_ON_BOARD = (6.6, 10.1, 13.6)              # 基板左端からの距離 : **assumption / 要実測 (M9)**
MIC_XS = tuple(round(xiao[0] + _mx, 6) for _mx in MIC_X_ON_BOARD)
# --- 内部リブ類 (AABB) ---
# XIAO コーナーシート (基板4隅の座面。ピン列カステレーション x16.1-31.3 を回避)
#   v1.3: 座標を xiao[0] 基準の相対値に変更 (IW を変えると絶対値がずれ、
#   シートとストップリブが干渉したため)。カステレーション帯は基板左端から
#   2.9〜18.1mm なので、その外側にリブを置く。
#   v1.5: y 側も絶対値 (29.5/32.0/44.6/47.1) をやめ xiao[1]/xiao[3] 相対にした。
#   旧版は GAP_BX / M_TOP を変えると座面だけが取り残され、
#   `INTERFERENCE: seat0 <-> xnub_b0` で assert が落ちた (pcb/LAYOUT.md §1.2 の指摘)。
_CAST_L = xiao[0] + 2.9                         # カステレーション帯 左端
_CAST_R = xiao[0] + 18.1                        # 同 右端
xiao_seats = [
    (xiao[0], xiao[1] + 0.1, xiao[0] + 2.5, xiao[1] + 2.6, WALL, WALL + XIAO_LIFT),
    (xiao[2] - 2.6, xiao[1] + 0.1, xiao[2], xiao[1] + 2.6, WALL, WALL + XIAO_LIFT),
    (xiao[0], xiao[3] - 2.6, xiao[0] + 2.5, xiao[3] - 0.1, WALL, WALL + XIAO_LIFT),
    (xiao[2] - 2.6, xiao[3] - 2.6, xiao[2], xiao[3] - 0.1, WALL, WALL + XIAO_LIFT),
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
# スイッチ両端の挟みリブ (本体の左右を 0.3mm のすきまで挟む)
#   v1.5: y0 の絶対値 44.6 を sw[1] 相対に変更 (IH を変えるとスイッチだけ動いて
#   リブが取り残されるため)。
#   v1.8: 右端のリブを追加。旧版は「右端は XIAO ストップリブが兼ねる」としていたが、
#   ストップリブは x14.4.. / y40..44 でスイッチ右端 (x12.7 / y44.5..) とは x も y も
#   離れており、実際には何も押さえていなかった (位置決めは上壁の凹み 0.7mm だけ)。
#   左と対称のリブを床から立てる (上壁とつながるのでサポート不要)。
sw_rib = (2.9, round(sw[1] - 0.4, 6), 3.7, WALL + IH, WALL, 8.4)
sw_rib_r = (sw[2] + 0.3, round(sw[1] - 0.4, 6), sw[2] + 1.1, WALL + IH, WALL, 8.4)
sw_ribs = [sw_rib, sw_rib_r]

# --- carrier: XIAO はキャリア基板に直はんだされるので、床から立つ XIAO 位置決めリブ
#     (座面/左ストップ/上下ナブ) とスイッチ挟みリブは基板と同じ空間を取り合う。
#     位置決めは「基板シェルフ + 取付ボス2本」に置き換え、スイッチは上壁の凹み
#     (深さ0.7・幅 sw+0.4) だけで横ずれを止める。pcb/LAYOUT.md §4 の障害物リストと一致。
if PCB == "carrier":
    xiao_seats, xiao_stops, xiao_nubs_top, xiao_nubs_bot, sw_ribs = [], [], [], [], []
# ---------------------------------------------------------------------------
# 基板 (v1.5) — 外形・実装部品の高さ・筐体側の保持フィーチャ
#   座標はすべて pcb/LAYOUT.md (gen_pcb.py が本ファイルを live import して決めた値)
#   と一致する。ここでは逆に「その基板が本当に入るか」を筐体側から検算し、
#   位置決め・保持・THT ピン逃げを筐体形状として実装する。
# ---------------------------------------------------------------------------
pcb = None              # 基板外形 AABB
pcb_j1 = None           # J1 (JST PH2.0) 嵌合体 AABB (基板上面から J1_BODY_Z)
pcb_parts = []          # 基板上の実装部品 (ラベル, AABB)。0805列 / ワイヤランド
pcb_guides = []         # 位置決めガイド壁 (床から立ち上がる)
pcb_ledges = []         # 抜け止め爪 (差し込み保持。基板上面の上に張り出す)
pcb_stops = []          # y- 側ストップナブ (爪から抜ける方向を止める)
pcb_shelf = []          # carrier: 基板の座 (h=PCB_SHELF)
pcb_bosses = []         # carrier: 取付ボス (φ1.8 ピン。基板の φ2.2 穴に通す)
pcb_reliefs = []        # THT ピン逃げ (床の座ぐり。cut する)
PCB_SMD_Z = 0.95        # 0805 (MLCC 含む) の最大実装高さ : assumption
PCB_WIRE_Z = 1.5        # ワイヤランド上のはんだ + AWG28 の盛り上がり : assumption
PCB_BOSS_D = 1.8        # 取付ボスのピン径 (基板穴 φ2.2 に対し片側 0.2 のクリアランス)
PCB_HOLE_D = 2.2        # 基板の取付穴径 (pcb/LAYOUT.md §5.2 MH1/MH2)

if PCB == "sense":
    # --- MC-SENSE-A: 左ポケット床置き ---------------------------------------
    # ポケット = 内壁 .. XIAO左ストップリブ / 電池上端 .. スイッチ挟みリブ
    _pk = (WALL, bat[3], xiao_stops[0][0], sw_rib[1])          # 1.6, 28.2, 12.4, 44.6
    # v1.6: 基板は固定物 (LAYOUT.md の 10.0×15.6)。ポケット寸法から導出すると
    # 筐体幅の変更で「基板が育つ」ため、外形を定数にして左壁アンカーで置く。
    pcb = (_pk[0] + PCB_CLR, _pk[1] + PCB_CLR,
           _pk[0] + PCB_CLR + 10.0, _pk[1] + PCB_CLR + 15.6, PCB_Z0, PCB_Z1)
    if not (pcb[2] <= _pk[2] - PCB_CLR + 1e-6 and pcb[3] <= _pk[3] - PCB_CLR + 1e-6):
        # v1.8: 実測スイッチ (本体高さ 4.0、旧仮定 3.5) でスイッチ挟みリブが 0.5mm 下がり、
        # ポケット高さが 15.9mm (必要 16.4mm) に縮んだ。sense は v2 の検討用 (発注禁止) なので、
        # 基板を実際に作る段階でスイッチ位置か基板外形と一緒に再設計する。
        raise SystemExit(
            f"MINDCLIP_PCB=sense: MC-SENSE-A (10.0x15.6) のポケットが不足 "
            f"(高さ {_pk[3] - _pk[1]:.1f}mm < 必要 {15.6 + 2 * PCB_CLR:.1f}mm)。"
            f"実測スイッチ (SW_H={SW_H}) では成立しない。v2 で再設計すること")
    # J1: (7.0, 31.6) rot180 / コートヤード 8.4 x 5.2 (gen_pcb.py fp_jst_ph2)
    pcb_j1 = (2.8, 29.0, 11.2, 34.2, PCB_Z1, PCB_Z1 + J1_BODY_Z)
    pcb_parts = [
        ("smd_vbus", (2.75, 34.25, 10.05, 37.15, PCB_Z1, PCB_Z1 + PCB_SMD_Z)),  # R2/R3/C2
        ("smd_vbat", (2.75, 37.75, 10.05, 40.65, PCB_Z1, PCB_Z1 + PCB_SMD_Z)),  # R4/R5/C1
        ("wire_j2", (2.70, 41.20, 10.30, 43.90, PCB_Z1, PCB_Z1 + PCB_WIRE_Z)),  # →XIAO 6本
    ]
    # 位置決め: 左=内壁 / 右=XIAO左ストップリブの側面 (x12.4) / 上=ガイド壁 / 下=ストップナブ
    _gz1 = PCB_Z1 + 0.6                                        # ガイド壁 上端 z3.0
    pcb_guides = [
        (WALL, _pk[3], sw_rib[0], _pk[3] + 1.0, WALL, _gz1),          # 上ガイド 左片
        (sw_rib[2], _pk[3], _pk[2], _pk[3] + 1.0, WALL, _gz1),        # 上ガイド 右片
    ]
    _lz0 = PCB_Z1 + PCB_GUIDE_GAP                              # 爪 下面 z2.65
    pcb_ledges = [
        (4.5, _pk[3] - PCB_LEDGE_OVH, 7.5, _pk[3], _lz0, _gz1),
        (9.0, _pk[3] - PCB_LEDGE_OVH, 12.0, _pk[3], _lz0, _gz1),
    ]
    # ストップナブ: 爪から基板が下 (y-) へ抜けるのを止める。電池の下 (z<3.0) に隠す。
    _sy1 = pcb[1]                                              # 28.6 (爪の掛かり 0.2 以上)
    pcb_stops = [
        (2.0, _sy1 - 1.0, 5.0, _sy1, WALL, WALL + BOSS_H),
        (9.0, _sy1 - 1.0, 12.0, _sy1, WALL, WALL + BOSS_H),
    ]
    # J1 の THT ピン (x6.0 / x8.0, y31.6, φ0.9) 逃げ。床に残る肉厚は MAG_WEB と同じ 0.8。
    pcb_reliefs = [(4.8, 30.2, 9.2, 33.0, WALL - J1_PIN_Z, WALL)]
    # v1.6: ポケット右端が基板右端より 0.5mm 広がったため、右側のガタ止めナブを追加。
    # J1 嵌合体 (y..34.2, z2.4..) と smd_vbus (x..10.05, z2.4..) を避けた位置・高さ。
    pcb_stops.append((pcb[2] + 0.1, 35.5, pcb[2] + 0.9, 38.5, WALL, WALL + BOSS_H))
elif PCB == "carrier":
    # --- MC-CARRIER-A: XIAO を載せるキャリア基板 -----------------------------
    # v1.6: 外形を定数 34.2×21.0 に固定・左アンカー (基板上の部品座標が絶対値のため)。
    # 右壁との隙間は 0.2→0.7 に増える。XIAO はキャリアに直はんだされ位置は基板が決める。
    pcb = (WALL + 0.4, bat[3] + 0.2, WALL + 0.4 + 34.2, bat[3] + 0.2 + 21.0,
           PCB_Z0, PCB_Z1)
    assert pcb[2] <= WALL + IW - 0.2 + 1e-6 and pcb[3] <= WALL + IH - 0.2 + 1e-6, (
        'MC-CARRIER-A does not fit cavity')
    # J1: (10.0, 32.2) rot180
    pcb_j1 = (5.8, 29.6, 14.2, 34.8, PCB_Z1, PCB_Z1 + J1_BODY_Z)
    pcb_parts = [
        ("smd_vbus", (2.75, 34.95, 10.05, 37.85, PCB_Z1, PCB_Z1 + PCB_SMD_Z)),  # R2/R3/C2
        ("smd_vbat", (2.75, 38.45, 10.05, 41.35, PCB_Z1, PCB_Z1 + PCB_SMD_Z)),  # R4/R5/C1
        ("smd_rled", (13.15, 34.95, 14.85, 37.85, PCB_Z1, PCB_Z1 + PCB_SMD_Z)),  # R1 220R
        ("wire_led", (12.80, 39.30, 15.20, 42.50, PCB_Z1, PCB_Z1 + PCB_WIRE_Z)),  # J3
        ("wire_sw", (12.80, 43.80, 15.20, 47.00, PCB_Z1, PCB_Z1 + PCB_WIRE_Z)),  # J2
        ("tp_row", (5.25, 46.25, 12.65, 47.75, PCB_Z1, PCB_Z1 + 0.2)),  # TP1..TP4
    ]
    # 基板の座 (シェルフ)。BATアクセス窓 (x25.8..35.8 / y32.9..44.9) と
    # J4 の B.Cu ジャンパランド (x23.7..25.7 / y37.2..40.6) と J1 の THT ピンを避ける。
    _sh = (WALL, PCB_Z0)
    pcb_shelf = [
        (pcb[0], pcb[1], pcb[0] + 4.0, pcb[1] + 3.2, *_sh),
        (pcb[0], pcb[3] - 3.4, pcb[0] + 4.0, pcb[3], *_sh),
        (16.0, pcb[1], 20.0, pcb[1] + 3.0, *_sh),
        (16.0, pcb[3] - 3.0, 20.0, pcb[3], *_sh),
        (30.5, pcb[1], pcb[2], pcb[1] + 3.0, *_sh),
        (30.5, pcb[3] - 3.4, pcb[2], pcb[3], *_sh),
        (20.5, 35.0, 22.5, 43.0, *_sh),
    ]
    # 取付ボス: MH1(3.4,31.0) / MH2(3.4,47.6)。φ1.8 ピンが基板の φ2.2 穴を貫通し、
    # USB-C 挿入反力 (5〜20N) をせん断で床へ逃がす。頭は基板上面 +0.6 まで出す。
    pcb_bosses = [(3.4, 31.0), (3.4, 47.6)]
    pcb_reliefs = [(7.0, 30.8, 13.0, 33.6, WALL - 0.4, WALL)]   # J1 の THT ピン逃げ

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
#   LIP_D (lip の挿入深さ 2.2) は先頭のパラメータ節で定義済み
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
# v1.5: 基板ありの構成は <variant>_<pcb> に分ける (既定 none は従来のパスのまま)
OUT_TAG = VARIANT if PCB == "none" else f"{VARIANT}_{PCB}"
STL_DIR = os.path.join(HW_DIR, "stl", OUT_TAG)
REN_DIR = os.path.join(HW_DIR, "renders", OUT_TAG)


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


def clearance(a, b):
    """2つの AABB の分離距離 (mm)。負なら 3軸すべてで重なっている = 干渉。
    各軸の分離量の最大値を返す (1軸でも離れていればその軸の隙間が最小距離の下界)。"""
    return max(max(b[0] - a[2], a[0] - b[2]),
               max(b[1] - a[3], a[1] - b[3]),
               max(b[4] - a[5], a[4] - b[5]))


def check_layout():
    boss_r = MAG_D / 2 + MAG_FIT / 2 + 1.5      # ボス外半径 4.7
    bosses = [(mx - boss_r, MAG_Y - boss_r, mx + boss_r, MAG_Y + boss_r,
               WALL - 1.2, WALL + BOSS_H) for mx in MAG_XS]
    parts = {
        "battery": bat, "xiao": xiao, "switch": sw, "led": led,
        "led_flange": led_flange,
        # v1.5 rev2: 「箱にならない部品」も AABB で持つ (これが無いと組立時にしか
        # 分からない干渉がすり抜ける)。sw_terms = スイッチ端子 + はんだ + 熱収縮、
        # led_leads = 90度に曲げた LED リード + 220Ω + 継ぎ目 + 熱収縮。
        "sw_terms": sw_terms, "led_leads": led_leads,
        "lip_left": lip_left, "lip_top": lip_top,
        "lip_bottom": lip_bottom, "lip_right": lip_right,
        "boss_L": bosses[0], "boss_R": bosses[1],
    }
    for i, b in enumerate(sw_ribs):
        parts[f"sw_rib{i}"] = b
    # --- 基板とその実装部品 / 保持フィーチャ (v1.5) ---
    for nm, b in (("pcb", pcb), ("pcb_j1", pcb_j1), ("harness_jst", harness_jst),
                  ("harness_splice", harness_splice)):
        if b is not None:
            parts[nm] = b
    for nm, b in pcb_parts:
        parts["pcb_" + nm] = b
    for i, b in enumerate(pcb_guides):
        parts[f"pcb_guide{i}"] = b
    for i, b in enumerate(pcb_ledges):
        parts[f"pcb_ledge{i}"] = b
    for i, b in enumerate(pcb_stops):
        parts[f"pcb_stop{i}"] = b
    for i, b in enumerate(pcb_shelf):
        parts[f"pcb_shelf{i}"] = b
    for i, (bx, by) in enumerate(pcb_bosses):
        r = PCB_BOSS_D / 2
        parts[f"pcb_boss{i}"] = (bx - r, by - r, bx + r, by + r,
                                 WALL, PCB_Z1 + 0.6)
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
    if led_sleeve is not None:
        parts["led_sleeve"] = led_sleeve
    # 意図的に接触/内包している組み合わせは除外
    allowed = {frozenset(p) for p in [
        ("battery", "boss_L"), ("battery", "boss_R"),   # ボス上面=バッテリー底 (接触)
        ("lip_left", "lip_bottom"), ("lip_bottom", "lip_right"),  # コーナー共有
        ("lip_left", "lip_top"),                                  # コーナー共有
        ("switch", "sw_terms"), ("led", "led_leads"),   # 部品と自分の端子/リード (連続)
        ("led", "led_flange"), ("led", "led_sleeve"),   # LED はツバと一体、スリーブを貫通
    ] + [(f"pcb_boss{i}", t) for i in range(len(pcb_bosses))
         for t in (["pcb"] + [f"pcb_shelf{j}" for j in range(len(pcb_shelf))])]}
    # ↑ 取付ボスは基板の φ2.2 穴を貫通し、シェルフと一体成型される (意図した内包)
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
    # スイッチ本体は「キャビティ + 上壁の位置決め凹み」の中に全軸で収まること。
    #   x / z は凹み (sw_recess_pocket) の内側、y は下端がキャビティ内・上端が凹みの底まで。
    #   (旧版は sw[3] をその定義式と比べるだけの恒真式だった)
    _rp = sw_recess_pocket
    assert _rp[0] >= WALL - 1e-6 and _rp[2] <= WALL + IW + 1e-6, "switch recess outside cavity (x)"
    assert _rp[4] >= WALL - 1e-6 and _rp[5] <= BODY_D + 1e-6, \
        "switch recess outside cavity (z): スイッチが床かフタ内面に当たる"
    assert (sw[0] >= _rp[0] + 0.1 - 1e-6 and sw[2] <= _rp[2] - 0.1 + 1e-6
            and sw[4] >= _rp[4] + 0.1 - 1e-6 and sw[5] <= _rp[5] - 0.1 + 1e-6), \
        "switch body does not fit the recess pocket (need 0.1mm/side)"
    assert sw[1] >= WALL - 1e-6 and sw[3] <= _rp[3] + 1e-6, "switch body outside cavity+recess (y)"
    assert abs((sw[3] - sw[1]) - SW_H) < 1e-6, "switch AABB height != SW_H"
    # 凹みを掘ったあとに残る上壁の肉厚 (外面 y=H まで)
    _top_left = H - _rp[3]
    assert _top_left >= 0.8 - 1e-6, f"top wall only {_top_left:.2f}mm at switch recess (<0.8)"
    # レバー (v1.8: SW_LEVER を初めて検査に使う)。本体上面 (= 凹みの底) から SW_LEVER 出る。
    #   外面からの突出が 1.5〜3.0mm: 短いと指が掛からず、長いと服に引っ掛かって勝手に切り替わる。
    _lever_out = (sw[3] + SW_LEVER) - H
    assert 1.5 - 1e-6 <= _lever_out <= 3.0 + 1e-6, (
        f"switch lever protrudes {_lever_out:.2f}mm beyond the top face (need 1.5..3.0)")
    #   スロット長 (スライド方向) >= レバー幅 + スライド量 + FDM 代 0.4。
    #   SW_LEVER_W は assumption (要実測 M6)。実測が 2.6mm を超えたら SW_SLOT_L を広げること。
    _slot_need = SW_LEVER_W + SW_TRAVEL + 0.4
    assert SW_SLOT_L >= _slot_need - 1e-6, (
        f"lever slot {SW_SLOT_L}mm < lever {SW_LEVER_W} + travel {SW_TRAVEL} + 0.4 = {_slot_need}")
    #   スロットは凹み (= スイッチ本体) の内側に収まる (本体の肩がスロットの縁に掛かって抜けない)
    assert SW_SLOT_L <= SW_L - 1.0 + 1e-6 and SW_SLOT_W <= SW_W - 1.0 + 1e-6, \
        "lever slot too large: switch body would not be retained"
    print(f"[layout] switch: lever {_lever_out:.2f} mm beyond top face | slot {SW_SLOT_L} >= "
          f"lever {SW_LEVER_W} (assumption) + travel {SW_TRAVEL} + 0.4 = {_slot_need:.1f} | "
          f"top wall left at recess {_top_left:.2f} mm")
    # スイッチ両端の挟みリブ: 本体の左右に 0.2〜0.5mm で対向し、y / z が本体と重なること
    if len(sw_ribs) >= 2:
        _gl, _gr = sw[0] - sw_ribs[0][2], sw_ribs[1][0] - sw[2]
        assert 0.2 - 1e-6 <= _gl <= 0.5 + 1e-6 and 0.2 - 1e-6 <= _gr <= 0.5 + 1e-6, \
            f"switch end ribs gap L {_gl:.2f} / R {_gr:.2f} out of 0.2..0.5"
        for _r in sw_ribs:
            assert _overlap1(_r[1], _r[3], sw[1], sw[3]) and _overlap1(_r[4], _r[5], sw[4], sw[5]), \
                "switch end rib does not face the switch body"
    # マイク穴: XIAO の幅の内側で、上ナブ (壁とつながったリブ) に塞がれない位置にあること
    for _hx in MIC_XS:
        assert xiao[0] + 1.0 <= _hx - MIC_HOLE_R and _hx + MIC_HOLE_R <= xiao[2] - 1.0, \
            f"mic hole x{_hx:.1f} is not over the XIAO"
        for _nb in xiao_nubs_top:
            assert not _overlap1(_hx - MIC_HOLE_R, _hx + MIC_HOLE_R, _nb[0], _nb[2]), \
                f"mic hole x{_hx:.1f} is blocked by a top nub"
    assert WALL + 0.5 <= MIC_Z - MIC_HOLE_R and MIC_Z + MIC_HOLE_R <= BODY_D - 0.5, \
        "mic holes too close to the back face / lid seam"
    print("[layout] mic holes (top wall, exit y%.1f): x %s = XIAO left edge + %s (assumption, M9) | "
          "z %.2f..%.2f" % (H, " / ".join(f"{x:.1f}" for x in MIC_XS),
                            " / ".join(f"{x:.1f}" for x in MIC_X_ON_BOARD),
                            MIC_Z - MIC_HOLE_R, MIC_Z + MIC_HOLE_R))
    # 磁石ウェブ (背面残し肉厚)
    pocket_bottom_z = WALL + BOSS_H - (MAG_T + 0.2)   # 3.0 - 2.2 = 0.8
    assert abs(pocket_bottom_z - MAG_WEB) < 1e-6, "magnet web != 0.8mm"
    # ボス上面 = バッテリー底 (支持)
    assert abs((WALL + BOSS_H) - bat[4]) < 1e-6, "battery not resting on bosses"
    # XIAO 裏面はんだ逃げ: 基板下面と床の間。ELECTRICAL.md §5.3 の実装要求は
    #   「はんだ盛り + AWG28 + カプトン で 1.0〜1.5mm 突出」。XIAO_LIFT=1.4 は
    #   その**最悪値 1.5 に対して 0.1mm 不足している**(意図的)。埋め合わせは
    #   「裏面で線を重ねない・はんだ盛りを低く抑える」という組立手順側の要求で行う
    #   (README §7 手順8)。ここは 1.2 ではなく実装値 1.4 を下限として固定する
    #   (旧版の 1.2 は実装値より緩く、リフトを下げても発火しない空の検査だった)。
    assert xiao[4] - WALL >= 1.4 - 1e-6, "no solder/wire relief under XIAO"
    # XIAO とリッド内面のクリアランス
    assert BODY_D - xiao[5] >= 0.5 - 1e-6, "XIAO stack too close to lid"
    # XIAO 横方向拘束: 左ストップリブの面が基板左端に 0.1-0.3mm で対向
    if xiao_stops:
        assert 0.1 <= xiao[0] - xiao_stops[0][2] <= 0.3, "XIAO left stop gap wrong"
    else:
        # carrier のみ: XIAO はキャリア基板に直はんだされるので床のストップリブが無い。
        # USB-C 挿入反力は 基板 → 取付ボス2本 + 基板左端〜内壁 で受ける (下の 6) で検査)。
        assert PCB == "carrier" and pcb is not None and len(pcb_bosses) >= 2, \
            "XIAO has no lateral restraint"
    # lip 帯と電池の非干渉。
    #   v1.4: 旧版は電池厚を 5.3mm 固定で検算しており、allday (8.0mm) では
    #   常に成立する空っぽの assert になっていた。実際の電池厚から判定する。
    #   z で逃げ切れる場合 (slim) はそれでよく、z が重なる場合 (allday) は
    #   左右の水平隙間が公差代 BAT_TOL 以上あることを要求する。
    _bat_top_worst = bat[4] + BAT_T + 0.3        # 厚め個体 (+0.3mm) を見込む
    _z_clear = (BODY_D - LIP_D) - _bat_top_worst
    if _z_clear < 0.4:
        assert lip_right[0] - bat[2] >= BAT_TOL - 1e-6, \
            (f"battery may hit right lip: gap {lip_right[0] - bat[2]:.2f}mm "
             f"< {BAT_TOL}mm (z clearance only {_z_clear:.2f}mm)")
        assert bat[0] - lip_left[2] >= BAT_TOL - 1e-6, \
            (f"battery may hit left lip: gap {bat[0] - lip_left[2]:.2f}mm "
             f"< {BAT_TOL}mm (z clearance only {_z_clear:.2f}mm)")
    # 左 lip 内面と電池のたわみ代 (スナップ嵌合に 0.35mm 必要 → 0.5mm 以上確保)
    assert bat[0] - lip_left[2] >= 0.5 - 1e-6, "no snap deflection room at battery"
    # 電池リード曲げチャネル (左端面出射、AWG28 x2)
    assert bat[0] - WALL >= 2.2 - 1e-6, "battery lead channel too narrow"
    # USB-C: レセプタクル先端 (基板右端 + USB_PROTRUDE) が外面より内側で、かつ座ぐりの底
    #   (外面 - USB_CB_D) より引っ込んでいないこと (引っ込むとプラグが奥まで届かない)。
    _usb_face = xiao[2] + USB_PROTRUDE
    assert W - USB_CB_D - 1e-6 <= _usb_face <= W + 1e-6, (
        f"USB-C receptacle face x{_usb_face:.2f} not between counterbore floor "
        f"x{W - USB_CB_D:.2f} and outer face x{W:.2f}")
    #   開口は XIAO の y 中心・実測の中心高さに合っており、body の肉の中に収まること
    assert abs(USB_CY - (xiao[1] + xiao[3]) / 2.0) < 1e-6, "USB opening not centred on the XIAO"
    assert abs((USB_Z0 + USB_OPEN_H / 2.0) - (xiao[4] + USB_CENTER_ABOVE_STACK)) < 1e-6, \
        "USB opening not at the measured connector centre"
    assert USB_Z0 >= WALL - 1e-6 and USB_Z0 + USB_OPEN_H <= BODY_D - 1.0 + 1e-6, \
        "USB opening cuts into the floor or leaves <1.0mm bridge under the lid"
    assert xiao[1] <= USB_CY - USB_OPEN_W / 2 and USB_CY + USB_OPEN_W / 2 <= xiao[3], \
        "USB opening wider than the XIAO board"
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
    # =======================================================================
    # v1.5: 基板まわりの検査 (既存の検査は一切弱めず、ここに追加のみ)
    # =======================================================================
    # --- 「箱にならない部品」の最小クリアランス (v1.5 rev2) --------------------
    #   旧版は harness_jst についてのみ、しかも **6部品に対して >= 0.0 (接触を合格)**
    #   という実質デッドコードだった。全部品との総当たりに変え、要求値も持たせる。
    _soft = [("harness_jst", 0.3), ("harness_splice", 0.3), ("sw_terms", 0.3),
             ("led_leads", 0.3 if PCB == "none" else 0.15)]
    for _sn, _need in _soft:
        if _sn not in parts:
            continue
        for _on, _ob in parts.items():
            if _on == _sn or frozenset((_sn, _on)) in allowed:
                continue
            _g = clearance(parts[_sn], _ob)
            assert _g >= _need - 1e-6, \
                f"{_sn} clearance to {_on} = {_g:.2f}mm < {_need}mm"
        # キャビティ内に収まること (壁を突き抜けない)
        _b = parts[_sn]
        assert (_b[0] >= WALL - 1e-6 and _b[2] <= WALL + IW + 1e-6
                and _b[1] >= WALL - 1e-6 and _b[3] <= WALL + IH + SW_RECESS + 1e-6
                and _b[4] >= WALL - 1e-6 and _b[5] <= BODY_D + 1e-6), \
            f"{_sn} outside cavity"
    if harness_jst is not None:
        # SCHEMATIC.md §5.5: JST 嵌合体は必ず Y方向。X方向 (5.8 と 11.0 を入替) だと
        # 利用可能幅 10.8mm を超えて xiao_stops[0] に当たることを毎回再現確認する。
        assert harness_jst[2] - harness_jst[0] < harness_jst[3] - harness_jst[1], \
            "harness JST must be laid along Y (SCHEMATIC.md §5.5)"
        assert harness_jst[2] <= xiao_stops[0][0] - 0.2 + 1e-6, \
            "harness JST hits XIAO left stop rib"
        _rot = (harness_jst[0], harness_jst[1],
                harness_jst[0] + HARNESS_JST_XYZ[1], harness_jst[1] + HARNESS_JST_XYZ[0],
                harness_jst[4], harness_jst[5])
        # v1.6: 内寸幅 34.8→35.8 の拡大で X置きも幾何的には成立するようになった
        # (クリアランス約0.6mm)。Y置きは「唯一の可能解」ではなく「採用した慣例」に
        # 変わったため、不成立を主張する旧 assert は撤去し、状況をログに残すだけにする。
        # 組立ガイド・SCHEMATIC §5.5・本CADのガイド形状はすべて Y置き前提のままであり、
        # X置きへ変更する場合はそれら一式を更新すること。
        _xg = clearance(_rot, xiao_stops[0])
        print(f"[harness] X-laid JST clearance to xiao stop: {_xg:.2f}mm "
              f"({'geometrically viable but NOT the documented placement' if _xg >= 0.3 else 'not viable'})")
        # 旧配置 (y31.0..42.0) に戻すと必ずスイッチ端子と当たること = 回帰テスト
        _old_y = (harness_jst[0], 31.0, harness_jst[2], 42.0,
                  harness_jst[4], harness_jst[5])
        assert clearance(_old_y, sw_terms) < 0.3, \
            "regression: the old y31..42 placement must clash with the switch terminals"
        # 天井余裕: 嵌合体の上に電線の曲げ代 (J1_BEND_Z) が要る。
        #   LED を x 方向へ逃がしたことで、この帯の天井は「LED本体の下面」ではなく
        #   「リッド内面」になった (旧配置での上限は allday 7.20 / slim 5.50mm だった)。
        _jst_need = harness_jst[5] + J1_BEND_Z
        assert _jst_need <= BODY_D + 1e-6, (
            f"JST mated body + wire bend {_jst_need:.2f} > lid inner {BODY_D:.2f}")
        _jst_max = BODY_D - WALL - J1_BEND_Z
        print(f"[harness] mated body height limit (floor-laid) = {_jst_max:.2f}mm "
              f"(actual {HARNESS_JST_XYZ[2]:.2f} = assumption / 要実測)")
        print(f"[harness] JST(Y-laid) x{harness_jst[0]:.2f}..{harness_jst[2]:.2f} / "
              f"y{harness_jst[1]:.2f}..{harness_jst[3]:.2f} / "
              f"z{harness_jst[4]:.2f}..{harness_jst[5]:.2f}  "
              f"min clearance: sw_terms {clearance(harness_jst, sw_terms):.2f} / "
              f"led_leads {clearance(harness_jst, led_leads):.2f} / "
              f"battery {clearance(harness_jst, bat):.2f} / "
              f"ceiling {BODY_D - harness_jst[5]:.2f}mm")
    if harness_splice is not None:
        # 継ぎ目は JST 嵌合体の真上 (同じ x / y の範囲内) に載り、リッド内面より下に収まる
        _sp = harness_splice
        assert (_sp[0] >= harness_jst[0] - 1e-6 and _sp[2] <= harness_jst[2] + 1e-6
                and _sp[1] >= harness_jst[1] - 1e-6 and _sp[3] <= harness_jst[3] + 1e-6
                and _sp[4] >= harness_jst[5] + 0.3 - 1e-6), "splice joints must lie on top of the JST body"
        assert _sp[3] - _sp[1] >= SPLICE_L - 1e-6 and _sp[2] - _sp[0] >= 2 * SPLICE_D - 1e-6, \
            "no room for two splice joints on the JST body"
        assert BODY_D - _sp[5] >= 0.5 - 1e-6, "splice joints too close to the lid"
        # 置いてはいけない場所 (XIAO の下 / ストップリブの切れ目) と重ならない
        _under_xiao = (xiao[0], xiao[1], xiao[2], xiao[3], WALL, xiao[4])
        _rib_gap = (xiao_stops[0][0], xiao_stops[0][3], xiao_stops[0][2], xiao_stops[1][1],
                    WALL, BODY_D)
        assert clearance(_sp, _under_xiao) >= 1.0 and clearance(_sp, _rib_gap) >= 1.0, \
            "splice joints sit under the XIAO or in the stop-rib gap"
        _others = {n: clearance(_sp, b) for n, b in parts.items() if n != "harness_splice"}
        _nn = min(_others, key=_others.get)
        print(f"[harness] splice joints (2 x phi{SPLICE_D} x {SPLICE_L:.0f}, on top of the JST) "
              f"x{_sp[0]:.2f}..{_sp[2]:.2f} / y{_sp[1]:.2f}..{_sp[3]:.2f} / z{_sp[4]:.2f}..{_sp[5]:.2f}  "
              f"nearest part: {_nn} {_others[_nn]:.2f}mm | ceiling {BODY_D - _sp[5]:.2f}mm")
        # M4 (嵌合体の実測) の合否に使う上限。継ぎ目を真上に載せる標準手順での値:
        #   高さ: 継ぎ目 (0.3 + SPLICE_D) を載せても、リッド内面 -0.5 と左 lip 下端 -0.3 の低い方に収まる
        #   長さ: 上端がスイッチ端子の帯 (sw_terms) の 0.3mm 手前まで
        #   幅  : LED 窓の x が嵌合体の幅に追従する (HARNESS_JST_XYZ[0] を変えると lid が変わる)
        _h_max = min(BODY_D - 0.5, lip_left[4] - 0.3) - (0.3 + SPLICE_D) - WALL
        _l_max = sw_terms[1] - 0.3 - harness_jst[1]
        assert HARNESS_JST_XYZ[2] <= _h_max + 1e-6 and HARNESS_JST_XYZ[1] <= _l_max + 1e-6
        print(f"[harness] M4 limits for the mated JST body (splice on top): height <= {_h_max:.1f} mm, "
              f"length <= {_l_max:.1f} mm, width = {HARNESS_JST_XYZ[0]:.1f} mm (LED window follows it)")
        print(f"[harness] wire passage under the XIAO: stop-rib gap x{_rib_gap[0]:.2f}..{_rib_gap[2]:.2f} / "
              f"y{_rib_gap[1]:.2f}..{_rib_gap[3]:.2f}, lift {xiao[4] - WALL:.2f}mm (wire OD <= 1.3)")
    if pcb is not None:
        pw, ph = pcb[2] - pcb[0], pcb[3] - pcb[1]
        cav = (WALL, WALL, WALL + IW, WALL + IH, WALL, BODY_D)
        # 1) キャビティ収容と外形寸法 (pcb/LAYOUT.md の値と一致すること)
        assert (pcb[0] >= cav[0] and pcb[2] <= cav[2] and pcb[1] >= cav[1]
                and pcb[3] <= cav[3] and pcb[4] >= cav[4] and pcb[5] <= cav[5]), \
            "PCB outside cavity"
        _want = {"sense": (10.0, 15.6), "carrier": (34.2, 21.0)}[PCB]
        assert abs(pw - _want[0]) < 1e-6 and abs(ph - _want[1]) < 1e-6, \
            f"PCB outline {pw:.2f}x{ph:.2f} != LAYOUT.md {_want}"
        assert abs((pcb[5] - pcb[4]) - PCB_T) < 1e-6, "PCB thickness mismatch"
        # 2) 電池・磁石ボス・リッドlip とのクリアランス (コードで恒久保証)
        for nm, need in (("battery", 0.2), ("boss_L", 0.5), ("boss_R", 0.5),
                         ("lip_left", 0.3), ("lip_bottom", 0.3), ("lip_right", 0.3),
                         ("lip_top", 0.3), ("lidrib0", 0.3), ("lidrib1", 0.3)):
            g = clearance(pcb, parts[nm])
            assert g >= need - 1e-6, \
                f"PCB clearance to {nm} = {g:.2f}mm < {need}mm"
        # 3) 背の高い実装部品 (J1 嵌合体 / 0805 / ワイヤランド) の周辺クリアランス
        for hn in ["pcb_j1"] + ["pcb_" + n for n, _ in pcb_parts]:
            hb = parts[hn]
            for nm, need in (("battery", 0.2), ("led", 0.15), ("switch", 0.2),
                             ("lip_left", 0.3), ("lip_top", 0.3), ("xiao", 0.2)):
                if nm not in parts:
                    continue
                g = clearance(hb, parts[nm])
                assert g >= need - 1e-6, \
                    f"{hn} clearance to {nm} = {g:.2f}mm < {need}mm"
            assert hb[5] <= BODY_D + 1e-6, f"{hn} top z={hb[5]:.2f} > lid inner {BODY_D}"
        # 4) J1 の天井余裕 = 嵌合体 + 電線曲げ代 (pcb/LAYOUT.md §4.2 と同じ判定)
        _need_z = pcb_j1[5] + J1_BEND_Z
        assert _need_z <= BODY_D + 1e-6, (
            f"J1 mated body + wire bend {_need_z:.2f} > lid inner {BODY_D:.2f} "
            f"(need ID +{_need_z - BODY_D:.2f}mm)")
        # 5) THT ピン逃げ座ぐりを引いた後の床の残し肉厚 (磁石ウェブと同じ 0.8 以上)
        for r in pcb_reliefs:
            assert r[4] >= MAG_WEB - 1e-6, \
                f"PCB pin relief leaves only {r[4]:.2f}mm floor (< {MAG_WEB})"
            assert r[5] <= WALL + 1e-6, "PCB pin relief must stay under the floor face"
        # 6) 保持機構
        if PCB == "sense":
            # 位置決めクリアランス (片側) が公差代 0.3〜0.5 に収まる。
            # v1.6: 右側はポケット壁でなく「右ガタ止めナブ」(pcb_stops末尾) が位置決めを
            # 担うため、右のみナブ内面までの距離で判定する。
            _right_stop_x = min(s[0] for s in pcb_stops if s[0] > pcb[2] - 1e-6)
            for g in (pcb[0] - _pk[0], _right_stop_x - pcb[2],
                      pcb[1] - _pk[1], _pk[3] - pcb[3]):
                assert 0.05 - 1e-6 <= g <= 0.5 + 1e-6, \
                    f"PCB pocket clearance {g:.2f}mm out of range"
            # ガイド壁は基板厚を越えて立つ (基板が乗り上げない)
            for gd in pcb_guides:
                assert gd[5] >= PCB_Z1 + 0.4 - 1e-6, "PCB guide wall too low"
            # 抜け止め爪: 下面は基板上面より上、掛かりしろ 0.2mm 以上を常に確保
            for ld in pcb_ledges:
                assert ld[4] >= PCB_Z1 + 0.1 - 1e-6, "ledge would clamp the PCB"
                assert ld[4] - PCB_Z1 <= 0.4 + 1e-6, "ledge gap too large (rattle)"
            _engage_min = (pcb_stops[0][3] + ph) - (_pk[3] - PCB_LEDGE_OVH)
            assert _engage_min >= 0.2 - 1e-6, \
                f"ledge engagement can drop to {_engage_min:.2f}mm"
            # 差し込み成立条件: 上端を爪の下へ押し込んだとき下端がストップナブを越える
            _slide = (_pk[3] - ph) - pcb_stops[0][3]
            assert _slide >= 0.3 - 1e-6, \
                f"cannot slide PCB under the ledges (only {_slide:.2f}mm)"
        if PCB == "carrier":
            # XIAO はキャリア基板の上に載る (床からのリフト = シェルフ + 基板厚)
            assert abs(xiao[4] - PCB_Z1) < 1e-6, "XIAO must sit on the carrier PCB"
            assert abs(XIAO_LIFT - (PCB_SHELF + PCB_T)) < 1e-6, "XIAO_LIFT mismatch"
            # 取付ボスは基板の穴に対し片側 0.2mm 以上のクリアランス
            assert (PCB_HOLE_D - PCB_BOSS_D) / 2 >= 0.2 - 1e-6, "boss too tight"
            # ボスは基板面より上に頭を出す (位置決め + 溶着/接着代)
            for i in range(len(pcb_bosses)):
                assert parts[f"pcb_boss{i}"][5] >= PCB_Z1 + 0.4 - 1e-6, "boss too short"
            # USB-C 挿入反力 (-x) の受け: 基板左端と内壁の隙間
            assert pcb[0] - WALL <= 0.5 + 1e-6, "carrier PCB can slide too far in -x"
            # 基板は全シェルフに載る (シェルフは基板の外へはみ出さない)
            for i, s in enumerate(pcb_shelf):
                assert (s[0] >= pcb[0] - 1e-6 and s[2] <= pcb[2] + 1e-6
                        and s[1] >= pcb[1] - 1e-6 and s[3] <= pcb[3] + 1e-6), \
                    f"shelf{i} sticks out of the PCB"
                assert abs(s[5] - PCB_Z0) < 1e-6, f"shelf{i} height != PCB_Z0"
        print(f"[pcb] {PCB}: {pw:.1f} x {ph:.1f} x {PCB_T:.1f}t at "
              f"x{pcb[0]:.2f}..{pcb[2]:.2f} / y{pcb[1]:.2f}..{pcb[3]:.2f} / "
              f"z{pcb[4]:.2f}..{pcb[5]:.2f}")
        print(f"[pcb] J1 mated top z={pcb_j1[5]:.2f} + bend {J1_BEND_Z} = "
              f"{_need_z:.2f} <= lid inner {BODY_D:.2f} "
              f"(margin {BODY_D - _need_z:.2f}mm)")
        if PCB == "carrier":
            # carrier では XIAO 下端ナブ (＝v1 の電池上端ストップ) が基板に置き換わる。
            # 電池の y 公差がそのまま基板下端との隙間 (0.20mm) を食う。
            print(f"[pcb] warn: battery top edge to PCB edge = "
                  f"{clearance(pcb, parts['battery']):.2f}mm only. "
                  f"y方向の電池ストップは基板端になるため、高さ 25.0+0.2mm を超える"
                  f"個体は使わないこと (v1 の xiao_nubs_bot は carrier で消える)")
        if PCB == "sense" and BODY_D - _need_z < 0.4:
            print(f"[pcb] warn: J1 天井余裕 {BODY_D - _need_z:.2f}mm。"
                  f"{VARIANT} は非推奨 (LAYOUT.md §4.2: MC-SENSE-A は allday 専用)")
    # =======================================================================
    # 既定パラメータでの外形を直接固定する (v1.5 rev2 で追加)
    #   ID / IH は部品寸法 (XIAO_STACK_T, BAT_T, J1_BODY_Z ...) から計算される
    #   ため、assumption を書き換えると **assert を一つも出さずに外形だけが育つ**
    #   という穴があった (MECHANICAL.md §11.4 の「負のテスト」が自己充足的だった原因)。
    #   公開値と食い違ったら必ず落ちるようにし、落ちたら MECHANICAL.md §1 / §11.1 と
    #   README §6 の寸法を更新してからでないと STL を出せないようにする。
    GOLDEN_OUTER = {
        # v1.8: 実測 (電池 32mm → 幅 +1.0 / XIAO 8.2mm → slim の奥行き +0.7) を反映。
        #       sense は実測スイッチで成立しないため対象外 (モジュール読み込み時に SystemExit)。
        #       carrier も基板外形が IW 36.8 に追従していないため対象外 (同じく SystemExit)。
        #       → 実行できるのは次の 2 構成だけ。
        ("allday", "none"): (40.0, 49.4, 14.6),
        ("slim", "none"): (40.0, 49.4, 13.6),
    }
    assert (VARIANT, PCB) in GOLDEN_OUTER, (
        f"[{VARIANT}/{PCB}] は公開寸法を持たない構成 (sense / carrier は v2 で再設計するまで実行不可)")
    _g = GOLDEN_OUTER[(VARIANT, PCB)]
    assert (abs(W - _g[0]) < 1e-6 and abs(H - _g[1]) < 1e-6
            and abs(TOTAL_D - _g[2]) < 1e-6), (
        f"outer {W:.2f} x {H:.2f} x {TOTAL_D:.2f} != published "
        f"{_g[0]} x {_g[1]} x {_g[2]} for [{VARIANT}/{PCB}]. "
        f"assumption (XIAO_STACK_T={XIAO_STACK_T} / BAT_T={BAT_T} / "
        f"J1_BODY_Z={J1_BODY_Z}) を変えたなら MECHANICAL.md §1・§11.1 と "
        f"README §6 の寸法を更新してから GOLDEN_OUTER を書き換えること")
    # v1.7: LED を沈めたぶん深くなったリード帯が床に届かないこと (沈め量の打ち切り条件そのもの)
    assert led_leads[4] >= WALL + 0.3 - 1e-6, (
        f"LED lead band bottom z={led_leads[4]:.2f} < floor+0.3 ({WALL + 0.3:.2f}); "
        f"LED_RECESS={LED_RECESS} が深すぎる")
    print(f"[layout] LED recess {LED_RECESS:.2f} mm -> dome "
          + (f"{-LED_DOME_PROTRUDE:.2f} mm below lid face" if LED_DOME_PROTRUDE <= 0
             else f"protrudes {LED_DOME_PROTRUDE:.2f} mm ("
                  + ("variant depth limit" if PCB == "none" else "PCB config: not recessed")
                  + ")"))
    # 左ポケットの各部品の実座標 (README 手順10 の配置図・MECHANICAL.md の表はこの行から転記する)
    for _n in ("battery", "xiao", "switch", "sw_terms", "harness_jst", "harness_splice",
               "led", "led_leads", "led_flange", "led_sleeve", "sw_rib0", "sw_rib1",
               "xstop0", "xstop1", "lip_left", "lip_top"):
        if _n in parts:
            _b = parts[_n]
            print(f"[box] {_n:15s} x{_b[0]:6.2f}..{_b[2]:6.2f}  y{_b[1]:6.2f}..{_b[3]:6.2f}  "
                  f"z{_b[4]:6.2f}..{_b[5]:6.2f}")
    print("[layout] all interference checks passed")
    print(f"[layout] outer: {W:.1f} x {H:.1f} x {TOTAL_D:.1f} mm (W x H x D, lid込み) "
          f"= published value")


# ---------------------------------------------------------------------------
# XIAO 右上コーナーの逃げ (ソリッド検査)
# ---------------------------------------------------------------------------
XIAO_CORNER_RELIEF = 0.15       # 角ばった基板 (R=0) でも右上の角に残すすきま
# 切り欠き = XIAO の輪郭を y+ へ XIAO_CORNER_RELIEF 広げた箱の右上部分。
#   キャビティの直線部ではもともと空間なので、実際に肉が削れるのはコーナー R の内側だけ。
xiao_corner_relief = (xiao[2] - R_IN - 0.5, xiao[3] - R_IN - 0.5,
                      xiao[2], xiao[3] + XIAO_CORNER_RELIEF,
                      xiao[4], BODY_D + 0.5)
XIAO_CORNER_WALL_MIN = 0.8      # 逃げの最深部に残す外壁の最小肉厚 (0.4 ノズル 2 周)


def xiao_solid(corner_r, grow_y=0.0):
    """XIAO スタックの占有ソリッド。corner_r=0 なら四角、>0 なら基板コーナーを丸める。
    grow_y は上辺 (y+) 側だけを広げる量 (すきまの検査用)。"""
    w, h = xiao[2] - xiao[0], xiao[3] - xiao[1] + grow_y
    wp = (cq.Workplane("XY", origin=((xiao[0] + xiao[2]) / 2, xiao[1] + h / 2, xiao[4]))
          .rect(w, h).extrude(xiao[5] - xiao[4]))
    if corner_r > 0:
        wp = wp.edges("|Z").fillet(corner_r)
    return wp


def check_xiao_fit(body):
    """body と XIAO のソリッド同士のブーリアン (AABB では見えないコーナー R の食い込みを検出)。
      1) 想定形状 (コーナー R = XIAO_CORNER_R) の XIAO が body と重ならない
      2) R=0 の四角い基板でも重ならず、上辺を XIAO_CORNER_RELIEF 広げても重ならない
         (= 右上の角に 0.15mm 以上のすきま。コーナー R が未実測でも成立する)
      3) 陽性対照: 逃げを切る前の形状相当 (四角い基板を右上へ 0.5mm ずらす) は必ず重なる
      4) 逃げの最深部に残る外壁の肉厚 >= XIAO_CORNER_WALL_MIN
    右内壁と基板右端・座面と基板下面は設計上の接触面 (体積 0) なので重なりに数えない。"""
    def vol(wp):
        r = body.intersect(wp)
        return sum(s.Volume() for s in r.solids().vals())
    v_round = vol(xiao_solid(XIAO_CORNER_R))
    v_sq = vol(xiao_solid(0.0))
    v_sq_clr = vol(xiao_solid(0.0, grow_y=XIAO_CORNER_RELIEF))
    assert v_round < 1e-3, f"XIAO (corner R{XIAO_CORNER_R}) overlaps the body by {v_round:.3f} mm3"
    assert v_sq < 1e-3, f"square-cornered XIAO overlaps the body by {v_sq:.3f} mm3"
    assert v_sq_clr < 1e-3, (
        f"square-cornered XIAO has < {XIAO_CORNER_RELIEF}mm clearance at the top-right "
        f"cavity corner ({v_sq_clr:.3f} mm3 overlap)")
    v_pos = vol(xiao_solid(0.0).translate(cq.Vector(0.5, 0.5, 0)))
    assert v_pos > 1e-2, "positive control failed: a shifted XIAO must hit the body"
    # 逃げの最深点 (切り欠きの右上の角) から外形コーナー円弧までの肉厚
    _ox, _oy = W - R_OUT, H - R_OUT
    _px, _py = xiao_corner_relief[2], xiao_corner_relief[3]
    wall = R_OUT - math.hypot(_px - _ox, _py - _oy) if (_px > _ox and _py > _oy) \
        else min(W - _px, H - _py)
    assert wall >= XIAO_CORNER_WALL_MIN - 1e-6, (
        f"outer wall at the XIAO corner relief is {wall:.2f}mm (< {XIAO_CORNER_WALL_MIN})")
    print(f"[xiao] solid fit: overlap round(R{XIAO_CORNER_R}) {v_round:.3f} / square {v_sq:.3f} / "
          f"square+{XIAO_CORNER_RELIEF} {v_sq_clr:.3f} mm3 (positive control {v_pos:.2f} mm3) | "
          f"outer wall at relief corner {wall:.2f} mm (min; elsewhere >= 1.6)")


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
    # v1.5: 基板の位置決めガイド壁・抜け止め爪・ストップナブ・キャリア基板シェルフを追加
    for rb in (xiao_seats + xiao_stops + xiao_nubs_top + xiao_nubs_bot
               + bat_stops_left + bat_stops_bot + sw_ribs
               + pcb_guides + pcb_ledges + pcb_stops + pcb_shelf):
        body = body.union(cq.Workplane(obj=bbox_solid(rb)))
    # 基板取付ボス (φ1.8 ピン。基板の φ2.2 穴を貫通して x/y を決め、USB-C 反力を受ける)
    for bx, by in pcb_bosses:
        body = body.union(cq.Workplane(obj=cq.Solid.makeCylinder(
            PCB_BOSS_D / 2, PCB_Z1 + 0.6 - WALL, cq.Vector(bx, by, WALL))))
    # THT ピン逃げ (床の座ぐり。残し肉厚は check_layout で MAG_WEB 以上を保証)
    for rb in pcb_reliefs:
        body = body.cut(cq.Workplane(obj=bbox_solid(rb)))
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
    body = body.cut(cq.Workplane(obj=bbox_solid(sw_recess_pocket)))
    sw_cx = (sw[0] + sw[2]) / 2
    sw_cz = (sw[4] + sw[5]) / 2
    body = body.cut(cq.Workplane(obj=bbox_solid(
        (sw_cx - SW_SLOT_L / 2, WALL + IH + SW_RECESS - 0.1, sw_cx + SW_SLOT_L / 2, H + 0.5,
         sw_cz - SW_SLOT_W / 2, sw_cz + SW_SLOT_W / 2))))  # スロット 5.0 x 2.2
    # マイク開口 (上面、XIAO 上方に φ1.5 x 3。Sense拡張ボード上面高さに合わせる)
    #   x は XIAO 左端からの相対値 MIC_X_ON_BOARD (assumption / 要実測 M9)
    for hx in MIC_XS:
        body = body.cut(cq.Workplane(
            obj=cq.Solid.makeCylinder(MIC_HOLE_R, WALL + 1.0,
                                      cq.Vector(hx, WALL + IH - 0.2, MIC_Z),
                                      cq.Vector(0, 1, 0))))
    # XIAO 右上コーナーの逃げ (v1.8)。XIAO は右内壁に密着・上内壁から M_TOP=0.6 の位置に
    #   居るので、基板の右上の角はキャビティのコーナー R (R_IN=2.5) の肉に食い込む
    #   (角ばった箱でブーリアンすると数 mm3 の重なりが出る。AABB 検査では見えなかった)。
    #   基板のコーナー R (XIAO_CORNER_R) は未実測なので、R=0 の四角い基板でも上側に
    #   XIAO_CORNER_RELIEF のすきまが残るよう、基板の輪郭 +0.15 (y+) をそのまま切り欠く。
    #   座面 (コーナーシート, z<=WALL+XIAO_LIFT) は残す。検査は check_xiao_fit (ソリッド)。
    body = body.cut(cq.Workplane(obj=bbox_solid(xiao_corner_relief)))
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
    # LED スリーブ (v1.7): ツバの座をリッド内面から LED_RECESS 下げる筒。
    #   外面を下にして印刷するので筒はベッドから真上に立ち、サポート不要。
    if LED_RECESS > 0:
        lid = lid.union(cq.Workplane(obj=cq.Solid.makeCylinder(
            LED_SLEEVE_R, LED_RECESS + 0.5,
            cq.Vector(LED_POS[0], LED_POS[1], BODY_D - LED_RECESS))))
    # LED 窓 (φ3.4 = LED_D + LED_WIN_FIT の貫通。LEDは内側から挿してツバをスリーブ下端に当てる)
    lid = lid.cut(cq.Workplane(
        obj=cq.Solid.makeCylinder(LED_WIN_R, LID_T + LED_RECESS + 1.0,
                                  cq.Vector(LED_POS[0], LED_POS[1],
                                            BODY_D - LED_RECESS - 0.5))))
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
# strapplate (v1.7: カバンのショルダーストラップ用マウント)
# ---------------------------------------------------------------------------
# 磁石クランプ (body + backplate で布を挟む) は布越しの磁力で保持するため、厚さ 3〜5mm の
# ストラップでは磁石間距離が開きすぎて留まらない (README §9.7)。そこで:
#   - ストラップは板の 2 本のスロットに「編み込む」(トライグライド = コキカン と同じ原理)。
#     チェスト側 → 上スロット → 中央バーの上 (本体側のポケット内) → 下スロット → チェスト側。
#     S 字の摩擦で位置が固定され、ストラップ上をずり落ちない。
#   - 本体は板のリム (周囲の低い壁) に嵌まり、横方向の力はリムが受ける。
#   - 本体と板の間に布が無いので磁力は最大 (磁石間 = 本体ウェブ 0.8 + 板側の沈み 0.2)。
#     板はストラップに付けたまま、本体だけ磁石で着脱する (夜の充電時に外す)。
# 座標: 板中心 = 原点 (backplate と同じ流儀)。z=0 がチェスト側 (ベッド面)、z=SP_T が本体側。
# ストラップ寸法は環境変数で上書きできる (MEASUREMENTS.md の M7 で実測した値を入れる)。
STRAP_W = float(os.environ.get("MINDCLIP_STRAP_W", "38.0"))  # 通せる最大ストラップ幅
STRAP_T = float(os.environ.get("MINDCLIP_STRAP_T", "2.5"))   # 通せる最大ストラップ厚
SP_RIM_CLR = 0.3            # 本体外形とリム内面の片側すきま (FDM 公差)
SP_RIM_W = 1.2              # リム肉厚 (0.4 ノズル 3 周)
SP_RIM_H = 2.5              # リム高さ。本体背面の R1.0 を越えて直線部に 1.5mm 掛かる
SP_BAR_T = 2.2              # 中央バー (ラダー層) の厚さ
SP_POCKET_D = round(STRAP_T + 0.4, 2)          # 本体側ポケットの深さ (ストラップが本体を押さない)
SP_T = round(SP_BAR_T + SP_POCKET_D, 2)        # 板厚 (リム除く)
SP_SLOT_H = round(STRAP_T + 1.5, 2)            # スロット幅 (y)。ストラップが曲がって通る代
SP_CBAR_H = 5.0             # 中央バーの幅 (y)
SP_SLOT_L = round(STRAP_W + 1.0, 2)            # スロット長 (x)
SP_END_WALL = 1.5           # スロット端の残し肉
SP_MAG_MARGIN = 2.0         # 磁石ポケットと編み込み帯の間の残し肉
SP_OUT_W = W + 2 * (SP_RIM_CLR + SP_RIM_W)     # リム外形 (= 本体 + 3.0)
SP_OUT_H = H + 2 * (SP_RIM_CLR + SP_RIM_W)
SP_W = max(SP_OUT_W, SP_SLOT_L + 2 * SP_END_WALL)
SP_H = SP_OUT_H
SP_R = R_OUT + SP_RIM_CLR + SP_RIM_W
_SP_MAG_R = MAG_D / 2 + MAG_FIT / 2
SP_MAGS = [(mx - CX, MAG_Y - H / 2) for mx in MAG_XS]       # 本体の磁石と同軸
# 編み込み帯 (下スロット / 中央バー / 上スロット) は磁石の上に置く
SP_YB0 = round(max(my for _, my in SP_MAGS) + _SP_MAG_R + SP_MAG_MARGIN, 2)
SP_YA1 = round(SP_YB0 + 2 * SP_SLOT_H + SP_CBAR_H, 2)
SP_SLOTS = [(SP_YB0, SP_YB0 + SP_SLOT_H), (SP_YA1 - SP_SLOT_H, SP_YA1)]
# USB-C 座ぐりの前でリムを切り欠く (板に付けたままでも充電ケーブルが挿さる)
SP_USB_NOTCH = (USB_CY - H / 2 - USB_CB_W / 2 - 0.5, USB_CY - H / 2 + USB_CB_W / 2 + 0.5)
# 切り欠きの z 範囲 (板座標)。リムの全高 (SP_T .. SP_T+SP_RIM_H) を上下 0.5mm 余分に抜く
SP_USB_NOTCH_Z = (SP_T - 0.5, SP_T + SP_RIM_H + 0.5)


def check_strapplate():
    """strapplate の寸法整合。ストラップ寸法を変えたときに壊れる箇所を全部ここで止める。"""
    if STRAP_W > W - 1.0 + 2 * SP_RIM_CLR + 1e-6:
        raise SystemExit(
            f"MINDCLIP_STRAP_W={STRAP_W} は本体幅 {W:.1f}mm を超えるため、ポケットが本体で"
            f"覆えずリムも切れる。{W - 1.0 + 2 * SP_RIM_CLR:.1f}mm までのストラップ用の設計です "
            f"(幅広・クッション入りのリュック肩ベルトは別形状が必要)")
    assert 1.0 <= STRAP_T <= 4.0, f"MINDCLIP_STRAP_T={STRAP_T} は想定範囲 (1.0〜4.0mm) 外"
    # スロット端の肉 (ラダーのバーを両端で支える)
    assert (SP_W - SP_SLOT_L) / 2 >= SP_END_WALL - 1e-6, "strap slot end wall too thin"
    # ポケットは本体の外形内 (本体が蓋になる) かつリム内面より内側
    assert SP_SLOT_L / 2 <= W / 2 + SP_RIM_CLR + 1e-6, "strap pocket wider than rim opening"
    # 磁石ポケットと編み込み帯が重ならない
    for mx, my in SP_MAGS:
        assert my + _SP_MAG_R + SP_MAG_MARGIN <= SP_YB0 + 1e-6, "magnet pocket overlaps strap band"
        assert my - _SP_MAG_R >= -H / 2 + 1.0, "magnet pocket too close to plate edge"
    # 本体を支える上側の当たり面 (外側バーを兼ねる) が十分に残る
    top_land = H / 2 - SP_YA1
    assert top_land >= 6.0 - 1e-6, f"top support land only {top_land:.1f}mm (<6.0)"
    # 帯が本体の直線部 (コーナーR の外) に収まり、ポケットの上を本体の平面が完全に覆う
    assert SP_YA1 <= H / 2 - R_OUT + 1e-6 and SP_YB0 >= -H / 2 + R_OUT - 1e-6, \
        "strap band reaches the body's corner radius"
    # 磁石の下に残る肉 (チェスト側)
    assert SP_T - (MAG_T + 0.2) >= 1.6 - 1e-6, "too little material under strap-plate magnets"
    # リムはスイッチの帯より下で止まる
    assert SP_RIM_H <= sw[4] - 1.0 + 1e-6, "rim reaches the switch band"
    # USB 座ぐりとリムの関係。v1.8 で開口が 0.3mm 下がり、座ぐり下端 (本体 z1.9) は
    # リム上端 (本体 z2.5) より**低く**なった。つまりリムは座ぐりの下 0.6mm ぶんと高さが重なる。
    # それでもプラグが挿さるのは「リムを座ぐりの前で全高にわたって切り欠いている」からで、
    # 保証しているのは次の 2 点 (リムが座ぐりより低いこと、ではない):
    #   (a) 切り欠きの y 範囲が座ぐりの y 範囲を両側 0.5mm 以上の余裕で含む
    #   (b) 切り欠きの z 範囲がリムの全高を含む (リムが座ぐりの前に 1 層も残らない)
    # 形状としての確認 (切り欠きの中に肉が無いこと) は check_strapplate_fit のブーリアンで行う。
    usb_cb_z0 = USB_Z0 + USB_OPEN_H / 2.0 - USB_CB_H / 2
    _cb_y = (USB_CY - H / 2 - USB_CB_W / 2, USB_CY - H / 2 + USB_CB_W / 2)
    assert SP_USB_NOTCH[0] <= _cb_y[0] - 0.5 + 1e-6 and SP_USB_NOTCH[1] >= _cb_y[1] + 0.5 - 1e-6, \
        "USB notch does not span the counterbore in y (need 0.5mm each side)"
    assert SP_USB_NOTCH_Z[0] <= SP_T + 1e-6 and SP_USB_NOTCH_Z[1] >= SP_T + SP_RIM_H - 1e-6, \
        "USB notch does not span the full rim height"
    assert -SP_OUT_H / 2 + SP_RIM_W < SP_USB_NOTCH[0] and SP_USB_NOTCH[1] < SP_OUT_H / 2 - SP_RIM_W, \
        "USB notch runs into the rim corners"
    _ovl = SP_RIM_H - usb_cb_z0
    print(f"[strap] plate {SP_W:.1f} x {SP_H:.1f} x {SP_T:.1f} mm (+rim {SP_RIM_H}) | "
          f"strap <= {STRAP_W:.0f} x {STRAP_T:.1f} mm (width limit {W - 1.0 + 2 * SP_RIM_CLR:.1f}) | "
          f"band y {SP_YB0:.1f}..{SP_YA1:.1f} | top land {top_land:.1f} mm")
    print(f"[strap] USB: counterbore bottom z{usb_cb_z0:.1f} (body) vs rim top z{SP_RIM_H} -> "
          + (f"rim overlaps the counterbore by {_ovl:.1f} mm in height; " if _ovl > 0
             else "rim is below the counterbore; ")
          + f"cleared by the full-height rim notch y{SP_USB_NOTCH[0]:.1f}..{SP_USB_NOTCH[1]:.1f} "
            f"(counterbore y{_cb_y[0]:.1f}..{_cb_y[1]:.1f}, plate coords)")


def check_strapplate_fit(body, sp):
    """本体を板に載せた実形状で検査する (AABB ではなくソリッドのブーリアン)。
    陰性対照だけだと「リムが存在しない」場合も通ってしまうため、横にずらした本体が
    リムに当たること (陽性対照) も必ず確かめる。"""
    def overlap(dx, dy):
        r = body.translate(cq.Vector(-CX + dx, -H / 2 + dy, SP_T)).intersect(sp)
        return sum(s.Volume() for s in r.solids().vals())
    seated = overlap(0.0, 0.0)
    assert seated < 1e-3, f"body interferes with strap plate when seated ({seated:.3f} mm3)"
    shift = SP_RIM_CLR + 0.3        # すきまを超える横ずれ → リムに当たらなければならない
    for dx, dy in ((shift, 0), (-shift, 0), (0, shift), (0, -shift)):
        v = overlap(dx, dy)
        assert v > 1e-3, f"rim does not stop a {shift:.1f}mm shift at ({dx:+.1f},{dy:+.1f})"
    # USB 座ぐりの前 (座ぐりの y 範囲 x リム全高) にリムの肉が残っていないこと
    _cb_y = (USB_CY - H / 2 - USB_CB_W / 2, USB_CY - H / 2 + USB_CB_W / 2)
    _front = cq.Workplane(obj=bbox_solid(
        (W / 2, _cb_y[0], SP_OUT_W / 2 + 1.0, _cb_y[1], SP_T + 0.01, SP_T + SP_RIM_H + 1.0)))
    _rim_left = sum(s.Volume() for s in sp.intersect(_front).solids().vals())
    assert _rim_left < 1e-3, f"rim material left in front of the USB counterbore ({_rim_left:.3f} mm3)"
    # 陽性対照: 反対側 (左辺) の同じ位置にはリムがある
    _back = cq.Workplane(obj=bbox_solid(
        (-SP_OUT_W / 2 - 1.0, _cb_y[0], -W / 2, _cb_y[1], SP_T + 0.01, SP_T + SP_RIM_H + 1.0)))
    assert sum(s.Volume() for s in sp.intersect(_back).solids().vals()) > 1.0, \
        "positive control failed: rim missing on the side opposite the USB notch"
    print(f"[strap] fit: seated overlap 0, rim stops a {shift:.1f} mm shift in all 4 directions, "
          f"no rim in front of the USB counterbore")


def build_strapplate():
    sp = rounded_slab(SP_W, SP_H, SP_R, SP_T, 0, 0, 0)
    sp = sp.edges("<Z").fillet(1.0)                 # チェスト側の縁 (ストラップ・服に当たる)
    # リム: 本体外形 + すきま の内側を抜いたリング。USB 前を切り欠いてから結合する
    ring = rounded_slab(SP_OUT_W, SP_OUT_H, SP_R, SP_RIM_H, 0, 0, SP_T)
    ring = ring.cut(rounded_slab(W + 2 * SP_RIM_CLR, H + 2 * SP_RIM_CLR,
                                 R_OUT + SP_RIM_CLR, SP_RIM_H + 1.0, 0, 0, SP_T - 0.5))
    # 上端の面取りは切り欠き前の単純なリングにだけ掛ける (切り欠き後に掛けると OCC が
    # 不正なソリッドを返し、union で黙ってリムが消える。v1.7 開発時に実際に起きた)
    ring = ring.edges(">Z").fillet(0.4)
    ring = ring.cut(cq.Workplane(obj=bbox_solid(
        (W / 2 - 1.0, SP_USB_NOTCH[0], SP_OUT_W / 2 + 1.0, SP_USB_NOTCH[1],
         SP_USB_NOTCH_Z[0], SP_USB_NOTCH_Z[1]))))
    assert ring.val().isValid(), "strap-plate rim solid is invalid"
    sp = sp.union(ring)
    _bb = sp.val().BoundingBox()
    assert sp.val().isValid() and abs(_bb.zmax - (SP_T + SP_RIM_H)) < 1e-3, (
        f"strap-plate rim missing after union (top z={_bb.zmax:.2f}, "
        f"expected {SP_T + SP_RIM_H:.2f})")
    # 本体側ポケット (ストラップが中央バーの上を通る空間。本体が蓋になる)
    sp = sp.cut(cq.Workplane(obj=bbox_solid(
        (-SP_SLOT_L / 2, SP_YB0, SP_SLOT_L / 2, SP_YA1, SP_BAR_T, SP_T + 0.5))))
    # スロット 2 本 (ラダー層を貫通)
    for y0, y1 in SP_SLOTS:
        sp = sp.cut(cq.Workplane(obj=bbox_solid(
            (-SP_SLOT_L / 2, y0, SP_SLOT_L / 2, y1, -0.5, SP_BAR_T + 0.5))))
    # 磁石ポケット (本体側から圧入、上面から 0.2 沈める。backplate と同じ深さ)
    for mx, my in SP_MAGS:
        sp = sp.cut(cq.Workplane(obj=cq.Solid.makeCylinder(
            _SP_MAG_R, MAG_T + 0.2 + 0.5, cq.Vector(mx, my, SP_T - MAG_T - 0.2))))
    return sp


# ---------------------------------------------------------------------------
# magsafeplate (v1.10: スマホ背面の MagSafe に付ける取り付け板)
# ---------------------------------------------------------------------------
# 板のスマホ側の面に市販の「貼り付け式 MagSafe 磁石リング」を沈めて貼り、反対の面に本体を
# strapplate と同じリム + 磁石 2 個で載せる。本体は服用・カバン用と共通のまま付け替えられる。
# 座標: 板中心 = 原点 = リング中心 = 本体中心。z=0 がスマホ側 (ベッド面)、z=MS_T が本体側。
# リングは製品ごとに寸法が違うため環境変数で合わせる (買ったリングをノギスで測って入れる)。
MS_RING_OD = float(os.environ.get("MINDCLIP_MS_RING_OD", "54.9"))   # リング外径 (ESR HaloLock 2Z515 実測)
MS_RING_ID = float(os.environ.get("MINDCLIP_MS_RING_ID", "46.1"))   # リング内径 (外径 − 輪の幅 4.4 x 2)
MS_RING_T = float(os.environ.get("MINDCLIP_MS_RING_T", "0.6"))      # リング厚 (粘着層込み、実測)
MS_RING_FIT = 0.5           # 溝の径方向の余裕 (片側 0.25)
MS_RING_PROUD = 0.1         # リングを板の面からわずかに出す (磁石面を確実にケースへ当てる)
MS_WEB = 1.0                # リング溝の天井 / 磁石ポケットの底に残す肉
MS_EDGE = 1.0               # リング溝の外側に残す壁。iPhone 17 Pro + MagSafe ケースの実測で
#   リング上端〜カメラ台座 (段差 4mm) のすき間が 3mm しかないため細くしてある
MS_CAMERA_GAP = 3.0         # リング外周からカメラ台座までのすき間 (実測)
MS_T = round(max(MS_RING_T - MS_RING_PROUD, MAG_T + 0.2) + MS_WEB, 2)   # 板厚 (リム除く)
MS_DISC_R = round(MS_RING_OD / 2 + MS_RING_FIT / 2 + MS_EDGE, 2)        # 円板の半径


def check_magsafeplate():
    assert MS_RING_ID < MS_RING_OD and 0.3 <= MS_RING_T <= 3.5, "MagSafe ring dims out of range"
    # 本体用の磁石ポケットはリングの内側に収まる (溝と平面で重ならない = 板厚を足さずに済む)
    for mx, my in SP_MAGS:
        r = math.hypot(mx, my) + _SP_MAG_R
        assert r + 0.8 <= MS_RING_ID / 2 - MS_RING_FIT / 2 + 1e-6, (
            f"body magnet pocket (r={r:.1f}) overlaps the MagSafe ring groove "
            f"(inner r={MS_RING_ID / 2:.1f})")
    assert MS_RING_PROUD < MS_RING_T, "ring thinner than its protrusion"
    # 正立時、板の最上端 (円板) と本体の座の上辺がカメラ台座に 1.5mm 以上届かないこと
    _cam = MS_RING_OD / 2 + MS_CAMERA_GAP
    _top = max(MS_DISC_R, SP_OUT_H / 2)
    assert _cam - _top >= 1.5 - 1e-6, (
        f"plate top {_top:.1f} is within 1.5mm of the camera plateau at {_cam:.1f}")
    print(f"[magsafe] clearance to camera plateau when upright: {_cam - _top:.2f} mm")
    print(f"[magsafe] plate dia {2 * MS_DISC_R:.1f} + body nest {SP_OUT_W:.1f} x {SP_OUT_H:.1f}, "
          f"thickness {MS_T:.1f} (+rim {SP_RIM_H}) | ring {MS_RING_OD:.0f}/{MS_RING_ID:.0f} x "
          f"{MS_RING_T:.1f} | stack on phone case: {MS_T + MS_RING_PROUD + TOTAL_D:.1f} mm")


def build_magsafeplate():
    # 円板 (リングを抱える) と角丸矩形 (本体の座) の和。本体の四隅は円板からはみ出すため。
    ms = (cq.Workplane("XY").circle(MS_DISC_R).extrude(MS_T)
          .union(rounded_slab(SP_OUT_W, SP_OUT_H, SP_R, MS_T, 0, 0, 0)))
    ring = rounded_slab(SP_OUT_W, SP_OUT_H, SP_R, SP_RIM_H, 0, 0, MS_T)
    ring = ring.cut(rounded_slab(W + 2 * SP_RIM_CLR, H + 2 * SP_RIM_CLR,
                                 R_OUT + SP_RIM_CLR, SP_RIM_H + 1.0, 0, 0, MS_T - 0.5))
    ring = ring.edges(">Z").fillet(0.4)             # 切り欠き前に掛ける (strapplate と同じ理由)
    ring = ring.cut(cq.Workplane(obj=bbox_solid(
        (W / 2 - 1.0, SP_USB_NOTCH[0], SP_OUT_W / 2 + 1.0, SP_USB_NOTCH[1],
         MS_T - 0.5, MS_T + SP_RIM_H + 0.5))))
    assert ring.val().isValid(), "magsafe-plate rim solid is invalid"
    ms = ms.union(ring)
    # MagSafe リングの溝 (スマホ側の面から)。天井は幅 5mm 強の環状ブリッジで、サポート不要
    depth = MS_RING_T - MS_RING_PROUD
    groove = (cq.Workplane("XY").workplane(offset=-0.5)
              .circle(MS_RING_OD / 2 + MS_RING_FIT / 2)
              .circle(MS_RING_ID / 2 - MS_RING_FIT / 2).extrude(depth + 0.5))
    ms = ms.cut(groove)
    for mx, my in SP_MAGS:                          # 本体用の磁石 (本体側から圧入)
        ms = ms.cut(cq.Workplane(obj=cq.Solid.makeCylinder(
            _SP_MAG_R, MAG_T + 0.2 + 0.5, cq.Vector(mx, my, MS_T - MAG_T - 0.2))))
    _bb = ms.val().BoundingBox()
    assert ms.val().isValid() and abs(_bb.zmax - (MS_T + SP_RIM_H)) < 1e-3, \
        "magsafe-plate rim missing after union"
    return ms


def check_magsafeplate_fit(body, ms):
    """strapplate と同じ実形状検査: 載せて干渉 0、横ずれはリムが止める (陽性対照)。"""
    def overlap(dx, dy):
        r = body.translate(cq.Vector(-CX + dx, -H / 2 + dy, MS_T)).intersect(ms)
        return sum(s.Volume() for s in r.solids().vals())
    assert overlap(0.0, 0.0) < 1e-3, "body interferes with magsafe plate when seated"
    shift = SP_RIM_CLR + 0.3
    for dx, dy in ((shift, 0), (-shift, 0), (0, shift), (0, -shift)):
        assert overlap(dx, dy) > 1e-3, f"magsafe rim does not stop a shift at ({dx:+.1f},{dy:+.1f})"
    print(f"[magsafe] fit: seated overlap 0, rim stops a {shift:.1f} mm shift in all 4 directions")


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
def export_all():
    os.makedirs(STL_DIR, exist_ok=True)
    os.makedirs(REN_DIR, exist_ok=True)
    check_layout()

    print("[build] body ...")
    body = build_body()
    check_xiao_fit(body)
    print("[build] lid ...")
    lid = build_lid()
    print("[build] backplate ...")
    backplate = build_backplate()
    check_strapplate()
    print("[build] strapplate ...")
    strapplate = build_strapplate()
    check_strapplate_fit(body, strapplate)
    check_magsafeplate()
    print("[build] magsafeplate ...")
    magsafeplate = build_magsafeplate()
    check_magsafeplate_fit(body, magsafeplate)

    paths = {}
    for name, wp in (("body", body), ("lid", lid), ("backplate", backplate),
                     ("strapplate", strapplate), ("magsafeplate", magsafeplate)):
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
        if name not in ("strapplate", "magsafeplate"):   # backplate と差し替える別マウント (合算しない)
            total_print_mass += mass
        print(f"[verify] {name}: watertight={m.is_watertight}  "
              f"volume={m.volume/1000.0:.2f} cm3  mass(PETG)={mass:.1f} g  "
              f"tris={len(m.faces)}")
        assert m.is_watertight, f"{name} STL is not watertight"
    _bat_g = 11.0 if VARIANT == "allday" else 10.0   # allday: 採用品の実測 11g (M3) / slim: 公称
    comp_mass = _bat_g + 5.0 + 4 * 0.44 + 1.0  # 電池+XIAOスタック+磁石+SW/LED/配線
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
    fig.suptitle(f"MindClip DIY — orthographic views (mm) [{OUT_TAG}] / mic port &"
                 " switch on top, USB-C on right side", fontsize=11)
    fig.savefig(os.path.join(REN_DIR, "views.png"), bbox_inches="tight")
    plt.close(fig)
    print("[render] views.png")

    # ---- internal.png (蓋なし内部レイアウト) ----
    fig = plt.figure(figsize=(9, 9), dpi=140)
    ax = fig.add_subplot(111, projection="3d")
    C_PCB = (0.10, 0.42, 0.25)
    C_CON = (0.92, 0.92, 0.92)
    comp = [
        (f"{BAT_LABEL} ({BAT_W:.0f}x{BAT_H:.0f}x{BAT_T:.0f})", bat, C_BAT),
        ("XIAO ESP32S3 Sense stack", xiao, C_XIAO),
        ("slide switch SS-12D00", sw, C_SW),
    ]
    # v1.5: 基板と背の高い実装部品 / 基板なし構成の JST 嵌合体
    if pcb is not None:
        comp.append((f"PCB {PCB}", pcb, C_PCB))
        comp.append(("J1 mated", pcb_j1, C_CON))
        comp += [(f"pcb {n}", b, C_PCB) for n, b in pcb_parts]
    if harness_jst is not None:
        comp.append(("JST mated body", harness_jst, C_CON))
    if harness_splice is not None:
        comp.append(("splice joints + shrink", harness_splice, (0.95, 0.80, 0.35)))
    # v1.5 rev2: 端子・曲げリードの包絡 (「箱にならない部品」)
    comp.append(("switch terminals + shrink", sw_terms, (0.85, 0.55, 0.45)))
    comp.append(("LED leads + 220R + shrink", led_leads, (0.90, 0.62, 0.62)))
    ledm = trimesh.creation.cylinder(radius=1.5, height=4.0, sections=24)
    ledm.apply_transform(tf(LED_POS[0], LED_POS[1], BODY_D - 2.0 - LED_RECESS))
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
    _sub = {"none": "harness (no PCB) — JST mated body + splice joints on top of it shown",
            "sense": "MC-SENSE-A satellite PCB 10.0x15.6x0.8t in the left pocket",
            "carrier": "MC-CARRIER-A carrier PCB 34.2x21.0x0.8t (XIAO soldered on it)"}[PCB]
    ax.set_title(f"MindClip DIY — internal layout (lid removed)\n{_sub}", fontsize=10)
    fig.savefig(os.path.join(REN_DIR, "internal.png"), bbox_inches="tight")
    plt.close(fig)
    print("[render] internal.png")

    # ---- pcb_pocket.png (基板ポケットの平面詳細 / 保持機構) ----
    import matplotlib.patches as mpatches
    fig, (axp, axs) = plt.subplots(1, 2, figsize=(13, 7), dpi=140,
                                   gridspec_kw={"width_ratios": [1.35, 1]})

    def rect(ax, b, fc, ec, lw=1.0, hatch=None, a=1.0, ij=(0, 1)):
        i, j = ij
        lo = (b[[0, 1, 4][i] if i < 2 else 4], b[[0, 1, 4][j] if j < 2 else 4])
        return None

    def add(ax, b, fc, ec="black", a=1.0, hatch=None, lw=0.9, plane="xy"):
        if plane == "xy":
            x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
        else:                                   # "xz" 断面
            x0, y0, x1, y1 = b[0], b[4], b[2], b[5]
        ax.add_patch(mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0,
                                        facecolor=fc, edgecolor=ec, alpha=a,
                                        hatch=hatch, linewidth=lw, zorder=2))

    def label(ax, b, txt, plane="xy", dy=0.0, fs=7, ha="center"):
        if plane == "xy":
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        else:
            cx, cy = (b[0] + b[2]) / 2, (b[4] + b[5]) / 2
        ax.text(cx, cy + dy, txt, fontsize=fs, ha=ha, va="center", zorder=6)

    cavity_b = (WALL, WALL, WALL + IW, WALL + IH, WALL, BODY_D)
    add(axp, (0, 0, W, H, 0, BODY_D), "#e9eef3", "#5a6b7a", lw=1.4)
    add(axp, cavity_b, "#ffffff", "#5a6b7a", lw=1.2)
    add(axp, bat, "#e8c84a", "#8a7420", a=0.85)
    label(axp, bat, f"LiPo {BAT_W:.0f}x{BAT_H:.0f}x{BAT_T:.0f}", fs=8)
    add(axp, xiao, "#3d9960", "#1f5c37", a=0.85)
    label(axp, xiao, "XIAO", fs=8)
    add(axp, sw, "#d05a4a", "#7a2a20", a=0.8)
    for rb in (xiao_seats + xiao_stops + xiao_nubs_top + xiao_nubs_bot
               + bat_stops_left + bat_stops_bot + sw_ribs):
        add(axp, rb, "#b9c6d2", "#5a6b7a", lw=0.6)
    for rb in pcb_shelf:
        add(axp, rb, "#8fa8bd", "#3f5668", lw=0.6)
    for rb in pcb_guides:
        add(axp, rb, "#7f96c9", "#33456f", lw=0.8)
    for rb in pcb_stops:
        add(axp, rb, "#7f96c9", "#33456f", lw=0.8)
    for rb in pcb_reliefs:
        add(axp, rb, "none", "#c0392b", lw=1.0, hatch="///")
    if pcb is not None:
        add(axp, pcb, "#1f6f3f", "#0d3a20", a=0.55)
        label(axp, (pcb[0], pcb[1], pcb[2], pcb[1] + 3.0), f"PCB {PCB}\n"
              f"{pcb[2]-pcb[0]:.1f} x {pcb[3]-pcb[1]:.1f} x {PCB_T:.1f}t", fs=8)
        add(axp, pcb_j1, "#f2f2f2", "#444444", a=0.95)
        label(axp, pcb_j1, "J1", fs=8)
        for n, b in pcb_parts:
            add(axp, b, "#cfa227", "#6b5310", a=0.9, lw=0.5)
        for rb in pcb_ledges:
            add(axp, rb, "#2f4f9f", "#12224a", lw=0.8)
    if harness_jst is not None:
        add(axp, harness_jst, "#f2f2f2", "#444444", a=0.95)
        label(axp, harness_jst, "JST mated body\n(Y-laid, §5.5)\n+ splice joints\non top\n"
              f"x{harness_jst[0]:.1f}-{harness_jst[2]:.1f}\n"
              f"y{harness_jst[1]:.1f}-{harness_jst[3]:.1f}", fs=6)
    if harness_splice is not None:
        add(axp, harness_splice, "none", "#b8860b", lw=1.0, hatch="||")
    add(axp, sw_terms, "none", "#c0392b", lw=1.0, hatch="xx")
    label(axp, sw_terms, "switch terminals\n+ solder + shrink", fs=6)
    add(axp, led_leads, "none", "#e03030", lw=1.0, hatch="..")
    label(axp, led_leads, "LED leads\n+ 220R", fs=6, dy=-3.0)
    add(axp, led, "#e03030", "#7a1010", a=0.5)
    label(axp, led, "LED", fs=7)
    for b in (lip_left, lip_top, lip_bottom, lip_right):
        add(axp, b, "none", "#8e44ad", lw=0.8, a=0.9)
    for _hx in MIC_XS:      # マイク穴 (上壁を貫通)
        axp.plot([_hx, _hx], [WALL + IH, H], color="#1f4e79", lw=2.0, zorder=5)
    axp.text(MIC_XS[1], H + 0.6, "mic ports x3", fontsize=6, ha="center", zorder=6)
    axp.set_xlim(-2, W + 2)
    axp.set_ylim(-2, H + 2)
    axp.set_aspect("equal")
    axp.set_title(f"left-pocket plan (XY) — {OUT_TAG}\n"
                  "blue = PCB retention (guide / ledge / stop), "
                  "red hatch = THT pin relief / lead envelopes, "
                  "gold || = splice joints, purple = lid lip", fontsize=9)
    axp.set_xlabel("x [mm]", fontsize=8)
    axp.set_ylabel("y [mm]", fontsize=8)
    axp.tick_params(labelsize=7)

    # --- 右: z 方向のスタック断面 (高さ予算) ---
    axs.set_title("height budget (XZ section through the pocket)", fontsize=9)
    add(axs, (0, 0, W, H, 0, BODY_D + LID_T), "#e9eef3", "#5a6b7a",
        lw=1.4, plane="xz")
    add(axs, (WALL, 0, WALL + IW, 0, WALL, BODY_D), "#ffffff", "#5a6b7a",
        lw=1.2, plane="xz")
    add(axs, (WALL, 0, WALL + IW, 0, BODY_D, BODY_D + LID_T), "#dfe7ee",
        "#5a6b7a", lw=1.0, plane="xz")
    add(axs, bat, "#e8c84a", "#8a7420", a=0.85, plane="xz")
    add(axs, xiao, "#3d9960", "#1f5c37", a=0.85, plane="xz")
    for rb in pcb_shelf + pcb_guides + pcb_stops:
        add(axs, rb, "#7f96c9", "#33456f", lw=0.6, plane="xz")
    for rb in pcb_reliefs:
        add(axs, rb, "none", "#c0392b", lw=1.0, hatch="///", plane="xz")
    if pcb is not None:
        add(axs, pcb, "#1f6f3f", "#0d3a20", a=0.8, plane="xz")
        add(axs, pcb_j1, "#f2f2f2", "#444444", a=0.95, plane="xz")
        label(axs, pcb_j1, "J1 mated\n7.5", plane="xz", fs=7)
        bend = (pcb_j1[0], 0, pcb_j1[2], 0, pcb_j1[5], pcb_j1[5] + J1_BEND_Z)
        add(axs, bend, "none", "#c0392b", lw=1.0, hatch="\\\\\\", plane="xz")
        label(axs, bend, f"wire bend {J1_BEND_Z}", plane="xz", fs=7)
        for n, b in pcb_parts:
            add(axs, b, "#cfa227", "#6b5310", a=0.9, lw=0.5, plane="xz")
        for rb in pcb_ledges:
            add(axs, rb, "#2f4f9f", "#12224a", lw=0.8, plane="xz")
        axs.axhline(BODY_D, color="#c0392b", lw=1.0, ls="--")
        axs.text(W + 0.5, BODY_D, f" lid inner z={BODY_D:.2f}", fontsize=7,
                 va="center", color="#c0392b")
        axs.text(0.02, 0.97,
                 f"J1 head-room margin {BODY_D - (pcb_j1[5] + J1_BEND_Z):+.2f} mm",
                 fontsize=8, va="top", ha="left", color="#c0392b",
                 transform=axs.transAxes)
    add(axs, sw_terms, "none", "#c0392b", lw=0.8, hatch="xx", plane="xz")
    add(axs, led_leads, "none", "#e03030", lw=0.8, hatch="..", plane="xz")
    if harness_jst is not None:
        add(axs, harness_jst, "#f2f2f2", "#444444", a=0.95, plane="xz")
        label(axs, harness_jst, "JST mated\n(loose, on floor)", plane="xz", fs=7)
        _bend = (harness_jst[0], 0, harness_jst[2], 0,
                 harness_jst[5], harness_jst[5] + J1_BEND_Z)
        add(axs, _bend, "none", "#c0392b", lw=1.0, hatch="\\\\\\", plane="xz")
        if harness_splice is not None:
            add(axs, harness_splice, "#f3d27a", "#b8860b", a=0.9, plane="xz")
            label(axs, harness_splice, "splice x2", plane="xz", fs=6)
        axs.axhline(BODY_D, color="#c0392b", lw=1.0, ls="--")
        axs.text(W + 0.5, BODY_D, f" lid inner z={BODY_D:.2f}", fontsize=7,
                 va="center", color="#c0392b")
        axs.text(0.02, 0.97,
                 f"JST head-room margin "
                 f"{BODY_D - (harness_jst[5] + J1_BEND_Z):+.2f} mm  "
                 f"(mated body limit {BODY_D - WALL - J1_BEND_Z:.2f} mm)",
                 fontsize=8, va="top", ha="left", color="#c0392b",
                 transform=axs.transAxes)
    axs.set_xlim(-2, W + 12)
    axs.set_ylim(-2, BODY_D + LID_T + 3)
    axs.set_aspect("equal")
    axs.set_xlabel("x [mm]", fontsize=8)
    axs.set_ylabel("z [mm]", fontsize=8)
    axs.tick_params(labelsize=7)
    fig.suptitle(f"MindClip DIY — PCB integration detail [{OUT_TAG}]  "
                 f"outer {W:.1f} x {H:.1f} x {TOTAL_D:.1f} mm", fontsize=11)
    fig.savefig(os.path.join(REN_DIR, "pcb_pocket.png"), bbox_inches="tight")
    plt.close(fig)
    print("[render] pcb_pocket.png")

    # ---- strapplate.png (v1.7: ストラップ板の外観 + ストラップの通し方の断面) ----
    #   断面図はパラメータから描く。一致は開発時に STL のスライスで 0.1mm 刻みで確認済み
    #   (スロット / 中央バー / ポケット / リムの y 区間)。
    from matplotlib.patches import Rectangle
    spm = meshes["strapplate"]
    fig = plt.figure(figsize=(13, 6.6), dpi=140)
    ax3 = fig.add_subplot(1, 2, 1, projection="3d")
    draw_scene(ax3, [(spm, C_BP, 1.0)])
    finish(ax3, spm.vertices, elev=48, azim=-58, zoom=1.15)
    ax3.set_title(f"strap plate {SP_W:.1f} x {SP_H:.1f} x {SP_T:.1f} mm (+rim {SP_RIM_H})\n"
                  f"2 slots for straps up to {STRAP_W:.0f} mm wide / {STRAP_T:.1f} mm thick",
                  fontsize=10)
    axs2 = fig.add_subplot(1, 2, 2)
    C_PL, C_BD, C_ST = "#8c8c94", "#4d73a0", "#d08a2a"
    def rect(y0, y1, z0, z1, fc, ec="none", **kw):
        axs2.add_patch(Rectangle((z0, y0), z1 - z0, y1 - y0, fc=fc, ec=ec, **kw))
    (bya, byb), (aya, ayb) = SP_SLOTS
    rect(-SP_H / 2, bya, 0, SP_T, C_PL)                       # 下側 (磁石を含む)
    rect(byb, aya, 0, SP_BAR_T, C_PL)                         # 中央バー
    rect(ayb, SP_H / 2, 0, SP_T, C_PL)                        # 上側の当たり面
    for s in (1, -1):                                         # リム
        y_in = s * (H / 2 + SP_RIM_CLR)
        rect(min(y_in, s * SP_H / 2), max(y_in, s * SP_H / 2), SP_T, SP_T + SP_RIM_H, C_PL)
    for _, my in SP_MAGS[:1]:                                 # 磁石 (x=±9 にあるので破線)
        for zz, lab in ((SP_T - MAG_T - 0.2, "magnet (plate)"), (SP_T + MAG_WEB, "magnet (body)")):
            rect(my - MAG_D / 2, my + MAG_D / 2, zz, zz + MAG_T, "none", ec="#333", ls="--", lw=0.8)
        axs2.text(-4.0, my, "magnets\n(x=±9, 1.0 mm apart)", fontsize=7, ha="right", va="center")
    rect(-H / 2, H / 2, SP_T, SP_T + BODY_D, C_BD, alpha=0.30)   # 本体 + リッド
    rect(-H / 2, H / 2, SP_T + BODY_D, SP_T + TOTAL_D, C_BD, alpha=0.45)
    axs2.text(SP_T + TOTAL_D / 2, H / 2 - 4, "body + lid\n(snaps on with magnets)",
              fontsize=8, ha="center", va="top")
    zb, zp = -STRAP_T / 2 - 0.3, SP_BAR_T + STRAP_T / 2 + 0.1
    ya, yb = (aya + ayb) / 2, (bya + byb) / 2
    path_y = [SP_H / 2 + 7, ya, ya, yb, yb, -SP_H / 2 - 7]
    path_z = [zb, zb, zp, zp, zb, zb]
    axs2.plot(path_z, path_y, color=C_ST, lw=5.5, solid_capstyle="butt", alpha=0.9)
    axs2.annotate("", xy=(zb, SP_H / 2 + 1), xytext=(zb, SP_H / 2 + 7),
                  arrowprops=dict(arrowstyle="->", color=C_ST, lw=1.5))
    axs2.text(zb + 1.2, SP_H / 2 + 5, "strap (from shoulder)", fontsize=8, ha="left", color="#8a5a10")
    axs2.text(zp + 0.6, (ya + yb) / 2, "strap runs over\nthe centre bar\ninside the pocket",
              fontsize=7, va="center", color="#8a5a10")
    axs2.text(-4.0, -SP_H / 2 - 4, "chest side", fontsize=8, ha="right")
    axs2.set_aspect("equal")
    axs2.set_xlim(-24, SP_T + TOTAL_D + 4)
    axs2.set_ylim(-SP_H / 2 - 9, SP_H / 2 + 9)
    axs2.set_xlabel("depth z (mm)")
    axs2.set_ylabel("height y (mm, worn: up)")
    axs2.set_title("section x=0: weave the strap  behind → up through top slot → over bar\n"
                   "→ down through bottom slot → behind (tri-glide grip, does not slide)",
                   fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(REN_DIR, "strapplate.png"), bbox_inches="tight")
    plt.close(fig)
    print("[render] strapplate.png")

    # ---- magsafeplate.png (v1.10: 板の両面 + スマホ背面に付けた見え方) ----
    #   スマホの外形・カメラ台座は目安の作図 (寸法の根拠にしない)。
    from matplotlib.patches import FancyBboxPatch, Circle
    msm = meshes["magsafeplate"]
    fig = plt.figure(figsize=(15, 6.4), dpi=140)
    axa = fig.add_subplot(1, 3, 1, projection="3d")
    draw_scene(axa, [(msm, C_BP, 1.0)])
    finish(axa, msm.vertices, elev=50, azim=-58, zoom=1.15)
    axa.set_title("body side: rim + 2 magnets\n(the clip snaps in here)", fontsize=10)
    axb = fig.add_subplot(1, 3, 2, projection="3d")
    flip = msm.copy()
    flip.apply_transform(np.array([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, MS_T], [0, 0, 0, 1.0]]))
    draw_scene(axb, [(flip, C_BP, 1.0)])
    finish(axb, flip.vertices, elev=50, azim=-58, zoom=1.15)
    axb.set_title(f"phone side: groove for a stick-on MagSafe ring\n"
                  f"(dia {MS_RING_OD:.0f}/{MS_RING_ID:.0f} x {MS_RING_T:.1f} mm)", fontsize=10)
    axc = fig.add_subplot(1, 3, 3)
    PW, PH = 71.9, 150.0                      # iPhone 17 Pro の外形 (目安)
    axc.add_patch(FancyBboxPatch((-PW / 2, -PH / 2), PW, PH, boxstyle="round,pad=0,rounding_size=9",
                                 fc="#d9d6d0", ec="#555", lw=1.2))
    axc.add_patch(FancyBboxPatch((-PW / 2 + 2, PH / 2 - 40), PW - 4, 38,
                                 boxstyle="round,pad=0,rounding_size=7", fc="#bdb9b1", ec="#555", lw=0.8))
    for cx_, cy_ in ((-20, PH / 2 - 13), (-20, PH / 2 - 29), (-5, PH / 2 - 21)):
        axc.add_patch(Circle((cx_, cy_), 6.5, fc="#33363b", ec="#111"))
    axc.text(8, PH / 2 - 21, "camera\n(approx.)", fontsize=7, va="center")
    MSY = -8.0                                # MagSafe 中心の高さ (目安)
    axc.add_patch(Circle((0, MSY), MS_DISC_R, fc="#8c8c94", ec="#333", lw=1.0))
    axc.add_patch(FancyBboxPatch((-SP_OUT_W / 2, MSY - SP_OUT_H / 2), SP_OUT_W, SP_OUT_H,
                                 boxstyle=f"round,pad=0,rounding_size={SP_R}", fc="#8c8c94", ec="#333", lw=1.0))
    axc.add_patch(FancyBboxPatch((-W / 2, MSY - H / 2), W, H,
                                 boxstyle=f"round,pad=0,rounding_size={R_OUT}", fc="#2b2d31", ec="#000", lw=1.0))
    for mxh in MIC_X_ON_BOARD:
        axc.add_patch(Circle((xiao[0] + mxh - CX, MSY + H / 2 - 1.0), 0.75, fc="#888", ec="none"))
    axc.add_patch(Circle((LED_POS[0] - CX, MSY + LED_POS[1] - H / 2), LED_WIN_R, fc="#55585e", ec="none"))
    axc.annotate("mic ports (top edge)", xy=(xiao[0] + MIC_X_ON_BOARD[1] - CX, MSY + H / 2),
                 xytext=(12, MSY + H / 2 + 14), fontsize=7, arrowprops=dict(arrowstyle="-", lw=0.6))
    axc.annotate("USB-C", xy=(W / 2, MSY + USB_CY - H / 2), xytext=(W / 2 + 6, MSY + USB_CY - H / 2),
                 fontsize=7, va="center", arrowprops=dict(arrowstyle="-", lw=0.6))
    axc.text(0, MSY - 4, "MindClip", color="#9a9da3", fontsize=8, ha="center")
    axc.text(0, -PH / 2 + 8, f"sticks out {MS_T + MS_RING_PROUD + TOTAL_D:.1f} mm from the case",
             fontsize=8, ha="center")
    axc.set_aspect("equal"); axc.set_xlim(-PW / 2 - 8, PW / 2 + 22); axc.set_ylim(-PH / 2 - 6, PH / 2 + 6)
    axc.set_axis_off()
    axc.set_title("on the back of an iPhone 17 Pro (to scale, layout approximate)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(REN_DIR, "magsafeplate.png"), bbox_inches="tight")
    plt.close(fig)
    print("[render] magsafeplate.png")


if __name__ == "__main__":
    paths = export_all()
    verify_and_render(paths)
    print("[done] all outputs generated")
