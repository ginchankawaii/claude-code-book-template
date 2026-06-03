# フォワード運転（本番への王道）手順書

目的：**OANDAデモ口座の実価格**で Steady を前向きに走らせ、ダッシュボードで
数ヶ月見守る。**注文はまだシミュレート（実弾なし＝リスクゼロ）**。バックテスト
通りに動くか確認してから、実発注（次フェーズ）へ進む。

## 1. OANDAデモ口座とトークン
1. https://www.oanda.com/ で**practice（デモ）口座**を無料開設。
2. 管理画面 → **Manage API Access** → **API トークン**を生成してコピー。
3. **Account ID**（`xxx-xxx-xxxxxxxx-xxx` 形式）も控える。

## 2. 設定（fxsim/.env に書く）
```
FXSIM_PROVIDER=oanda
OANDA_API_TOKEN=（あなたのトークン）
OANDA_ACCOUNT_ID=（あなたの口座ID）
OANDA_ENV=practice
FXSIM_INSTRUMENTS=USD_JPY
FXSIM_GRANULARITY=D
FXSIM_STRATEGY=trend
```
※ 実行マシンから `api-fxpractice.oanda.com` に通信できること（自宅PC/VPSなら問題なし）。

## 3. 動かす
```bash
cd fxsim && . .venv/bin/activate

# 常駐（つけっぱなし。日足を自動で待って判断）
python -m scripts.run_steady_live

# 別ターミナルでダッシュボード
python -m app.server          # → http://localhost:8000/live
```
- **実価格・シミュレート約定**。新しい日足が確定するたびに1回判断＆記録。
- 損益・ポジション・自己調整リスク・取引履歴が `/live` にリアルタイム表示。
- 全データは `data/fxsim.db`（SQLite）に保存。

## 4. 24時間動かす（任意）

**方式A：cronで1日1回（日足ならこれで十分・軽い）**
```cron
# 毎日 UTC 21:10（NY 17:10＝日足確定後）に一度だけチェック
10 21 * * *  cd /path/to/fxsim && ./.venv/bin/python -m scripts.run_steady_live --once >> steady.log 2>&1
```

**方式B：常駐サービス（systemd・VPS向け）**
```ini
# /etc/systemd/system/steady.service
[Service]
WorkingDirectory=/path/to/fxsim
ExecStart=/path/to/fxsim/.venv/bin/python -m scripts.run_steady_live
Restart=always
[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now steady
```
※ 自宅PCは電源/スリープで止まるので、本気で24hなら**安いVPS**推奨。

## 5. 確認するポイント（数ヶ月）
- バックテストと**同じ頻度・同じ向き**でポジションを取っているか。
- ドローダウン時に**リスクが自動で絞られている**か（調整履歴を見る）。
- スプレッド/約定の感触（デモの約定価格と想定の差）。

## 次フェーズ（まだ未実装）
- **実発注コード**（OANDAに本物の注文）＋安全装置（最大建玉・緊急停止・1日損失上限）。
- これを足して、**最小ロットのリアル**へ。フォワードでOKが出てから着手。
