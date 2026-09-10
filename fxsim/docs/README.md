# ドキュメントの歩き方（まずここ）

このフォルダには開発の経緯上、**3世代分の手順書**が共存している。
**今の運用で読むべきものは上の3つだけ**。下2つは歴史的経緯（読む必要なし）。

| 読む順 | ドキュメント | 内容 | 状態 |
|---|---|---|---|
| 1 | **DOCKER.md** | 起動・更新・ログ確認（日常運用のすべて） | ✅ 現行 |
| 2 | **AI_TRADER.md** | 売買ロジックの仕様・EAの入れ方・安全弁・AI権限 | ✅ 現行 |
| 3 | **RESEARCH.md** | なぜこの設計なのかの検証記録（Round-1〜3） | ✅ 現行 |
| - | GOLIVE.md | 旧OANDA REST方式の手順。**「本番移行の基準」チェックリストだけ現役** | ⚠️ 一部歴史 |
| - | MT5_BRIDGE.md | 旧 `run_bridge`（AI無し脳・Windows Python直呼び）の手順 | 🗄️ 歴史 |
| - | MT5_SETUP.md | `MetaTrader5` IPC方式（接続失敗で廃止） | 🗄️ 歴史 |

## 今の構成（1枚で）

```
[Windows] MT5 + SteadyBridge EA（発注・ハートビート監視表示）
    ↕ 共有フォルダ (steady_*.csv / steady_signal.txt)
[Docker] fx コンテナ = run_ai_bridge（検証済みトレンドエッジ＋Python側ストップ、
                                      AIはshadow=助言のみ）
[Docker] dashboard → http://localhost:8000/live
```

## 日常でこれだけ覚えれば運用できる

```powershell
cd C:\Users\penan\claude-code-book-template\fxsim
git pull && docker compose restart        # 更新の反映
docker compose ps                          # 生きているか（PC再起動後は必ず）
docker compose logs -f fx                  # 判断ログ
docker compose run --rm app python -m scripts.diagnose_live   # 損益の解剖
docker compose run --rm app python -m scripts.run_monitor     # PDCA健康診断
```

MT5側はチャート左上の `brain OK (heartbeat valid Xm)` が生存確認
（`!! BRAIN SILENT !!` が出ていたらDockerが死んでいる → DOCKER.md参照）。
