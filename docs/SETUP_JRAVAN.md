# JRA-VAN 実データ導入 — 環境・法務 相談メモ

`keiba/` の分析層は合成データで一通り完成しています(M0–M4)。実データ
(JRA-VAN DataLab)につなぐ M5 以降は **あなたの環境といくつかの判断** が要ります。
ここで論点を整理し、それぞれに推奨を添えます。出典は `RESEARCH_JRAVAN.md`。

---

## 0. 全体像(データの流れ)

```
[JRA-VAN DataLab 会員] ──JV-Link(32bit COM)──▶ 取得層(Windows 常駐機)
                                                   │ keiba.jvlink.RealJVLinkBackend
                                                   │   or EveryDB2 / jrvltsql
                                                   ▼
                                          正規化DB(DuckDB/SQLite/PostgreSQL)  ★境界
                                                   │ keiba.store.DuckDBBackend
                                                   ▼
                                    分析層(任意OS)= 既に完成している keiba/
                       特徴量(PiT)→ 学習 → 較正 → 市場ブレンド → walk-forward回収率 → EV/ケリー
```

**要点**: 取得層と分析層は「DBファイル」で疎結合。あなたがやるのは主に**取得層の用意**だけで、
分析層は無改修で本番データに切り替わります。

---

## 1. 用意するもの(チェックリスト)

- [ ] **JRA-VAN DataLab 会員**(月額 2,090円税込・初月無料)。利用キー(17桁)が発行される。
- [ ] **Windows マシン**(常時 or 定期起動できると運用が楽)。JV-Link は Windows 専用 COM。
- [ ] **Python 環境**(下の「判断1」で 32bit か 64bit を決める)+ `pywin32`。
- [ ] 分析層の依存(`pip install -e .` で numpy/pandas/scikit-learn/lightgbm/duckdb)。
- [ ] 初回セットアップ用のディスク(1986年以降の全データ取得は数十万〜数百万件・長時間)。

---

## 2. 判断が要る論点(★はあなたに決めてほしい)

### 判断1: JV-Link を 32bit Python で叩くか、64bit + DllSurrogate か ★
- **32bit Python**: 一番素直。COM がそのまま生成できる。学習側と環境を分けるなら問題なし。
- **64bit + DllSurrogate**: 64bit に統合できるがレジストリ設定の検証コストがある。
- **推奨**: まず **取得層だけ 32bit Python** で動かし、DuckDB に吐く。学習層は別環境(64bit)で
  そのDBを読む。COM の不安定要素を切り離せる。

### 判断2: 取込は自前(`keiba.jvlink`)か、既存ツール(EveryDB2 / jrvltsql)か ★
- **自前 `RealJVLinkBackend`**: コードを完全に掌握できるが、JV-Data 各レコードの固定長
  オフセットを `JV-Data4512.xlsx` 等で確定する作業が必要(桁ズレ厳禁)。
- **EveryDB2(GUI)/ miyamamoto/jrvltsql(Python)**: JV-Link→DB 構築を肩代わり。最短ルート。
  吐いた DB を `keiba.store` で読む or スキーマを合わせる。
- **推奨**: **まず jrvltsql か EveryDB2 で DB を作り**、分析層を実データで早く回す。自前パーサは
  必要になってから(細かい列が欲しくなった時)育てる。`keiba.jvlink` の枠組みはその時の土台。

### 判断3: 当日運用は半自動(指示出力)か、自動投票(iPAT)か ★
- **半自動(推奨・最初はこれ一択)**: 発走前に「買い目・賭け金」を出力するだけ。金銭事故ゼロ。
- **自動投票**: Selenium/Playwright で iPAT を操作。HTML 変更で壊れやすく、残高/重複投票の
  バグが**即・金銭損失**。十分な実績を積むまで保留。

---

## 3. ★法務で確認してほしいこと(最優先・実装前に)

> 私は法律家ではありません。下記は「確認すべき論点」であり、最終判断は規約原文・
> 必要なら専門家に当たってください。

1. **DataLab 規約の再配布範囲**: 取得データ・**予測結果・学習済みモデル**を公開/商用提供して
   よいか。DataLab は**個人利用前提・再配布制限あり**。趣味の範囲なら問題になりにくいが、
   ブログ公開・販売・API提供を考えるなら**規約原文の精読が必須**。
2. **iPAT 自動投票の可否**: JRA ネット投票規約上、Selenium 等での自動操作が許容されるか
   (明文の可否は未確認)。半自動なら論点を回避できる。
3. **netkeiba 等のスクレイピング回避**: 規約で運営妨害となるスクレイピングは禁止、過剰
   アクセスで通信制限(実測 約24時間)。当日オッズは **JV-Link 速報系(JVRTOpen)** で取れば
   規約・通信制限リスクを避けられる。

---

## 4. おすすめの最短ルート(私の提案)

1. DataLab 会員登録(初月無料)→ 利用キー取得。
2. Windows 機に **EveryDB2 か jrvltsql** で SQLite/DuckDB を構築(まず数年分でよい)。
3. その DB を `keiba.store.DuckDBBackend`(or スキーマ合わせ)で読み、**分析層をそのまま実行**。
   → 合成データで見ていた leak 監査・較正・walk-forward 回収率が、実データで出る。
4. **リーク除去後の構造ROIは80%前後まで落ちるのが現実**(研究の一致した警告)。市場ブレンドで
   残差を取れるかを **複数年 out-of-time** で検証。ここで初めて「勝てるか」が分かる。
5. 勝ち筋が見えたら **半自動運用**(JVRTOpen 速報オッズ→較正確率→EV→分数ケリー→買い目出力)。
6. 自動投票・公開/商用化は、実績と法務確認の後に。

---

## 4.5 具体的ランブック(DBが出来たら)

取得層(EveryDB2/jrvltsql)で SQLite/DuckDB を作ったら、分析層につなぐのは数行です。
JV-Data の列名は `keiba.ingest` の `*_FIELDS` / `TABLE_MAP` で**設定駆動**にしてあるので、
あなたのDBの実列名に合わせて上書きするだけです。

```python
from keiba.ingest import from_duckdb, validate_runners
from keiba.features import build_features
from keiba.backtest import walk_forward

# 1) JV-Data DB を正規化スキーマへ(テーブル名が違えば table_map で上書き)
runners, races = from_duckdb("your_jravan.duckdb",
                             table_map={"se": "NL_SE", "ra": "NL_RA", "o1": "NL_O1"})

# 2) まず健全性チェック(列・着順・オッズスケールの不整合を列挙)
issues = validate_runners(runners)
print(issues or "クリーン")            # ← 問題が出たら、その内容を私に送ってください

# 3) そのまま分析層へ(特徴量→walk-forward回収率)。分析層は無改修。
bt = walk_forward(build_features(runners))
print(bt["flat"]["roi"], bt["quality"]["blend_logloss"])
```

**あなたから私に欲しいもの**: 上記 `validate_runners` の出力、または DBの
**テーブル名一覧＋ SE/RA/O1 の列名**(できれば各先頭数行)。これで `*_FIELDS` を
あなたのDBに合わせて確定し、`odds_scale`/`futan_scale` 等も詰めます。

> 注: 実 JV-Data には脚質・含水率・血統(種牡馬)・時系列オッズなど、合成データに
> あった一部の特徴が直接は無い/別テーブルです。これらは当面 NaN のまま動きます
> (GBDT が吸収)。精度を詰める段で UM/血統・TS_O1(時系列オッズ)の取り込みを足します。

## 5. 私が次にできること(言ってくれれば)

- `RealJVLinkBackend` の **JV-Data 固定長スペックを実レコードに合わせて精緻化**(仕様の該当
  オフセットを教えてもらえれば、RA/SE/HR/O1… のフィールドマップを実装します)。
- jrvltsql/EveryDB2 が吐く **DB スキーマ → keiba.schema へのマッピング層**の実装。
- 当日運用(JVRTOpen 速報オッズ取得→買い目出力)の**半自動パイプライン**の骨組み。

> 実データ取得そのものはこのサンドボックス(Linux・egress 許可制)では実行できません。
> 上記はあなたの Windows 機で動かす**コード**として用意します。
