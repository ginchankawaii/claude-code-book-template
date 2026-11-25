# 引き継ぎメモ（MindClip DIY）

新しいセッション（Surface のローカルなど）で作業を続けるときに、最初に読むメモ。
最終更新: 2026-11-25

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
   - Surface: Surface Pro 9（Intel i5、16GB）、Windows、Docker Desktop。**ほかのシステムも Docker で動いている**ので、
     コンテナで分離し、干渉させない。`.wslconfig` は既存の設定を消さず `memory=` だけ直す。`wsl --shutdown` は
     ほかのシステムも止めるので、利用者に時間を確認してから。
   - Obsidian の保管庫の場所と、日記のフォルダ名（既定 `Daily Notes`）はまだ聞けていない。
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
