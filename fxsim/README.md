# 💱 FX Paper-Trading Simulator

Claude(Claude Code)がどれくらい FX で利益を出せるかを検証するための、
**ペーパートレード**自動売買シミュレータです。実レート（OANDA v20）を取得し、
約定はローカルでシミュレーションします。テクニカル分析とファンダメンタル分析
（Claude によるニュース分析）を組み合わせ、売買結果を SQLite に保存し、
Web GUI でグラフィカルに確認できます。

> ⚠️ これはペーパートレード（仮想売買）です。実資金の発注は行いません。
> バックテストで継続的に利益が出ることを確認してから本番（実口座）を検討してください。

---

## アーキテクチャ

```
                ┌─────────────┐
   OANDA v20 ──▶│  providers  │── sample(オフライン合成データ) も選択可
   (実レート)    └──────┬──────┘
                       │ candles
                ┌──────▼──────┐   ┌──────────────┐
                │ indicators  │   │ fundamental  │ Claude API + web 検索
                │ (テクニカル) │   │ (ニュース分析) │ → bias [-1,1]
                └──────┬──────┘   └──────┬───────┘
                       └────────┬────────┘
                          ┌─────▼─────┐  weighted blend (技術60% / ファンダ40%)
                          │ strategy  │
                          └─────┬─────┘  signal score [-1,1]
                          ┌─────▼─────┐  リスクベースのサイズ計算 + ATR ストップ
                          │  engine   │  spread / commission のコストモデル
                          └─────┬─────┘
                          ┌─────▼─────┐
                          │  SQLite   │  runs / trades / equity / signals
                          └─────┬─────┘
                          ┌─────▼─────┐
                          │  FastAPI  │  Web ダッシュボード (Chart.js)
                          └───────────┘
```

| レイヤ | ファイル | 役割 |
|---|---|---|
| 設定 | `app/config.py` | 環境変数で全挙動を制御 |
| 保存 | `app/db.py` | SQLite スキーマと CRUD |
| データ取得 | `app/providers/` | `oanda`（実レート） / `csv`（ブローカー書出しの実データ） / `sample`（オフライン） |
| テクニカル | `app/indicators.py`, `app/strategies/technical.py` | SMA/EMA/RSI/MACD/Bollinger/ATR のアンサンブル |
| ファンダ | `app/fundamental/`, `app/strategies/fundamental.py` | Claude がニュースを分析しバイアスを生成 |
| 統合戦略 | `app/strategies/combined.py` | テクニカル＋ファンダの加重ブレンド |
| 約定エンジン | `app/engine.py` | ペーパートレード、コスト/サイズ/ストップ管理 |
| バックテスト | `app/backtest.py` | 履歴をバー単位で再生し成績を算出 |
| ライブ | `app/live.py` | 新しいバー毎に1ステップ実行（実レート・仮想約定） |
| Web | `app/server.py`, `app/static/` | ダッシュボード & JSON API |

---

## セットアップ

```bash
cd fxsim
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 必要に応じて編集
```

## 使い方

### 1. オフラインのバックテスト（ネットワーク不要 / すぐ試せる）

```bash
python -m scripts.run_backtest --provider sample --instrument USD_JPY --bars 1500
```

`sample` は合成データ（ランダムウォーク）なので、利益が出ないのが正常です
（スプレッド分だけ削れます）。**戦略の有効性は実データで評価してください。**

### 2. Web ダッシュボード

```bash
python -m app.server      # http://localhost:8000
```

- リターン / 勝率 / プロフィットファクター / 最大DD / シャープ などの指標カード
- エクイティカーブ、価格＋売買マーカー、シグナル分解（テクニカル/ファンダ/統合）
- 取引履歴テーブル、ファンダメンタル見解
- 画面から新規バックテストを実行可能

### 3. 自分のブローカーのCSVで実データ・バックテスト（許可リスト不要）

セントラル短資FX など、外部APIを持たないブローカーでも、書き出した
ヒストリカルCSVをそのまま使えます。**ネットワーク設定は一切不要**です。

```bash
# data/USD_JPY.csv に置く（列名は日本語/英語どちらでも自動判定）
python -m scripts.run_backtest --provider csv --instrument USD_JPY --bars 5000
```

対応フォーマット（自動判定）:
- 区切り: カンマ / タブ / セミコロン
- 文字コード: UTF-8 / Shift-JIS(cp932)
- 列名: `日時/始値/高値/安値/終値/出来高` や `Date,Time,Open,High,Low,Close`、
  ヘッダ無しの MT4/MT5 形式（`date time o h l c vol`）など
- ファイル名: `USD_JPY.csv` / `USDJPY.csv` / `usd_jpy.csv` 等

> 注: セントラル短資FXは外部から呼べる売買APIを公開していないため、**ライブ**の
> リアルタイム取得はできません。実データのバックテストは上記CSVで、ライブの
> リアルタイム判定が必要なら無料の OANDA practice 口座を「データ取得専用」に
> 使うのがおすすめです（入金・発注は不要）。

### 4. 実レートでのバックテスト / ライブ（OANDA）

```bash
export FXSIM_PROVIDER=oanda
export OANDA_API_TOKEN=<practice トークン>
export OANDA_ENV=practice
python -m scripts.run_backtest --provider oanda --instrument USD_JPY --bars 2000
python -m scripts.run_live --instrument USD_JPY --granularity M15
```

---

## ⚠️ ネットワーク許可リスト（重要）

Claude Code on the web の実行環境はネットワークポリシーで外部アクセスを
制限しています。本ツールが実レート / ニュースを取得するには、以下のホストを
許可リストに追加してください（環境設定で変更可能）:

| 用途 | ホスト |
|---|---|
| OANDA 実レート（practice） | `api-fxpractice.oanda.com` |
| OANDA 実レート（live） | `api-fxtrade.oanda.com` |
| ファンダ分析（Claude API） | `api.anthropic.com` |

許可リスト設定前は `FXSIM_PROVIDER=sample` / `FXSIM_FUND_MODE=file` で
完全オフライン動作します。
詳細: https://code.claude.com/docs/en/claude-code-on-the-web

---

## ファンダメンタル分析の3モード（`FXSIM_FUND_MODE`）

- `stub` … 常に中立（テクニカルのみで評価したいとき）
- `file` … `data/fundamental.json` のキャッシュを読む（既定）。Claude が随時更新可能
- `anthropic` … Claude API + web 検索で実ニュースを読み、`{bias, reason, half_life_hours}`
  を生成して `data/fundamental.json` にキャッシュ（`ANTHROPIC_API_KEY` が必要）

バイアスは `asof` からの経過時間で線形に減衰し、古いニュースが取引を支配しないように
なっています。

---

## リスク / サイズ計算

- 1トレードの損失は `FXSIM_RISK`（既定 2%）× 現在エクイティ
- ストップ = 1.5 × ATR、利確 = 2 × ストップ（リワード:リスク = 2:1）
- 口座通貨はペアの**クォート通貨**（USD_JPY なら JPY）と仮定（単一ペアの厳密計算のため）
- コスト: スプレッド（`FXSIM_SPREAD_PIPS`）＋手数料（`FXSIM_COMMISSION` / 100万通貨）

## テスト

```bash
python -m pytest tests/ -q
```

## 既知の制約 / 今後

- 現状は単一ペアを想定（複数ペア同時運用は今後）
- `sample` データはランダムで、利益検証には不適（実データを使用すること）
- 本番（実発注）は未実装 — OANDA の order API を engine に差し込めば拡張可能
