# Docker で「解析層」を動かす

> ⚠️ **JV-Link(データ取得)は Docker では動きません。** JV-Link は Windows 専用の
> 32bit COM で、Linux コンテナ(Wine/Windowsコンテナ含む)では実質動作しません。
> なので **取得は Windows 側**、**解析は Docker** に分けます(本システムの
> 「取得層↔分析層を DB ファイルで疎結合」という設計そのもの)。環境はほぼ無傷です。

```
[Windows 側]  jrvltsql + JV-Link(venv で隔離) ──▶  keiba.db を生成
                                                        │ ファイルを ./data/ に置く
[Docker 側]   keiba 分析層(LightGBM 等すべて)  ◀──────┘  解析・バックテスト・可視化
```

## 取得側(Windows・Docker不可・但し venv で隔離して環境を汚さない)

```powershell
# 32bit Python の venv を作って jrvltsql をそこだけに入れる(システムを汚さない)
py -3-32 -m venv jvenv
.\jvenv\Scripts\activate
pip install git+https://github.com/miyamamoto/jrvltsql.git
# DataLab のサービスキーは JV-Link(ステップ2で設定済み)経由で使われる
quickstart.bat                      # data\keiba.db が出来る(全期間・SQLite)
# 期間指定なら: quickstart_timeseries.bat --db sqlite --from 20150101 --to 20260412
deactivate                          # venv を抜ければ環境は元通り。消すなら jvenv フォルダ削除
```

## 解析側(Docker)

```bash
# 0) keiba.db を ./data/ に置く(Windowsで作った data\keiba.db をコピー)
mkdir -p data plots && cp /path/to/jrvltsql/data/keiba.db data/

# 1) イメージをビルド(初回のみ)
docker compose build

# 2) まず取り込み健全性チェック + 実データ解析(単勝)
docker compose run --rm keiba --db /data/keiba.db
#    → 「バリデーション: クリーン」なら成功。列名違いなら警告が出る(その1行を共有)

# 3) 連系券種も含めて
docker compose run --rm keiba --db /data/keiba.db --exotic

# 4) 可視化(./plots に PNG)
docker compose run --rm --entrypoint python keiba -m keiba.dashboard --out /app/plots

# 5) テスト(健全性)
docker compose run --rm --entrypoint python keiba -m pytest -q

# 合成デモ(DBなしでも動作確認できる)
docker compose run --rm keiba --days 540
```

## 補足

- `docker compose` を使わず素の docker でも可:
  `docker build -t keiba-analysis . && docker run --rm -v "$PWD/data:/data" keiba-analysis --db /data/keiba.db`
- 取得側も丸ごと隔離したいなら、Windows 機自体を VM(Hyper-V/VMware)にして
  そこに DataLab+JV-Link+jrvltsql を入れる手もある(ホストOSを一切触らない)。
- イメージには JV-Link を含めないので、コンテナだけ配っても取得はできない(設計通り)。
