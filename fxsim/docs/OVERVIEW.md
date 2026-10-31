# FX自動売買システム — まとめ（概要・仕組み・起動・運用）

> USD/JPYを「H1の長期トレンド」で長く持ち、要所だけClaude(Opus)がファンダ判断で
> ブレーキをかける、低頻度・リスク管理重視の自動売買システム。
> **コアはインデックス投資、これはサテライト（失っていい範囲の実験）。**

---

## 1. これは何か（1行）

**価格がH1の100日平均より上の間だけUSD/JPYをロング、流れが切れたら降りて待つ。
要所でOpusが指標・ファンダを見て建てない/小さくする。** ショートはしない。

- 検証値（2015-2026・H1実データ）：**CAGR ≈ 12.4% / 最大DD ≈ 34% / 年20取引**
- 正直な期待値：OOSはもっと地味（年6〜10%）、**負ける年もある・レジーム依存**
- 性格：勝率は低い（小さく何度も負け、たまに大きく勝つ）。地味だが頑健。

---

## 2. 仕組み（アーキテクチャ）

```
 [Windows]  MT5 + SteadyBridge EA ──共有フォルダ(steady_*.csv/.txt)──┐
                                                                     │
 [Docker]   fx コンテナ (run_ai_bridge) ─── Python頭脳（判断）────────┘
 [Docker]   dashboard コンテナ (app.server) → http://localhost:8000/live
            （記録は SQLite: data/fxsim.db に集約）
```

**役割分担：**

| 部品 | 実体 | 役割 |
|---|---|---|
| EA | MT5内 `SteadyBridge.mq5` | 手足。H1バー・口座状況を書き出す／注文を執行 |
| Python頭脳 | `scripts/run_ai_bridge.py` | いつ・何を売買するか判断（トレンド＋Opus） |
| 記録 | `data/fxsim.db` | 判断ログ・エクイティ・建玉を保存 |
| 監視 | `app.server` | DBを読んで `/live` に表示 |

**判断はすべてPython側。EAは賢いことをしない。** MT5とはファイル経由でやり取り（IPCが不安定なため）。

### 判断の流れ（1回 = decide_once）
```
 statusとH1バーを読む
   → 現在値 > SMA2400(≒100日線)？
       ・下 → FLAT（待機・Opusは呼ばない）
       ・上 → Opusに相談（ここぞ）
              ・LONG賛成 → 確信度でサイズ決定
              ・拒否(flat/short) → 見送り（ショートは絶対しない）
              ・Opus呼べない → トレンド単独でLONG（フェイルセーフ）
   → サイズ計算（確信度 × リスク4% × DDブレーキ、ただし5倍レバ上限）
   → signalファイルに書く（"LONG 0.95" or "FLAT 0"）→ EAが執行
   → 判断理由・エクイティをDBに記録
```
判断のタイミング：**1日1回 ＋ 高インパクト指標の直後45分以内**だけ（それ以外は何もしない＝API節約）。

---

## 3. 戦略の確定設定（なぜこれか）

| 項目 | 値 | 理由 |
|---|---|---|
| 通貨 | USD/JPY のみ | 多通貨検証で「エッジはUSD/JPY専用」と判明 |
| 時間足 | H1 | 日足より良くコスト頑健（OOS検証） |
| トレンド | SMA2400（≒100日） | 1800〜2400で堅い・低頻度 |
| 方向 | ロングのみ | 円のキャリー＋構造的上方ドリフト。ショートは利益ゼロ |
| リスク/取引 | 4% | これ以上はDDだけ増えCAGR頭打ち |
| レバ上限 | 5倍（ハード） | 複利の天井。超えると逆効果 |
| 利確(TP) | なし | 勝ちを伸ばす |
| AI | hybrid（Opus拒否権） | 要所でファンダ/イベントを見て事故回避 |
| モデル | claude-opus-4-8 | — |

**検証で棄却した案（＝なぜこの設定なのか）：**

| 試したこと | 結果 |
|---|---|
| レバ5倍超 | ❌ CAGR低下・DD爆発 |
| 短い足(M15) | ❌ 過剰売買でコスト負け |
| ショート追加 | ❌ 利益ゼロ上乗せ・DD増 |
| 週末ノーポジ | ❌ リターン↓・DD↑ |
| 利確(TP)あり | ❌ 勝ちを切りすぎ |
| 上位足フィルター追加 | ❌ 高値掴み増 |
| 多通貨分散(4ペア) | ❌ 薄まるだけ（エッジはUSDJPY専用） |

→ 結論：**いじらない方が強い。** 現行が局所最適。

---

## 4. 起動方法（Docker・Windows）

> 前提：Docker Desktop インストール済み・起動済み（Engine running）

```powershell
cd C:\Users\penan\claude-code-book-template\fxsim
git pull

# 初回のみビルド（数分）
docker compose build

# 健全性チェック（任意・安全）
docker compose run --rm app python -m pytest tests -q        # 90 passed が出ればOK

# FX＋監視だけ起動（株は起動しない）
docker compose up -d dashboard fx

# 稼働確認
docker compose ps                                            # dashboard と fx が running
```
- 監視画面：**http://localhost:8000/live** →「FX」タブ
- `.env` に `ANTHROPIC_API_KEY` と `MT5_COMMON_FILES_HOST=C:/Users/penan/AppData/Roaming/MetaQuotes/Terminal/Common/Files`
- MT5側：USDJPYチャートにSteadyBridge EA（H1配信）を付けて**アルゴ取引ON**

---

## 5. 日常運用

```powershell
docker compose logs -f fx                                     # FXの判断ログを追う
docker compose run --rm app python -m scripts.run_monitor     # 週1のPDCA点検
docker compose restart fx                                     # git pull後の反映
docker compose down                                           # 全停止
```

**監視ツール `run_monitor` の見方：**
- 🟢 健全（バックテスト通り）
- 🟡 観察 or データ不足（最初の数ヶ月は正常に🟡）
- 🔴 要対応：最大DDが想定34%超／戦略と建玉の不一致／過剰売買

**正常な挙動：** MT5+EA稼働中なら `trend-up... > SMA2400 → wrote signal: LONG x.xx`。
MT5未起動なら `waiting for EA status`（＝正常、起動すれば繋がる）。

---

## 6. 本番移行の基準（時間でなく「揃ったら」で判断）

デモの目的は「儲かるか」でなく**配管と自分の心臓の確認**（エッジは検証済み）。
下が揃ったら（目安4週間）→ **¥5〜10万・最小ロットで本番**。

- [ ] `run_monitor` の執行一致が数週間🟢
- [ ] 週末＋高インパクト指標を跨いでクラッシュ無し
- [ ] レバが5倍以内
- [ ] エントリー→決済の1サイクルが正常
- [ ] −10〜34%の含み損を見ても投げない自信

**増やし方：レバUPではなく「信頼できた分だけ入金」。コア=インデックスは崩さない。**
小口座のうちは `--calendar-mode file`（Opus無し・API代ゼロ・トレンド単独）でも可。

---

## 7. コスト（API）

| 項目 | 目安 |
|---|---|
| FX運用（Opus込み・定常） | 月 **$30〜45（¥5,000〜7,000）** |
| FXトレンド単独（Opus無し） | **¥0** |
| 株Opus常駐（参考） | 月 $45〜60（¥7,000〜9,000） |

- **必ず：Anthropicコンソールで月上限を$50に下げる**（暴走課金の安全弁）
- 小口座のうちはOpus代が利益を食う → トレンド単独推奨

---

## 8. リスク・正直な注意

- **必勝法ではない。** 検証12%はレジーム依存（2022-24円安に乗った結果込み）。負ける年もある。
- 最大DD 34%（¥300万なら一時¥200万割れ）に耐える前提。底で投げないこと。
- 単一通貨・単一戦略。相場の質が変われば効かなくなりうる。
- **コアはインデックス、これはサテライト（資産の1割・失っていい範囲）。**
- 「1日100万」系SNSは生存者バイアス。高レバ＝いつか全滅とセット。真似しない。

---

## 9. コマンド早見表

| やること | コマンド（fxsimフォルダ内） |
|---|---|
| 起動 | `docker compose up -d dashboard fx` |
| 停止 | `docker compose down` |
| 稼働確認 | `docker compose ps` |
| FXログ | `docker compose logs -f fx` |
| 点検 | `docker compose run --rm app python -m scripts.run_monitor` |
| テスト | `docker compose run --rm app python -m pytest tests -q` |
| 株sim(無料) | `docker compose run --rm app python -m scripts.run_stock_ai --sim --sim-steps 8` |
| 更新反映 | `git pull` → `docker compose restart` |
| 監視画面 | http://localhost:8000/live |

---

## 10. トラブルシュート

- **localhost:8000が開かない** → `docker compose ps` で dashboard が up か。8000使用中なら compose の `"8000:8000"`→`"8001:8000"`
- **fxが waiting のまま** → `.env` のMT5パス／MT5でEAアルゴ取引ON か
- **Docker起動しない** → WSL2更新(`wsl --update`→`wsl --shutdown`)・仮想化有効化・再起動
- **ファイルが繰り返し消える** → ウイルス対策の隔離を疑う（Pythonフォルダを除外）

---

## 関連ドキュメント（リポジトリ内）
- `docs/RESEARCH.md` — 全検証の記録（なぜこの設定か）
- `docs/DOCKER.md` — Docker詳細
- `docs/AI_TRADER.md` — FXのOpus層の仕様
- `docs/GOLIVE.md` — 本番移行手順
- `scripts/research_run7/8/9.py` — レバ・時間足・多通貨の再現スクリプト
