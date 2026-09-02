# Surface（Windows）セットアップ手順

2段階に分かれています。**ステップ1だけで、いま一番知りたいことは分かります。**

---

## ステップ1: probe だけ動かす（10分・Docker不要）

`probe_standalone.py` は Python の標準ライブラリだけで動きます。
pip install も不要です。

### 1-1. Python を入れる

すでに入っているか確認：

```powershell
python --version
```

`Python 3.11.x` などと出れば入っています。出ない場合：

- Microsoft Store で「Python 3.12」を検索してインストール（一番簡単）
- または https://www.python.org/downloads/ から入れる
  → インストーラの最初の画面で **「Add python.exe to PATH」に必ずチェック**

入れたら PowerShell を開き直して `python --version` を再確認。

### 1-2. ファイルを取ってくる

Git を使わない場合（一番簡単）：

1. ブラウザで下記を開く
   `https://github.com/ginchankawaii/claude-code-book-template/blob/claude/earnings-revision-backtest-xsamsb/backtest/probe_standalone.py`
2. 右上の **Raw** ボタン → 右クリック → 名前を付けて保存
3. 保存先はどこでもよい（例：`C:\Users\<ユーザー名>\Documents\jq\`）

Git を使う場合：

```powershell
winget install --id Git.Git -e
# PowerShell を開き直してから
cd $HOME\Documents
git clone https://github.com/ginchankawaii/claude-code-book-template.git jq
cd jq
git checkout claude/earnings-revision-backtest-xsamsb
cd backtest
```

### 1-3. APIキーを環境変数に入れて実行

```powershell
cd C:\Users\<ユーザー名>\Documents\jq        # 保存したフォルダへ
$env:JQUANTS_API_KEY="ダッシュボードで発行したキー"
python probe_standalone.py
```

- `$env:` で入れた値は、その PowerShell ウィンドウを閉じると消えます。
  それで構いません（毎回入れ直す方が安全）。
- キーをファイルに書いたり、チャットに貼ったりしないこと。

### 1-4. 結果を渡す

同じフォルダに `probe_result.txt` ができます。

```powershell
notepad probe_result.txt
```

中身をコピーして共有してください。**APIキーは含まれません。**

---

## ステップ2: 本番環境（Docker）

probe の結果で `config.yaml` を直してから組めば十分です。

### 2-1. Docker Desktop を入れる

```powershell
winget install --id Docker.DockerDesktop -e
```

- WSL2 が必要です。求められたら指示に従って有効化し、**PC を再起動**。
- 初回起動時に「Use WSL 2 based engine」を有効のままにする。
- ダウンロードは数GBあります。

確認：

```powershell
docker --version
docker compose version
```

### 2-2. リポジトリを用意

```powershell
cd $HOME\Documents
git clone https://github.com/ginchankawaii/claude-code-book-template.git jq
cd jq
git checkout claude/earnings-revision-backtest-xsamsb
cd backtest
```

### 2-3. APIキーを .env に置く

```powershell
Copy-Item .env.example .env
notepad .env
```

`JQUANTS_API_KEY=` の右に発行したキーを書いて保存。
`.env` は `.gitignore` 済みなので、GitHub には上がりません。

### 2-4. イメージを作る

```powershell
docker compose build
```

初回は数分かかります。

### 2-5. 動作確認

```powershell
docker compose run --rm --entrypoint python erb -m pytest -q
```

`61 passed` と出れば正常です（合成データによるテスト）。

### 2-6. 使う

```powershell
docker compose run --rm erb probe        # 列名の突き合わせ
docker compose run --rm erb histogram    # 修正率の分布
docker compose run --rm erb run          # グリッド実行
```

データは `backtest\data\` に置きます。結果は `backtest\results\` に出ます。
どちらもホスト側のフォルダなので、エクスプローラからそのまま開けます。

---

## Docker を使わない場合（venv・軽い）

正直なところ、この処理はローカルのCSVを pandas で読むだけなので
Docker がなくても困りません。環境を汚したくないだけなら venv で十分です。

```powershell
cd $HOME\Documents\jq\backtest
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
$env:JQUANTS_API_KEY="キー"
erb probe
```

`Activate.ps1` が実行ポリシーで弾かれる場合：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Docker との違いは、Python 本体とパッケージがホストに入るかどうかだけです。
分離を重視するなら Docker、手軽さなら venv。

---

## つまずきやすい点

| 症状 | 原因と対処 |
|---|---|
| `python` が見つからない | PATH に入っていない。Python を入れ直して「Add to PATH」にチェック |
| `docker` が見つからない | Docker Desktop を起動していない。タスクトレイのクジラが動いているか確認 |
| `Activate.ps1 ... 実行できません` | 実行ポリシー。上記の `Set-ExecutionPolicy` を実行 |
| probe で全部 403 | APIキーが違う、または環境変数が入っていない。`echo $env:JQUANTS_API_KEY` で確認 |
| probe で TOPIX だけ 403 | 正常。TOPIX は Light 以上のデータ |
| probe で 404 が並ぶ | エンドポイントのパスが違う。結果を共有してもらえば直します |
