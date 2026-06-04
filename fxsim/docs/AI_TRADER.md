# AI主導トレード（Opus＋web検索）— MT5全自動

教科書的な数値だけでなく、**実際の重要指標（NFP/CPI/FOMC/BOJ 等の実績値）と
最新ニュースをClaude Opusがweb検索で取得**し、テクニカル状態・現在ポジションと
合わせて**方向・レバレッジ・利確/手仕舞いを総合判断**する。"ここぞ"だけOpusを
使うことでコスト効率を保つ。

## 仕様（あなたの確定設定）
- 判断主体：**Opus**（claude-opus-4-8）＋ web_search
- 方向：**ロング/ショート両方**（AIが選ぶ）
- 頻度：**毎日1回＋高インパクト指標の直後**（イベント時刻で発火）
- サイズ：AIの確信度 × **最大リスク5%/取引**（安全上限・固定）。ドローダウン時は自動で縮小
- 利確/手仕舞い：毎判断でターゲット再評価（flat/反転も）＝出口もAIが管理
- 対象：USD/JPY

## 前提
1. **SteadyBridge EA**（ショート対応版）をMT5のUSDJPY,D1に付けてアルゴ取引ON。
   - `mt5_ea/SteadyBridge.mq5` を更新したので **MetaEditorで再コンパイル（F7）** すること。
2. `fxsim/.env` に **`ANTHROPIC_API_KEY=...`** を記入（このPCで実行＝web検索＆Opus課金）。
3. Python 3.12 環境（既存のまま）。

## 使い方
```powershell
cd C:\Users\penan\claude-code-book-template\fxsim
git pull

# まず1回・ドライラン（Opusに聞くが発注しない）
py -3.12 -m scripts.run_ai_bridge --once --dry

# 1回・本番（signalを書く＝EAが執行）
py -3.12 -m scripts.run_ai_bridge --once

# 常駐（毎日＋指標直後に自動判断）※イベント反応にはこれが必要
py -3.12 -m scripts.run_ai_bridge --calendar-mode anthropic
```
- `--calendar-mode anthropic`：起動時/毎日、Opusのweb検索で**最新の経済指標スケジュール**を
  取得して `data/calendar.json` を更新（イベント発火の時刻源）。`file` だと同梱の予定を使う。
- ダッシュボード：`py -3.12 -m app.server` → `http://localhost:8000/live`

## 重要：旧トレンド版と併用しない
signalファイルは1本。**AI版を使うなら、旧 `run_bridge`（トレンド）のタスクは停止**すること
（二重に書き込むと競合する）。タスクスケジューラの "SteadyBridge"(=run_bridge) を無効化し、
AI版を常駐で動かす。

## パラメータ
| 引数 | 既定 | 意味 |
|---|---|---|
| `--max-risk` | 0.05 | 1取引の最大リスク（AIはこの範囲でサイズ決定） |
| `--max-lots` | 5.0 | ロット上限（暴走防止の固い上限） |
| `--event-window-min` | 45 | 高インパクト指標の発表後この分数以内に判断 |
| `--daily-gap-h` | 20 | 定例判断の間隔（時間） |
| `--model` | claude-opus-4-8 | 使用モデル |

## 挙動の理解（正直に）
- AIは**しばしば「見送り(flat)」を選ぶ**（例：NFP直前の介入ライン付近では張らない）。
  これは欠陥ではなく**規律**。無駄な負けを避けるのがAIの主な価値。
- 実指標が絡むため**厳密なバックテストは不可**。検証は**フォワード（デモ）中心**。
- まずデモで数ヶ月、判断の質・約定・コストを観察 → 納得したら本番・最小ロット。

## 安全弁
- 最大リスク5%/取引・最大ロット上限・magic番号で自分の建玉のみ操作。
- ドローダウン時は実効上限を自動で縮小（資金保全）。
- API/解析エラー時は **flat（何もしない）** にフォールバック。
