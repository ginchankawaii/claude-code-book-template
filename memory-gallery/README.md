# memory-gallery

覚えたい素材を手描き風マインドマップ画像にして Notion ギャラリーに貯める記憶符号化システム。
設計・制約は **CLAUDE.md（引き継ぎ書）が正**。

- **既定モード（v2）**: 素材（テキスト/画像）→ 構造化マインドマップ → 忠実性チェック → 手描き風イラスト（Nano Banana / Gemini）→ Notion カードのカバー＋本文に自動添付
- **v1 連想鎖モード（`--chains`）**: アンカー台帳ベースの連想鎖3案＋Mermaid（画像生成なし）

## セットアップ（Docker 推奨）

```bash
cp .env.example .env   # NOTION_TOKEN / ANTHROPIC_API_KEY / GEMINI_API_KEY を記入
                       # GEMINI_API_KEY は既定（v2）の作画フローに必須。
                       # https://aistudio.google.com/apikey で発行（--chains だけ使うなら不要）
docker compose build
docker compose run --rm mg python -m src.main run --dry-run   # 動作確認
```

夜間バッチや対話実行も同じ形:

```bash
docker compose run --rm mg python -m src.main run          # 対話（構造の本人確認あり）
docker compose run --rm mg python -m src.main run --yes    # 無人バッチ
docker compose run --rm mg python -m src.main run --chains # v1 連想鎖モード
docker compose run --rm mg python -m unittest discover -s tests   # テスト
```

### Docker を使わない場合

```bash
pip install -r requirements.txt
cp .env.example .env   # NOTION_TOKEN / ANTHROPIC_API_KEY / GEMINI_API_KEY を記入
```

## 使い方

```bash
# 既定（v2）: 連想鎖が空の記憶カードをマインドマップ画像にして Notion に添付
python3 -m src.main run

# 作画・書き込みなしで動作確認（構造抽出まで）
python3 -m src.main run --dry-run

# 特定カードだけ処理
python3 -m src.main run --card <page_id>

# 夜間バッチ（確認プロンプトなし。素材のないカードは処理しない）
python3 -m src.main run --yes

# v1 連想鎖モード（アンカー台帳ベースの3案生成＋Mermaid。画像生成なし）
python3 -m src.main run --chains
python3 -m src.main run --chains --yes   # 無人（事実照合ゲートを通った場合のみ書き込み）
```

### 夜間バッチ例（cron）

```
0 3 * * * cd /path/to/memory-gallery && python3 -m src.main run --yes >> batch.log 2>&1
```

## フロー（既定: v2 マインドマップ画像）

```
記憶カードに素材を追加（本文にテキスト or 表スクショ/図の画像）
  → notion.py  未処理カード＋アンカー台帳DB＋本文の素材（テキスト/画像）を取得
  → mindmap.py Claude が素材から構造化マインドマップを抽出（素材にない事実は入れない）
  → mindmap.py 忠実性チェック（誤りを絵にしない。素通し禁止）
  → graph.py   要所1〜3箇所にアンカー・既習カードを結線（v3。人名等は静的チェックで遮断）
  → interview.py 台帳に効くアンカーが無ければ本人に質問して新アンカーを発掘
                （v3.1。対話モードのみ。y確認で状態=採用のまま台帳に追加→即結線）
  → render.py  Nano Banana (Gemini) が構造を一字一句保ったまま手描き風イラスト化
  → notion.py  カバー＋本文に画像添付、Mermaid（検証用の正）も本文へ
閲覧 = 記憶カードDBのギャラリービューを眺めるだけ
```

## v1 連想鎖モード（--chains）

```
記憶カードに1行追加（テキスト or 画像添付）
  → notion.py  未処理カード＋アンカー台帳DBを取得
  → chain.py   （画像なら）事実抽出 → 連想鎖3案
  → gate.py    事実照合ゲート（NGなら書き込まない）
  → skeleton.py 各案を Mermaid 化（検証用の正）
  → notion.py  カードへ書き戻し、状態=一言待ち
  → 【人間】「自分の一言」を手で書く → Ping-t へ戻る
```

※ 台帳に「状態=採用 かつ 未使用」の属性アンカー1件＋感情アンカー1件以上が必要
（足りない場合はカード処理前に案内を出して終了する）。

## テスト

```bash
python3 -m unittest discover -s tests
```
