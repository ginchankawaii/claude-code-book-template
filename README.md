# 日本株 投資シミュレーター（仮想資金）

Claude が日本株の売買をどこまでできるかを、**リアルマネーを使わず**に試すための
投資シミュレーターです。実際の株価データを取得し、仮想資金で売買を行い、
売買履歴と損益を SQLite3 に保存して Web ダッシュボードで確認できます。

売買の判断は **Claude API（AIアドバイザー）** が自動で行えます。手動売買も可能です。

> ⚠️ これはあくまで学習・実験用のシミュレーターです。投資助言ではありません。
> 公開を想定していない個人利用向けの構成です。

## 主な機能

- 📊 **ポートフォリオ・ダッシュボード**: 総資産・現金・評価額・損益をひと目で確認
- 📈 **価格チャート**: 各銘柄の日足チャートとテクニカル指標（移動平均・RSI・トレンド）
- 🤖 **AI売買判断 (Claude)**: 価格履歴・指標・保有状況を Claude に渡し、
  BUY / SELL / HOLD・数量・確信度・根拠を構造化出力。自動執行も選択可能
- 🛒 **手動売買**: 単元株（100株）単位で買い／売り
- 🗒️ **履歴の保存**: 取引履歴・AI判断ログを SQLite3 に保存し UI で閲覧
- 👀 **ウォッチリスト**: 任意の証券コードを登録して一覧監視

## 技術構成

| レイヤ | 採用技術 |
| --- | --- |
| バックエンド | Python / FastAPI |
| データベース | SQLite3（標準ライブラリ） |
| 株価データ | Yahoo Finance / Stooq（APIキー不要）／ オフライン用 mock |
| AI判断 | Anthropic Claude API（`anthropic` SDK、構造化ツール出力） |
| フロントエンド | バニラ JS + Chart.js（ローカル同梱） |

## セットアップ

```bash
# 1. APIキー等を設定（AI判断を使う場合）
cp .env.example .env
#   .env を編集して ANTHROPIC_API_KEY を設定

# 2. 起動（仮想環境作成・依存インストール・サーバ起動を自動で実行）
./run.sh
```

ブラウザで <http://127.0.0.1:8000> を開きます。

手動で起動する場合:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 設定（環境変数 / `.env`）

| 変数 | 既定値 | 説明 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | （空） | Claude API キー。未設定だと AI判断は無効 |
| `ADVISOR_MODEL` | `claude-sonnet-4-6` | 判断に使う Claude モデル |
| `MARKET_DATA_SOURCE` | `yahoo` | `yahoo` / `stooq` / `mock` |
| `MARKET_FALLBACK_TO_MOCK` | `true` | 実データ取得失敗時に mock へ自動切替 |
| `STARTING_CASH` | `1000000` | 初期の仮想資金（円） |
| `TRADE_UNIT` | `100` | 単元株数 |
| `DEFAULT_WATCHLIST` | 主要6銘柄 | 初期ウォッチリスト（コードをカンマ区切り） |

### 株価データソースについて

- `yahoo` / `stooq` は実際の株価を取得します（APIキー不要）。**ネットワークが
  これらのホストへ到達できる必要があります**。
- ネットワークが制限された環境（許可リスト制のサンドボックス等）では、
  `MARKET_DATA_SOURCE=mock` を使うと、証券コードから決定論的に生成される
  擬似データで全機能をオフライン動作させられます。
- `MARKET_FALLBACK_TO_MOCK=true`（既定）の場合、実データ取得に失敗すると
  自動的に mock にフォールバックします。

## API エンドポイント

| メソッド | パス | 説明 |
| --- | --- | --- |
| GET | `/api/status` | データソース・AI有効状態など |
| GET | `/api/portfolio` | 現金・保有・評価額・損益 |
| GET | `/api/quote/{code}` | 現在値 |
| GET | `/api/history/{code}?days=120` | 価格履歴＋指標 |
| GET | `/api/trades` | 取引履歴 |
| POST | `/api/trade/buy` / `/api/trade/sell` | 手動売買 `{code, quantity}` |
| GET / POST / DELETE | `/api/watchlist` | ウォッチリスト管理 |
| POST | `/api/advisor/decide` | 1銘柄を Claude が判断 `{code, auto_execute}` |
| POST | `/api/advisor/run-all` | ウォッチリスト全件を判断 |
| GET | `/api/decisions` | AI判断ログ |
| POST | `/api/reset` | シミュレーションを初期化 |

## ディレクトリ構成

```
app/
  config.py       設定（環境変数の読み込み）
  database.py     SQLite スキーマ・初期化
  market.py       株価取得（yahoo / stooq / mock）
  indicators.py   テクニカル指標
  engine.py       売買執行・ポートフォリオ計算
  advisor.py      Claude API による売買判断
  main.py         FastAPI（REST + 静的配信）
static/           フロントエンド（HTML / CSS / JS, Chart.js 同梱）
tests/            pytest（engine / market）
data/             SQLite DB（gitignore 対象）
```

## テスト

```bash
source .venv/bin/activate
pytest -q
```

売買ロジック・損益計算・データ取得（mock）を検証します（ネットワーク不要）。

## 仕組み（AI判断）

`app/advisor.py` が、対象銘柄の価格履歴・テクニカル指標・現在の保有状況・
利用可能資金をまとめて Claude に渡し、`submit_decision` ツールで
`action / quantity / confidence / rationale` を構造化出力させます。
`auto_execute` が有効なら、その判断に従って `engine.py` が売買を執行し、
すべての判断と取引を SQLite3 に記録します。
