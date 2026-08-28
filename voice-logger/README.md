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

## デバイス受信API (Phase 1)

自作ウェアラブル **MindClip DIY** から音声を受け取る HTTP サーバ。プロトコルは
[`../firmware/SPEC.md`](../firmware/SPEC.md) §6 で確定済み。追加依存は無し（標準ライブラリのみ）。

```bash
voice-logger serve                    # config.toml の [ingest] に従って起動
voice-logger serve --gen-key          # 共有秘密(HMAC)を1つ生成して表示（デバイスと同じ値を使う）
voice-logger serve --allow-plaintext --host 127.0.0.1 --port 8080   # 試験用（TLSなし）
```

| エンドポイント | 用途 | 応答 |
|---|---|---|
| `GET /api/v1/time` | デバイスのRTC補正（NTPで外に出ない） | `{ok, server_epoch, tz_offset_min, iso}` |
| `POST /api/v1/ingest` | WAVの生バイト列を受信（Content-Type: `audio/wav`） | `{ok, sha256, stored_name, bytes, duplicate, server_epoch, tz_offset_min, iso}` |
| `GET /healthz` | 死活確認のみ（情報を返さない） | `{ok}` |

**認証は二重**（どちらか一方では受けない）:

- **mTLS** — プライベートCAでクライアント証明書を検証（`[ingest] client_ca`）
- **共有秘密 HMAC-SHA256** — `Authorization: MindClip-HMAC dev=…,nonce=…,sig=…`。
  署名対象は `"<method>\n<path>\n<device_id>\n<sha256_hex_of_body>\n<nonce_hex>"`。
  タイムスタンプを使わないのはデバイスのRTCが未同期でも認証を成立させるため。
  リプレイは nonce の LRU（4096件/24h）とボディ sha256 の冪等化で防ぐ。

共有秘密が1つも設定されていなければサーバは**起動を拒否する**（無認証で待ち受けない）。
TLS証明書が無い場合も同様（`allow_plaintext = true` を明示した時だけ平文で起動する）。

**受信の順序**（デバイスは 200 を見て初めてSDから削除するため、この順序が安全性そのもの）:
`inbox/*.wav.part` に書く → `fsync` → sha256照合 → `rename()` で `.wav` へ →
ディレクトリ `fsync` → **ここで 200**。`.part` は `iter_audio_files()` が拾わないので、
受信中のファイルを `watch` が処理してしまうことはない。
プロセスが強制終了されて残った `.ingest-*.wav.part` は、次の `serve` 起動時に掃除する。

**エラーの返し分け**（デバイスの動作が変わるので重要。SPEC §6.3）:

| 状況 | 応答 | デバイス側 |
|---|---|---|
| 鍵・署名・デバイスID・証明書CNの不正、nonce再利用 | **401 / 403** | セッション全体を中止（設定を直すまで直らない） |
| 受信したボディが `X-MindClip-Sha256` と一致しない・ヘッダ不整合・部分受信 | **400** | そのファイルだけ持ち越して次へ進む |
| サイズ超過 / ディスク不足 | **413 / 507** | 413は次へ、507はセッション中止 |

署名の検証対象は「デバイスが宣言した sha256」で、実ボディとの照合は別に行う。
こうしないと *SDの読み出しがぶれた1ファイル* が 401＝設定不正と誤診され、
デバイスがその晩の同期をまるごと諦めてしまう。
またエラー応答は（上限内なら）ボディを読み捨ててから返す — 読まずに切ると
送信中のデバイスには送信失敗しか見えず、413/507 の意味が伝わらないため。

`srv.url` に末尾スラッシュを入れると（`https://host:8443/`）リクエストパスが
`//api/v1/ingest` になる。この場合は署名不一致の 401 ではなく、
**理由を書いた 404** を返す（Python の `http.server` はパスを正規化してしまうため、
そのままだと原因が分からない）。

**inbox には `YYYYMMDD_HHMMSS.wav` しか置かない。** デバイスのRTCが未同期のまま録音された
ファイル（`X-MindClip-Unsynced: 1`）は `server_now − X-MindClip-Age-Ms` から正規名を復元して保存する。
同名衝突は `_1`, `_2` … を付ける（timeparse は先頭一致なので日時解釈は保たれる）。
同一 sha256 の再送は保存せず `duplicate: true` を返す（デバイスは安心して削除できる）。

### PKI の用意（自宅LAN用のプライベートCA）

```bash
mkdir -p ~/voice-logger/pki && cd ~/voice-logger/pki
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=MindClip CA" \
  -keyout ca.key -out ca.crt
# サーバ証明書（CN/SANはサーバのLAN IP）
openssl req -newkey rsa:2048 -nodes -subj "/CN=192.168.1.10" -keyout server.key -out server.csr
echo "subjectAltName=IP:192.168.1.10" > server.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 3650 \
  -extfile server.ext -out server.crt
# デバイス証明書（CNはデバイスID）
openssl req -newkey rsa:2048 -nodes -subj "/CN=mindclip-01" -keyout device.key -out device.csr
echo "extendedKeyUsage=clientAuth" > device.ext
openssl x509 -req -in device.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 3650 \
  -extfile device.ext -out device.crt
voice-logger serve --gen-key > hmac.key    # デバイスの NVS hmac.key と同じ値にする
```

`ca.crt` / `device.crt` / `device.key` / `hmac.key` をデバイスの NVS に入れる
（手順は `firmware/SPEC.md` §10.2）。運用は `serve`（受信）と `watch`（処理）を
別プロセスで常駐させる形が基本。

## テスト

重量級依存なしで動くコアロジック（ノート挿入・日時推定）と、
受信APIを**実際に起動して**叩くテスト（認証・部分受信・重複・mTLS 等）:

```bash
cd voice-logger
python -m pytest tests/ -q          # 推奨（PYTHONPATH は pyproject.toml で設定済み）
PYTHONPATH=src python -m unittest discover tests -v   # 素の unittest で回す場合は PYTHONPATH が要る
```

## プライバシーに関する注意

- 音声・文字起こし・分析結果はすべてこのマシン内に保存される。外部送信は一切ない
  （Ollama / faster-whisper ともローカル推論）
- `archive/` の生音声は蓄積し続けるので、テキスト化後 N 日で削除する等の
  ポリシー運用を推奨（将来 `voice-logger prune` として実装予定）
- 他者との会話を記録する場合の配慮は設計書の「法的・倫理面」の節を参照
