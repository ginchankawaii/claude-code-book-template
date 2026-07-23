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


def llm_fact_check(
    fact: str, proposals: list[ChainProposal]
) -> list[tuple[int | None, str]]:
    """懐疑モードの Claude で技術的断定を検証する。

    返り値は (案番号, 指摘) のリスト。案番号 None は事実そのものの誤り（全案NG級）。
    失敗時は (None, NG理由) を返す（素通し禁止）。
    """
    try:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY が未設定です")
        import anthropic  # 遅延 import

        chains = "\n".join(f"案{i}: {p.chain}" for i, p in enumerate(proposals, 1))
        prompt = f"""あなたは CCNP ENCOR(350-401) の技術審査官です。以下の「覚えたい事実」と各連想鎖に含まれる技術的断定を検証してください。

# 覚えたい事実
{fact}

# 連想鎖（記憶術の連想です）
{chains}

# 審査基準（厳守）
- 指摘するのは【技術的な断定が誤っている場合】のみ。
- 個人的な記憶・比喩へのこじつけは記憶術として正当。審査しない。
  ただし比喩が技術的な因果・理由として断定され、それが誤りの場合は指摘する
  （例: 「エリア内に留まるのはTTLのせい」→ 実際はフラッディングスコープの仕様なので誤り）。
- 説明の省略・不完全さ・網羅性の欠如は指摘しない（誤りではない）。
- 「覚えたい事実」自体が誤っている場合は proposal を null にして指摘する。
- 問題がなければ issues は空配列。

# 出力形式（このJSONのみをコードフェンスで出力）
```json
{{"issues": [{{"proposal": 2, "issue": "指摘内容"}}]}}
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
        results: list[tuple[int | None, str]] = []
        for item in data.get("issues") or []:
            if isinstance(item, dict):
                prop = item.get("proposal")
                prop = int(prop) if isinstance(prop, (int, float)) else None
                results.append((prop, str(item.get("issue") or "")))
            else:  # 想定外の形式は全案NG級として扱う（防御）
                results.append((None, str(item)))
        return [(p, t) for p, t in results if t]
    except Exception as e:  # noqa: BLE001 - 失敗=素通しを防ぐため一括でNGに倒す
        return [(None, f"事実照合ゲートを実行できませんでした（素通し禁止のためNG扱い）: {e}")]


def verify(
    fact: str,
    proposals: list[ChainProposal],
    anchors: list[Anchor],
    has_images: bool,
) -> GateResult:
    """静的チェック＋LLM事実照合。

    - 静的チェック違反（構造の問題）→ 全案NG
    - 事実そのものの誤り／ゲート実行不能 → 全案NG
    - 特定の案の技術的誤り → その案だけ除外し、無傷の案は kept_indices に残す
    """
    static_issues = static_checks(fact, proposals, anchors)
    if static_issues:
        return GateResult(ok=False, issues=static_issues, needs_human=True, kept_indices=[])

    llm_issues = llm_fact_check(fact, proposals)
    fatal = [t for p, t in llm_issues if p is None or not (1 <= p <= len(proposals))]
    bad_numbers = {p for p, _ in llm_issues if p is not None and 1 <= p <= len(proposals)}
    kept = [i for i in range(len(proposals)) if (i + 1) not in bad_numbers]
    texts = [f"案{p}: {t}" if p else t for p, t in llm_issues]

    if fatal or not kept:
        return GateResult(ok=False, issues=texts, needs_human=True, kept_indices=[])
    return GateResult(
        ok=True,
        issues=texts,  # 除外した案の理由（書き込み時に記録される）
        needs_human=bool(has_images) or bool(texts),
        kept_indices=kept,
    )
