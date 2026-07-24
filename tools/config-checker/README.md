# 構成チェッカー — BOMを「既知の落とし穴」と照合するリンター

CCW見積エクスポート等のBOM(機器リスト)CSVを読み込み、ルールDB
([rules.yaml](rules.yaml))と照合して、**受注前に**ライセンス漏れ・構成ミスを
検出するツールです。

過去に実際に発生した追加原価事例(WLCパフォーマンスライセンス不足・
ASA HAライセンス不足)を初期ルールとして収録しています。

## 設計思想

- **判定型ルール(check)**: BOM内で完結して白黒つくもの。
  例: ASA 2台なのにライセンスが1本 → ⚠️警告
- **質問型ルール(question)**: BOMだけでは判定できないが、BOMのパターンから
  「既存環境の確認」を強制するもの。例: APがあるのにWLCが無い → 既存WLC収容の
  はず → 機種・現在のAP数・ライセンス余力を**回答必須の質問**として出力
- 質問への回答は、そのまま**前提条件・見積条件としてレビュー提出物に添付**する。
  これにより「人によって粒度がバラバラな前提条件」が標準化される
- チェックは決定的(同じ入力→同じ結果)。**利用者にAIライセンスは不要**。
  AIはルールの作成・保守時に使う

## 使い方

Python 3.8以上があれば動きます。**追加ライブラリ不要**
(PyYAMLが無い環境用のパーサーを同梱)。

```
python checker.py 見積.csv
python checker.py 見積.csv --out report.md        # レポートをファイルに保存
python checker.py 見積.csv --col-part "Part Number" --col-qty "Qty" --col-desc "Description"
python checker.py 見積.csv --no-header             # ヘッダー無し(型番,説明,数量の列順)
python checker.py 見積.csv --rules 別のルール.yaml  # ルールファイルを差し替え
```

- 文字コードはUTF-8/CP932(Excel保存のShift-JIS)/UTF-16(Excelの「Unicodeテキスト」
  保存・タブ区切り)を自動判定
- ヘッダー行は先頭30行から自動検出(Part Number / Product ID / 型番 / 数量 等)。
  CCWの実際のエクスポートと列名が合わない場合は `--col-part` 等で指定
- 全角の型番・数量も自動で半角に正規化

終了コード: `0`=指摘なし / `1`=承認済みルールの指摘あり / `2`=エラー。

### デモ

```
python checker.py samples/bom_wlc_incident.csv   # WLC事例: 確認事項が出る
python checker.py samples/bom_asa_incident.csv   # ASA事例: 警告が出る
python checker.py samples/bom_clean.csv          # 問題ない構成: 指摘なし
```

samples/ の2つの incident ファイルは過去の失敗事例を模したものです。
**実際の当時のBOMを入手して置き換えれば、「このツールがあれば受注前に
検出できた」というデモになります。**

## ルールの育て方(ここが本体)

`rules.yaml` が支店の落とし穴知識の本体です。checker.py は使い捨てできますが、
このDBは時間とともに価値が増える資産です。

### 運用ルール

1. **追加原価が発生したら、必ず対応するルールを1件追加する**
   (ソフトウェア開発の「バグには必ず回帰テストを書く」文化の移植)
2. 新ルールは `status: draft` で入れる → 有識者レビューで `confirmed` に昇格
3. draftルールの指摘は「参考」として表示され、終了コードに影響しない
4. `patterns:` のSKU正規表現こそベテランの赤入れ対象
   (例: `^AIR-AP[0-9]` はブラケット等の部材を誤検出しないための工夫)

### ルールの書き方

```yaml
- id: XXX-001            # 一意なID
  name: ルールの名前
  type: question         # question(質問型) か check(判定型)
  status: draft          # draft → レビュー後に confirmed
  trigger:               # 発火条件(全て満たすと発火)
    present: [グループ名]   # このグループの型番が1つ以上ある
    absent: [グループ名]    # このグループの型番が1つも無い
    min_qty:               # このグループの数量合計がN以上
      グループ名: 2
  check:                 # type: check のときのみ
    qty_at_least:
      group: 対象グループ
      reference: 比較先グループ   # または min: 固定値
  message: "警告文。{qty:グループ名} で数量を埋め込める(グループ名は半角英数字)"
  questions:             # 出力する質問(質問型は必須)
    - "質問文"
  rationale: なぜこのルールがあるか
  incident: 元になった実際の事例(年・案件・追加原価額)
```

グループ(型番の正規表現リスト)は `patterns:` に定義します。
グループ名は半角英数字とアンダースコアで付けてください。

## テスト

```
python -m unittest discover -s tests
```

ルールを追加・変更したら実行してください。過去事例の検出が退行していないか
(WLC/ASA事例が検出され続けるか)を自動で確認します。

## 既知の制限・今後

- CCWエクスポートの実際の列名・形式は未確認(入手次第 `--col-*` 既定値を調整)
- 現状の対象はCisco中心。Firepower(FPR)・Meraki・他社製品のルールは今後追加
- 「既存構成の台帳」と自動突合できれば質問型の一部を判定型に昇格できる(構想)
