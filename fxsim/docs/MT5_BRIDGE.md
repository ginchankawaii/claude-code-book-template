# MT5 ファイル連携方式（IPCを使わない確実な全自動）

OANDA MT5 端末ビルドが新しすぎて `MetaTrader5` Python パッケージのIPCが通らない
（-10005 IPC timeout）場合の回避策。**端末自体は正常**なので、IPCを使わず
**ファイル経由**でPythonの頭脳とMT5を連携させる。

```
  MT5内のEA  --(steady_bars.csv / steady_status.csv)-->  Python（判断・自己調整）
  MT5内のEA  <--(steady_signal.txt "LONG 0.30")---------  Python
```

## 1. EA を MT5 に入れる
1. MT5 → **ツール → MetaQuotes Language Editor**（MetaEditor）を開く
2. ナビゲータの **Experts** を右クリック →「新規フォルダ」不要、`SteadyBridge.mq5` を
   `MQL5\Experts\` に置く：
   - エクスプローラで `C:\Users\penan\claude-code-book-template\fxsim\mt5_ea\SteadyBridge.mq5` を
   - MT5データフォルダ（MT5の **ファイル → データフォルダを開く**）の `MQL5\Experts\` にコピー
3. MetaEditorで `SteadyBridge.mq5` を開き **コンパイル（F7）**。エラー0を確認。

## 2. EA をチャートに付ける
1. MT5で **USDJPY の D1（日足）チャート**を開く
2. ナビゲータ → エキスパートアドバイザ → **SteadyBridge** をチャートにドラッグ
3. ダイアログで **「アルゴリズム取引を許可」にチェック** → OK
4. チャート右上に **SteadyBridge ☺（笑顔）** が出ればEA稼働中
   - ツールバーの **アルゴ取引ボタンが緑**であること

これでEAが30秒ごとに `steady_bars.csv` / `steady_status.csv` を共有フォルダに書き出す。
共有フォルダ＝ `C:\Users\<user>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\`

## 3. Python の頭脳を動かす
別の管理者PowerShellで：
```powershell
cd C:\Users\penan\claude-code-book-template\fxsim
git pull
# まず安全確認（判断するが signal は書かない＝発注されない）
py -3.12 -m scripts.run_bridge --once --dry
```
`[bridge][DRY] LONG 0.30 lots ...` のように出ればPythonがEAのファイルを読めている。

問題なければ本番（signalを書く＝EAがデモに発注）：
```powershell
py -3.12 -m scripts.run_bridge --once          # 1回（Task Schedulerで毎日）
py -3.12 -m scripts.run_bridge                 # 常駐（60秒ごと）
```

ダッシュボード：
```powershell
py -3.12 -m app.server     ->  http://localhost:8000/live
```

## 4. 毎日自動（日足なので1日1回で十分）
Windowsタスクスケジューラで、毎日（NY引け後＝日本時間 朝6〜7時頃）に：
```
py -3.12 -m scripts.run_bridge --once
```
EAは常駐（MT5を開いてEAを付けたまま）。VPSなら24時間。

## 動作の流れ（まとめ）
1. EA が日足＋口座状況をファイルに書く
2. Python が読む → トレンド判断＋自己調整リスクで「LONG 0.xx / FLAT」を決定 → signalファイルに書く＋SQLiteに記録
3. EA が signal を読んで発注（ロングor手仕舞い、ロングオンリー）
4. ダッシュボードで損益・ポジション・自己調整を確認

## 安全
- まず `--dry` で「読めるか」を確認してから signal を書く。
- EAは **magic番号(770077)** の自分の建玉だけ操作。手動取引には触れない。
- `--max-lots` で上限。最初はデモで数ヶ月。
