# Docker で動かす（Windows Python に二度と触らない）

壊れやすい Windows の Python を**完全に捨てて**、Python の頭脳をクリーンなコンテナで
動かす。Windows 側に入れるのは **Docker Desktop ひとつだけ**。MT5（EA）はこれまで通り
Windows ネイティブで動かし、コンテナとは MT5 の共有フォルダ越しに通信する。

```
  [Windows] MT5 + SteadyBridge EA  ──共有フォルダ──┐
                                                   │ (steady_*.csv / .txt)
  [Docker] fx コンテナ (run_ai_bridge) ────────────┘  ← Python はここに隔離
  [Docker] dashboard コンテナ (app.server) → http://localhost:8000/live
```

## 1. Docker Desktop を入れる（1回だけ）
- https://www.docker.com/products/docker-desktop/ から Windows 版をインストール
- WSL2 バックエンド推奨（インストーラの指示通りでOK）。インストール後に起動して
  「Engine running」になっていればOK。

## 2. `.env` を用意（`fxsim\.env`）
```ini
ANTHROPIC_API_KEY=sk-ant-...
FXSIM_FUND_MODE=stub        # 実ニュースのOpusファンダを使うなら anthropic

# MT5 の共有フォルダ（FXブリッジが読み書きする）。スラッシュは「/」で書く：
MT5_COMMON_FILES_HOST=C:/Users/penan/AppData/Roaming/MetaQuotes/Terminal/Common/Files
```
※ `MT5_COMMON_FILES_HOST` を入れないと、FXブリッジは空フォルダを見て「待機」になる
（dashboard と株 sim は動く）。

## 3. 起動（これだけ）
```powershell
cd C:\Users\penan\claude-code-book-template\fxsim
docker compose up -d --build
```
- `dashboard`（監視）と `fx`（FX自動売買）が立ち上がる。
- 監視画面： **http://localhost:8000/live**

## 4. ログ・操作
```powershell
docker compose logs -f fx          # FXの判断ログを追う
docker compose logs -f dashboard   # サーバのログ
docker compose ps                  # 稼働状況
docker compose restart fx          # コードを git pull した後の反映（再ビルド不要）
docker compose down                # 全部停止
```

## 5. 単発コマンド（監視・株sim・テスト）
コードは `./:/app` でマウント済みなので、`git pull` だけで即反映。単発実行は `run`：
```powershell
# PDCA健康診断
docker compose run --rm app python -m scripts.run_monitor

# 株のオフラインsim（無料）
docker compose run --rm app python -m scripts.run_stock_ai --sim --sim-steps 8

# テスト一式
docker compose run --rm app python -m pytest tests -q
```

## 6. 更新の流れ
```powershell
git pull
docker compose restart            # コードだけの変更（マウント反映）→ 再起動でOK
# requirements.txt が変わった時だけ：
docker compose up -d --build
```

## つまづきポイント
- **`http://localhost:8000` が開かない** → `docker compose ps` で dashboard が up か確認。
  ポート8000が他で使われてたら compose の `"8000:8000"` を `"8001:8000"` 等に変更。
- **FXが「waiting for EA status」** → `.env` の `MT5_COMMON_FILES_HOST` のパスが正しいか、
  MT5でSteadyBridge EAが動いてアルゴ取引ONかを確認。パスは「/」区切りで。
- **株の検証環境(kabuステーション)に繋ぎたい（審査通過後）** → コンテナからは
  `host.docker.internal:18081` で Windows 上の kabuステーションに届く（compose設定済み）。
  `docker compose run --rm app python -m scripts.run_stock_ai --once --dry` 等。
- **Windows の Python は一切不要**。`py` や `python` が壊れていても Docker には無関係。

## ディスクを食い潰さない運用（Cドライブ対策）

Dockerは**放置すると静かに容量を食う**。Windowsでは全部WSL2の `ext4.vhdx` に入り、
**このファイルは一度膨らむと自動では縮まない**ので、Cドライブの空きだけが減っていく。

原因は3つ、効くのもこの順:

1. **ビルドキャッシュ** — `docker compose up -d --build` のたびに層が積まれる。数GBになる。
2. **古いイメージ** — 再ビルドのたびに前の `fxsim:latest` が名無し(dangling)で残る。1本1GB弱。
3. **コンテナログ** — json-fileドライバの既定は**無制限**。常駐サービスには
   `logging: max-size 10m / max-file 3` を設定済み（1サービス最大30MBで頭打ち）。
   ※既存コンテナには効かないので、一度 `docker compose up -d` で作り直すこと
   （`restart` では適用されない）。取引コードは `./:/app` マウントなので影響なし。

```powershell
# 0) compose を触るコマンドは必ず fxsim ディレクトリで（yml はここにある）
cd C:\Users\penan\claude-code-book-template\fxsim

# 1) まず何がどれだけ使っているか見る（RECLAIMABLE が回収可能な量）
docker system df

# 2) 使っていないイメージを削除（起動中コンテナのイメージは保護される）
# `-a` は「どのコンテナも使っていない」イメージを全部消す。fxsim は起動中なので
# 保護されるが、他プロジェクトのイメージ（postgres, redis 等）も消える点に注意。
# 消えても次に使うとき再取得されるだけで、データは失われない。
docker image prune -a -f

# 3) ビルドキャッシュを削除（たいていここが一番大きい）
docker builder prune -a -f

# 4) 停止済みコンテナの残骸
docker container prune -f
```

**重要**：ここまでやってもWindowsの空き容量は増えない。vhdxが縮まないため。
Docker Desktop → **Settings → Resources → Advanced → "Disk usage" の Clean / Purge data**、
または Docker Desktop を終了してから:

```powershell
wsl --shutdown
Optimize-VHD -Path "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx" -Mode Full
```
（`Optimize-VHD` はHyper-V機能。無い場合は `diskpart` の `compact vdisk`、
またはDocker Desktopの Clean/Purge を使う。パスはバージョンにより
`...\Docker\wsl\data\ext4.vhdx` のこともあるので、実際に存在する方を指定する。）

**やってはいけないこと**：`docker system prune --volumes` は不要。このプロジェクトは
名前付きボリュームを使っておらず全部bind mount（`./` と MT5のCommon\Files）なので、
消して得はなく、他プロジェクトのデータを巻き込む危険だけがある。
`data/fxsim.db` はホスト側にあるので prune では消えない（ライブ記録は安全）。
