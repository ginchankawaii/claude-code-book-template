# rakuten-portfolio-mcp

楽天証券の保有商品・信用建玉をローカルで正規化して、Claude に渡す MCP サーバー。
「俺のポートフォリオ見て、信用のリスクどう？」に数字で答えられるようにするためのもの。

## 前提: 楽天証券に「AIが取りに行ける口」は無い

作る前に確認したこと。

| 経路 | 状態 |
| --- | --- |
| 楽天証券の公式 REST API | 提供されていない |
| iSPEED の外部連携 API | 無い（表示専用アプリ） |
| 公式 MCP サーバー | 無い |
| マーケットスピード II RSS | あり。ただし Windows + Excel 限定 |
| マネーフォワード ME / Moneytree LINK | 楽天証券の資産は取り込めるが、API は法人契約のみ |
| 個人に REST API を開放している証券会社 | 三菱UFJ eスマート証券（kabu STATION API）、立花証券（e支店API）。楽天・SBI は非対応 |

自動ログインによるスクレイピングは規約・2FA・DOM 変更の三重苦なので採らない。
**CSV を人が落として、正規化と分析を機械がやる**という分担にしている。
CSV ダウンロードは週1回30秒。それ以外は全部このサーバーがやる。

## できること

- 楽天証券の保有商品一覧 CSV（Shift_JIS・セクション分割・列名の揺れ込み）を読む
- 現物・信用建玉・投資信託・現金を1つのモデルに正規化する
- **委託保証金維持率**と「**あと何%下げたら追証か**」を算出する
- 現物と信用建玉を**通算した**銘柄集中度（iSPEED ではタブが分かれていて見えない部分）
- 一律ショック・個別銘柄ショックのストレステスト
- NISA / 課税口座を分けた損益と概算税額、損益通算の候補
- 制度信用の返済期限（建日から6ヶ月）の管理
- スナップショットを保存して「先月から何が変わったか」を比較

売買の結論はサーバー側で出さない。数値と機械判定できる注意フラグだけを返し、
解釈と助言は Claude 側に任せる設計にしてある。

## セットアップ

```bash
cd rakuten-portfolio-mcp
uv sync            # または: pip install -e .
```

### Claude Code に登録する

```bash
claude mcp add rakuten-portfolio \
  --env RPM_DATA_DIR=/絶対パス/rakuten-portfolio-mcp/data \
  -- uv --directory /絶対パス/rakuten-portfolio-mcp run rakuten-portfolio-mcp
```

### Claude Desktop に登録する

`claude_desktop_config.json` に追記する。

```json
{
  "mcpServers": {
    "rakuten-portfolio": {
      "command": "uv",
      "args": ["--directory", "/絶対パス/rakuten-portfolio-mcp", "run", "rakuten-portfolio-mcp"],
      "env": { "RPM_DATA_DIR": "/絶対パス/rakuten-portfolio-mcp/data" }
    }
  }
}
```

## データの置き方

### 1. CSV を落とす

楽天証券Web にログインして、以下を `data/` に保存する。

- 「保有商品一覧」→ CSV ダウンロード
- 「信用建玉一覧」→ CSV ダウンロード

1ファイルに現物と信用が混在していても、別々のファイルでも読める。

### 2. 保証金情報を手入力する

**維持率の計算にはこれが必須**。CSV に保証金が載っていないことが多いので、
`data/portfolio.example.yaml` を `data/portfolio.yaml` にコピーして
`margin_account` を埋める（iSPEED の信用建余力画面か、楽天証券Web の信用取引 > 保証金状況）。

```yaml
margin_account:
  cash_deposit: 800000        # 保証金現金
  substitute_value: 1200000   # 代用有価証券の時価（掛目適用前）
  substitute_haircut: 0.8     # 楽天証券の代用掛目は原則80%
```

同じ YAML に、CSV で取れない銘柄を手入力で足すこともできる。
**CSV と YAML の両方に同じ銘柄を書くと二重計上になる**（検出したら警告を出す）。

### 3. 使う

```
> 俺のポートフォリオ見てアドバイスして
> 信用の維持率どうなってる？あと何%下げたら追証？
> ソニーが決算で20%飛んだらどうなる？
```

`/portfolio_review` `/margin_check` のプロンプトも用意してある。

## MCP ツール

| ツール | 用途 |
| --- | --- |
| `get_advice_brief` | 全部入り。「見て」と言われたらまずこれ |
| `get_portfolio` | 正規化済みのポジション一覧 |
| `get_margin_status` | 維持率、追証までの下落率、期日の近い建玉 |
| `analyze_concentration` | 現物＋信用を通算した集中度と HHI |
| `simulate_shock` | 一律下落シナリオでの損益と維持率 |
| `simulate_single_name` | 特定銘柄だけが動いた場合の影響 |
| `list_expiring_margin` | 返済期限が近い建玉 |
| `get_pnl_summary` | NISA/課税別の損益、概算税額、損益通算の候補 |
| `save_snapshot` / `list_snapshots` / `compare_snapshots` | 時系列比較 |
| `list_sources` / `inspect_file` | データの鮮度確認と CSV の読み取り診断 |

## 環境変数

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `RPM_DATA_DIR` | `./data` | CSV と YAML を置くフォルダ |
| `RPM_MAINTENANCE_THRESHOLD` | `20` | 最低委託保証金維持率(%) |
| `RPM_WARNING_THRESHOLD` | `30` | 警戒ライン(%) |
| `RPM_INITIAL_MARGIN_RATE` | `30` | 新規建に必要な委託保証金率(%) |
| `RPM_SUBSTITUTE_HAIRCUT` | `0.8` | 代用有価証券の掛目 |
| `RPM_TAX_RATE` | `0.20315` | 譲渡益課税率 |
| `RPM_PRICE_SOURCE` | `stooq` | 株価の補完取得元。`none` で無効化 |
| `RPM_USDJPY` | 自動取得 | 円換算レートの固定値 |

## 動作確認

MCP に繋ぐ前に CLI で確認できる。CSV がちゃんと読めているかはここで見るのが早い。

```bash
uv run rakuten-portfolio sources                  # 読み込み対象の一覧
uv run rakuten-portfolio inspect あなたのCSV名.csv  # 文字コードと認識した列
uv run rakuten-portfolio brief                    # 全部入り
```

サンプルデータで試す場合:

```bash
RPM_DATA_DIR=samples uv run rakuten-portfolio margin
```

テスト:

```bash
uv run --extra dev pytest
```

## 計算の前提

- 委託保証金維持率 = (受入保証金 + 建玉評価損益) ÷ 建玉代金合計 × 100
- 「あと何%下げたら追証か」は、維持率が株価に対して1次式であることを使って解析的に解いている。
  **代用有価証券も株価と一緒に目減りする分を式に含めている**（ここを落とすと追証までの距離を甘く見積もる）
- 買建と売建が相殺していると株価がいくら動いても閾値に届かないことがある。
  その場合は `margin_call_reachable: false` を返す
- ストレステストは全銘柄が同率で動く単純モデル。ベータ・相関・流動性は考慮していない
- 制度信用の返済期限は建日から6ヶ月として補完する。一般信用（無期限）は補完しない
- 投資信託の基準価額は1万口あたりとして評価額を計算する
- 税額は概算。繰越控除・配当との通算・特定口座の源泉徴収の扱いは考慮していない

## 制限

- **リアルタイムではない**。CSV を落とした時点のスナップショット。
  現在値だけは stooq から補完を試みるが、取得できなければ取得単価ベースで計算し警告を出す
- 発注はできないし、するつもりもない。読むだけ
- 外部ネットワークが塞がれた環境では株価補完が効かない。`RPM_PRICE_SOURCE=none` にするか、
  YAML に `last_price` を書く

## 免責

自分の口座データを整理して眺めるための道具であって、投資助言ではない。
数字は入力した CSV / 手入力の正確さに依存する。発注判断は自己責任で。

`data/` の中身は `.gitignore` で除外している（テンプレート以外はコミットされない）。
実際の口座データを公開リポジトリに push しないよう注意。
