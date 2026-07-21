# memory-gallery

Ping-t で繰り返し落ちる項目に、個人アンカー経由の連想鎖を張る記憶符号化システム。
設計・制約は **CLAUDE.md（引き継ぎ書）が正**。v1 ＝ 連想鎖＋Mermaid のみ（画像生成 L3 は測定ゲート後）。

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env   # NOTION_TOKEN / ANTHROPIC_API_KEY を記入
```

## 使い方

```bash
# 連想鎖が空の記憶カードを処理（画像入力カードは「覚えたい事実」の確認プロンプトあり）
python3 -m src.main run

# 書き込みなしで動作確認
python3 -m src.main run --dry-run

# 特定カードだけ処理
python3 -m src.main run --card <page_id>

# 夜間バッチ（確認プロンプトなし。画像入力カードは事実照合ゲートを通った場合のみ書き込み）
python3 -m src.main run --yes
```

### 夜間バッチ例（cron）

```
0 3 * * * cd /path/to/memory-gallery && python3 -m src.main run --yes >> batch.log 2>&1
```

## フロー（v1）

```
記憶カードに1行追加（テキスト or 画像添付）
  → notion.py  未処理カード＋アンカー台帳DBを取得
  → chain.py   （画像なら）事実抽出 → 連想鎖3案
  → gate.py    事実照合ゲート（NGなら書き込まない）
  → skeleton.py 各案を Mermaid 化（検証用の正）
  → notion.py  カードへ書き戻し、状態=一言待ち
  → 【人間】「自分の一言」を手で書く → Ping-t へ戻る
```

## テスト

```bash
python3 -m unittest discover -s tests
```
