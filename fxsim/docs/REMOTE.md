# 外出先からダッシュボードを見る（Cloudflare Tunnel）

自宅PCのダッシュボードを、ルーターのポート開放なしでインターネット公開する。
PCから外向きにトンネルを張るだけなので安全・簡単。

> ⚠️ ダッシュボードは口座状況（残高・建玉・損益）が見える。発注はできない読み取り
> 専用だが、**公開前に必ずパスワードを設定**すること。

## 手順0（必須）：ダッシュボードにパスワードを付ける
`fxsim\.env` に：
```ini
FXSIM_DASH_USER=admin
FXSIM_DASH_PASS=好きな長いパスワード
```
→ 反映：
```powershell
docker compose up -d dashboard
```
ブラウザで `localhost:8000` を開くとログインを求められればOK（パスワード空なら無認証＝ローカル専用）。

---

## 方法A：固定URL（推奨・Cloudflareアカウント要）

1. **Cloudflare** に無料登録（独自ドメインがあると `fx.example.com` のような固定URLにできる）
2. **Zero Trust → Networks → Tunnels → Create a tunnel**（Cloudflared を選択）
3. 表示される **トークン**（`eyJ...`）をコピー → `.env` に：
   ```ini
   CLOUDFLARE_TUNNEL_TOKEN=eyJ...
   ```
4. トンネルの **Public Hostname** を追加：
   - Subdomain/Domain：好きなホスト名
   - **Service：`http://dashboard:8000`**（←コンテナ名で届く）
5. （強く推奨）**Zero Trust → Access → Applications** で、そのホストにメール認証等の
   ログインゲートを追加 → 自分だけ閲覧可に
6. 起動：
   ```powershell
   docker compose --profile tunnel up -d tunnel
   ```
   → 設定した固定URLで外出先から閲覧できる（PCとDockerが起動している間）。

## 方法B：今すぐ試す（アカウント不要・URLは毎回ランダム）
```powershell
docker run --rm --network fxsim_default cloudflare/cloudflared:latest `
  tunnel --no-autoupdate --url http://dashboard:8000
```
ログに出る `https://xxxx.trycloudflare.com` が一時公開URL。手順0のパスワードで保護される。
（URLは再起動で変わる・あくまでお試し用）

---

## 確認・運用
- 公開URLにアクセス → ログイン → `/live` が見えればOK
- 止める：方法A `docker compose stop tunnel` ／ 方法B はターミナルで Ctrl+C
- PC（とDocker）が起動している間だけ見られる。常時見たいなら自宅PCつけっぱ or VPS

## トラブル
- **502/繋がらない** → `dashboard` コンテナが up か（`docker compose ps`）、Cloudflare側の
  Service が `http://dashboard:8000` か
- **ログインが出ない** → `.env` の `FXSIM_DASH_PASS` を設定して `docker compose up -d dashboard`
- **ネットワーク名が違う** → `docker network ls` で実際の名前を確認（既定 `fxsim_default`）
