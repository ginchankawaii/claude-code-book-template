# Surface（Windows）セットアップ手順

**ホストに入れるのは Docker Desktop と Git だけ。Python はホストに入れません。**
Python もライブラリも全てコンテナの中に閉じ込めるので、
このPCの他の Python 環境とは一切干渉しません。

---

## 0. ホストに入れるもの（この2つだけ）

```powershell
winget install --id Docker.DockerDesktop -e
winget install --id Git.Git -e
```

- Docker Desktop は WSL2 を要求します。求められたら有効化して **PC を再起動**。
  初回起動時の「Use WSL 2 based engine」は有効のままにする。
  ダウンロードは数GBあります。
- Git は Python とは無関係のツールなので、既存環境に影響しません。
  どうしても入れたくなければ、GitHub の Code → Download ZIP でも代用できます。

入れたら PowerShell を開き直して確認：

```powershell
docker --version
docker compose version
git --version
```

`docker` が見つからない場合は Docker Desktop が起動していません。
タスクトレイのクジラのアイコンが動いているか確認してください。

---

## 1. C直下に置く

Documents 配下は OneDrive 同期になっていることが多く、`.git` や
中間ファイルが同期対象になって面倒が起きます。C直下が無難です。

```powershell
cd C:\
git clone https://github.com/ginchankawaii/claude-code-book-template.git jquants
cd C:\jquants
git checkout claude/earnings-revision-backtest-xsamsb
cd backtest
```

ブランチが見つからないと言われたら：

```powershell
git fetch origin
git checkout -b claude/earnings-revision-backtest-xsamsb origin/claude/earnings-revision-backtest-xsamsb
```

`C:\` に書き込めない場合は PowerShell を「管理者として実行」でやり直し、
作成後に自分のユーザーへ権限を付けておくと以後が楽です：

```powershell
icacls C:\jquants /grant "$($env:USERNAME):(OI)(CI)F"
```

---

## 2. APIキーを .env に置く

```powershell
Copy-Item .env.example .env
notepad .env
```

`JQUANTS_API_KEY=` の右に、ダッシュボードの [API Keys] で発行したキーを
貼って保存します。`.env` は `.gitignore` 済みなので GitHub には上がりません。

---

## 3. probe を回す（ビルド不要・1コマンド）

```powershell
docker compose run --rm probe
```

`python:3.12-slim` の使い捨てコンテナで `probe_standalone.py` を実行します。
イメージのビルドは不要です（初回のみ 50MB 程度のダウンロード）。

確認するのは4点：

```
[ ] エンドポイントのパス（推定のものは候補を順に試して当たりを探す）
[ ] 実際の列名（config.yaml と突き合わせる）
[ ] DocType の実際の値（業績予想修正 / 配当予想修正 / 決算短信の区別）
[ ] 上場廃止銘柄が過去データに残っているか   ← 最重要
```

結果は `C:\jquants\backtest\probe_result.txt` に出ます。

```powershell
notepad probe_result.txt
```

中身をそのまま共有してください。**APIキーは含まれません。**

TOPIX が 403 になるのは Free プランでは正常です（TOPIX は Light 以上）。

---

## 4. 本番環境を作る（probe の結果を反映してから）

```powershell
docker compose build
docker compose run --rm --entrypoint python erb -m pytest -q
```

`61 passed` と出れば正常です（合成データによるテスト）。

### 使い方

```powershell
docker compose run --rm erb probe        # 列名の突き合わせ（パッケージ版）
docker compose run --rm erb histogram    # 修正率の分布
docker compose run --rm erb run          # グリッド実行
```

データは `C:\jquants\backtest\data\` に置き、結果は
`C:\jquants\backtest\results\` に出ます。どちらもホスト側のフォルダなので
エクスプローラからそのまま開けます。

---

## つまずきやすい点

| 症状 | 原因と対処 |
|---|---|
| `docker` が見つからない | Docker Desktop が未起動。タスクトレイのクジラを確認 |
| `env file .env not found` | 手順2をやっていない。`Copy-Item .env.example .env` |
| probe で全部 403 | `.env` のキーが違う。ダッシュボードで再発行して貼り直す |
| probe で TOPIX だけ 403 | 正常。TOPIX は Light 以上のデータ |
| probe で 404 が並ぶ | エンドポイントのパスが違う。結果を共有してもらえば直します |
| ビルドが遅い / 落ちる | Docker Desktop の設定でメモリを 4GB 以上に |
| `git checkout` でブランチが無い | 上記の `git fetch origin` 版を使う |

---

## ホストを汚さないことについて

このセットアップで **ホストに入る Python 関連のものはゼロ** です。

```
ホスト        : Docker Desktop / Git のみ
コンテナの中  : Python 3.12 / pandas / numpy / pyarrow / pytest / requests
```

コンテナを消せば全部消えます：

```powershell
docker compose down
docker rmi erb:latest python:3.12-slim
```

`C:\jquants` のファイル（コード・データ・結果）はホスト側に残ります。
