# JRA-VAN 競馬予想システム リサーチ統合

> 本ドキュメントは、5観点(JV-Link取得技術 / モデリング手法 / 特徴量とリーク防止 / 評価とベッティング / OSS・先行事例)のリサーチ結果を、**設計判断に直結する形**で統合したものです。実装の出発点となる現行リポジトリ(`horse_racing/` に `jra.py` / `data.py` / `model.py` / `cli.py` が既存)を前提に、サンドボックス制約下で「今すぐ作れるもの」と「実データ/Windows機が要るもの」を区別して記述します。

---

## 1. エグゼクティブサマリ(勝つための要点)

1. **最適化対象は的中率ではなく「控除率込みの回収率(ROI)」**。的中率100%でもトリガミで損になりうる。学習段は較正済みlog-loss/Brier/ランキング、選定段はEV閾値、評価段はROI・最大ドローダウン・破産確率を見る多層目的関数にする。

2. **超えるべき壁は控除率そのもの**。単複20% / 馬連・ワイド・枠連22.5% / 馬単・三連複25% / 三連単27.5% / WIN5 30%。予想能力ゼロなら回収率は払戻率(80%前後)に収束する。**まず控除率が最も低い単複・ワイドで「較正と期待値の正しさ」を検証**してから高控除券種に進む。

3. **市場(確定オッズ由来の確率)は最強クラスの予測子**。日本の中央競馬は極めて効率的で、1番人気を買い続けても回収率は約80%とフラット(英米のfavorite-longshot biasがそのまま当てはまらない)。Benter流に**市場確率を別軸でブレンド**し、市場が織り込めていない小さな残差だけを狙う設計が本筋。

4. **データリークが最大の敵**。確定オッズ・着順・走破タイム・上がり3F・払戻を当該レース特徴に混入させる、集計を未来の走まで含めて算出する、ランダムk-foldを使う——これらが「バックテストだけ異常に高ROI」を生む。リークを正しく潰すと構造ROIは80%前後まで落ちるのが現実。

5. **オッズ滑り(中間→確定でオッズが下がる)を前提に設計**。購入時点では最終オッズが未確定。中間オッズでのバックテストは楽観バイアスを持つため、確定オッズ予測モデルか下方補正係数を必ずかける。薄いプール(穴・エキゾチック)ほど自己インパクトでEVが消える。

6. **アーキテクチャは「取得層(Windows/32bit COM)」と「分析層(Linux/任意ビット)」を物理分離**する。JV-LinkはWindows専用32bit COMなので、取得層は常駐Win機でSQLite/DuckDB/PostgreSQLに正規化し、特徴量・学習・バックテストはDBを入力に別環境で動かす。**サンドボックスではCOMは不可なので、合成データでパイプライン全体を先に完成させる**。

7. **資金配分は分数ケリー(1/2以下、実務は1/4目安)**。フルケリーは推定勝率の過大評価で破産・巨大ドローダウンを招く。1点・1レース・1日の上限と、勝率の下側信頼区間を使う保守化を入れる。

8. **検証はwalk-forward(時系列分割)+ out-of-time ホールドアウト + リーク監査の制度化**。バックテスト118%級でもフォワードで崩れるのが通常(survivorship / look-ahead / regime shift / 市場効率の4劣化要因)。フォワードテスト(実確定オッズ・実投票)を本番判断の最終ゲートにする。

---

## 2. データ取得(JV-Link/DataLab)の現実と推奨構成

### 2.1 JV-Linkの正体と固定フロー

- **ProgID**: `JVDTLab.JVLink`、**Windows専用の32bit(x86) COM/ActiveX**。公式SDKはVB/VC#/VC++/Delphi向け。
- **料金**: DataLab会員 **月額2,090円(税込)** 固定・取得量無制限。JV-Link導入日から1か月無料。キーは2台分発行。**個人利用前提・再配布制限あり**(商用化・データ公開を想定するなら規約原文の精読が必須)。
- **過去データ**: セットアップで1986年以降を一括取得可。ただし**賭式ごとに提供開始年が異なる**(三連単O6/票数H6は2004年8月〜、ワイドO3は1999年10月〜、馬単O4・三連複O5は2002年6月〜、WIN5は2011年4月〜)。古い年に新賭式を期待するとNULL。

### 2.2 主要メソッドと固定フロー

```
蓄積系(過去一括/差分):
  JVInit(sid) → [サービスキー設定] → JVOpen(dataspec, fromtime, option)
    → JVStatus() でDL完了を監視 → JVRead ループ → JVClose

速報系(当日リアルタイム):
  JVInit(sid) → JVRTOpen(dataspec, key)   ← DLスレッドを使わず呼び出し時に完結
    → JVRead/JVGets → JVClose
```

| メソッド | 役割・戻り |
|---|---|
| `JVInit(sid)` | 最初に必須。sid はソフト識別用(認証ではない)。戻り0で成功 |
| `JVSetServiceKey(key)` | 17桁認証キー。**API不安定で-100を返すことあり** |
| `JVOpen(dataspec, fromtime, option, &readcount, &downloadcount, &lastfiletimestamp)` | 蓄積系読込準備+DLスレッド起動 |
| `JVRTOpen(dataspec, key)` | 速報系をキー指定で要求、戻る前に完了 |
| `JVRead(buff, size, filename)` | 1呼出1レコード、SJIS→Unicode。**0=EOF / -1=ファイル境界 / 負=エラー** |
| `JVGets(buff, size, filename)` | SJISのまま返す高速版 |
| `JVStatus()` | DL済みファイル数を返す(引数なし) |
| `JVSkip()` / `JVCancel()` / `JVClose()` / `JVFiledelete()` | 読飛ばし/停止/全閉/削除 |

### 2.3 dataspec と option の対応

- **option**: `1`=通常/差分、`2`=今週、`3`=セットアップ(ダイアログ有)、`4`=セットアップ(ダイアログ無/初回のみ)。
- **fromtime**: `YYYYMMDDhhmmss`。`'20240101000000-20241231235959'` のようにハイフンで範囲指定可。**差分運用は前回の `lastfiletimestamp` を次回 `fromtime` に渡す**のが基本。
- **蓄積系dataspec(4桁固定)**: `RACE`(RA/SE/HR/H1/H6/O1〜O6/WF/JG)、`DIFF/DIFN`(UM競走馬・KS騎手・CH調教師・BR生産者・BN馬主・RC等)、`BLOD/BLDN`(HN繁殖・SK産駒・BT系統)、`MING`(DMタイム型・TM対戦型マイニング)、`SNAP/SNPN`(出走別着度数)、`SLOP`(坂路)、`WOOD`(ウッド)、`YSCH`(開催スケジュール)、`HOSE/HOSN`(市場取引価格)、`HOYU`(馬名由来)、`COMM`(コース情報)。
- **速報系dataspec(0B11〜0B51)**: `0B12`=成績確定(RA/SE/HR)、`0B15`=出走馬名表、`0B11`=速報馬体重(WH)、`0B14/0B16`=天候馬場/出走取消(AV)/騎手変更(JC)/発走時刻変更(TC)/コース変更(CC)、`0B30`=全賭式オッズ、`0B31〜0B36`=各賭式(O1〜O6)、`0B41/0B42`=時系列オッズ(単複枠/馬連)、`0B51`=速報WIN5。

### 2.4 Python(pywin32 32bit)での取得フロー

```python
import win32com.client
jvlink = win32com.client.Dispatch('JVDTLab.JVLink')
jvlink.JVInit('UNKNOWN')           # sid は識別用
# サービスキーは DataLab アプリ側 or レジストリで事前設定
rc, read_cnt, dl_cnt, last_ts = jvlink.JVOpen('RACE', '20240101000000', 1)
# JVStatus() で DL 完了を待ちつつ JVRead ループ
while True:
    rc, buf, size, fname = jvlink.JVRead(b'', 0, '')
    if rc == 0:        # EOF
        break
    if rc == -1:       # 次ファイルへ
        continue
    if rc < 0:         # エラー
        raise RuntimeError(rc)
    record_type = buf[:2]          # 先頭2バイトで RA/SE/HR... を判定
    # 未知IDは黙ってスキップ(将来のレコード追加に耐える)
jvlink.JVClose()
```

**実装上の鉄則**:
- **32bit Python が事実上必須**(64bitは `REGDB_E_CLASSNOTREG`)。64bit統合が要るなら **DllSurrogate**(`dllhost.exe` をアウトプロセスCOMサーバ化するレジストリ追加)で回避。
- `JVSetServiceKey` が-100を返すなら **`HKLM\SOFTWARE\JRA-VAN\JV-Link` の `ServiceKey` にレジストリ直書き** が定石。
- 戻りはタプル: `JVOpen`→`(rc, read_count, download_count, last_file_timestamp)`、`JVRead`→`(rc, buff, size, filename)`、`JVRTOpen`→`(rc, read_count)`。
- **Shift-JIS(CP932)固定長**。pywin32のBSTR経由で文字化けしやすいので `cp932`/`latin-1` 再エンコードと CP1252(0x80-0x9F)対策が必要。
- **未知レコード種別IDは必ず読み飛ばす**(公式仕様の明記事項。バージョンアップ耐性)。
- 初回は `option=3 or 4` でセットアップ一括取込(数十万〜数百万件、長時間。`lastfiletimestamp` を保存して途中再開)、以後 `option=1` 差分、当週の出馬表は `option=2`。

### 2.5 代替/補助ツール

- **EveryDB2**: JV-Linkで取得し SQL Server/Oracle/Access/PostgreSQL/MySQL/SQLite/Excel 等へ構築。全データ初回構築 約1日、速報・時系列オッズ取得可。**自前ラッパーを書かない最短ルート**。
- **PC-KEIBA Database**: JRA・地方両対応、PostgreSQL専用(AWS Aurora運用例あり)。
- **miyamamoto/jrvltsql**(Python, 19★, v1.6.0 / 2026-06): SQLite/DuckDB/PostgreSQL対応。`NL_RA, NL_SE, NL_HR, NL_O1〜O6, TS_O1/TS_O2, TS_SOKUHO_O1〜O6` 等のテーブル設計が**雛形として優秀**。同作者の `jvlink-mcp-server` も。
- **urasandesu/JVLinkToSQLite**(C#, 15★): Python非依存で安定運用したい場合。
- **TARGET frontier JV**: JV-Linkにデータ取得を委譲しDB構築・CSV出力する2層構成。

### 2.6 サンドボックス制約(Windows COM不可・egress許可制)を踏まえた現実的なデータ受け渡し設計

サンドボックス(Linux・COM不可・外部通信許可制)では JV-Link を直接叩けない。したがって**取得層と分析層を疎結合にし、両者の境界を「正規化済みファイル/テーブル」に固定**する。

```
┌─────────────── Windows 常駐機(サンドボックス外)───────────────┐
│  JV-Link(32bit COM) ──► パーサ(SJIS固定長, 種別IDでディスパッチ) │
│      │ JVOpen/JVRTOpen                                            │
│      ▼                                                            │
│  正規化DB(SQLite/DuckDB 1ファイル)  ← jrvltsql/EveryDB2 を流用    │
└───────────────────────────┬───────────────────────────────────┘
                            │  ★境界 = DBファイル or Parquet/CSV
                            │  (rsync / クラウドストレージ / 物理コピー)
                            ▼
┌─────────────── 分析層(サンドボックス内 = Linux 任意ビット)──────┐
│  正規化DB/Parquet を入力に:                                       │
│  特徴量(PiT)→ LightGBM 学習 → 較正 → walk-forward → EV/ケリー      │
└──────────────────────────────────────────────────────────────────┘
```

- **境界フォーマットの推奨**: DuckDB / Parquet。列指向で分析層から高速に読め、スキーマも保持。SQLite単一ファイルでも可。
- **egress許可制への対応**: 分析層は**外部通信に依存しない**(DBファイルを受け取って完結)。どうしてもオンラインが要るなら、許可されたエンドポイント(自前ストレージ等)経由でDBファイルのみ転送。
- **抽象化レイヤ**: 分析層は「DBスキーマ」だけを知り、`JVLinkReader` インターフェースを **合成データ生成器**でモック実装しておく(後述M0)。本番Win機ができたら実装を差し替えるだけで分析層は無改修。
- 現行リポジトリの `jra.py` は、この**`JVLinkReader` 抽象 + 合成データバックエンド**の置き場所として位置づける。

---

## 3. データモデル(正規化スキーマの方針)

JV-Dataの1ファイル/1 dataspec に複数レコード種別が混在するため、**レコード種別ID(先頭2バイト)単位でテーブルを分離**するのが基本。jrvltsql/EveryDB2のテーブル設計を雛形にする。

### 3.1 中核テーブル(蓄積系)

| テーブル | レコード | 主キー | 主な列 |
|---|---|---|---|
| `race`(RA) | レース詳細 | `race_id`(年+回+日+場+R) | 開催日, 場, 距離, コース, 馬場状態, 天候, クラス, 頭数 |
| `runner`(SE) | 馬毎レース情報 | `(race_id, horse_id)` | 馬番, 枠, 騎手ID, 斤量, 馬体重/増減, **着順/走破タイム/上がり3F/通過順(=確定後)** |
| `payout`(HR) | 払戻 | `race_id` | 各賭式の的中組合せ・払戻金(**確定後**) |
| `odds_o1..o6`(O1〜O6) | 確定オッズ | `(race_id, 組合せ)` | 賭式別オッズ・人気 |
| `vote_h1/h6`(H1/H6) | 票数 | `(race_id, 組合せ)` | 票数 |
| `win5`(WF) | WIN5 | `win5_id` | 対象レース・払戻 |

### 3.2 マスタ・時系列・速報

| 種別 | テーブル | 内容 |
|---|---|---|
| マスタ(DIFF) | `horse`(UM), `jockey`(KS), `trainer`(CH), `breeder`(BR), `owner`(BN), `record`(RC) | 競走馬/騎手/調教師/生産者/馬主/レコード |
| 血統(BLOD) | `broodmare`(HN), `offspring`(SK), `bloodline`(BT) | 繁殖/産駒/系統 |
| 調教 | `slope`(SLOP), `wood`(WOOD) | 坂路/ウッド |
| 時系列オッズ | `ts_odds_o1`, `ts_odds_o2` … | 発売開始〜締切の推移(スナップショット時刻付き) |
| 速報 | `rt_weight`(WH), `rt_odds_*`, `rt_change`(AV/JC/TC/CC) | 当日直前情報 |

### 3.3 設計原則

- **時刻列を全レコードに必ず持たせる**: `race_date`(発走日時), `recorded_at`(取得スナップショット時刻), `availability`(`pre_race` / `post_race` のフラグ)。これが第4章のPiTマスクの根拠になる。
- **馬の同一性は血統登録番号(`horse_id`)をキー**にSEを時系列整列。
- **時系列オッズはスナップショット時刻をキーに含める**(例: 発走5分前固定での学習特徴抽出を可能に)。
- **コード表(JV-Data2311.xls)を別テーブル化**して場・賭式・馬場状態等のコードを名称解決。
- まず SQLite/DuckDB → 本格運用で PostgreSQL。境界フォーマットは Parquet/DuckDB。

---

## 4. 特徴量設計とリーク防止(point-in-time)の原則

### 4.1 特徴量の分類

1. **過去走由来の能力指標**: 過去N走のスピード指数(西田式: `指数=(基準タイム−走破タイム)×距離指数+馬場指数+(斤量−55)×2+80`)、上がり3F、通過順、PCI(ペースチェンジ指数=脚質の数値化)、クラス推移。**いずれも当該レース分は確定後情報なので過去走のみ使用**。
2. **出走条件適性**: コース/距離/馬場/枠順。枠は**出走頭数で正規化**し(8番は18頭立てなら内、8頭立てなら大外)、コース・距離別z値でバイアスを過去データから推定。
3. **人・血統の集計成績**: 騎手勝率・厩舎成績・種牡馬(産駒)成績・コース別成績。**必ず `race_date` より過去だけで算出**。
4. **当日情報(発走前に確定)**: 斤量、馬体重・増減(速報WH)、ローテ間隔、含水率・クッション値(**当日9:30頃公表=発走前に利用可**)。クッション値=芝+路盤の反発力、含水率=路盤の水分のみ、で使い分け。
5. **オッズ時系列**: 発走前の中間/直前オッズのみ。**確定オッズ・最終人気・払戻は厳禁**。

### 4.2 リーク防止の3本柱

**(A) Point-in-Time マスク(LeakageProtector方式)**
各特徴に「取得可能時刻(`pre_race`/`post_race`)」のメタ情報を付与し、JV-Dataの**速報系(JVRTOpen: WH馬体重・O1〜O6)と蓄積系(SE着順/HR払戻)の別を根拠に、レース後カラムを推論時に強制NaN化**する。当該レースの着順・走破タイム・上がり3F・通過順・確定オッズ・払戻が最も典型的なリーク。

**(B) 集計・JOINの全段に `race_date < 対象レース日` フィルタ**
集計関数側だけでなく **JOIN先テーブル(past_races等)にも独立してフィルタを入れる**。「集計元は絞ったのにJOINで未来走が混入」が頻出バグ(「フィルタを4箇所に入れて気づいた」事例)。フィルタ箇所をテストで網羅検証する。target encoding等のカテゴリ符号化も**out-of-fold/過去window限定**で行い、未来込み全体平均での符号化を避ける(LightGBMネイティブカテゴリ機能の利用が安全)。

**(C) walk-forward 検証(ランダムk-fold禁止)**
「予測対象年の前年末までで学習」を年度単位で繰り返す。`TimeSeriesSplit` で過去→未来の順序を保証。未来観測で過去を予測する分割はリーク源。

### 4.3 欠損・特殊ケース

- **新馬・初出走馬**: 過去走系がNaN。**安易な0埋め/平均埋めをせず、生NaN + 「過去走なしフラグ」を別特徴**として追加(GBDTはNaNを分岐で扱える)。「過去走なし」自体に情報がある。学習・推論で欠損処理を完全一致させる。
- **異常に高いバックテストROIはリークの強いシグナル**。リーク除去で構造ROIは80%前後まで落ちるのが正常。

### 4.4 一次仕様での裏取り

各フィールドのレース前/後区分を **JV-Data4512.xlsx(データ種別一覧)/ JV-Data2311.xls(コード表)** で逐一確認し、特徴定義書に出典を残す。

---

## 5. モデリング方針(手法選択と較正、レース内相対化)

### 5.1 3系統と使い分け

| 手法 | 長所 | 短所 |
|---|---|---|
| **GBDT 2値分類(LightGBM)** | 非線形・交互作用を自動学習、SHAP解釈、欠損に強い | 出力確率がレース内で合計1にならず**較正必須**、各馬独立で相対性が弱い |
| **Learning-to-Rank(LambdaMART/`objective=lambdarank`)** | レース内相対順位を直接最適化(各レースをgroup/query) | 出力が順位スコアで**確率較正が別途必要** |
| **条件付きロジット/Plackett-Luce(レース内ソフトマックス)** | レース内で確率合計1、市場確率合成と相性良、解釈容易 | 線形仮定で表現力低くGBDTより精度が出にくい |

**学術的源流**: Bolton-Chapman(1986, 多項ロジットでwithin-race competitionをモデル化)→ Benter(1994, 二段階モデルでファンダメンタル確率と市場確率を第2のロジットで合成、5年間実利益)。韓国(ソウル, 2024)研究では pairwise(LambdaMART)が pointwise より優位、CatBoost Ranker が最良(NDCG=0.8895)。

### 5.2 推奨アーキテクチャ(有力な組み合わせ)

```
GBDT で強いスコア(各レースを group として相対学習)
  → レース内ソフトマックス/較正で確率化(合計1に正規化)
  → 市場確率(正規化済み)と Benter 流ブレンド(第2段ロジット or 重み付き幾何平均)
  → 較正済み勝率 × 購入時オッズ = EV
```

### 5.3 較正(必須工程)

- 学習データとは**別期間**で **Isotonic Regression(データ多)/ Platt scaling(少)/ temperature scaling** を適用。
- **キャリブレーション・プロット(信頼性曲線)・ECE・Brier・log-loss** で質を確認。「AUCを上げる技術ではなく確率の質を上げる技術」。較正前後でROIがどう変わるかを必ず比較。
- 較正後に**レース内で正規化(合計1)**してからEV計算へ。

### 5.4 市場確率の扱い

- 単勝オッズ由来の暗黙確率は実勝率にほぼ一致する**最強ベンチマーク兼特徴量**。
- **控除率分のオーバーラウンドがあるので合計1に正規化**してからブレンド/EV計算。
- 改善度は **McFadden擬似R²(市場単独 vs 市場+自モデル)の差** や log-loss差で評価。

### 5.5 連系券種の確率展開

- 単勝確率pから **Harville(1973)型逐次条件付き確率**で展開。馬単 `AB = pA × pB/(1−pA)`、三連単 `p1 × p2/(1−p1) × p3/(1−p1−p2)`。
- **Harvilleは上位人気を過大評価するバイアス**あり。discounted Harville補正、または可能なら**2着/3着・ワイドを直接学習するモデル**で補正。
- **まず控除率の低い単複・ワイドで較正と期待値の正しさを検証**してから三連系へ。

---

## 6. 評価とベッティング戦略(回収率で勝つ)

### 6.1 控除率の壁(出発点)

| 券種 | 払戻率 | 控除率 |
|---|---|---|
| 単勝・複勝 | 80% | 20% |
| 枠連・馬連・ワイド | 77.5% | 22.5% |
| 馬単・三連複 | 75% | 25% |
| 三連単 | 72.5% | 27.5% |
| WIN5 | 70% | 30% |

予想能力ゼロなら期待回収率は払戻率に収束。控除率を継続的に超えるには**市場が誤って付けたオッズ(=市場確率と自モデル較正確率の乖離)**を狙うしかない。

### 6.2 EV と購入フィルタ

- `EV = 較正済み勝率 × 購入時オッズ`。市場平均EVは控除で0.75前後。
- **EV > 1+α(実務 α≈0.1、すなわちEV≥1.1)のみ購入**。αは推定誤差・オッズ滑り・控除を吸収するマージン。
- 較正が信頼できる確率帯のみに賭ける(信頼性曲線で確認)。

### 6.3 ケリー基準

- `f = (的中率×オッズ − 1) / (オッズ − 1)`。例: 勝率20%・6倍 → 資金の4%。
- **フルケリー禁止**(過大評価時に破産)。**分数ケリー(1/2以下、実務1/4目安)**。Benter・Thorpも保守的。
- 1点・1レース・1日の**上限**を併設し、勝率の**下側信頼区間**で保守化。破産確率・ドローダウン分布を**モンテカルロで事前把握**。

### 6.4 オッズ滑りと自己インパクト

- 中間オッズでのバックテストは楽観バイアス(購入時50倍超→確定37倍の例)。**確定オッズ予測モデルか下方補正係数**をかけてから閾値判定。
- パリミュチュエルは**下げる方が上げるより約250倍容易**。薄いプール(穴・エキゾチック)に大きく賭けると自分の投票でオッズが下がりEVが消える。賭け金をプール規模に対して制限。

### 6.5 日本市場の特性

- 中央の単勝市場は**極めて効率的**。1番人気も回収率約80%でフラット、多くの帯が70〜80%。**英米のfavorite-longshot bias(人気馬過小評価=買い)は成立しにくい**。極端な人気薄(100倍以上)の単勝回収率は約47%まで低下(穴は過大評価)。10〜14.9倍帯が約86%とやや高い例外。
- ablation検証では未使用の構造化特徴を足してもオッズ帯横断でほぼフラット → **容易な特徴での超過収益は困難**。

### 6.6 検証プロトコル(回収率で勝つための制度化)

1. **walk-forward + out-of-time ホールドアウト**(ランダムシャッフルCV禁止)。
2. **リーク監査をチェックリスト化**(`race_date`フィルタを集計の各段に挿入したか)。
3. バックテストは**確定オッズ(または下方補正オッズ)**で、複数年・out-of-time。バックテスト118%級がフォワードで崩れる前提(survivorship / look-ahead / regime shift / 市場効率の4劣化)。
4. **フォワードテスト(実確定オッズ・実投票)を最終ゲート**に。
5. ダッシュボードに **ROI / 的中率 / バンクロール推移 / 最大ドローダウン / 破産確率 / 年次ROI / Brier / log-loss / ECE** を並べる。
6. 券種ごとにEVモデルを分け、**控除率・プール規模・自己インパクトを織り込んだ現実的ROIを別々に評価**。

---

## 7. アーキテクチャ全体像

```
                        ┌───────── サンドボックス外(Windows 常駐機)─────────┐
[JRA-VAN DataLab] ─JV-Link(32bit COM)─►  パーサ(SJIS固定長, 種別IDディスパッチ, 未知ID skip)
   蓄積系 JVOpen                              │
   速報系 JVRTOpen ─当日直前オッズ/馬体重──►  │
                                              ▼
                                     正規化DB(SQLite/DuckDB/PostgreSQL)
                                     race/runner/payout/odds/ts_odds/rt_*
                        └────────────────────────┬───────────────────────────┘
                                                 │ ★境界: DuckDB/Parquet ファイル
                                                 ▼
                        ┌───────── サンドボックス内(Linux 分析層)──────────┐
                        │  ① 特徴量パイプライン(PiTマスク + race_date 全段フィルタ)
                        │  ② LightGBM 学習(2値 or lambdarank, group=レース)
                        │  ③ 確率較正(Isotonic/Platt)→ レース内正規化
                        │  ④ 市場確率ブレンド(Benter 第2段)
                        │  ⑤ walk-forward 回収率バックテスト(確定/補正オッズ)
                        │  ⑥ EV>1.1 フィルタ → 分数ケリー資金配分
                        └───────────────────────┬────────────────────────────┘
                                                 │ 投票指示(JSON/CSV)
                                                 ▼
                        ┌───────── 当日運用(Windows 機)────────────────────┐
                        │  JVRTOpen 速報オッズ取得 → 較正確率 → EV判定
                        │  → 分数ケリー → iPAT 投票(まず半自動: 指示出力のみ)
                        │  → 残高/重複投票ガード + 失敗時アラート
                        └──────────────────────────────────────────────────┘
```

- **取得層と分析層を疎結合**(境界=DBファイル)にすることで、サンドボックスでも分析層フルパイプラインを合成データで完成できる。
- 当日運用は **JV-Link速報オッズ(JVRTOpen)を優先**(netkeibaスクレイピングは規約・通信制限リスク。約24時間の通信制限が当日運用を止める)。
- **自動投票はSelenium/Playwright依存で壊れやすく金銭損失に直結**。まず**投票指示出力のみの半自動**から始め、残高・重複投票ガードと失敗アラートを必須に。商用IPAT API(team-nave等)も検討。

---

## 8. 段階的ロードマップ(マイルストーン)

> 設計指針: **最初のマイルストーンで、合成データだけで「正規化スキーマ / リーク安全な特徴量パイプライン / LightGBM学習 / walk-forward回収率バックテスト / EV・ケリーのベッティング」を一気通貫で完成**させる。実データ/Win機が要る部分は後段に分離し、分析層は無改修で本番データに差し替えられる構造にする。

### M0 — 合成データ基盤と正規化スキーマ(★サンドボックスで今すぐ)
- **今すぐ作れる**: 第3章スキーマ(`race/runner/payout/odds/ts_odds/rt_*`)をDuckDB/SQLiteで定義。**JV-Data準拠の合成データ生成器**(レース・馬・騎手・血統・オッズ・払戻を整合的に生成、時刻列 `race_date/recorded_at/availability` 付き)。`JVLinkReader` 抽象インターフェース(合成バックエンド実装)。現行 `jra.py`/`data.py` をこの土台に拡張。
- **実データ/Win機が要る**: なし。

### M1 — リーク安全な特徴量パイプライン(★サンドボックスで今すぐ)
- **今すぐ作れる**: PiTマスク(`availability=post_race` 列を推論時NaN化)、`race_date < 対象日` を集計・JOIN全段に適用、過去N走集計(スピード指数/上がり/通過順/PCI)、枠の頭数正規化・コース別z値、騎手/種牡馬の過去限定集計、新馬NaN+フラグ。**リーク監査テスト**(未来走混入検知、フィルタ箇所網羅)を最初から書く。
- **実データ/Win機が要る**: フィールドのレース前/後区分の最終確定(JV-Data4512.xlsx での裏取り)。

### M2 — LightGBM学習 + 確率較正(★サンドボックスで今すぐ)
- **今すぐ作れる**: 2値分類(3着内/外)と `objective=lambdarank`(group=レース)の両方を実装。別期間でIsotonic/Platt較正 → レース内正規化。Brier/log-loss/ECE/信頼性曲線。現行 `model.py` を拡張。
- **実データ/Win機が要る**: なし(合成データで配管を完成。精度の絶対値は実データでのみ意味を持つ)。

### M3 — walk-forward 回収率バックテスト + EV・ケリー(★サンドボックスで今すぐ)
- **今すぐ作れる**: `TimeSeriesSplit`/年度walk-forward。EV>1.1フィルタ、分数ケリー(1/4)、1点/1日上限。**確定オッズ vs 下方補正オッズ**の両方で評価。ROI/最大DD/破産確率/バンクロール推移ダッシュボード。モンテカルロでドローダウン分布。**オッズ滑りシミュレータ**(購入時→確定の補正係数)。
- **実データ/Win機が要る**: なし。これがM0-M3で完成する**最初の到達点**。

### M4 — 市場確率ブレンド(Benter第2段)(★サンドボックスで今すぐ)
- **今すぐ作れる**: 合成オッズから市場確率を逆算・正規化、第2段ロジット/重み付き幾何平均でブレンド。McFadden擬似R²/log-loss差で改善度評価。Harville展開(+discounted補正)で連系へ。
- **実データ/Win機が要る**: 市場効率の現実値検証(実オッズが必要)。

### M5 — 実データ取得層(実データ/Win機が必要)
- **Win機が必要**: Windows常駐機 + 32bit Python + pywin32 + DataLab会員。`JVLinkReader` を実COM実装に差し替え(`JVInit→JVOpen→JVStatus→JVRead→JVClose`、未知ID skip、SJIS固定長パース、DllSurrogate or 32bit、サービスキーのレジストリ回避)。または **EveryDB2/jrvltsql で代替**しDBファイルを境界に。セットアップで1986年以降一括 → 差分運用。
- **今すぐの準備**: 抽象インターフェースとパーサのSJIS固定長ロジックは合成データでテスト可能。

### M6 — 実データでのwalk-forward再検証(実データが必要)
- **実データが必要**: M1-M4のパイプラインを実DBに接続(分析層は無改修)。複数年・out-of-timeでROI再検証。リーク除去で構造ROI80%前後まで落ちることを確認し、市場ブレンドで残差を取れるか評価。
- **今すぐの準備**: 検証プロトコル・ダッシュボードはM3で完成済み。

### M7 — 当日運用(半自動)(実データ/Win機が必要)
- **Win機が必要**: JVRTOpen速報オッズ取得 → 較正確率 → EV判定 → 分数ケリー → **投票指示出力(半自動)**。発走n分前スケジュール実行。残高/重複ガード+アラート。
- **今すぐの準備**: 速報オッズの入力スキーマをM0で定義済みなので、ロジックは合成速報データで先行実装可能。

### M8 — フォワードテスト & 自動投票(実運用・要慎重判断)
- **実運用が必要**: 少額フォワードテストを最終ゲートに。iPAT自動投票(Selenium/Playwright or 商用API)は半自動で十分な実績を積んでから。survivorship/look-ahead/regime shift/市場効率を継続監視。

---

## 9. リスクと未解決事項(open questions / 要ユーザー確認)

**技術・取得層**
- 64bit統合を選ぶか32bit Pythonに固定するか(DllSurrogate検証コスト)。**→ 要ユーザー判断**。
- `JVOpen` の `readcount/downloadcount` の厳密な意味(レコード件数かファイル件数か)と巨大セットアップの正確な進捗計算式。
- 速報系 `JVRTOpen` の key フォーマット(`YYYYMMDDJJRR` 等)の賭式・dataspec別の必須/任意の組合せ。
- JVGets のメモリ解放と JVRead との性能差の定量データ。

**当日運用・オッズ**
- JV-Link速報/時系列オッズの**配信開始時刻・更新頻度・締切何分前まで取得可能か**(オッズ滑り補正の実効性を左右)。**実機検証が必要**。
- 時系列オッズで「どの時点スナップショットまで学習特徴に使うか」(例: 発走5分前固定)の標準設計。

**モデリング・市場**
- 日本中央の favorite-longshot bias の最新・大標本での人気別/券種別回収率テーブル(独立した一次データで検証したい)。
- 「市場確率と較正確率の乖離を突く」戦略が日本でも控除率を超えて機能するかの公開実証が乏しい。
- LightGBM lambdarank出力の確率較正(レース内ソフトマックス温度推定)の定量比較。
- Harville展開 vs 2着/3着直接学習の連系的中精度比較(日本データ)。
- Plackett-Luceで算出した三連系確率がエキゾチック・オッズと整合するかの較正検証。

**評価・資金管理**
- 分数ケリーの最適分数(1/2か1/4か)と、複数頭・複数券種・複数レース同時ベットのポートフォリオ破産確率/DDの定量関係(高分散下の数値)。
- 自己インパクト(自分の投票によるオッズ低下)の一般式・実測関係。
- 控除率込み・オッズ滑り込みで現実的に到達可能な持続的ROIの上限。

**法務(★要ユーザー確認・最優先)**
- **DataLab規約上、予測結果やモデルの公開・商用提供がどこまで許容されるか(再配布の線引き)**。個人利用前提・再配布制限あり。商用化/公開を想定するなら**規約原文の精読が必須**。**→ 要ユーザー判断**。
- iPATをSelenium等で操作する自動投票がJRAネット投票規約上問題ないか(明文の可否未確認)。**→ 要ユーザー確認**。
- netkeiba現行robots.txtのDisallow範囲・許容アクセス間隔(非公開、実測ベース)。可能ならJV-Link/公式データに統一。
- 年額/法人/商用ライセンスの正確な金額(今回は月額2,090円税込のみ確認)。

**運用上の現実認識(ユーザーと共有すべき期待値)**
- ネット上の「回収率100%超」報告の多くは**確定オッズ前提・リーク・過剰適合・締切オッズずれ**を含み、実運用での再現は容易でない。LightGBM 35年検証で単勝回収率73.7%、別事例81.4%、独学例は年で88〜121%と変動。**控除率を継続的に超えるのは構造的に難しい**ことを前提に投資すべき。

---

## 10. 参照リンク集(カテゴリ別)

**JV-Link / データ取得(公式・仕様)**
- JV-Link メソッド仕様: https://github.com/cariandrum22/Xanthos/blob/main/design/specs/methods.md
- JV-Data データ種別一覧: https://github.com/cariandrum22/Xanthos/blob/main/design/specs/data_types.md
- 公式SDK: https://jra-van.jp/dlb/sdv/sdk.html
- JV-Data4512.xlsx(データ種別一覧): https://jra-van.jp/dlb/sdv/sdk/JV-Data4512.xlsx
- DataLab 機能/料金: https://jra-van.jp/dlb/feature.html
- DataLab 会員サポート(料金・無料体験): https://support.jra-van.jp/jravan/detail?site=SVKNEGBV&id=24&hot_list=true
- 開発者コミュニティ(JV-Data/SDK): https://developer.jra-van.jp/t/topic/49
- 開発者コミュニティ(速報/時系列オッズ): https://developer.jra-van.jp/t/topic/613

**JV-Link 実装 / OSS**
- miyamamoto/jrvltsql(Python, SQLite/DuckDB/PostgreSQL): https://github.com/miyamamoto/jrvltsql
- jrvltsql wrapper.py(pywin32実装・サービスキー回避): https://github.com/miyamamoto/jrvltsql/blob/master/src/jvlink/wrapper.py
- jrvltsql README(32bit Python推奨): https://github.com/miyamamoto/jrvltsql/blob/master/README.md
- urasandesu/JVLinkToSQLite(C#): https://github.com/urasandesu/JVLinkToSQLite
- 取得フロー解説(Zenn): https://zenn.dev/nozele/articles/c64e456d0c77e4
- DllSurrogate手順(Qiita/HRAPS): https://qiita.com/hraps/items/594936369b5f0c856a8f
- SJIS固定長パース(note/HRAPS): https://note.com/hraps/n/ne756e8a041b3

**DB構築ツール / 補助**
- EveryDB2: https://jra-van.jp/dlb/sft/lib/everydb.html
- TARGET frontier JV: https://jra-van.jp/target/howtotarget.html
- JvlinktoImporter: https://jra-van.jp/dlb/sft/lib/JvlinktoImporter.html
- オッズ期待値アナライザー: https://jra-van.jp/dlb/sft/lib/oddskitaichi.html

**モデリング(学術)**
- Bolton-Chapman(1986, 多項ロジット): https://gwern.net/doc/statistics/decision/1986-bolton.pdf
- Benter(1994, 二段階モデル): https://gwern.net/doc/statistics/decision/1994-benter.pdf
- 韓国 Learning-to-Rank(2024): https://koreascience.kr/article/JAKO202414143309228.page
- Plackett-Luce for LTR: https://www.researchgate.net/publication/335854849_Plackett-Luce_model_for_learning-to-rank_task
- Harville展開(discounted Harville, arXiv): https://arxiv.org/pdf/1503.06535
- スポーツベッティングML系統レビュー(arXiv 2024): https://arxiv.org/html/2410.21484v1
- XGBoost LTRチュートリアル: https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html

**特徴量・リーク防止**
- PiT生成・リーク防止(Zenn/ricotiler): https://zenn.dev/ricotiler/articles/keiba-ai-15-pit-generation-leak-prevention
- race_dateフィルタ4箇所(Qiita/umascore): https://qiita.com/umascore/items/de0b9f40212d3446fb13
- スピード指数(西田式): https://www.keibasite.com/speed-nishida/
- PCI(ペースチェンジ指数): https://keibasys.seesaa.net/article/482086231.html
- 枠順バイアスz値: https://saratoga.jp/gate-in/
- データリーク一般(IBM): https://www.ibm.com/think/topics/data-leakage-machine-learning
- 馬場(含水率/クッション値)解説(JRA): https://www.jra.go.jp/keiba/baba/kaisetsu/ , https://www.jra.go.jp/keiba/baba/moist/

**評価・ベッティング**
- JRA払戻率変更(2014): https://www.jra.go.jp/news/other/20140303.html
- 回収率の基礎(JRA-VAN): https://jra-van.jp/fun/baken/index7.html
- 期待値1.1以上フィルタ: https://www.aolplatforms.jp/column/keiba-expectation/
- オッズ滑り: https://note.com/_manchi_/n/nad13f8659093
- ケリー基準: https://baku-chi.com/article/kelly-criterion
- favorite-longshot bias(神戸大): https://da.lib.kobe-u.ac.jp/da/kernel/81006950/
- 日本市場の回収率フラット性: https://www.humantransport.org/4711/
- 市場効率ablation検証(Qiita/umascore): https://qiita.com/umascore/items/158e93974ad781d4a302
- バックテスト劣化4構造(Qiita/umascore): https://qiita.com/umascore/items/2eb5854b5bd12f45e0f6
- 較正と評価指標(Qiita/architectJapan): https://qiita.com/architectJapan/items/1f7cfb2b156038c65f99
- 三連単EV/Plackett-Luce(Qiita/KuboTech): https://qiita.com/KuboTech/items/afc5bd8d82a16a20bf19
- 較正(Isotonic/Platt, Zenn): https://zenn.dev/keiba_ai_rui/articles/0bd6771159a6eb

**実装教材 / 先行事例**
- 競馬予想で始める機械学習(Zenn/dijzpeb): https://zenn.dev/dijzpeb/books/848d4d8e47001193f3fb , https://zenn.dev/dijzpeb/books/951e0f755229125bb79c
- LightGBM検証(Zenn/keita2399): https://zenn.dev/keita2399/articles/keiba-ai-lgbm-verification
- 期待値ベースのベット選択(note/CATA): https://note.com/cata_keiba_ai/n/nca5f41dddb5c
- 収集〜自動投票パイプライン(note/ポケットモンタロウ): https://note.com/gaisenmontaro/n/nde9b4d0a03b2
- iPAT自動投票(Zenn): https://zenn.dev/_lambda314/articles/e4ceaa81b045c5
- 特徴量エンジニアリング(agusblog): https://agusblog.net/keiba-ai-feature-value-engineering/
- 二値分類/LambdaRank(PC-KEIBA): https://pc-keiba.com/wp/binary/ , https://pc-keiba.com/wp/lambdarank/
- netkeiba-scraper(117★): https://github.com/stockedge/netkeiba-scraper
- nkparser(KeibaScraper): https://github.com/new-village/KeibaScraper

**法務・規約**
- netkeiba 通信制限/規約: https://support.keiba.netkeiba.com/hc/ja/articles/18841959592857

---

### 設計判断への直結ポイント(まとめ)

- **最初に作るべきはM0-M3**(合成データで正規化スキーマ→PiT特徴量→LightGBM→walk-forward回収率バックテスト→EV・分数ケリー)。これは**サンドボックス内で完結**でき、実データ到着時に分析層を無改修で本番化できる。現行リポジトリの `jra.py`(JVLinkReader抽象+合成バックエンド)/`data.py`(正規化・特徴量)/`model.py`(学習・較正)/`cli.py`(バックテスト・ベッティング)に役割を割り当てるとよい。
- **取得層(Win/32bit COM)は境界=DBファイルで疎結合化**し、サンドボックス制約を物理的に回避する。
- **法務(DataLab再配布範囲・iPAT自動投票の規約適合)はM5以前にユーザー確認が必須**。