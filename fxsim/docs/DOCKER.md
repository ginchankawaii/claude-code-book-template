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
