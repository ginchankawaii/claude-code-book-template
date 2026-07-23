"""v3.1 アンカー発掘インタビュー: 台帳に効く記憶がないとき、本人に質問して新アンカーを引き出す。

設計原則（本人と合意済み・2026-07-23）:
- 発動は「台帳に合うアンカー結線が1つも成立しなかった時」だけ（対話モードのみ。--yes では発動しない）
- 質問は誘い水つきの自由回答（ヒント2〜3方向を添え、本人の言葉で答えてもらう）
- 本人がその場で語り y 確認した記憶は **状態=採用** で台帳に入れ、即結線してよい
  （「自動提案は候補どまり」規約は機械の発明への防波堤。本人の口述はこれに当たらない）
- 回答にない事柄を勝手に補完しない。曖昧すぎる回答はアンカー化しない（fail-closed）
- visual（絵に入る描写）に固有名詞を入れてよい（本人決定 2026-07-23: 本人専用ギャラリーのため。
  台帳で「絵に出さない」をチェックした名前だけ graph.static_check_links が遮断する）
"""
from __future__ import annotations

from .chain import _client, _response_text
from .gate import _extract_json
from .models import Anchor, MemoryCard, anthropic_model

ALLOWED_KINDS = ("属性", "人物", "感情", "数字")
ALLOWED_EMOTIONS = ("報酬", "嫌悪", "罪悪", "痛み", "屈辱")


# ---------------------------------------------------------------------------
# 純関数（テスト用に公開）
# ---------------------------------------------------------------------------

def _parse_question(data: dict, mindmap: dict) -> dict | None:
    """質問JSON → {node, question, hints}。ノードがマップに無い等は None（質問しない）。"""
    if not isinstance(data, dict):
        return None
    node = str(data.get("node") or "").strip()
    question = str(data.get("question") or "").strip()
    hints = [str(h).strip() for h in (data.get("hints") or []) if str(h).strip()]
    labels = {str(b.get("label", "")).strip() for b in mindmap.get("branches") or []}
    labels.add("center")
    if not question or node not in labels:
        return None
    return {"node": node, "question": question, "hints": hints[:3]}


def _parse_interview_anchor(data: dict) -> dict | None:
    """回答の整形JSON → アンカー行 dict。必須欠落・不正値は None（無理にアンカー化しない）。"""
    if not isinstance(data, dict) or data.get("ok") is False:
        return None
    name = str(data.get("name") or "").strip()
    body = str(data.get("body") or "").strip()
    visual = str(data.get("visual") or "").strip()
    reason = str(data.get("reason") or "").strip()
    connection = str(data.get("connection") or "").strip()
    if not (name and body and visual and reason and connection):
        return None
    kinds = [k for k in (data.get("kinds") or []) if k in ALLOWED_KINDS]
    kinds = list(dict.fromkeys(kinds)) or ["属性"]
    emotion = str(data.get("emotion") or "").strip()
    if emotion not in ALLOWED_EMOTIONS:
        emotion = ""
    if "感情" in kinds and not emotion:
        # 感情種別なのに感情ラベルが定まらない行は専有管理が壊れるため属性へ落とす
        kinds = [k for k in kinds if k != "感情"] or ["属性"]
    return {
        "name": name,
        "kinds": kinds,
        "body": body,
        "emotion": emotion,
        "connection": connection,
        "reason": reason,
        "visual": visual,
    }


# ---------------------------------------------------------------------------
# LLM 呼び出し
# ---------------------------------------------------------------------------

def propose_question(mindmap: dict, card: MemoryCard, anchors: list[Anchor]) -> dict | None:
    """一番効きそうなノード1つを選び、本人の記憶を引き出す質問を作る。作れなければ None。"""
    branch_labels = "\n".join(
        f"- {b.get('label', '')}" for b in mindmap.get("branches") or []
    )
    ledger_rows = "\n".join(
        f"| {a.name} | {'/'.join(a.kinds)} | {a.connection} |" for a in anchors
    ) or "（空）"
    prompt = f"""あなたは記憶術（精緻化インタビュー）の専門家です。
以下のマインドマップには、台帳のアンカーでは効く結線が見つかりませんでした。
本人の記憶から新しいアンカーを引き出すため、**一番間違えやすい・重要なノードを1つ**選び、
そのノードの性質を日常の体験に言い換えて、本人の記憶を思い出させる質問を1つ作ってください。

# マインドマップ
中央: {mindmap.get('center', '')}
枝:
{branch_labels}

# 既存の台帳（すでにある記憶と重複する質問はしない）
| アンカー | 種別 | 接続先 |
|---|---|---|
{ledger_rows}

# 質問ルール
- **概念や理屈ではなく、本人の具体的な体験（いつ・どこで・何があった）を聞く質問にする**
  （例:「"よそから入ってきたもの"で思い出す自分の体験・出来事は？」）
- hints: 答えの方向の例を2〜3個、一般語で（例: 転校生 / 外来種 / 中途入社）。誘導しすぎない
- node は枝ラベルと一字一句同じ、または "center"

# 出力形式（このJSONのみをコードフェンスで出力）
```json
{{"node": "枝ラベルまたはcenter", "question": "質問文", "hints": ["方向1", "方向2"]}}
```"""
    response = _client().messages.create(
        model=anthropic_model(),
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_question(_extract_json(_response_text(response)), mindmap)


def anchor_from_answer(node: str, question: str, answer: str, card: MemoryCard) -> dict | None:
    """本人の回答をアンカー台帳の1行に整形する。曖昧なら None（fail-closed）。"""
    prompt = f"""あなたは記憶術の専門家です。本人がいま語った記憶を、アンカー台帳の1行に整形します。

# 覚えたい項目
{card.title}（結線先ノード: {node}）

# 質問
{question}

# 本人の回答（この中に書かれていることだけを使う。補完・創作は禁止）
{answer}

# 整形ルール
- name: 回答の中の言葉を使った短い見出し（15文字以内）。本人が言っていない固有名詞を発明しない
- kinds: {"/".join(ALLOWED_KINDS)} から1〜2個。強い感情を伴う体験なら「感情」を含める
- body: その記憶の中身を1文（本人の言葉ベース）
- emotion: {"/".join(ALLOWED_EMOTIONS)} のどれかに明確に当てはまる時だけ。無理なら空文字
- connection: 「{node}」に接続する理由の要点（例: 外から来たもの）
- reason: なぜこの結線で覚えられるか1文（固有名詞可。Notion 本文にだけ載る）
- visual: 絵に描く小さな挿絵の描写。本人だけが見るギャラリーなので、回答に出てきた人名・固有名詞を入れてよい
- **回答が概念・一般論・理屈だけで、本人の具体的な体験（場面・出来事）を含まない場合は {{"ok": false}} だけを返す**。
  アンカーは本人の記憶でなければ機能しない。曖昧・抽象的な回答を無理にアンカー化しない

# 出力形式（このJSONのみをコードフェンスで出力）
```json
{{"ok": true, "name": "見出し", "kinds": ["属性"], "body": "1文", "emotion": "",
  "connection": "要点", "reason": "1文", "visual": "挿絵の描写"}}
```"""
    response = _client().messages.create(
        model=anthropic_model(),
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_interview_anchor(_extract_json(_response_text(response)))
