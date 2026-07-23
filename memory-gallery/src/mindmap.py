"""v2 構造層: 素材（テキスト/画像）→ 構造化マインドマップ(JSON) → Mermaid（検証用の正）。

構造と文字は決定論的に扱い、素材に書かれていないことは入れない。
生成された構造は verify_mindmap で素材との忠実性を照合してから作画に渡す。
"""
from __future__ import annotations

import json

from .chain import _client, _image_blocks, _response_text
from .gate import _extract_json
from .models import MemoryCard, anthropic_model


def _text_material(card: MemoryCard) -> str:
    """テキスト素材の共通表現。build_mindmap と verify_mindmap に**同一の素材**を渡す。

    素材の実体はカード本文のテキスト（notion.fetch_card_text で card.source_text に格納）。
    本文が空の場合は項目名だけになる（呼び出し側で needs_human 扱いにすること）。
    """
    parts = [f"素材（テキスト）: {card.title}"]
    if card.return_to:
        parts.append(f"戻り先: {card.return_to}")
    body = (card.source_text or "").strip()
    if body:
        parts.append(f"素材本文:\n{body}")
    return "\n".join(parts)


def build_mindmap(card: MemoryCard) -> dict:
    """素材からマインドマップ構造を抽出する。

    返り値: {"center": str, "theme": str, "branches": [
        {"label": str, "emoji": str, "children": [{"label": str}, ...]}, ...]}
    """
    client = _client()
    instruction = f"""この素材から、記憶定着用のマインドマップ構造を抽出してください。テーマ: 「{card.title}」（分野: {card.domain or '未指定'}）

# 厳守
- 素材に書かれていることだけを使う。推測・補完・一般知識の追加は禁止。
- 枝(branches)は素材の構造に従う（表なら行ごと、など）。3〜8本。
- 各枝の children は素材の属性をそのまま短いラベルにする（深さは1段まで）。
- ラベルは素材の表記を保つ（略しすぎない。数値・略語は一字一句そのまま）。
- emoji は各枝に1つ、内容に合うものを選ぶ。
- theme は中央に描くべき題材を一言で（例: OSPFルータとネットワーク）。

# 出力形式（このJSONのみをコードフェンスで出力）
```json
{{"center": "中心タイトル", "theme": "中央の題材", "branches": [
  {{"label": "枝1", "emoji": "🔴", "children": [{{"label": "属性A"}}, {{"label": "属性B"}}]}}
]}}
```"""
    if card.images:
        content: list[dict] = _image_blocks(card.images)
        content.append({"type": "text", "text": instruction})
    else:
        content = [{"type": "text", "text": f"{_text_material(card)}\n\n{instruction}"}]
    response = client.messages.create(
        model=anthropic_model(),
        max_tokens=4000,
        messages=[{"role": "user", "content": content}],
    )
    data = _extract_json(_response_text(response))
    if not data.get("center") or not data.get("branches"):
        raise ValueError("マインドマップ構造を抽出できませんでした（center/branches が空）")
    return data


def verify_mindmap(mindmap: dict, card: MemoryCard) -> list[str]:
    """構造が素材に忠実かを照合する。素材にない断定・矛盾のみ指摘（省略は指摘しない）。

    失敗時は素通しにせず NG 扱いの指摘を返す。
    """
    try:
        client = _client()
        instruction = f"""以下のマインドマップ構造(JSON)が、素材に忠実かを審査してください。

# マインドマップ構造
{json.dumps(mindmap, ensure_ascii=False)}

# 審査基準
- 素材に存在しない事実の追加、素材と矛盾する記述のみを指摘する
- 素材の一部が構造に含まれていない（省略）は指摘しない
- ラベルの言い換え・短縮は、意味が変わらなければ指摘しない
- 問題がなければ issues は空配列

# 出力形式（このJSONのみをコードフェンスで出力）
```json
{{"issues": ["指摘1"]}}
```"""
        if card.images:
            content: list[dict] = _image_blocks(card.images)
            content.append({"type": "text", "text": instruction})
        else:
            content = [{"type": "text", "text": f"{_text_material(card)}\n\n{instruction}"}]
        response = client.messages.create(
            model=anthropic_model(),
            max_tokens=2000,
            messages=[{"role": "user", "content": content}],
        )
        data = _extract_json(_response_text(response))
        return [str(x) for x in data.get("issues") or []]
    except Exception as e:  # noqa: BLE001 - 失敗=素通し禁止
        return [f"忠実性チェックを実行できませんでした（素通し禁止のためNG扱い）: {e}"]


def _sanitize_label(label: str) -> str:
    """Mermaid mindmap の構文文字を全角に逃がす（丸括弧はノード形状の構文になるため）。"""
    return (
        str(label)
        .replace("(", "（").replace(")", "）")
        .replace("[", "［").replace("]", "］")
        .replace("{", "｛").replace("}", "｝")
        .strip()
    )


def to_mermaid_mindmap(mindmap: dict) -> str:
    """構造を Mermaid mindmap に決定論的に変換する（検証用の正・Notion本文に残す）。"""
    lines = ["mindmap", f"  root(({_sanitize_label(mindmap.get('center', ''))}))"]
    for branch in mindmap.get("branches") or []:
        emoji = str(branch.get("emoji") or "").strip()
        label = _sanitize_label(branch.get("label", ""))
        lines.append(f"    {(emoji + ' ') if emoji else ''}{label}")
        for child in branch.get("children") or []:
            lines.append(f"      {_sanitize_label(child.get('label', ''))}")
    return "\n".join(lines)


def summary_line(mindmap: dict) -> str:
    """「連想鎖」プロパティに入れる処理済みマーカー兼サマリ。"""
    labels = " / ".join(
        _sanitize_label(b.get("label", "")) for b in mindmap.get("branches") or []
    )
    return f"🗺 mindmap生成済み: {labels}"
