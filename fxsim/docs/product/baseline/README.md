# baseline/ — 基準測定（2026-11-22）の再現スクリプト

`../gap_baseline/`（視点ごとの6ファイル）の証拠として、測定を行ったエージェントが書いた走り書きのスクリプトです。
**テストではありません。** 製品化の指示書（`docs/PRODUCT_PROMPT.md`）のM3で、ここから正式なシナリオと変異の一覧を作るための出発点として保存しています。

- すべてコミット `40771f9` の `fxsim/` に対して書かれています。行が動くと動かなくなるものがあります。
- リポジトリには書き込みません（一時フォルダか、引数で渡した作業フォルダを使います）。
- クラウドのセッションのパス（`/home/user/claude-code-book-template/fxsim`）を前提にしています。
- Anthropic APIは呼びません。市場データも取得しません。

| ファイル | 何を示すか | 使い方 |
|---|---|---|
| `sre/repro_1116.py` | 2026-11-16の事故を、本物の `main()` とEAの期限切れ分岐の模型で再生する。引数 `weekday` で「平日なら決済されていた」を示す | `python sre/repro_1116.py` ／ `python sre/repro_1116.py weekday` |
| `sre/logs_1116_anonymised.txt` | 2026-11-16の一次記録（所有者のMT5と脳のログ）の匿名化した抜粋。**再生スクリプトの仮定と、記録にある事実を区別するための原本** | 読むだけ |
| `sre/frozen_weekday.py` | 平日に配信が凍っても、75時間までは脳も健康診断も正常と読む（MT5側の挙動は仮定） | `python sre/frozen_weekday.py` |
| `assurance/incident_sim.py` | 同じ事故を、リポジトリのFakeEAを拡張して再生する別実装 | `python assurance/incident_sim.py <作業フォルダ> weekday` |
| `assurance/mutate.py` | 注文経路に手で入れる36個の欠陥と、テスト全体での検出結果 | **必ず `fxsim` の複製に対して**：`python assurance/mutate.py <複製のパス> <python>` |
| `assurance/mutation_results.txt` | 上の実行結果（20個検出・16個素通り） | — |
| `maintain/blind.py` | 未ログインのEAが書く状態行で、脳が理由を出さずに盲目になることを示す | `python maintain/blind.py <作業フォルダ>` |
| `maintain/graph.py` | モジュールの依存関係（ライブ経路・運用ツール・どちらでもない） | `python maintain/graph.py` |
| `quant/engine_full.py` `quant/repro.py` | 本物のエンジンとハーネスの一致、近傍9通りの数字の再生成 | `python quant/engine_full.py` |
| `security/foreign_writer.py` | 偽のシグナル行に対するEA（Python転写）の反応 | `python security/foreign_writer.py <作業フォルダ>` |
| `security/probe.py` | ダッシュボードの認証と入力処理の探針 | `python security/probe.py` |

**残していないもの**：網羅率の測定結果（cov.json）は保存していません。測り直すときは、測定の道具を固定した環境の外に入れて（`pip install --target <作業フォルダ> coverage`）、`scripts/run_ai_bridge.py` を対象に分岐つきでテスト全体を走らせます。
**注意**：再生スクリプト（`repro_1116.py`・`incident_sim.py`・`blind.py`）は「ログアウト中のEAは残高0・建玉なしと書く」を**仮定として**埋め込んでいます。走らせ直しても、この仮定は確かめられません。
