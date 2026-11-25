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
   - 要約が同じ 16秒の音声で 2分→5分とばらつく。`timeout_sec = 600`（1チャンク）なので、長い録音では時間切れの
     おそれがある。一日分を流す前に、長め（数十分）の音声で確かめる。
   - 本物の録音の文字起こし・日記の中身は、クラウドの AI（Claude）のセッションに読ませない（家の外へ出るため）。
     確認はログの行・ファイルの移動・`data/failed` が空かどうかだけで行い、中身は利用者が Obsidian で見る。
   - **肉声でも確認済み（2026-11-26）。** サウンド レコーダーの .m4a（33秒）が文字起こし約20秒・要約約1分20秒で
     日記に入り、利用者が Obsidian（`C:\MindClipVault` を 2つ目の保管庫として開いた）で表示を確かめた。→ 手順1は完了。
   - 読み上げ音声の試し（作り話）の記録は、利用者の指示で日記から削除し、試しの音声ファイルも消した。
2. **【2026-11-26 済】本体とサーバをつなぐ。** 本体で話した音声が mTLS + HMAC で届き、日記に入るところまで通った。
   - PKI: CA の秘密鍵と本体の鍵は Surface の `%USERPROFILE%\.mindclip-pki`（リポジトリ外）。サーバ用の
     `server.crt/server.key/ca.crt/hmac.key` だけを `voice-logger/data/pki` に置いた（コンテナにマウントされるため）。
     サーバ証明書の SAN は `192.168.11.74`。`.env` に `INGEST_BIND=192.168.11.74`。
   - **Surface の IP は DHCP のまま。** ルーターで予約（固定）するまでは、IP が変わると証明書の作り直しになる。
   - Windows: Wi-Fi を「プライベート」に変更、受信規則「MindClip ingest 8443」（TCP 8443、Private のみ、
     ローカル 192.168.11.74、リモート LocalSubnet）を追加。Docker 関係の受信規則は元から無い（fxsim の 8000 は閉じたまま）。
   - ファーム: Surface の Arduino IDE 同梱の arduino-cli（esp32 core **3.3.12**）で `PSRAM=opi` を付けて書き込み。
     起動行 `buf=60s psram=1` を確認。フタが接着でボタンが押せないので、リセットは esptool の `read-mac`
     （`--after hard-reset`）で行い、起動直後 3秒の受付窓で CLI に入る。
   - プロビジョニングは `firmware/tools/provision.ps1`（Wi-Fi パスワードはその場で入力、鍵・パスワードは画面に出さない）。
     `test wifi` OK（**RSSI -72dBm**。目安 -75 にぎりぎり。アンテナが電池の上にある影響かも）、`test server` OK。
   - 30秒の会話 → スイッチ OFF で 4ファイル（3秒の無音で分割）が届き、文字起こし・要約されて日記に追記された。
     3秒しかない断片は 0 セグメントで、日記には書かれない。**短い断片ごとに日記の記録が分かれる**ので、
     まとめ方（`cfg.gap_sec` やサーバ側での結合）は今後の検討事項。
   - **要約が一度ハングした。** 15秒の断片で ollama の応答が 600秒来ず時間切れ → 60秒後の再試行では 10秒で完了。
     `analyze.py` の要求に `num_predict`（出力トークンの上限）が無く、JSON スキーマ付き出力が止まらなくなった可能性
     （推測・未確認）。上限を付けるのが次の手。
   - 元の手順メモ: プライベート CA と証明書・HMAC 鍵を作り（`voice-logger/README.md` の「PKI の用意」、
   `firmware/README.md` §4〜5）、`docker compose --profile device up -d` で受信 API を起動、本番ファームを書き込んで
   シリアルからプロビジョニング（Wi-Fi・証明書・鍵）。
3. 長めの録音（数十分）で要約が時間切れにならないか、身につけたときの Wi-Fi（RSSI）、消費電流（28mA ゲート）、
   Surface の IP 固定。MagSafe リングを付属の粘着で貼る（切れ目はふだんの付け方で下側に）。
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
