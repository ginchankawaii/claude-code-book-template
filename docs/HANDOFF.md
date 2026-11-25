# 引き継ぎメモ（MindClip DIY）

新しいセッション（Surface のローカルなど）で作業を続けるときに、最初に読むメモ。
最終更新: 2026-11-26

## これは何か

一日中身につけて会話を録音し、家の Surface に送って、**家の中だけで**文字起こしと要約をして
Obsidian の日記に追記する装置「MindClip DIY」。
**録音データを家の外（インターネット）に一切出さない**のが絶対条件。

- 作業ブランチ: `claude/local-llm-voice-device-0hcvx9`（ここに commit して push する。PR は頼まれるまで作らない）
- ハードウェア: `hardware/`（3D データは `hardware/cad/mindclip_case.py`、組み立ては `hardware/README.md`）
- ファームウェア: `firmware/`（XIAO ESP32S3 Sense、Arduino）
- サーバ: `voice-logger/`（Docker。faster-whisper + Ollama）
- 製作ログ（note 記事の材料）: `docs/build-log.md`

## 今の状態（2026-11-25）

**ハードウェアは組み上がった。**

- 一体型の本体（MagSafe の円板付き、`stl/allday/mindclip_phonebody.stl` v1.16）に組み込み済み。フタは閉めると浮いたので、
  スーパーX で接着した（ゴム状なので、薄い刃でこじれば開けられる）。浮いた原因は未特定。
- スイッチで LED が点く（テスト用スケッチが入っている。本番ファームはまだ書き込んでいない）。
- 電池で動作、USB からの充電ランプ点滅も確認済み。
- 未確認: 30分充電して熱くならないか／外からマイクの穴 3つが見通せるか。
- アンテナ（Seeed の FPC フィルム）はフタの裏の USB 側の縁に沿って縦に貼った。電池と XIAO の真上なので、
  Wi-Fi が届くかは通信テストで確かめる必要がある。
- microSD は本体右の壁の切り欠きから外へ約 1.7mm 出ている。

## 次にやること

1. **Surface にサーバを立てる** — 手順書 `hardware/server-guide.html`（公開版: https://claude.ai/artifact/Y2jR7JB4TtgmZ8S1ApCw1C ）。
   ゴールは「Surface で録った試しの音声が Obsidian の日記に入る」まで。
   - Surface: **Surface Pro 8**（i5-1135G7、4コア8スレッド、16GB）、Windows、Docker Desktop。
     （以前は Pro 9 と書いていたが、2026-11-26 に実機で確認したら Pro 8 だった。）
     **ほかのシステム（fxsim）も Docker で動いている**ので、コンテナで分離し、干渉させない。
   - 2026-11-26 に済ませたこと: `C:\mindclip` に clone（ZIP 展開の代わり）、`.wslconfig` を新規作成（memory=12GB,
     swap=4GB。それまでは無かった）、`wsl --shutdown`（fxsim は restart=unless-stopped で自動復帰した）。
     `voice-logger/docker-compose.override.yml`（git 管理外、`.git/info/exclude`）で CPU 上限を ollama・voice-logger
     とも 4 に下げ、保管庫のマウントを差し替えた。
   - **日記の書き込み先は専用の保管庫 `C:\MindClipVault`（フォルダ `Daily Notes`）。** 既存の Obsidian 保管庫は
     毎朝クラウドの AI による自動処理が日記を読むため、そこに書くと録音の要約が家の外へ出る。利用者が専用の
     保管庫を選んだ。Obsidian で「保管庫を開く」から 2つ目の保管庫として開く。
   - **2026-11-26 に通しで動いた。** Windows 内蔵の音声合成（Haruka）で作った 16秒の試し音声を `data/inbox` に置くと、
     自動で文字起こし→要約→`C:\MindClipVault\Daily Notes\2026-11-26.md` に追記→`data/archive` へ移動した。
     処理時間（CPU 上限 4）: 文字起こし 約15秒、要約（qwen3:4b）2〜5分。初回の Whisper モデル取得で一度 DNS の
     名前解決に失敗したが、再実行で通った（`wsl --shutdown` 直後だったためと推測）。
   - 残り: 利用者の肉声（サウンド レコーダーの .m4a）での確認と、Obsidian で `C:\MindClipVault` を開いて見てもらうこと。
2. **本体とサーバをつなぐ** — プライベート CA と証明書・HMAC 鍵を作り（`voice-logger/README.md` の「PKI の用意」、
   `firmware/README.md` §4〜5）、`docker compose --profile device up -d` で受信 API を起動、本番ファームを書き込んで
   シリアルからプロビジョニング（Wi-Fi・証明書・鍵）。
3. 通しの確認（録音 → スイッチ OFF で同期 → 日記に追記）、Wi-Fi が届くか、消費電流。
4. 最後に note の記事（有料 100円程度）を Claude が書く。材料は `docs/build-log.md`。

## 利用者について（進め方の好み）

- 日本語。電子工作は初心者寄りだが、手は動く。**文章だけだとわかりにくいので、図・写真への書き込み・
  プラモの説明書のような手順図**で示すと進みが良い。
- 買い物のリンクは**実際に開けるか・在庫があるかを確かめてから**出す（以前、型違いや売り切れを買わせてしまった）。
  確かめられない場合は、そう言う。
- 実物で測っていない寸法を前提にしない。「未確認」の仮定は、組み込みの前に実物で確かめてもらう
  （SD カードのはみ出し・アンテナの大きさで失敗した）。
- 利用者の個人情報（メールアドレスなど）は外部に送らない。
- コミットメッセージやリポジトリの成果物にモデル名を書かない。
