# keiba — JRA-VAN を見据えた競馬予想 分析層

`horse_racing`(依存ゼロのヒューリスティック版)に対し、`keiba` は **JRA-VAN
実データでの精度追求** を目的とした本格的な分析層です。リサーチ
([`../docs/RESEARCH_JRAVAN.md`](../docs/RESEARCH_JRAVAN.md))の設計指針に沿って、
**リーク防止・確率較正・市場ブレンド・回収率ベースの評価** を一気通貫で実装しています。

> ⚠️ 同梱データは **合成データ** です。現実の競馬を当てる器ではなく、配管
> (リーク防止・較正・ROI会計)の正しさを実データ無しで検証するためのものです。
> 実データでの回収率は控除率の壁により大きく下がるのが現実です。

## クイックスタート

```bash
pip install -e .          # numpy/pandas/scikit-learn/lightgbm が入ります
python -m keiba           # 合成データで分析層パイプラインを実行

# 市場効率を変えてエッジの出方を観察(0=効率的でエッジ無し 〜 大=非効率)
python -m keiba --myopia 0.3     # ほぼ効率的: 「市場に勝てない」正直な結果
python -m keiba --myopia 0.9     # 近視眼的市場: ブレンドが市場を上回る
python -m keiba --objective lambdarank   # Learning-to-Rank で学習
```

出力には **リーク監査・確率品質(Brier/LogLoss/ECE)・回収率(フラット/分数
ケリー)・モンテカルロ破産確率** が並びます。

## 設計の核(なぜ勝てる/勝てないが分かるのか)

1. **最適化対象は的中率ではなく回収率(ROI)**。控除率(単勝20%)が壁。
2. **データリークが最大の敵**。特徴量は発走前情報のみ、履歴集計は対象レース日
   より厳密に前に限定。`leakage.audit_temporal_invariance` が「未来データを消しても
   特徴量が変わらない」ことを経験的に検証する。
3. **市場は最強の予測子**。Benter 流に市場確率を別軸でブレンドし、市場が
   取りこぼす残差(本合成では form の近視眼的読み)だけを取りにいく。
4. **評価は walk-forward(時系列分割)**。ランダム分割は禁止。

## モジュール構成(M0→M4)

| モジュール | 役割 | マイルストーン |
|---|---|---|
| `synth.py` | JV-Data風の合成データ生成(Plackett-Luce で着順、近視眼的市場) | M0 |
| `reader.py` | `JVLinkReader` 抽象 + 合成/実(雛形)バックエンド | M0 |
| `schema.py` | 正規化スキーマと発走前/確定後の可用性定義 | M0 |
| `features.py` | point-in-time なリーク安全特徴量 | M1 |
| `leakage.py` | 静的検査 + 時間不変性によるリーク監査 | M1 |
| `model.py` | LightGBM(binary / lambdarank)+ レース内正規化 | M2 |
| `calibration.py` | Isotonic/Platt 較正 + Brier/LogLoss/ECE/信頼性曲線 | M2 |
| `blend.py` | 市場確率ブレンド(Benter)+ Harville 連系展開 | M4 |
| `betting.py` | EV/エッジフィルタ + 分数ケリー + モンテカルロ破産確率 | M3 |
| `backtest.py` | walk-forward 回収率バックテスト | M3 |
| `pipeline.py` / `__main__.py` | 一気通貫オーケストレーション + CLI | — |

## 実データ(JRA-VAN)への接続

取得層(Windows/32bit COM の JV-Link)と分析層(本パッケージ)は **DBファイルを
境界に疎結合** です。実データ運用時は `reader.RealJVLinkBackend`(M5)を実装して
`schema` 準拠の `runners`/`races` を供給すれば、**下流(特徴量〜バックテスト)は
無改修** でそのまま動きます。手順は [`../docs/RESEARCH_JRAVAN.md`](../docs/RESEARCH_JRAVAN.md)
第2章・第8章(ロードマップ M5〜M8)を参照。
