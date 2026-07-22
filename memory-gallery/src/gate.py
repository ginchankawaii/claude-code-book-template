"""L1 事実照合ゲート: 記憶システムの安全装置の本体。

誤った連想を書き込むくらいなら何も作らない（CLAUDE.md 5章）。
static_checks は API 呼び出しなしの決定論チェック（純関数・テスト可能）。
llm_fact_check は懐疑モードの Claude で技術的断定を検証する。
API 失敗は「素通し」にせず issue として返す。
"""
from __future__ import annotations

import json
import os
import re

from .models import Anchor, ChainProposal, GateResult, anthropic_model


def _name_variants(name: str) -> list[str]:
    """アンカー名の許容表記。台帳名そのもの＋括弧の補足を除いた短縮形（例: 銀ちゃん（柴）→ 銀ちゃん）。"""
    variants = [name]
    base = re.sub(r"[（(].*?[）)]", "", name).strip()
    if base and base != name:
        variants.append(base)
    return variants


def _appears_in(name: str, chain_text: str) -> bool:
    return any(v in chain_text for v in _name_variants(name))


def static_checks(
    fact: str, proposals: list[ChainProposal], anchors: list[Anchor]
) -> list[str]:
    """決定論チェック（ルール#1/#3/#4ほか）。違反を日本語メッセージで返す。空リスト=合格。"""
    issues: list[str] = []
    by_name = {a.name: a for a in anchors}

    if len(proposals) != 3:
        issues.append(f"提案が3件ではありません（{len(proposals)}件）")

    anchor_sets: list[frozenset[str]] = []
    for idx, p in enumerate(proposals, 1):
        kinds: set[str] = set()
        for name in p.anchors:
            anchor = by_name.get(name)
            if anchor is None:
                issues.append(
                    f"案{idx}: 台帳にないアンカー「{name}」を使用しています（ルール#1）"
                )
                continue
            if anchor.used_by:
                issues.append(
                    f"案{idx}: 使用済みアンカー「{name}」を使い回しています（ルール#3）"
                )
            kinds.update(anchor.kinds)
        if "属性" not in kinds:
            issues.append(f"案{idx}: 属性アンカーが含まれていません（ルール#4）")
        if "感情" not in kinds:
            issues.append(f"案{idx}: 感情アンカーが含まれていません（ルール#4）")
        for name in p.anchors:
            if not _appears_in(name, p.chain):
                issues.append(f"案{idx}: アンカー「{name}」が連想鎖の文中に現れません")
        anchor_sets.append(frozenset(p.anchors))

    if len(anchor_sets) != len(set(anchor_sets)):
        issues.append("アンカー構成が完全に同一の案があります（3案は互いに変えること）")

    return issues


def _extract_json(text: str) -> dict:
    """LLM応答からJSONを頑健に取り出す（コードフェンス優先 → 裸JSON）。"""
    for m in re.finditer(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL):
        try:
            return json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"応答からJSONを抽出できません: {text[:200]!r}")


def llm_fact_check(fact: str, proposals: list[ChainProposal]) -> list[str]:
    """懐疑モードの Claude で技術的断定を検証する。失敗時はNG扱いの issue を返す（素通し禁止）。"""
    try:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY が未設定です")
        import anthropic  # 遅延 import

        chains = "\n".join(f"案{i}: {p.chain}" for i, p in enumerate(proposals, 1))
        prompt = f"""あなたは CCNP ENCOR(350-401) の技術審査官です。以下の「覚えたい事実」と各連想鎖に含まれる技術的断定を、公式ブループリントの知識で厳密に検証してください。

# 覚えたい事実
{fact}

# 連想鎖（記憶用の連想です。技術的断定の部分だけを審査してください）
{chains}

# 指示
- 技術的に誤り・不正確・古い断定だけを具体的に指摘する（連想の面白さ・良し悪しは審査しない）
- すべて正しければ issues は空配列にする

# 出力形式（このJSONのみをコードフェンスで出力）
```json
{{"issues": ["指摘1", "指摘2"]}}
```"""
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=anthropic_model(),
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        )
        data = _extract_json(text)
        return [str(x) for x in data.get("issues") or []]
    except Exception as e:  # noqa: BLE001 - 失敗=素通しを防ぐため一括でNGに倒す
        return [f"事実照合ゲートを実行できませんでした（素通し禁止のためNG扱い）: {e}"]


def verify(
    fact: str,
    proposals: list[ChainProposal],
    anchors: list[Anchor],
    has_images: bool,
) -> GateResult:
    """静的チェック＋LLM事実照合。静的チェックで違反があればLLMは呼ばない（すでにNG）。"""
    issues = static_checks(fact, proposals, anchors)
    if not issues:
        issues = llm_fact_check(fact, proposals)
    ok = not issues
    return GateResult(ok=ok, issues=issues, needs_human=bool(has_images) or not ok)
