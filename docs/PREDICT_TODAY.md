# 当日のレースを予想する（半自動・ペーパートレード）

> ⚠️ **検証前モデルの紙上テスト**。回収率が控除率を超える保証はまだ無い。
> 「モデルがどう予想するか」を記録して楽しむ用途。お金を賭ける根拠にはしないこと。

## 前提
- 過去データ（5年）の取得が**完了している**こと（学習＋各馬の過去成績に必要）。
- JV-Link セッションは1つだけ。**歴史DLが終わってから**下を実行する。

## 手順

### ① 今週の出馬表（まだ走っていないレース）を取得
歴史DLが終わったら、`jvenv` 有効のまま jrvltsql フォルダで:
```powershell
cd C:\keiba_ateru\jrvltsql
.\jvenv\Scripts\activate
jltsql fetch --spec RACE --option 2     # option 2 = 今週データ（出馬表＝着順未確定）
```
→ 今週の各レースの出走馬が NL_RA/NL_SE に入る（KakuteiJyuni 未確定＝着順 NaN）。

### ②（任意）現在オッズ（速報）も取る
EV／買い目判定にはオッズが要る。レース当日の朝以降:
```powershell
jltsql realtime start --specs 0B15,0B30   # 0B15=出馬表, 0B30=速報オッズ(全賭式,1週間)
# 少し動かしてオッズが入ったら Ctrl+C で停止
```
オッズ未取得でも**勝率ランキングは出る**（EV/買い目だけ出ない）。

### ③ 予測を実行（Docker）
```powershell
copy C:\keiba_ateru\jrvltsql\data\keiba.db C:\keiba_ateru\keiba-ateru\data\
cd C:\keiba_ateru\keiba-ateru
git pull                      # predict 経路を取り込む
docker compose build          # 初回 or 更新時のみ
docker compose run --rm --entrypoint python keiba -m keiba.predict --db /data/keiba.db
```

出力: レースごとに **勝率上位＋現在オッズ＋EV**、そして **EV閾値を超えた「買い目」** の一覧。

## 急ぐ場合（歴史DLが長い）の上級オプション
本システムの特徴量は当面 RACE 系（SE/RA/O1/HR）だけ使う（血統・調教はまだ不使用）。
なので **RACE の取得が終わった時点で Ctrl+C** して止めても学習はできる
（標準モードの BLOD/SLOP 等が途中でも可）。その後 ① に進む。
※ あくまで「早く試したい時」の裏技。基本は最後まで待つのが安全。

## うまくいかない時
- 「未確定レースが無い」→ ① の今週データ取得がまだ。`fetch --option 2` を実行。
- バリデーション警告（列名 NaN）→ その行を共有。`ingest` の `*_FIELDS` を即修正。
- EV/買い目が出ない→ オッズ未取得。② を実行するか、ランキングだけ見る。
