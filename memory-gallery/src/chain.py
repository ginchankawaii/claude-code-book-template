"""L1 連想層: 覚えたい事実の抽出と連想鎖3案の生成（Anthropic Messages API）。

- 入力はテキスト（カードの項目名）または画像（カード添付のスクショ/図）。
- アンカーは実行時に Notion のアンカー台帳から渡される（コードへのハードコード禁止）。
- 「自分の一言」は絶対に生成しない（CLAUDE.md ルール#6 / 生成効果）。
"""
from __future__ import annotations

import json
import os
import re

from .models import Anchor, CardImage, ChainProposal, MemoryCard, anthropic_model

# CLAUDE.md 4章「生成ルール（品質ゲート）」原文。プロンプトにそのまま埋め込む。
GENERATION_RULES = """\
1. **アンカーは必ず台帳から選ぶ。** 台帳外の一般的な連想は使わない。
2. **鎖は覚えたい事実に戻ること。** 「7→イチロー→野球」は逸れて終わりで不可。「7→イチロー→特別枠でメジャーへ→NSSA＝特別扱いのスタブ」なら可。
3. **同じアンカーを別項目に使い回さない。** 衝突すると両方消える。
4. **属性アンカーと感情アンカーを組み合わせる。** 属性だけだと冷たいパズル、感情だけだと戻ってこない。
5. **技術的断定は公式ブループリントと突合する。** 記憶システムでのハルシネーションは致命傷。間違った連想を焼き付けたら、何も作らないほうがマシ。
6. **最後に自分で一言書く。** ダサくていい。ここは絶対に自動化しない（生成効果）。"""

_EXTRACT_MAX_TOKENS = 2048
_CHAINS_MAX_TOKENS = 8192


def _client():
    """Anthropic クライアントを遅延生成する。APIキーが無ければ明快に落とす。"""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "環境変数 ANTHROPIC_API_KEY が設定されていません。"
            " .env を確認してください（cp .env.example .env）。"
        )
    import anthropic  # 遅延 import（依存未導入環境でも本モジュールの import を壊さない）

    return anthropic.Anthropic()


def _response_text(response) -> str:
    """Messages API 応答から text ブロックを連結して返す。"""
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _normalize_mime(mime: str) -> str:
    """Anthropic API が受け付ける media_type に正規化（それ以外は image/png に倒す）。"""
    m = (mime or "").split(";")[0].strip().lower()
    if m == "image/jpg":
        m = "image/jpeg"
    return m if m in _ALLOWED_IMAGE_TYPES else "image/png"


def _image_blocks(images: list[CardImage]) -> list[dict]:
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _normalize_mime(img.mime),
                "data": img.data_b64,
            },
        }
        for img in images
    ]


def extract_fact(card: MemoryCard) -> str:
    """カードから「覚えたい事実」をちょうど1つ抽出する。

    画像があれば画像から（マルチモーダル）、なければ項目名から定式化する。
    抽出結果は後段の gate.py / 人間の確認で必ず検証されること（CLAUDE.md 5章）。
    """
    client = _client()

    if card.images:
        instruction = (
            f"この画像から、項目「{card.title}」（分野: {card.domain or '未設定'}）に関して"
            "覚えるべき技術的事実を**ちょうど1つ**、1〜2文の検証可能な断定として抽出してください。\n"
            "制約:\n"
            "- 推測禁止。画像に書かれていることのみを根拠にすること。\n"
            "- 画像から事実が読み取れない場合は、その旨を1文で述べること。\n"
            "- 出力は事実の文のみ。前置き・説明・箇条書き記号は不要。"
        )
        content: list[dict] = _image_blocks(card.images)
        content.append({"type": "text", "text": instruction})
    else:
        instruction = (
            f"項目「{card.title}」（分野: {card.domain or '未設定'}"
            f"{'、戻り先: ' + card.return_to if card.return_to else ''}）について、"
            "覚えるべき技術的事実を**ちょうど1つ**、1〜2文の検証可能な断定として定式化してください。\n"
            "制約:\n"
            "- 項目名が既に事実文であれば、ほぼそのまま（表現を最小限整えるだけで）返すこと。\n"
            "- 項目名に含まれない知識を推測で付け足さないこと。\n"
            "- 出力は事実の文のみ。前置き・説明・箇条書き記号は不要。"
        )
        content = [{"type": "text", "text": instruction}]

    response = client.messages.create(
        model=anthropic_model(),
        max_tokens=_EXTRACT_MAX_TOKENS,
        messages=[{"role": "user", "content": content}],
    )
    fact = _response_text(response)
    if not fact:
        raise ValueError(f"事実抽出に失敗しました（応答が空）: card={card.title}")
    return fact


def _candidate_anchors(anchors: list[Anchor]) -> list[Anchor]:
    """状態=採用 かつ 未使用（used_by が空）のアンカーのみ候補にする（ルール#3）。"""
    return [a for a in anchors if a.status == "採用" and not a.used_by]


def _anchor_table(candidates: list[Anchor]) -> str:
    lines = ["| 名前 | 種別 | 中身 | 感情 | 接続先 | 強度 |", "|---|---|---|---|---|---|"]
    for a in candidates:
        lines.append(
            f"| {a.name} | {'・'.join(a.kinds)} | {a.body} | {a.emotion} | {a.connection} | {a.strength} |"
        )
    return "\n".join(lines)


def generate_chains(fact: str, card: MemoryCard, anchors: list[Anchor]) -> list[ChainProposal]:
    """fact に対する連想鎖を必ず3案生成する。"""
    candidates = _candidate_anchors(anchors)
    if not candidates:
        raise ValueError(
            "使用可能なアンカーがありません（状態=採用 かつ 未使用のものが台帳に無い）。"
            "アンカー台帳DBに行を足すか、使用済みを整理してください。"
        )

    prompt = f"""あなたは記憶術（連想鎖）の設計者です。以下の「覚えたい事実」に対して、
個人のアンカー台帳だけを使った連想鎖を**ちょうど3案**作ってください。

## 覚えたい事実
{fact}

## 対象カード
- 項目: {card.title}
- 分野: {card.domain or "未設定"}
- 戻り先: {card.return_to or "未設定"}

## 使用可能なアンカー台帳（この表にある名前だけを使うこと）
{_anchor_table(candidates)}

## 生成ルール（原文・厳守）
{GENERATION_RULES}

## 追加の制約
- 各案は、属性系アンカーを1個以上 と 感情系アンカーを1個以上 組み合わせること（ルール#4）。
  種別は上の表の「種別」列で判断する（属性/人物/感情/数字）。
- 鎖は必ず覚えたい事実に戻って終わること（ルール#2）。逸れて終わる鎖は不可。
- 台帳外のアンカー（表に無い名前）は絶対に使わないこと（ルール#1）。
- 3案は互いに異なるアンカー構成にすること（同じアンカーの組み合わせを繰り返さない）。
- ルール#6の「自分の一言」は人間が書く領域です。一言やその候補・例を出力に含めないこと。
- "anchors" には表の「名前」列と完全一致する文字列だけを入れること。

## 出力形式
以下のJSONを、```json コードフェンスで囲んで出力してください。JSON以外の文章は不要です。

```json
{{"proposals": [
  {{"anchors": ["アンカー名", "..."],
    "chain": "アンカーA → 連想 → ... → （覚えたい事実に戻る）",
    "rationale": "なぜこの鎖が事実に戻るかの説明"}},
  {{...}},
  {{...}}
]}}
```"""

    client = _client()
    response = client.messages.create(
        model=anthropic_model(),
        max_tokens=_CHAINS_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    text = _response_text(response)
    return _parse_proposals(text, fact)


def _parse_proposals(text: str, fact: str) -> list[ChainProposal]:
    """LLM応答テキストから ChainProposal を3件パースする（純関数・テスト用に公開）。

    コードフェンス内JSON → 裸JSON の順で試す。3件未満やパース不能は ValueError。
    """
    data = None
    # 1) コードフェンス内の JSON
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL):
        try:
            data = json.loads(m.group(1).strip())
            break
        except (json.JSONDecodeError, ValueError):
            continue
    # 2) 裸の JSON（最初の { から最後の } まで）
    if data is None:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                data = None
    if data is None:
        raise ValueError(
            "連想鎖の応答からJSONをパースできませんでした。応答冒頭: " + text[:200]
        )

    if not isinstance(data, dict) or not isinstance(data.get("proposals"), list):
        raise ValueError(
            'JSONの形式が不正です（{"proposals": [...]} を期待）。得られたキー: '
            + str(list(data.keys()) if isinstance(data, dict) else type(data).__name__)
        )

    proposals: list[ChainProposal] = []
    for i, item in enumerate(data["proposals"]):
        if not isinstance(item, dict):
            raise ValueError(f"proposals[{i}] がオブジェクトではありません: {item!r}")
        anchors = item.get("anchors")
        chain = item.get("chain")
        if not isinstance(anchors, list) or not all(isinstance(a, str) for a in anchors) or not anchors:
            raise ValueError(f"proposals[{i}].anchors が不正です（文字列の非空リストを期待）: {anchors!r}")
        if not isinstance(chain, str) or not chain.strip():
            raise ValueError(f"proposals[{i}].chain が不正です（非空文字列を期待）: {chain!r}")
        proposals.append(
            ChainProposal(
                fact=fact,
                anchors=[a.strip() for a in anchors],
                chain=chain.strip(),
                rationale=str(item.get("rationale", "")).strip(),
            )
        )

    if len(proposals) < 3:
        raise ValueError(f"連想鎖の案が3件未満です（{len(proposals)}件）。応答を確認してください。")
    return proposals[:3]
