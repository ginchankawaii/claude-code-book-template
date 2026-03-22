# GitHub Actions ワークフロー設定ドキュメント

このドキュメントでは、`.github/workflows/` 以下に配置されている GitHub Actions ワークフローの設定内容と使い方を説明します。

---

## 1. Claude Code (`claude.yml`)

### 概要

Issue やプルリクエストのコメントで `@claude` とメンションすることで、Claude AI を呼び出して自動的にタスクを処理させるワークフローです。

### トリガー条件

以下のイベントが発生したときに起動します。

| イベント | 条件 |
|---|---|
| `issue_comment` | コメントが新規作成され、かつ本文に `@claude` が含まれる |
| `pull_request_review_comment` | PRレビューコメントが新規作成され、かつ本文に `@claude` が含まれる |
| `pull_request_review` | PRレビューが送信され、かつ本文に `@claude` が含まれる |
| `issues` | Issue が開かれた・アサインされたとき、かつタイトルまたは本文に `@claude` が含まれる |

### 必要な権限 (permissions)

```yaml
permissions:
  contents: read
  pull-requests: read
  issues: read
  id-token: write
  actions: read
```

### 使用するシークレット

| シークレット名 | 説明 |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code を利用するための OAuth トークン。リポジトリの Secrets に設定が必要です。 |

### 主なステップ

1. **Checkout repository** — リポジトリをチェックアウト（`fetch-depth: 1` で最新コミットのみ取得）
2. **Run Claude Code** — `anthropics/claude-code-action@v1` を実行し、コメント内の指示を Claude が解釈して処理

### カスタマイズ

以下のオプションでワークフローの挙動を変更できます（現在はコメントアウト済み）。

- **`prompt`** — Claude に与えるカスタムプロンプト。指定しない場合は、コメント内の指示がそのままプロンプトになります。
- **`claude_args`** — Claude CLI のオプション引数。許可するツールの制限などが可能です。
  - 例: `'--allowed-tools Bash(gh pr:*)'`

### 使い方

Issue またはプルリクエストのコメント欄に以下のように書くと Claude が起動します。

```
@claude このコードをレビューしてください。
```

---

## 2. Claude Code Review (`claude-code-review.yml`)

### 概要

プルリクエストが作成・更新されたとき、Claude AI が自動的にコードレビューを行うワークフローです。

### トリガー条件

以下の PR イベントが発生したときに起動します。

| イベントタイプ | 説明 |
|---|---|
| `opened` | PR が新規作成されたとき |
| `synchronize` | PR に新しいコミットが追加されたとき |
| `ready_for_review` | ドラフト PR がレビュー可能になったとき |
| `reopened` | クローズされた PR が再オープンされたとき |

> **オプション**: `paths` フィルターを使うと、特定のファイルが変更された PR のみを対象にできます（現在はコメントアウト済み）。

### 必要な権限 (permissions)

```yaml
permissions:
  contents: read
  pull-requests: read
  issues: read
  id-token: write
```

### 使用するシークレット

| シークレット名 | 説明 |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code を利用するための OAuth トークン。リポジトリの Secrets に設定が必要です。 |

### 主なステップ

1. **Checkout repository** — リポジトリをチェックアウト（`fetch-depth: 1` で最新コミットのみ取得）
2. **Run Claude Code Review** — `anthropics/claude-code-action@v1` を実行し、プラグイン `code-review` を使って該当 PR のコードレビューを実施

### 使用するプラグイン

| 設定項目 | 値 |
|---|---|
| `plugin_marketplaces` | `https://github.com/anthropics/claude-code.git` |
| `plugins` | `code-review@claude-code-plugins` |

### カスタマイズ

- **PR 作成者によるフィルタリング**: `if` 条件でレビュー対象を特定のユーザーや初回コントリビューターに限定できます（現在はコメントアウト済み）。
  ```yaml
  if: |
    github.event.pull_request.user.login == 'external-contributor' ||
    github.event.pull_request.author_association == 'FIRST_TIME_CONTRIBUTOR'
  ```

- **対象ファイルの絞り込み**: `paths` フィルターで特定の拡張子のファイルが変更された PR のみレビューするよう設定できます。
  ```yaml
  paths:
    - "src/**/*.ts"
    - "src/**/*.tsx"
  ```

---

## 初期セットアップ

両ワークフローを利用するには、リポジトリに以下のシークレットを設定してください。

1. GitHub リポジトリの **Settings** → **Secrets and variables** → **Actions** を開く
2. **New repository secret** をクリック
3. 以下のシークレットを追加する

| 名前 | 値 |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code の OAuth トークン |

詳細は [claude-code-action の使用ドキュメント](https://github.com/anthropics/claude-code-action/blob/main/docs/usage.md) を参照してください。
