"""v2 意匠層 (L3): マインドマップ構造を Nano Banana (Gemini 画像生成API) で手描き風の絵にする。

構造・文字は build_image_prompt が一字一句そのまま指定し、絵柄だけを生成AIに任せる
（内容のハルシネーション余地を最小化する）。
"""
from __future__ import annotations

import base64
import os

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def gemini_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY が未設定です。https://aistudio.google.com/apikey で発行し .env に記入してください。"
        )
    return key


def gemini_image_model() -> str:
    """使用モデル。既定は Nano Banana Pro (Gemini 3 Pro Image)。env で上書き可。"""
    return os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")


def build_image_prompt(mindmap: dict, links: list[dict] | None = None) -> str:
    """構造を一字一句埋め込んだ作画指示を決定論的に組み立てる（テスト可能な純関数）。

    links の visual（人名を含まない挿絵描写）は該当ノードの近くに描かせる。
    """
    lines = [
        "以下の構造の「手描き風マインドマップ」のイラストを1枚描いてください。",
        "",
        "# 内容（文字は一字一句このまま。内容の追加・変更・省略は禁止）",
        f"中央: {mindmap.get('center', '')}（{mindmap.get('theme', '')} の可愛いイラストを添える）",
    ]
    for i, branch in enumerate(mindmap.get("branches") or [], 1):
        emoji = str(branch.get("emoji") or "").strip()
        lines.append(f"枝{i} {emoji}: {branch.get('label', '')}")
        for child in branch.get("children") or []:
            lines.append(f"  - {child.get('label', '')}")
    if links:
        lines += ["", "# 記憶フックの挿絵（指定ノードのすぐ近くに、目立つ小さな挿絵として描く）"]
        for link in links:
            node = link.get("node")
            place = "中央のすぐ横" if node == "center" else f"「{node}」の枝のすぐ近く"
            lines.append(f"- {place}: {link.get('visual', '')}")
            if link.get("related_card"):
                lines.append(
                    f"- マップの端、「{node}」寄りに小さな道標: 「関連: {link['related_card']}」"
                )
        lines.append("※ 挿絵は絵のみで説明文字を書かない（道標の「関連: …」だけは文字可）")
    lines += [
        "",
        "# スタイル",
        "- 紙のノートに色ペンで描いたような手描き風マインドマップ",
        "- 中央から色つきの太い曲線の枝が放射状に伸びる（枝ごとに別の色）",
        "- 各枝の先に小さなアイコンやイラスト（内容に対応するもの）",
        "- 文字は読みやすい手書き風の日本語。誤字なく正確に",
        "- 明るく記憶に残る配色、余白は少なめ、縦長",
        "# 禁止",
        "- 上記に無い文字・数値・事実を描き足すこと",
    ]
    return "\n".join(lines)


def _extract_image(payload: dict) -> tuple[bytes, str]:
    """generateContent 応答から最初の画像 (bytes, mime) を取り出す。camel/snake 両対応。"""
    for candidate in payload.get("candidates") or []:
        for part in ((candidate.get("content") or {}).get("parts")) or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                return base64.b64decode(inline["data"]), mime
    raise RuntimeError(
        "Gemini 応答に画像が含まれていません（テキストのみ返った可能性）。"
        " GEMINI_IMAGE_MODEL が画像生成対応モデルか確認してください。"
    )


def list_models() -> list[str]:
    """診断用: 利用可能なモデル名一覧を返す。"""
    import requests

    resp = requests.get(
        f"{GEMINI_API_BASE}/models", params={"key": gemini_api_key()}, timeout=60
    )
    if resp.status_code >= 400:
        return []
    return [m.get("name", "") for m in (resp.json().get("models") or [])]


def render_mindmap_image(mindmap: dict, links: list[dict] | None = None) -> tuple[bytes, str]:
    """マインドマップ構造から手描き風イラストを生成する。返り値 (画像bytes, MIME)。"""
    import requests

    model = gemini_image_model()
    body = {
        "contents": [{"parts": [{"text": build_image_prompt(mindmap, links)}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    resp = requests.post(
        f"{GEMINI_API_BASE}/models/{model}:generateContent",
        params={"key": gemini_api_key()},
        json=body,
        timeout=300,
    )
    if resp.status_code == 404:
        candidates = [m for m in list_models() if "image" in m.lower()]
        hint = f" 画像系モデル候補: {', '.join(candidates)}" if candidates else ""
        raise RuntimeError(
            f"モデル「{model}」が見つかりません(404)。.env の GEMINI_IMAGE_MODEL を修正してください。{hint}"
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Gemini API エラー {resp.status_code} (model={model}): {resp.text[:1500]}"
        )
    return _extract_image(resp.json())
