# MindClip DIY — 基板レイアウト仕様（LAYOUT.md / rev.B）

生成物: [`gen_pcb.py`](gen_pcb.py) →
[`mindclip_sense.kicad_pcb`](mindclip_sense.kicad_pcb) /
[`mindclip_carrier.kicad_pcb`](mindclip_carrier.kicad_pcb) /
`gerber/mc-sense-a/` · `gerber/mc-carrier-a/`（Gerber + Excellon + BOM/CPL）/
[`layout.png`](layout.png) / [`layout_top.svg`](layout_top.svg)

前提文書: [`SCHEMATIC.md`](SCHEMATIC.md) · [`netlist.json`](netlist.json) ·
[`../MECHANICAL.md`](../MECHANICAL.md) · [`../ELECTRICAL.md`](../ELECTRICAL.md) ·
[`../cad/mindclip_case.py`](../cad/mindclip_case.py)

---

## 0. 【最初に読む】この基板は v1.5 では使わない

| 構成 | 基板 | VBUS検出 | 電池監視 | 極性ミス排除 | 判定 |
|---|---|---|---|---|---|
| **v1.5 = 案A-1（採用）** | **なし**（空中配線＋JSTピグテール・はんだ10点） | **false** | **false** | **false** | **これを組む** |
| ~~案A-2~~ | なし（空中配線で分圧追加） | ✓ | ✓ | ✗ | **禁止**（SCHEMATIC.md §0.1） |
| **MC-SENSE-A**（本書） | サテライト基板 10.0×15.6 | ✓ | ✓ | ✗ | v2・ゲート後 |
| **MC-CARRIER-A**（本書） | キャリア基板 34.2×21.5 | ✓ | ✓ | ✗（下記） | v2+・筐体改造必須 |

- **本書の2枚はどちらも `netlist.json` の `V2_SENSE_SATELLITE` 側の設計**であり、
  v1.5 の組立手順には登場しない。SCHEMATIC.md §9.4 の離脱ゲートを1つ以上満たし、
  かつ **XIAO スタック総厚をノギスで実測**してからでなければ発注してはならない。
- VBUS検出・電池監視が必要になったときは、**空中配線（A-2）ではなくこの基板に載せる**。
  同一機能・同一部品のまま、A-2 最大の弱点である 3端子空中スプライス3箇所が
  基板ランドに置き換わる。
- **`removes_battery_polarity_risk` は 2枚とも false のまま。** J1 の極性キーと
  シルク（`+` / `-`）は「上下逆挿し」しか防がない。中華セルの赤黒逆結線は防げないので、
  SCHEMATIC.md §5.4 の**嵌合前テスタゲートは基板化しても必須のまま**である。
  さらに **MC-CARRIER-A rev.A には逆接続保護 FET（Q1/Q2）を載せていない**（§6.4）。

### 0.1 【重要】`[done] independent-DRC errors=0` を「検証済み」と読まない

`gen_pcb.py` の DRC は **2026-08-28 に全面拡張した独立ジオメトリ DRC** で、
旧版が原理的に見逃していた異ネット衝突（実測 41件・うち銅箔レベルの直短絡 16件）を
検出できるようになっている（§4.3 に根本原因）。それでも次は**やっていない**。

| やっていること | やっていないこと |
|---|---|
| 全銅箔（パッド／トラック／ビア）の異ネット総当たりクリアランス | **KiCad 本体の DRC** |
| 角R外形・窓（cutout）との距離を SDF で厳密に | **製造業者の DFM チェック** |
| 回転フットプリントのパッド絶対角トークンの有無 | 実物のフットプリント寸法との突合（§8） |
| シルクのパッド乗り／外形はみ出し | 熱設計・EMC・インピーダンス（本設計では不要） |
| 生成した Gerber/Excellon を**読み直して**生成元と数と座標を突合 | Gerber ビューアでの目視（推奨・§9） |

---

## 1. 基板外形は筐体内寸から決めた（`mindclip_case.py` の実行値）

`gen_pcb.py` は起動時に `cad/mindclip_case.py` を **両バリアントで import して
`check_layout()` を実行**し、その実値から外形を決める（ハードコードしていない）。

```
[case] allday src = cad/mindclip_case.py (live import, check_layout PASS)
[case] allday outer 38.0 x 49.4 x 14.6 / IW 34.8 IH 46.2 ID 11.2 / lid inner z 12.8
[case] slim   ID 9.5 / lid inner z 11.1
```

### 1.1 MC-SENSE-A の外形決定

| 項目 | 値 | 出どころ |
|---|---|---|
| 左ポケット床の利用可能域 X | 1.60 .. 12.40 mm | 内壁 `WALL` .. `xiao_stops[0].x0` |
| 同 Y | 28.20 .. 44.60 mm | 電池上端 `bat[3]` .. `sw_rib.y0` |
| 片側クリアランス | 0.40 mm | FDM ポケットは 0.1〜0.3mm 小さく出る（MECHANICAL §5）＋PCB外形公差 ±0.2mm |
| **基板外形** | **10.00 × 15.60 mm**（x 2.00..12.00 / y 28.60..44.20） | 上記の差 |
| 角R | **0.8 mm** | rev.B で 1.0→0.8。J2 の端ランドが角Rに食い込み **銅箔-外形 0.27mm** になっていたため |
| 板厚 | 0.80 mm | JLCPCB 標準厚。1.0t より 0.2mm 分の天井余裕が増える |
| 基板 z | 1.60 .. 2.40 mm（床置き） | 追加高さ **0.00 mm**・筐体CAD変更ゼロ |
| 基板↔筐体内寸クリアランス | **0.40 mm**（`check_case_fit` が毎回検算） | rev.B で追加した検査（§4.2） |

> **手切り基板（案D）に対する実利**: 案D は 10.2mm 幅を筐体内寸 10.8mm に
> 手で切り出す前提で、機構レビューから「CEM-3 を ±0.3mm に収めるのは初心者には
> 非現実的（実力 ±0.5mm 級）」と指摘されていた。製造基板の外形公差は ±0.2mm なので、
> **片側 0.4mm クリアランスなら最悪でも 0.2mm 残る**。ヤスリ調整も金ノコも要らない。

### 1.2 MC-CARRIER-A の外形決定（**筐体改造が前提**）

キャステレーション受けランドを XIAO の長辺の外に出す余裕が現行筐体には無い
（上 0.6mm / 下 1.2mm）。よって以下の筐体改造とセットでしか成立しない。

| パラメータ | 現行 | rev.A | rev.B（本書） | 理由 |
|---|---|---|---|---|
| `GAP_BX`（電池上端〜XIAO下端） | 1.2 | 1.8 | **2.1** | 1.8 だとランド外端〜基板端が **0.31mm** しかなく、外形ルーティング公差 ±0.2mm を吸収できない（→ 0.61mm） |
| `M_TOP`（XIAO上端マージン） | 0.6 | 1.8 | **2.0** | 上側ランド 0.51mm ＋ 基板と筐体上内壁の逃げ 0.2mm |
| `IH`（内寸高さ） | 46.2 | 48.0 | **48.5** | ↑の合計 |
| **外形高さ H** | 49.4 | 51.2 | **51.7 mm** | **body/lid 再印刷必須** |
| `XIAO_LIFT` | 1.4 | 1.6 | **1.6**（シェルフ0.8＋基板0.8） | 基板下に BAT ジャンパの逃げ |
| **内寸奥行 ID（allday）** | 11.2 | 11.5 | **11.5**（→外形 14.6 → **14.9 mm**） | J1 嵌合体＋電線曲げ代（§4.4） |

- **基板外形 34.20 × 21.50 × 0.80 mm**（x 2.00..36.20 / y 28.40..49.90、角R1.5）。
- 右端は XIAO 右端 36.4 に対し 0.2mm 手前で止め、USB-C の突出を邪魔しない。
  結果として **XIAO 本体は基板右端を 0.2mm 張り出す**（意図どおり）。
- **`cad/mindclip_case.py` は `GAP_BX`/`M_TOP` を触ると `INTERFERENCE: seat0 <-> xnub_b0`
  で assert が落ちる問題**（`xiao_seats` の y・`sw_rib.y0`・`LED_POS` が絶対値直書き）が
  機構レビューで指摘されている。**この修正は案Bを採らなくても入れるべき**（機構側の担当範囲）。

---

## 2. 層構成（2枚共通）

| # | 層 | 内容 |
|---|---|---|
| 1 | **F.Cu**（top, 1oz = 35µm） | 信号・電源配線（主）。0805/JST/ワイヤランド/テストポイント |
| — | F.Mask / F.SilkS / F.Paste | レジスト（緑）／シルク（白・**線幅 0.15mm**）／メタルマスク |
| — | FR-4 コア **0.8mm** | Tg140 標準材 |
| 2 | **B.Cu**（bottom, 1oz = 35µm） | 交差回避のジャンパ配線。MC-CARRIER-A では **J4（BATジャンパランド）** も B.Cu |
| — | B.Mask / B.SilkS | 裏面シルクに `MC-XXX V2 NOT FOR V1.5` を刻む |

- **ベタGND（zone）は置いていない。** µA オーダーの高抵抗分圧しか無く、
  全ネットを実配線で結線済み（未結線ゼロ）。**KiCad で開いた直後に「B」でゾーンを
  塗り直す必要が無い**＝初心者が「塗り忘れたまま Gerber を出す」事故が起きない。
- 内層なし・ブラインド/ベリードビアなし・インピーダンス制御なし。
- **シルク線幅は 0.15mm**（rev.A の 0.12mm は JLCPCB の最小線幅 0.15mm を下回っており、
  かすれ・欠けの可能性があった）。

---

## 3. 製造仕様（JLCPCB 発注時の設定値・そのまま入力する）

| 項目 | 設定値 | 備考 |
|---|---|---|
| Base Material | **FR-4** | |
| Layers | **2** | |
| Dimension | MC-SENSE-A: **10.0 × 15.6 mm** / MC-CARRIER-A: **34.2 × 21.5 mm** | Gerber の Edge.Cuts から自動認識 |
| PCB Qty | **5**（最小ロット） | JLCPCB の 2層・100×100mm 以下は5枚が最小 |
| Delivery Format | Single PCB | 10×15.6mm は**面付け不要**（JLCPCB の最小外形 10×10mm を満たす） |
| PCB Thickness | **0.8 mm** | 1.6 でも作れるが天井余裕が 0.8mm 減る（§4.4） |
| PCB Color | **Green**（緑） | 緑以外は追加料金・納期+1〜2日 |
| Silkscreen | White | |
| Surface Finish | **HASL (with lead)** で可 / 環境配慮なら **LeadFree HASL** | ENIG は不要（0805＋THT のみ、微細パッド無し） |
| Outer Copper Weight | **1 oz** | |
| Via Covering | Tented | ビア 7〜15本・電流µA級。生成した `*-F_Mask.gbr` はビアを開口していない |
| Board Outline Tolerance | ±0.2mm (Regular) | §1.1 のクリアランス根拠 |
| Remove Order Number | **「Specify a location」推奨** | 10×15.6mm に発注番号が入ると読めなくなるため位置指定 |

**費用と納期（2026-08 時点の一般的な相場。発注前に見積り画面で必ず確認すること = assumption）**

| | MC-SENSE-A | MC-CARRIER-A |
|---|---|---|
| 基板 5枚 | **$2**（2層・100×100mm 以下の定額） | $2 |
| 送料（Global Standard 等） | $1.5 〜 $7 | 同左 |
| 合計（¥150/USD 換算） | **約 ¥530 〜 ¥1,350 / 5枚** | 同左 |
| 着荷（日本） | **おおむね 1〜3週間** | 同左 |

- **SMT実装サービスは使わなくてよい。** 実装部品は 0805 が6個（MC-SENSE-A）/7個
  （MC-CARRIER-A）だけで、タスク前提の「0805 までなら初心者でも手はんだ可能」の
  範囲に収まる。SMT を頼むと 1台 ¥4,000〜5,000 に跳ね上がる。
  → 生成した `*-bom.csv` の **LCSC 品番欄は意図的に空**にしてある。SMT を頼む場合だけ、
  発注前に自分で品番を入れること（当てずっぽうの品番を書き込むより空の方が安全）。
- **キャステレーション加工の割増は発生しない。** カステレーションが要るのは XIAO 側で、
  キャリア基板は**それを受ける平ランドを置くだけ**（半円穴を切る加工は不要）。

### 3.1 DRC（`gen_pcb.py` が自動検査する値）

| 項目 | JLCPCB 最小 | 本設計の採用値 | 実測の最悪値 |
|---|---|---|---|
| 線幅 | 0.127 mm (5mil) | 0.25 mm | 0.25 mm |
| 導体間クリアランス | 0.127 mm | **0.25 mm** | **0.25 mm 以上**（rev.A は構造的に 0.15mm しか出せなかった） |
| 穴径（THT/ビア） | 0.30 mm | THT **0.75 mm** / ビア **0.40 mm** | 2.5倍 / 1.3倍 |
| アニュラリング | 0.13 mm | JST **0.225 mm** / ワイヤランドはSMD / ビア **0.20 mm** | 1.7倍 / 1.5倍 |
| 銅箔〜基板外形 | 0.30 mm | 0.30 mm 以上 | **角R部も SDF で検査**（rev.A は矩形近似で 0.2719mm を見逃していた） |
| 穴〜基板外形 | 0.30 mm | 0.30 mm 以上 | MH1/MH2 は rev.B で 0.30→**0.70 mm** に改善 |
| シルク線幅 | 0.15 mm | **0.15 mm** | ちょうど |
| 最小造形 | — | 0805・2.0mmピッチTHT・SMDワイヤランドのみ | QFN/BGA なし |

> **THT 穴径を 0.90 → 0.75mm に変更した**（rev.B）。JST PH の 0.5mm 角ポストに対し
> 0.90 はガタが大きく、KiCad 標準フットプリントも 0.75 を使っている。

---

## 4. 検証結果（`python3 gen_pcb.py` の実行ログ）

```
=== MC-SENSE-A  (mindclip_sense.kicad_pcb) ===
  outline      : 10.00 x 15.60 x 0.80 mm, corner R0.8
  placement    : x 2.00..12.00 / y 28.60..44.20 / z 1.60..2.40 (筐体座標)
  sexp         : balanced=True footprints=8 pads=20 nets=7 segments=32 vias=7 edge_lines=4
  routing      : ALL NETS ROUTED
  fit          : [allday] board-in-case clearance = 0.40 mm
  fit          : [allday] J1 嵌合体top z=9.90+曲げ代2.4 = 12.30 <= 天井 12.80: OK (余裕 0.50mm)
  fit          : [slim]   J1 ... = 12.30 > 天井 11.10 → NG。ID を +1.20mm 要する
  netlist xcheck: OK
  drc          : 68 copper primitives, 1476 異ネットペアを総当たり
  fab data     : gerber/mc-sense-a/ に 11 ファイル（読み直し検査 OK）

=== MC-CARRIER-A  (mindclip_carrier.kicad_pcb) ===
  outline      : 34.20 x 21.50 x 0.80 mm, corner R1.5
  placement    : x 2.00..36.20 / y 28.40..49.90 / z 2.40..3.20 (筐体座標)
  sexp         : balanced=True footprints=19 pads=43 nets=10 segments=61 vias=15 edge_lines=8
  routing      : ALL NETS ROUTED
  fit          : [allday] board-in-case clearance = 0.20 mm（case_mod 適用後の内寸）
  fit          : [allday] J1 ... = 13.10 > 天井 12.80 → NG。ID を +0.30mm（外形 14.6→14.9）要する
  netlist xcheck: OK
  drc          : 136 copper primitives, 6491 異ネットペアを総当たり
  fab data     : gerber/mc-carrier-a/ に 13 ファイル（読み直し検査 OK）

[done] independent-DRC errors=0  warnings=0
```

### 4.1 何を検査しているか

1. **S式の構文**: 自前トークナイザで `.kicad_pcb` をパースし、括弧の対応・
   トップレベルが1個の `kicad_pcb` であること・全パッドのネット名がネット表に
   宣言済みであることを確認。
2. **パッド絶対角トークン**: 回転しているフットプリントの全パッドに
   `(at x y ANGLE)` の ANGLE が付いているかを S式から読み直して確認（§4.5）。
3. **幾何 DRC（rev.B の中核）**: 基板上の全銅箔をプリミティブ化し、
   **異ネットで層を共有する全ペア**（sense 1,476組 / carrier 6,491組）の
   エッジ間距離を計算。0.127mm 未満は ERROR、0.25mm 未満は WARN。
   対象は **pad↔pad / pad↔track / pad↔via / track↔track / track↔via / via↔via**、
   さらに **ドリル穴と異ネット銅箔**。
4. **銅箔・穴と基板外形／窓**: 角R矩形の符号付き距離関数（SDF）で厳密に。
   矩形近似ではないので、角R部の違反も検出できる。
5. **未結線ゼロ**: 迷路ルータ（0.1mm グリッド／2層／方向転換ペナルティ付き
   ダイクストラ）で全ネットを結線。`ALL NETS ROUTED`。
6. **筐体との干渉（AABB）と収まり**: 基板外形・背の高い部品（J1 嵌合体）を
   電池／スイッチ／LED本体／リブ／lip と総当たり判定。加えて rev.B では
   **「基板外形が筐体内寸に収まっているか」**も検査する（§4.2）。
7. **シルク**: パッド乗り・基板外形はみ出し・線幅。
8. **製造データの読み直し**: 書き出した Gerber / Excellon / CSV を**開き直して**、
   フラッシュ座標の集合・描画本数・穴数・ヘッダを生成元と突合する（§9.2）。
9. **netlist.json との突合**: `connections` のうちこの基板に載る接続が全て基板上にあること。

### 4.2 rev.B で追加した「基板が筐体に収まっているか」検査

rev.A の `check_case_fit()` は電池・スイッチ・LED・リブ・lip との個別 AABB と
天井高さしか見ておらず、**基板そのものが筐体内寸を 1.60mm はみ出していても無警告**だった
（MC-CARRIER-A は y 28.40..49.40 に置かれる一方、当時の内寸は y 1.6..47.80）。

rev.B は内寸（キャリアは `case_mod` 適用後）との4辺クリアランスを毎回表示する。

| 基板 | 内寸 | クリアランス |
|---|---|---|
| MC-SENSE-A | x 1.6..36.4 / y 1.6..47.8 | **0.40 mm** |
| MC-CARRIER-A | x 1.6..36.4 / y 1.6..50.1（`case_mod` の IH=48.5） | **0.20 mm** |

### 4.3 rev.A にあった欠陥と、その根本原因（記録として残す）

レビューで指摘された **異ネット short 16件・クリアランス違反 41件** の原因は
**ルータの層変更判定**にあった。

```
旧 gen_pcb.py:629
    if self.occ[nl][self.idx(i, j)] in (0, nid):     # ← 反対層の 0.1mm セル1個しか見ていない
```

- 占有マップが層あたり1枚しかなく、**ビアランド φ0.8mm の実体**を他ネットの銅箔と
  突き合わせていなかった。keepout は `_commit()` で**配置後**にしか塗られないため、
  先に引かれた他ネットのトラックの脇 **0.400mm** にビアが「合法的に」落ちた。
  必要値は 0.25/2 + 0.8/2 + 0.127 = **0.652mm** なので、銅箔が 0.125mm 食い込む。
- さらにトラックのハローが `tw/2 + cl*0.5 = 0.25mm` しかなく、
  DRC dict が自ら宣言する `use_clear = 0.25` を**構造的に満たせなかった**
  （異ネット track↔track の最小が 0.150mm）。

**rev.B の修正**: 占有マップを層ごとに2枚に分ける。

| マップ | 意味 | 障害物からの塗り幅 |
|---|---|---|
| `occ_t[L]` | 他ネットの**トラック中心線**を禁止するセル | 実体 + `tw/2` + `clearance` |
| `occ_v[L]` | 他ネットの**ビア中心**を禁止するセル | 実体 + `via/2` + `clearance` |

ビアは **`occ_v` が両層とも空いているときだけ**打てる。`occ_v` の塗り範囲は
`occ_t` の上位集合なので、ビア判定は `occ_v` の2層チェックだけで足りる。
併せて `validate_pcb()` を §4.1-3 のとおり拡張したので、**同じ欠陥が再発しても
今度は検出される**（rev.A の検査項目にはこの種の衝突が1つも入っていなかった）。

### 4.4 いちばん厳しい寸法は「J1 の嵌合体＋電線曲げ代」

| | 基板上面 z | 嵌合体 7.5mm | ＋曲げ代 2.4mm | 天井 | 判定 |
|---|---|---|---|---|---|
| MC-SENSE-A / allday | 2.40 | 9.90 | 12.30 | **12.80** | **OK（余裕 0.50mm）** |
| MC-SENSE-A / slim | 2.40 | 9.90 | 12.30 | 11.10 | NG（ID +1.20 必要） |
| MC-CARRIER-A / allday | 3.20 | 10.70 | 13.10 | 12.80 | NG（ID +0.30 必要 → 外形 14.9mm） |
| MC-CARRIER-A / slim | 3.20 | 10.70 | 13.10 | 11.10 | NG（ID +2.00 必要） |

- 嵌合高さ **7.5mm は最悪値の assumption**。曲げ代 **2.4mm は AWG28（外径1.2mm）の
  最小曲げ半径 2×OD**。
- **結論: MC-SENSE-A は allday 専用**。slim で VBUS検出・電池監視が要るなら、
  基板ではなく**要件の方を落とす**（実装しない）。
- **MC-CARRIER-A は allday でも外形奥行き +0.3mm** が要る。外形高さ +2.3（49.4→51.7）と
  合わせると **38.0×51.7×14.9mm**。「高さ予算が最もシビアな制約」という本プロジェクトの
  前提に対し、これは大きな代償である。

### 4.5 パッド絶対角の欠落（rev.A の欠陥・修正済み）

KiCad の `pad (at x y ANGLE)` の ANGLE は**絶対角**で、フットプリント回転を含めて
書かねばならない（省略時は 0度）。rev.A は 90/270度 配置の 0805 全数で角度トークンが
無く、**ランドが 1.4(X)×1.025(Y) ではなく 1.025(X)×1.4(Y) で出力されていた**
（ランド間ギャップ 0.85 → 0.475mm、パッド幅 1.025mm がチップ幅 1.25mm より狭い）。

rev.B は角度を必ず書き、`validate_pcb()` が S式を読み直して欠落を ERROR にする。
生成した Gerber のアパーチャも `%ADD12R,1.400000X1.025000*%` と**回転後の実寸**になっている
（回転は 90度の倍数しか使っていないので矩形アパーチャで厳密に表せる）。

---

## 5. フットプリント一覧

### 5.0 【rev.B】ライブラリ名を `MindClip:` 名前空間に改めた

rev.A は KiCad 標準ライブラリ名（`Resistor_SMD:R_0805_2012Metric` 等）を名乗っていたが、
**インライン定義の寸法が標準フットプリントと一致していなかった**。

| フットプリント | rev.A のインライン定義 | KiCad 標準の実物 | rev.B |
|---|---|---|---|
| 0805 パッド位置 | ±0.9375 | **±0.9125** | 標準に合わせた |
| 0805 コートヤード | 2.90 × 1.70 | **3.36 × 1.90**（C は 3.40 × 1.96） | 標準に合わせた |
| 0805 シルク | ±1.55 の縦線2本（未回転パッドを突き抜ける） | パッド間の短い横線2本（±0.735） | 標準に合わせた |
| JST PH ドリル | φ0.90 | **φ0.75** | 標準に合わせた |
| JST PH パッド | 1.7 × 1.7 | **1.2 × 1.75** | 標準に合わせた |
| 取付穴のライブラリ名 | `MountingHole:MountingHole_2.2mm` | **実在しない**（正しくは `MountingHole_2.2mm_M2`） | 名前を訂正 |

「標準名を名乗るが中身は別物」は追跡性をむしろ壊すので、**全て `MindClip:` 接頭辞に改名**し、
各フットプリントの `descr` に「相当する KiCad 標準フットプリント名」を書いた。
フットプリントの実体は `.kicad_pcb` 内にインライン定義してあるので、
利用者側のライブラリ構成に依存せず開ける。

### 5.1 MC-SENSE-A（8個 / 20パッド / 7ネット）

配置方針: 0805 を **90度回転して縦置き**にし、2行 × 3列に並べる。こうすると各パッドが
左右（＝縦の配線レーン）から入れるようになり、**幅 0.65〜0.70mm の縦レーンが4本**
（x≈2.4–3.1 / 5.3–5.9 / 8.1–8.7 / 10.9–11.6）取れる。B.Cu はほぼ空なので、
交差はビアで逃がす。

| Ref | 値 | フットプリント | 位置(筐体座標) / 回転 | pads | ネット |
|---|---|---|---|---|---|
| J1 | JST PH 2.0mm 2P | `MindClip:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical_MC` | (7.00, 31.70) / 0° | 2 | BATP, BATN |
| R4 | 220k | `MindClip:R_0805_2012Metric_MC` | (4.20, 35.60) / 90° | 2 | BATP, VBAT_SENSE |
| R5 | 220k | `MindClip:R_0805_2012Metric_MC` | (7.00, 35.60) / 90° | 2 | VBAT_SENSE, GND |
| C1 | 100nF 50V X7R | `MindClip:C_0805_2012Metric_MC` | (9.80, 35.60) / 90° | 2 | VBAT_SENSE, GND |
| R2 | 220k | `MindClip:R_0805_2012Metric_MC` | (4.20, 39.40) / 90° | 2 | VBUS, VBUS_SENSE |
| R3 | 330k | `MindClip:R_0805_2012Metric_MC` | (7.00, 39.40) / 90° | 2 | VBUS_SENSE, GND |
| C2 | 100nF 50V X7R | `MindClip:C_0805_2012Metric_MC` | (9.80, 39.40) / 90° | 2 | VBUS_SENSE, GND |
| J2 | XIAO へ出る6本 | `MindClip:WireLand_SMD`（SMD 1.0×1.8mm × 6・ピッチ1.5） | (7.00, 42.90) / 0° | 6 | B−, B+, D4, D0, 5V, GND |

- **J2 の6ランドは「XIAOへの配線ランド」と「テストポイント」を兼ねる。**
  10.0×15.6mm に別途 TP を置く余地が無いためだが、`GND / VBAT_SENSE / VBUS_SENSE /
  BATN / BATP / VBUS` の6ネットが全て露出しているので、
  **基板単体で分圧比を測る**という目的（§7）はこれで満たせる。
- 分圧比を測るときの当て所: `B+`↔`D4` = R4（220k）、`D4`↔`GND` = R5（220k）、
  `5V`↔`D0` = R2（220k）、`D0`↔`GND` = R3（330k）。

### 5.2 MC-CARRIER-A（19個 / 43パッド / 10ネット）

| Ref | 値 | フットプリント | 位置 / 回転 | pads |
|---|---|---|---|---|
| U1 | XIAO ESP32S3 Sense | `MindClip:XIAO_ESP32S3_Castellated_2x7_P2.54mm` | (25.90, 39.20) / 0° | 14 |
| J1 | JST PH 2.0mm 2P | `MindClip:JST_PH_..._Vertical_MC` | (10.00, 32.40) / 0° | 2 |
| R4 / R5 | 220k / 220k | `MindClip:R_0805_2012Metric_MC` | (3.90 / 7.70, 36.40) / 0° | 各2 |
| C1 / C2 | 100nF / 100nF | `MindClip:C_0805_2012Metric_MC` | (3.90 / 7.70, 38.90) / 0° | 各2 |
| R2 / R3 | 220k / 330k | `MindClip:R_0805_2012Metric_MC` | (3.90 / 7.70, 41.40) / 0° | 各2 |
| R1 | 220R（LED電流制限） | `MindClip:R_0805_2012Metric_MC` | (13.50, 36.40) / 90° | 2 |
| J3 | LED配線ランド | `MindClip:WireLand_SMD` | (13.50, 40.60) / 0° | 2 |
| J2 | スイッチ配線ランド | `MindClip:WireLand_SMD` | (13.50, 45.00) / 0° | 2 |
| J4 | **BATジャンパランド（B.Cu）** | `MindClip:WireLand_SMD` | (24.60, 38.90) / 0° | 2 |
| TP1..TP4 | GND / BAT+ / VBUS_SENSE / VBAT_SENSE | `MindClip:TestPoint_Pad_D1.5mm_MC` | (6.5 / 8.5 / 10.5 / 12.5, 48.00) | 各1 |
| TP5 | BAT− | 同上 | (10.50, 45.20) | 1 |
| MH1, MH2 | 取付穴 φ2.2 NPTH | `MindClip:MountingHole_2.2mm_M2_MC` | (3.80, 31.20) / (3.80, 47.60) | 各1 |
| — | BATパッド アクセス窓 | Edge.Cuts の内側輪郭 **10.0 × 12.0 mm** | 中心 (30.80, 38.90) | — |

**rev.B で動かしたもの（すべて DRC 違反の解消が理由）**

| Ref | rev.A | rev.B | 理由 |
|---|---|---|---|
| MH1 / MH2 | x 3.40 | **x 3.80** | 穴縁〜外形が 0.30mm ちょうどで、外形ルーティング公差を吸収できなかった（→0.70mm） |
| R1 / J2 / J3 | x 14.00 | **x 13.50** | U1 のコートヤードと **0.000mm 接触**していた（→0.50mm） |
| J4 | x 24.70 | **x 24.60** | BAT窓との銅箔クリアランス 0.30 → **0.40mm** |
| TP1..TP5 | y 47.0 / 44.3 | **y 48.0 / 45.2**、x を +0.3 | TP1↔MH2、J2↔TP4 のコートヤードが重なっていた |
| U1 シルク | ±8.9 / ±10.5 | **±8.1 / ±10.1** | ランド内端 8.39 に乗っていた（silk-on-pad 14箇所）／基板端をはみ出していた |

### 5.3 筐体開口との対応

| 筐体側 | 座標 | 基板側の対応 |
|---|---|---|
| USB-C 開口（右側面） | y中心 38.30 / z0 3.80 | MC-CARRIER-A は右端を x36.2 で止め、XIAO の USB-C（x36.4）を遮らない |
| LED窓（正面リッド） | 中心 (9.80, 36.00)・本体は内側へ突出（v1.5 rev2 で x6.9→9.8 に移動） | **背の高い部品を置かない領域**。J1 は MC-SENSE-A で y≤33.4 に退避。0805（高さ0.5mm）は窓の下を通してよい |
| スイッチスロット（上面） | x4.0..12.7 / y45.0..48.5 | MC-CARRIER-A の J2（SW配線ランド）を x13.5, y45.0 に置き、配線を最短化 |
| マイク開口（上面） | z ≈ 9.6 | 基板・部品とも干渉なし（XIAO 上面の高さ） |
| 電池リード曲げチャネル | x1.6..4.0（幅2.4mm） | MC-SENSE-A の J1 は x3.05..10.95。セルのリードをチャネルから上げて J1 に挿す |

---

## 6. 置かなかったもの（正直に書く）

### 6.1 取付穴（MC-SENSE-A）

**取付穴を置いていない。** 10.0×15.6mm に対し J1（8.4×5.2）と6本のワイヤランドと
0805 ×6 を入れると、φ2.2 の穴が要求する 3.2×3.2mm のキープアウトを取れる場所が残らない。
**固定は薄手両面テープ＋左内壁へのホットボンド点付け**とする。
USB-C の挿入力を受けない位置なので、これで機械的要求は満たす。
無理に穴を開けて銅箔〜穴のクリアランスを削るより、**穴を置かないと明記する**方を採った。

### 6.2 ベタGND（zone）

§2 のとおり置いていない。µA オーダーの回路であり、置くと「塗り忘れ」事故が増えるだけ。

### 6.3 一部のリファレンス指示子

シルク文字は「基板内 かつ どのパッドにも乗らない かつ 他の文字と重ならない」位置に
しか置かない実装にしてある（`silk_items()`）。置けなかったものは実行ログの
`silk dropped` に出る（現状 MC-SENSE-A の `J1`/`J2`、MC-CARRIER-A の `U1`）。
**この3つは基板上で一意に識別できる**（J1 は唯一のTHTで `+`/`−` シルク付き、
J2 は唯一の6連ランドで各ランドに `B−/B+/D4/D0/5V/GND` が入っている、U1 は唯一の 2×7 ランド列）。
実装時は `layout_top.svg` を **1:1 で印刷**して手元に置くこと。

### 6.4 逆接続保護 FET（Q1/Q2）— MC-CARRIER-A rev.A には**載せていない**

SCHEMATIC.md §8.1 と `netlist.json` の `optional_blocks.V2_REVPROT` は
AO3401A ×2 の背中合わせを「電気的に正しい唯一の解」としているが、
**この2枚の基板にはフットプリントを置いていない**。理由:

1. キャリア基板でも BAT 経路は「窓 → ジャンパ線 → XIAO 裏面パッド」であり、
   保護FETは**その空中ジャンパの途中**に入ることになる。基板に載せる意味
   （シルク・キー・レジストで誤りを物理的に防ぐ）が最も薄い場所であり、
   「主電池経路に間欠断の候補を2箇所増やす」代償だけが残る。
2. SCHEMATIC.md §5.3 の前提（`BATN ≡ GND`）が未検証のままだと、
   FET を＋側と−側のどちらに入れるかを確定できない。実測前にアートワークは描けない。

よって **`removes_battery_polarity_risk` は MC-CARRIER-A rev.A でも `false`**。
逆接続保護は **rev.B の要件**として §8 の実測が終わってから設計する。
（SCHEMATIC.md §8.1・`netlist.json` の `not_on_mc_carrier_a_rev_a` と同じ内容。
 3文書で食い違いが無いことを確認済み。）

---

## 7. 組立と検査（基板を作った場合）

1. **基板単体で分圧比を検査する**（XIAO を繋ぐ前）。§5.1 の当て所にテスタを当て、
   `R2+R3` = 550k ±、`R4+R5` = 440k ± を確認。MC-CARRIER-A は
   **XIAO をはんだ付けすると取り外しが実質不可能**なので、この順序は必須。
2. **J1 と BAT ランドの導通・非導通**を確認（SCHEMATIC.md §5.4 の①②③に相当）。
3. **電池プラグの「コンタクト位置」の極性**をテスタで確認（④）。
   **線の色でも「どちらのリードが＋か」でもなく、キー面を基準にしたコンタクト位置**を見る。
4. 以上を全部通してから、はじめて電池を嵌合する。
5. ファーム側の要求（SCHEMATIC.md §7.4 / §6.4）: ウェイク後 **100ms 以上待って初回サンプルを捨てる**
   （Rth 110k/132k × 0.1µF → τ = 11.0 / 13.2ms）。`esp_adc_cal` で eFuse 校正。
   **USB挿入中は SOC 推定を無効化**。**`VBUS_SENSE` は 2.00V 閾値の二値判定にのみ使い、
   電圧値として読まない**（線形域の上端 ≈2.9V を超える）。

---

## 8. 未検証事項（発注前に潰す = assumption）

| 項目 | 状態 | 外したときの損害 |
|---|---|---|
| **XIAO カステレーションのフットプリント**（2×7 / P2.54 / 列間 17.78mm / ランド 1.6×1.8mm・外側オフセット 0.40mm） | **未検証**。17.78 = 7×2.54 は外形幅 17.8mm と整合するが実測していない | MC-CARRIER-A 5枚が全損。**必ず Seeed 公式 KiCad ライブラリ `Seeed-Studio/OPL_Kicad_Library` のフットプリントに差し替え、寸法を手打ちしないこと**（案C が使っていた 15.24mm は7ピンの列方向スパンであって列間ではない。流用禁止） |
| **XIAO パッド番号と D0..D10 の並び**（下列 = D7,D8,D9,D10,3V3,GND,5V／上列 = D6..D0） | assumption | ネットが全部ずれる。同上のライブラリで確認 |
| **XIAO 裏面 BAT+/BAT− パッドの座標** | **未実測**（README §9.1） | 窓 (10.0×12.0, 中心 30.80/38.90) を外すと MC-CARRIER-A が作り直し（+2週間） |
| **XIAO の BAT− ≡ GND** | **未検証** | 成立しないと J4 のジャンパが2本必要。SCHEMATIC.md §5.4② で確認 |
| **JST PH 嵌合高さ 7.0〜7.5mm / 嵌合体の実寸・ロール** | assumption（JST 原典PDF未取得） | §4.4 の 0.50mm 余裕が消える。**MC-SENSE-A の成立可否そのもの** |
| **XIAO スタック総厚 7.5mm** | **未実測** | MC-CARRIER-A の `XIAO_LIFT` と天井余裕が変わる |
| **JLCPCB の価格・納期** | 2026-08 の一般相場（Web検索） | 見積り画面で確認すれば済む |
| **`cad/mindclip_case.py` の相対座標バグ** | 既知（機構レビュー指摘） | MC-CARRIER-A 用に `GAP_BX`/`M_TOP` を変えると assert が落ち、STL が出せない |

---

## 9. 製造データ（`gerber/` 以下）

### 9.1 出力されるファイル

本環境に KiCad は無いが、rev.B からは **`.kicad_pcb` と同じ内部データ構造から直接**
製造データを書き出す（プロットではなく生成なので、両者は同じ幾何から作られた兄弟である）。

```
gerber/mc-sense-a/                      gerber/mc-carrier-a/
  mindclip_sense-F_Cu.gbr                 mindclip_carrier-F_Cu.gbr
  mindclip_sense-B_Cu.gbr                 mindclip_carrier-B_Cu.gbr
  mindclip_sense-F_Mask.gbr               mindclip_carrier-F_Mask.gbr
  mindclip_sense-B_Mask.gbr               mindclip_carrier-B_Mask.gbr
  mindclip_sense-F_Paste.gbr              mindclip_carrier-F_Paste.gbr
  mindclip_sense-F_Silkscreen.gbr         mindclip_carrier-B_Paste.gbr   (J4 用)
  mindclip_sense-B_Silkscreen.gbr         mindclip_carrier-F_Silkscreen.gbr
  mindclip_sense-Edge_Cuts.gbr            mindclip_carrier-B_Silkscreen.gbr
  mindclip_sense-PTH.drl                  mindclip_carrier-Edge_Cuts.gbr
  mindclip_sense-bom.csv                  mindclip_carrier-PTH.drl
  mindclip_sense-cpl.csv                  mindclip_carrier-NPTH.drl（MH1/MH2）
                                          mindclip_carrier-bom.csv / -cpl.csv
```

| 項目 | 仕様 |
|---|---|
| Gerber 形式 | **RS-274X / 4.6 形式 / mm / 絶対座標**（`%FSLAX46Y46*%` `%MOMM*%`） |
| 座標系 | **筐体座標（x右 / y上、原点 = body 外形の左下）を全層共通で使う**。Gerber は業界標準どおり「上から見た図」なので B.Cu / B.SilkS も鏡像にしない（B面の**文字だけ**鏡像で描く） |
| アパーチャ | 円 `C` / 矩形 `R` / 長円 `O` のみ。回転は 90度の倍数だけなので矩形で厳密に表せる |
| シルクの文字 | KiCad が無いので**ストロークフォントを自前で持ってベクタ化**している（英大文字・数字・記号）。したがって Gerber にも指示子とパッド名が入る |
| レジスト開口 | パッド外形 + 片側 0.05mm（`pad_to_mask_clearance`）。**ビアはテンティング**（開口しない） |
| ドリル | Excellon `M48 / FMAT,2 / METRIC,TZ`、PTH と NPTH を別ファイル |
| BOM / CPL | JLCPCB SMT 形式。**LCSC 品番欄は空**（§3 の理由） |

### 9.2 生成後に自動でやっている検査（`verify_fabrication()`）

書きっぱなしにしないため、**書き出した製造データを読み直して**次を確認している。

- `%FSLAX46Y46*%` で始まり `M02*` で終わること
- 使っている D コードが全て `%ADD..*%` で定義済みであること
- **フラッシュ座標の集合が生成元のパッド／ビア位置と完全一致**すること（欠け・余りを検出）
- 描画（`D01`）本数がトラック本数と一致すること
- ドリル穴数が THT パッド数 + ビア数と一致すること
- BOM/CPL のヘッダ行が JLCPCB の期待形式であること

### 9.3 それでも発注前に KiCad で DRC を通すこと（省略禁止）

1. KiCad 7 以降で `mindclip_sense.kicad_pcb` / `mindclip_carrier.kicad_pcb` を開く
   （version 20221018 形式）。
2. **U1 のフットプリントを Seeed 公式ライブラリ品に差し替える**（MC-CARRIER-A のみ・§8）。
3. `Inspect → Design Rules Checker` を JLCPCB ルール（線幅/間隔 0.127mm、穴 0.30mm、
   アニュラリング 0.13mm）で実行し、**エラー0** を確認する。
4. 差し替えや修正をしたら `File → Fabrication Outputs → Gerbers` + `Drill Files` で
   **KiCad 側から出し直す**（`gerber/` の中身は「そのまま発注できる形」だが、
   §8 の未検証項目を1つでも修正したら当然作り直しになる）。
5. Gerber ビューア（KiCad GerbView / JLCPCB のアップロード画面のプレビュー）で
   **全層を重ねて目視**する。特に Edge.Cuts の閉曲線と、BAT窓の位置。
6. ZIP にして JLCPCB にアップロードし、§3 の設定値を入れて発注。

> 本書の DRC は `gen_pcb.py` 内の独自実装であって KiCad の DRC ではない。
> **手順3 と手順5 を省略してはならない。**

---

## 10. 再現方法

```bash
cd hardware/pcb
python3 gen_pcb.py        # cad/mindclip_case.py を import して外形を決め、
                          # 2枚の .kicad_pcb / gerber 一式 / layout.png /
                          # layout_top.svg を生成し、
                          # S式パース・独立ジオメトリDRC・筐体干渉・
                          # netlist 突合・製造データ読み直しを検査する
python3 validate_netlist.py   # netlist.json 単体の整合（はんだ点数・分圧の再計算）
```

終了コードは検査エラー数が0なら 0。ただし **§0.1 のとおり、
`[done] independent-DRC errors=0` は「KiCad DRC を通した」という意味ではない。**
