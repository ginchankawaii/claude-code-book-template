# ドキュメントの歩き方（まずここ）

このフォルダには開発の経緯上、**3世代分の手順書**が共存している。
**今の運用で読むべきものは上の4つだけ**。下の3つは歴史的経緯（読む必要なし）。

| 読む順 | ドキュメント | 内容 | 状態 |
|---|---|---|---|
| 1 | **OVERVIEW.md** | まとめ：期待値・仕組み・更新の仕方・健康診断の見方・**年末年始の過ごし方** | ✅ 現行 |
| 2 | **DOCKER.md** | 起動・更新（再ビルドの確認方法）・ログ確認 | ✅ 現行 |
| 3 | **AI_TRADER.md** | 売買ロジックの仕様・EAの入れ方・安全弁・AI権限 | ✅ 現行 |
| 4 | **RESEARCH.md** | なぜこの設計なのかの検証記録（Round-1〜10C） | ✅ 現行 |
| - | GOLIVE.md | 旧OANDA REST方式（紙のフォワード）の手順 | 🗄️ 歴史 |
| - | MT5_BRIDGE.md | 旧 `run_bridge`（AI無し脳・Windows Python直呼び）の手順 | 🗄️ 歴史 |
| - | MT5_SETUP.md | `MetaTrader5` IPC方式（接続失敗で廃止） | 🗄️ 歴史 |
| - | PRODUCT_PROMPT.md | これを「製品」に引き上げるための、AIへの指示書（核）。場面ごとの手引きは `product/guide/` に7本。運用には不要 | 🧭 計画 |
| - | product/FOR_OWNER.md | 上の計画の、**所有者向けの説明**（何が手に入るか・何をお願いするか・始め方・年末年始の備え） | 🧭 計画 |
| - | product/ai_value/RESULTS.md | 「AIの判断は自分の費用を稼げるか」を設計の段階で計算した結果（いまの元手では稼げない。外すこと自体が高くつく）。残る問いを確かめる指示書は `AI_VALUE_PROMPT.md` | 🧭 計画 |
| - | product/deposit/RESULTS.md | 「元手を100万円に増やしてよいか」の計算（100万円でも割合は同じ／1〜3年後の元本割れの割合／一括と分割の差）と、入金時のコードの動き（健康診断は入金を知らない＝要修正） | 🧭 計画 |
| - | product/gap_baseline/ | 上の指示書の出発点：2026-11-22に測った製品化ギャップ63件（視点ごとに6ファイル。一覧は `README.md`）と、その再現スクリプト（`product/baseline/`） | 🧭 計画 |

## 今の構成（1枚で）

```
[Windows] MT5 + SteadyBridge EA（発注・ハートビート監視表示）
    ↕ 共有フォルダ (steady_*.csv / steady_signal.txt)
[Docker] fx コンテナ = run_ai_bridge（検証済みトレンドエッジ＋ブローカー側の実SL、
                                      AIはshadow=助言のみ）
[Docker] dashboard → http://localhost:8000/live
```

## 日常でこれだけ覚えれば運用できる

```powershell
cd C:\Users\penan\claude-code-book-template\fxsim
git pull                                   # 更新の取り込み
docker compose restart fx                  # 反映（再ビルドの案内があった時は docker compose up -d --build）
docker compose ps                          # 生きているか（PC再起動後は必ず）
docker compose logs -f fx                  # 判断ログ
docker compose run --rm app python -m scripts.diagnose_live   # 損益の解剖
docker compose run --rm app python -m scripts.run_monitor     # PDCA健康診断
```

MT5側はチャート左上の `brain OK (heartbeat valid Xm)` が生存確認
（`!! BRAIN SILENT !!` が出ていたらDockerが死んでいる → DOCKER.md参照）。

| - | COVERAGE.md | カバレッジ台帳（component × 不変条件 × 最後に攻撃したパス）。監査のたびに更新 | 🔎 現行 |
