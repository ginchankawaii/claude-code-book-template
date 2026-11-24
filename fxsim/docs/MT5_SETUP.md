# OANDA証券 MT5 で全自動運転（フォワード→本番）

ブローカーは **OANDA証券**、執行は **MT5 + Python（公式 `MetaTrader5`）**。
REST API（GOLD会員＝月50万ドル取引が必要）は使わず、**MT5デモは無料・即時・GOLD不要**。
同じコードでデモ→本番（最小ロット）へ一直線。

> **Windows が必要**（MT5端末＋`MetaTrader5`パッケージはWindows専用）。
> 自宅PCが無ければ FX向けの **Windows VPS（月1000〜2000円）** が定番。

## 1. OANDA証券で MT5 デモ用サブアカウント作成
- マイページ（デモ）→ FX → **「Meta Trader5用 FX サブアカウントを作成」**
- 控える：**MT5ログインID / パスワード / サーバー名**（例: OANDA-Japan MT5 Demo）
- ※ fxTrade ではなく **MT5** を選ぶこと。

## 2. Windows 側の準備
1. **MT5端末をインストール**（OANDA証券のMT5、または MetaQuotes 版）してデモ口座でログイン。
2. Python を入れて、このリポジトリを clone：
   ```
   git clone https://github.com/ginchankawaii/claude-code-book-template.git
   cd claude-code-book-template/fxsim
   python -m venv .venv && .venv\Scripts\activate
   pip install -r requirements.txt
   pip install MetaTrader5
   ```

## 3. 接続情報（任意）
MT5端末が既にログイン済みなら不要。明示するなら `fxsim/.env` に：
```
MT5_LOGIN=（MT5のログインID 数字）
MT5_PASSWORD=（パスワード）
MT5_SERVER=（サーバー名）
# MT5_PATH=C:\Program Files\OANDA MetaTrader 5\terminal64.exe   # 必要時
```

## 4. 動かす（必ず dry-run から）
```
# ① ドライラン：価格取得と判断だけ（注文は出さない）
python -m scripts.run_mt5_live --once

# ② デモへ実発注（resident・自己調整つき）
python -m scripts.run_mt5_live --live

# ③ ダッシュボード（別ウィンドウ）
python -m app.server      ->  http://localhost:8000/live
```
- 既定は **dry-run（発注しない）**。`--live` で初めてデモ口座に注文が出る。
- **ロング or 待機**のみ。建玉は目標に自動調整（自己調整リスクでサイズ決定）。
- 安全装置：最大ロット上限（`--max-lots`）、magic番号で手動取引には触れない。

## 5. 24時間化
- **cron的に1日1回**：タスクスケジューラで `python -m scripts.run_mt5_live --once --live` を毎日1回。
- **常駐**：`--live` を起動しっぱなし（VPS推奨）。

## 6. 進め方（厳守）
1. **デモで `--live` を数ヶ月**：バックテスト通りに建玉・損益・自己調整が動くか確認。
2. 問題なければ **本番MT5口座**に同じ設定で接続し、**最小ロット**から。
3. 徐々にロットを上げる。`--max-lots` で必ず上限を設ける。

> ⚠️ この実発注コードは Windows+MT5 が無いと動作テストできていない。最初の接続時は
> 必ず dry-run → 少額デモで挙動を一緒に確認すること。
