# 競馬予想 (Horse Racing Prediction)

馬の各種属性から **レースの着順と勝率** を予想する、外部依存ゼロ（Python 標準ライブラリのみ）のツールです。
ルールベースのスコアリングと softmax による勝率推定を行うため、**決定論的で結果が再現可能**です。

## 特徴

- 依存パッケージなし（Python 3.9+ ならそのまま動く）
- スピード指数・近走成績・斤量・人気オッズ・騎手評価・馬場適性の6項目から合成スコアを算出
- softmax の「温度」で本命寄り／穴党寄りの確率分布を調整可能
- CSV 入力対応、サンプルレース同梱、pytest テスト付き

## 使い方

```bash
# サンプルレース（8頭立て）を予想
python -m horse_racing

# 自前の CSV を読み込んで予想
python -m horse_racing data/sample_race.csv

# 温度を下げて本命に確率を集中させる
python -m horse_racing -t 0.2

# サンプル CSV を書き出す
python -m horse_racing --write-sample data/sample_race.csv
```

出力例:

```
 着 馬名                      勝率     スコア
-------------------------------------
 1 サンダーボルト              39.3%   3.391
 2 ミラクルスター              22.8%   3.201
 ...
◎ 本命: サンダーボルト (勝率 39.3%)
```

## CSV フォーマット

`name` 列のみ必須。その他は省略すると既定値が使われます。

| 列名 | 意味 | 例 | 備考 |
|------|------|----|------|
| `name` | 馬名（必須） | サンダーボルト | |
| `speed` | スピード指数 | 108 | 大きいほど速い (0–120目安) |
| `recent_form` | 近走平均着順 | 1.8 | **小さいほど好成績** |
| `weight` | 斤量 (kg) | 57 | **軽いほど有利** |
| `odds` | 単勝オッズ | 3.2 | **低いほど人気=強い** |
| `jockey` | 騎手評価 | 85 | 0–100、大きいほど好騎手 |
| `going_fit` | 馬場・距離適性 | 78 | 0–100 |

## ライブラリとして使う

```python
from horse_racing import Horse, predict_race

race = [
    Horse("サンダーボルト", speed=108, recent_form=1.8, odds=3.2),
    Horse("ミラクルスター", speed=104, recent_form=2.6, odds=4.5),
]
for p in predict_race(race):
    print(p.rank, p.horse.name, f"{p.win_probability:.1%}")
```

## 予想ロジック

各特徴量を概ね 0–1 に正規化（「小さいほど有利」な項目は反転）し、重み付き和で合成スコアを算出します。
オッズは対数スケールで扱います。勝率はスコアの softmax で、`temperature` が小さいほど上位馬に確率が集中します。

> ⚠️ これは学習・デモ目的のヒューリスティックモデルです。実際の馬券購入を保証・推奨するものではありません。

## テスト

```bash
pip install pytest
python -m pytest
```
