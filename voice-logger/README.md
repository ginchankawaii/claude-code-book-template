# voice-logger — ローカル完結型・音声ライフログパイプライン (Phase 0)

録音した音声ファイルを **完全ローカル** で処理し、Obsidian の Daily Note に
日々の会話ログを自動蓄積する。音声・文字起こし・要約を外部クラウドへ送らない
（例外と前提は「[プライバシーに関する注意](#プライバシーに関する注意)」に明記）。

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

## Docker で動かす（他システムと同居するマシン向け・Windows/Surface 推奨）

ホストに Python / Ollama を直接入れたくない場合はコンテナで動かす。
`Dockerfile` / `docker-compose.yml` / `config.container.toml` が同梱されている。

前提: [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Windows は WSL2 バックエンド）。

```bash
cd voice-logger

# 1. コンテナ用設定を config.toml に（パスは全てコンテナ内パスなので編集は最小限）
cp config.container.toml config.toml

# 2. docker-compose.yml の vault マウント1行だけ自分の環境に書き換える
#      - C:/Users/you/Documents/Obsidian/MyVault:/vault

# 3. データ用フォルダを用意
mkdir -p data/inbox data/archive data/state

# 4. 起動 + LLM モデル取得（初回のみ。ここだけ外部通信が発生する）
docker compose up -d
docker compose exec ollama ollama pull qwen3:4b

# 5. 動作確認（音声を data/inbox に置いてから）
docker compose run --rm voice-logger process --dry-run /data/inbox/test.m4a
```

- 既定で常駐するのは `ollama` と `watch`（inbox 監視）だけ。ログは `docker compose logs -f`。
  `voice-logger` は `ollama` のヘルスチェックが通ってから起動する
- モデルを pull する前に音声を置いても壊れない。`watch` は
  「Ollama にモデル 'qwen3:4b' がありません。`docker compose exec ollama ollama pull qwen3:4b` …」
  とログに出して待ち、pull が終わると自動で続きを処理する（文字起こしはやり直さない）
- whisper モデルは初回実行時に named volume (`whisper_cache`) へダウンロードされる。
  2回目以降はキャッシュだけでロードし、huggingface.co へは接続しない（`[whisper] offline = "auto"`）
- Ollama はコンテナ間ネットワークに閉じ、ホストにポートを公開しない

### タイムゾーン

コンテナは何も指定しないと UTC で動き、日本では 09:00 より前の録音が前日のノートに入る
（デバイスへ返す時刻のオフセットや、受信ファイル名もずれる）。compose は全サービスに
`TZ=Asia/Tokyo` を渡している。別の地域で使う場合は `.env` に `TZ=Europe/Berlin` のように書く。
`watch` / `serve` は起動時に `ローカル時刻: 2026-08-27T09:15:00+09:00 (TZ=Asia/Tokyo)` と
ログに出すので、ここが `+00:00` になっていないことを確認する。

### メモリと CPU（16GB の Surface を想定）

| サービス | `mem_limit` | `cpus` | 内訳 |
|---|---|---|---|
| `ollama` | 6g | 6 | qwen3:4b（約 3GB）+ `num_ctx = 8192` のコンテキスト |
| `voice-logger` | 4g | 6 | whisper large-v3-turbo (int8) + 長時間録音のデコード |
| `ingest` | 256m | — | 受信APIのみ（`--profile device` のときだけ） |

合計は約 10.3GB。**WSL2 の既定の上限は搭載メモリの半分（16GB 機で 8GB）なので足りない。**
`%UserProfile%\.wslconfig` に次を書き、`wsl --shutdown` で反映する:

```ini
[wsl2]
memory=12GB
swap=4GB
```

これで Windows 側に約 4GB 残る。他のアプリが苦しい場合は `[whisper] model = "medium"` と
`voice-logger` の `mem_limit: 3g`、`.wslconfig` の `memory=10GB` に下げる。

CPU だけで qwen3:4b を回すので、`config.container.toml` は `num_ctx = 8192` /
`chunk_chars = 4000` / `think = false`（思考モードなし）/ `timeout_sec = 600` にしてある。
1時間の録音は 5〜6 チャンクに分かれ、1チャンクあたり数分かかる。`ollama` は
`OLLAMA_MAX_LOADED_MODELS=1` / `OLLAMA_NUM_PARALLEL=1` で、処理が終わって 2 分たつと
モデルをメモリから降ろす（`OLLAMA_KEEP_ALIVE=2m`）。

### デバイス受信API を使う場合（Phase 1）

`ingest` は鍵と証明書が無いと起動できないので、既定の `docker compose up` には含めていない。
[PKI の用意](#pki-の用意自宅lan用のプライベートca)の手順で `data/pki/` に
`server.crt` / `server.key` / `ca.crt` / `hmac.key` を置いてから、プロファイルを付けて起動する:

```bash
mkdir -p data/pki            # ここに鍵・証明書を置く
echo "INGEST_BIND=192.168.1.10" >> .env      # この PC の LAN 側 IP に書き換える
docker compose --profile device up -d
docker compose --profile device logs -f ingest
```

- **`INGEST_BIND` を必ず設定する。** 未設定だと 8443 が全インターフェース（公衆 WiFi に
  繋いだときのアダプタも含む）で待ち受ける。IP を固定できない場合は未設定のままにし、
  下のファイアウォール規則だけで絞る
- **Windows ファイアウォールの受信規則は「プライベート」プロファイルに限定する。**
  「セキュリティが強化された Windows Defender ファイアウォール」→ 受信の規則 で、
  Docker Desktop が作った規則（Docker Desktop Backend 等）や自分で足した TCP 8443 の規則の
  プロパティ → 詳細設定 → プロファイルを「プライベート」だけにする。
  自宅の WiFi が「パブリック」扱いになっていたら、ネットワーク設定で「プライベート」に変える
- コンテナ運用では `[ingest] allowed_networks` は**接続元の絞り込みにならない**。
  Docker の NAT を通ると全ての接続元がブリッジ GW（172.x）に見えるためで、
  `172.16.0.0/12` を許可しておく必要がある（config.container.toml には設定済み）。
  絞り込みは `INGEST_BIND` とファイアウォール、認証は mTLS + HMAC が担う
- `[ingest] host = "0.0.0.0"` の起動時警告はコンテナ運用では想定内
- 鍵や証明書のファイルが無い場合、`serve` は
  「受信APIに必要なファイルがありません: /data/pki/…」と出して終了コード 2 で終わる。
  `restart: unless-stopped` のため再起動を繰り返すので、ファイルを置くか
  `docker compose --profile device stop ingest` で止める

### 外部通信を遮断する（モデル取得後）

モデルを取り終えたら、`ollama` と `voice-logger` を外へ出られないネットワーク
（`internal: true`）に閉じ込められる。設定の誤りやライブラリの挙動に関係なく、
経路そのものが無くなる:

```bash
docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d
# デバイスも使うなら --profile device を足す
```

毎回 `-f` を付けたくなければ `.env` に `COMPOSE_FILE=docker-compose.yml;docker-compose.offline.yml`
と書く（区切りは Windows が `;`、macOS / Linux は `:`）。

- 適用前に whisper モデルのダウンロードを済ませておくこと（一度 `watch` に音声を処理させるか、
  手順 5 の `process --dry-run` を1回実行する）。未取得のまま遮断すると
  「whisper モデル … をロードできません」と出て待ち続ける
- モデルを入れ替えるときは、`-f docker-compose.offline.yml` を外して起動 → 取得 → 付け直す
- `ingest` は LAN から届く必要があるので既定のネットワークのまま
  （Ollama にも文字起こしにも触れず、自分から外へ接続する処理も無い）

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

- **いつ処理を始めるか** — 2回続けてスキャンしてサイズも更新時刻も変わらず、かつ最後の
  更新から `[watch] min_age_sec`（既定はスキャン間隔の2倍＝60秒）たったファイルだけを処理する。
  コピー途中・転送が止まったファイルを掴まないため。`.` で始まる名前（macOS の `._*`、
  Syncthing の `.stversions/` や転送中の一時ファイル）は無視する
- **処理済みと同じ内容のファイル**がまた届いたら、inbox から退かす（同じ内容が archive に
  残っていれば削除、無ければ archive へ移動）。`process` コマンドでは退かさずスキップだけする
- **失敗したとき** — 下の「[うまく動かないとき](#うまく動かないとき)」を参照

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

途中で落ちても、同じファイルをもう一度流せば同じ結果に収束する:

- 文字起こしは LLM 分析の前に `state/transcript_cache/<sha256>.json` へ保存され、再試行では
  それを使う（完了すると消える）
- ノートのブロックには音源の目印 `<!-- vl:<sha256 先頭12桁> -->` が入り、同じ目印が
  ノートにあれば追記しない。追記の直後に落ちて再処理しても、ブロックは1つのまま。
  **この行は消さないこと**（HTML コメントなので閲覧表示には出ない。編集表示では
  1行のコメントとして見える）
- ノートは「一時ファイルに書く → fsync → 置き換え」で更新するので、書き込み途中で落ちても
  手書きの内容が欠けることはない
- 台帳 `state/manifest.json` は書くたびにディスクから読み直して合流するので、`watch` の
  常駐中に `process` を別に実行しても互いの記録を消さない。台帳が壊れていた場合は
  `manifest.json.corrupt-<日時>` に退避し、空の台帳で続行する（ログに ERROR が出る）

### 既知の制約: Obsidian で編集中のノートへの追記

外部からファイルを書き換える以上、次の2つは避けられない:

- **Obsidian でそのノートを開いて入力している最中に追記が重なった場合**、Obsidian が
  未保存の編集を後から保存すると、追記したブロックが上書きされて消えることがある
  （Obsidian は入力後 約2秒で自動保存するので、重なる時間はごく短い）。
  消えた場合も文字起こしと要約は `state/transcripts/*.json` に残っている
- **Windows で Obsidian や同期ソフト・ウイルス対策がノートを掴んでいる間**は置き換えが
  拒否される。短く数回やり直し、それでもだめなら「Daily Note に書き込めません」と出して
  後で再試行する（音声は inbox に残る）

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

実際のブロックでは見出しの次の行に目印 `<!-- vl:… -->` が入る（上の例では省略）。

## うまく動かないとき

`docker compose logs -f voice-logger`（Docker を使わない場合は `watch` の出力）を見る。
失敗は2種類に分けて扱われる。

**環境側の問題 — ファイルは inbox に残り、直るまで待つ。** 失敗回数には数えない。
30秒から最大5分まで間隔を伸ばしながら再試行し、直れば自動で再開する。

| ログ | 原因と対処 |
|---|---|
| `Ollama にモデル '…' がありません` | モデル未取得。`docker compose exec ollama ollama pull qwen3:4b`（Docker なしなら `ollama pull …`） |
| `Ollama (…) に接続できません` | Ollama が起動していない / URL 違い。`docker compose ps` で `ollama` が healthy か確認 |
| `Ollama がエラーを返しました (HTTP 500…)` | 多くはメモリ不足。`.wslconfig` の `memory`、`mem_limit`、`[ollama] num_ctx` を見直す |
| `Ollama がリクエストを拒否しました` | `[ollama]` の設定（`think` に対応しないモデル等）。`think` の行を消す |
| `whisper モデル '…' をロードできません` | 初回ダウンロードにはネット接続が必要。`docker-compose.offline.yml` や `offline = true` を一度外す |
| `Daily Note に書き込めません` | vault のマウント先が違う / Obsidian や同期ソフトがノートを掴んでいる |

**そのファイルの問題 — 回数を数えて、最後は隔離する。** 壊れた音声や、LLM が何度やっても
使える答えを返さない録音など。60秒 → 2分 → 4分 … と間隔を空けて再試行し、
`[watch] max_failures`（既定 5）回失敗すると **隔離ディレクトリへ移動**して
`5 回失敗したため隔離しました: …` とログに出す。

- 隔離先は `[paths] failed`。既定は inbox の隣の `failed/`（Docker 構成ではホストの `data/failed/`）
- 削除はしない。原因を直してから inbox に戻せば、回数は 0 から数え直して再処理される
- 回数と次回の再試行時刻は `state/failures.json` に保存され、再起動しても引き継がれる。
  すぐに再試行させたいときは、このファイルを消して `watch` を再起動する
- LLM の応答待ちが `[ollama] timeout_sec` を超えた場合もこちらに数える。長い録音で
  繰り返すなら `chunk_chars` を下げる

**日付が1日ずれる / 時刻が9時間ずれる** — コンテナの TZ が効いていない。起動ログの
`ローカル時刻:` を確認する（「[タイムゾーン](#タイムゾーン)」）。

**デバイスから繋がらない** — `docker compose --profile device ps` で `ingest` が動いているか、
`.env` の `INGEST_BIND` がこの PC の現在の LAN IP と一致しているか（DHCP で変わると
コンテナが起動できない）、ファイアウォール規則が今のネットワークのプロファイルで有効かを見る。

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
同じ内容が同時に2本届いた場合も、保存されるのは1本だけ（確認から保存までを直列化している）。

**接続の持ち時間。** 同時接続は16本まで。TLS ハンドシェイクは接続ごとのスレッドで行い、
15秒以内（`socket_timeout_sec` の方が短ければそちら）に終わらない接続は切る — 何も送って
こない接続が他のクライアントを待たせることはない。各リクエストにも期限があり、
ヘッダが `socket_timeout_sec` 以内に揃わない、またはボディが
`socket_timeout_sec + Content-Length ÷ min_bytes_per_sec` 秒以内に届き終わらない接続は
サーバ側から切る（デバイスには送信失敗に見え、そのファイルは次回へ持ち越される）。

**既知の制約: HMAC はメタデータヘッダを保護しない。** 署名対象は上の5項目だけで、
`X-MindClip-Filename` / `X-MindClip-Unsynced` / `X-MindClip-Age-Ms` は含まれない。
TLS を終端できる中間者がいれば、音声の中身は変えられなくても**保存名（＝録音日時）**を
書き換えられる。これを防いでいるのは mTLS（経路の暗号化と相手の検証）なので、
`require_mtls = false` や平文での運用はしないこと。署名対象に含めるにはデバイス側の
ファームウェアと同時に変える必要がある。

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
別プロセスで常駐させる形が基本。Docker 構成では同じファイルを `data/pki/` に置く
（`ca.key` と `device.key` はサーバに置く必要が無いので、別の場所に保管する）。

## テスト

重量級依存なしで動くコアロジック（ノート挿入・日時推定）、文字起こしと LLM を差し替えた
パイプラインの耐障害性（再試行・隔離・冪等な追記・台帳）、受信APIを**実際に起動して**叩く
テスト（認証・部分受信・重複・mTLS・無応答な接続 等）。`requests` が入っていれば
Ollama クライアントのテストも走る（無ければスキップ）:

```bash
cd voice-logger
python -m pytest tests/ -q          # 推奨（PYTHONPATH は pyproject.toml で設定済み）
PYTHONPATH=src python -m unittest discover tests -v   # 素の unittest で回す場合は PYTHONPATH が要る
```

## プライバシーに関する注意

音声・文字起こし・分析結果はこのマシンのディスクにだけ保存され、推論
（faster-whisper / Ollama）もローカルで行う。**データが外に出るのは次の場合だけ**で、
どれも利用者が選ぶもの:

- **Obsidian の vault を Obsidian Sync / iCloud / OneDrive / Dropbox 等で同期している場合、
  Daily Note に書かれた要約と全文文字起こしはその同期先（＝LAN の外）へ送られる。**
  voice-logger からは止められない。外に出したくなければ、同期対象でない vault（または
  同期から除外したフォルダ）を `obsidian_vault` / `daily_notes_dir` に指定する。
  ここは利用者の判断
- **モデルの取得** — `ollama pull` と whisper モデルの初回ダウンロードは外部
  （ollama.com / huggingface.co）に接続する。送るのはモデルの要求だけで、音声や
  文字起こしは送らない

それ以外で外へ出ないようにしてある仕組み:

- Ollama への HTTP は環境変数のプロキシ設定（`HTTP_PROXY` 等）を無視して直接つなぐ。
  `[ollama] url` には自機か LAN 内のアドレスだけを書くこと（ここに外部の URL を書けば、
  当然そこへ文字起こしが送られる）
- whisper モデルはキャッシュにあれば huggingface.co へ問い合わせずにロードする
  （`[whisper] offline = "auto"`。`true` にすると初回ダウンロードも禁止）。
  huggingface_hub の利用統計は送らない（`HF_HUB_DISABLE_TELEMETRY=1`）
- Docker 構成では、モデル取得後に `docker-compose.offline.yml` を重ねると、コンテナから
  外へ出る経路そのものを無くせる（「[外部通信を遮断する](#外部通信を遮断するモデル取得後)」）
- 受信API は LAN からの接続を受けるだけで、自分から外へ接続しない

その他:

- `archive/` の生音声は蓄積し続けるので、テキスト化後 N 日で削除する等の
  ポリシー運用を推奨（将来 `voice-logger prune` として実装予定）
- `data/`（音声・鍵・証明書）と `.env` は `.gitignore` 済み。バックアップ先を選ぶときも
  同じ扱いにすること
- 他者との会話を記録する場合の配慮は設計書の「法的・倫理面」の節を参照
