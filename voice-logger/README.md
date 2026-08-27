# voice-logger — ローカル完結型・音声ライフログパイプライン (Phase 0)

録音した音声ファイルを **完全ローカル** で処理し、Obsidian の Daily Note に
日々の会話ログを自動蓄積する。外部クラウドには一切データを送らない。

```
音声ファイル → faster-whisper (Silero VAD内蔵) → Ollama (ローカルLLM)
            → 要約・ToDo抽出・振り返り → Obsidian Daily Note 追記
```

設計全体は [`../docs/local-llm-voice-logger-design.md`](../docs/local-llm-voice-logger-design.md) を参照。
Phase 0 では音源はスマホ・ICレコーダー等の手持ち録音で、自作ウェアラブル（Phase 1）が
完成したら inbox に音声が自動投入されるようになるだけで、この部分は変更不要。

## セットアップ

前提: Python 3.11+、[Ollama](https://ollama.com) がローカルで稼働していること。
GPU があれば faster-whisper が自動で使う（CPUでも動くが遅い）。

```bash
cd voice-logger

# 仮想環境 + インストール（uv 推奨。pip なら python -m venv .venv && pip install -e .）
uv venv && uv pip install -e .

# LLMモデルの取得（例）
ollama pull qwen3:14b

# 設定
cp config.example.toml config.toml
$EDITOR config.toml   # Obsidian vault のパス等を自分の環境に合わせる
```

## 使い方

```bash
# 音声ファイルやディレクトリを指定して処理
voice-logger process ~/Recordings/2026-08-27_09-15-00.m4a

# まずは書き込みなしで出力を確認
voice-logger process --dry-run ~/Recordings/test.m4a

# inbox ディレクトリを監視して自動処理（常駐運用）
voice-logger watch
```

`watch` は inbox に置かれた音声を自動で処理する。スマホからは Syncthing /
AirDrop / SMB 共有などで inbox にファイルを送るだけでよい（この経路も LAN 内で完結する）。

## 処理の流れと成果物

1件の音声につき:

1. **文字起こし** — faster-whisper（`vad_filter=True` で無音除去込み）
2. **録音開始時刻の推定** — ファイル名の日時パターン（`2026-08-27_09-15-00` 等）、
   無ければ mtime − 録音長 にフォールバック
3. **LLM分析** — Ollama の structured outputs で要約 / ToDo / トピック / 振り返りをJSON取得。
   長い録音はチャンク分割 → 統合（map-reduce）
4. **Daily Note 追記** — `vault/Daily Notes/YYYY-MM-DD.md` の
   `## 🎙️ 会話ログ（自動生成）` セクション末尾にブロック挿入。
   手書きの既存セクションは壊さない。全文文字起こしは折りたたみ callout に格納
5. **後始末** — 文字起こしJSONを `state/transcripts/` に保存、音声を `archive/YYYY-MM/` へ移動、
   台帳（sha256）に記録して同一ファイルの二重処理を防止

生成されるノートの例:

```markdown
## 🎙️ 会話ログ（自動生成）

### 🎧 09:15–11:15（2026-08-27_09-15-00.m4a）
**サマリー**: 朝の予定確認の会話。資料送付の約束をした。
**トピック**: 予定確認、資料送付
**振り返り**: 朝のうちにタスクを整理できた一日だった。

**ToDo / 約束**
- [ ] 山田さんに資料を送る

> [!note]- 全文文字起こし
> - 09:15 おはようございます、今日の予定を確認しましょう。
```

## テスト

重量級依存なしで動くコアロジック（ノート挿入・日時推定）のテスト:

```bash
PYTHONPATH=src python -m unittest discover tests -v
```

## プライバシーに関する注意

- 音声・文字起こし・分析結果はすべてこのマシン内に保存される。外部送信は一切ない
  （Ollama / faster-whisper ともローカル推論）
- `archive/` の生音声は蓄積し続けるので、テキスト化後 N 日で削除する等の
  ポリシー運用を推奨（将来 `voice-logger prune` として実装予定）
- 他者との会話を記録する場合の配慮は設計書の「法的・倫理面」の節を参照
