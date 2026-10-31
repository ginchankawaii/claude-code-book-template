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

## 本番移行の基準（時間ではなく「これが揃ったら」で決める）
**デモの目的は「儲かるか」ではなく「配管と自分の心臓」の確認**。エッジは11年の
バックテストで証明済み。数ヶ月のデモで損益を判定するのはノイズ（赤い数ヶ月は正常）。
だから下が揃ったら（目安 **約4週間**）、**¥5〜10万・最小ロットで本番**へ進む。

- ☐ `run_monitor` の **執行一致が数週間🟢**（戦略=建玉が一致＝EAが正しく追従）
- ☐ **週末＋高インパクト指標を1回以上跨いでクラッシュ無し**（待機/Opus拒否が想定通り）
- ☐ ログで **レバが5倍を超えていない**
- ☐ **エントリー→決済（or 待機）の1サイクル**が正常に見えた
- ☐ **−10〜34%の含み損を見ても冷静でいられる**自信

→ デモの「利益」は go-live 条件にしない（短期はノイズ）。**執行の正しさ＋自分の準備＋小さく始める**が条件。

## 本番後の増やし方
- 本番・最小ロットで数ヶ月、`run_monitor` が🟢圏を維持 → **少しずつ増額**。
- 増やすレバーは **レバUPではなく「信頼できた分だけ入金」**。
- **コア=インデックス9割／FX=サテライト1割**の枠は崩さない（失っていい額で）。

## 実発注について（補足）
FXの実発注は **MT5ブリッジ経由（OANDA証券口座）** で既に動く（`run_ai_bridge`）。
EA側のdry_runを解除すれば本物の発注になる。安全装置（最大ロット・レバ5倍上限・
DD自動減量）は実装済み。**まずデモで上記チェック → 最小ロットのリアル**、の順。
