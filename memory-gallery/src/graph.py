"""v3 結線エンジン: マインドマップの要所に、本人の記憶（アンカー台帳）と既存カードを結線する。

合意済みポリシー（CLAUDE.md v3 参照）:
- 結線は1枚につき1〜3個だけ（全部を強烈にすると差が消える）
- 属性アンカー = 再利用可（体系ごとの固定キャラ化を推奨）／感情アンカー = 1項目専有
- 生成画像に入れてよいのは「視覚イメージ」のみ。人名・エピソード文字は絵に入れない
  （連想の説明文は Notion 本文にだけ記録する）
- 結線の中の技術的断定も事実照合の対象（誤った理由づけを絵にしない）
"""
from __future__ import annotations

import json

from .chain import _client, _response_text
from .gate import _extract_json, _name_variants
from .models import Anchor, MemoryCard, anthropic_model

MAX_LINKS = 3


def propose_links(
    mindmap: dict,
    card: MemoryCard,
    anchors: list[Anchor],
    other_cards: list[MemoryCard],
) -> list[dict]:
    """結線案を1〜3個提案する。

    返り値の各要素:
      {"node": 枝ラベル or "center", "anchor": 台帳名 or null,
       "related_card": 既存カード項目名 or null,
       "reason": なぜ効くか（Notion本文用。人名可）,
       "visual": 絵に描く小さな挿絵の描写（人名・固有エピソード語を含めない）}
    """
    usable = [
        a for a in anchors
        if a.status == "採用" and not ("感情" in a.kinds and a.used_by)
    ]
    if not usable and not other_cards:
        return []
    ledger_rows = "\n".join(
        f"| {a.name} | {'/'.join(a.kinds)} | {a.body} | {a.emotion} | {a.connection} |"
        + (" 使用済み |" if a.used_by else " 未使用 |")
        for a in usable
    )
    card_titles = "\n".join(f"- {c.title}" for c in other_cards if c.page_id != card.page_id)
    branch_labels = "\n".join(
        f"- {b.get('label', '')}" for b in mindmap.get("branches") or []
    )
    prompt = f"""あなたは記憶術（精緻化・既有知識への接続）の専門家です。
以下のマインドマップの「要所」に、本人の既存の記憶や既習カードを結線し、記憶定着を強化します。

# マインドマップ
中央: {mindmap.get('center', '')}
枝:
{branch_labels}

# 本人のアンカー台帳（この表からだけ選ぶ）
| アンカー | 種別 | 中身 | 感情 | 接続先 | 使用状況 |
|---|---|---|---|---|---|
{ledger_rows}

# 既習カード（関連が強いものがあれば結線できる）
{card_titles or '（なし）'}

# ルール（厳守）
- 結線は最大{MAX_LINKS}個。**一番間違えやすい・重要な箇所だけ**。全部に付けると差が消えて効かなくなる
- アンカーは台帳の表記と一字一句同じ名前で指定。台帳外は禁止
- 種別に「感情」を含むアンカーで「使用済み」のものは使えない（1項目専有）
- 属性アンカーは再利用可。番号・体系もの（例: タイプ番号）には「番号=属性」系アンカーを体系ごと固定するのが強い
- reason: なぜこの結線で覚えられるかを1文で（本人だけが読む。固有名詞可）
- visual: 絵に描く小さな挿絵の描写。**人名・ペット名・固有エピソードの文字は禁止**。
  一般名詞のイメージだけで書く（例:「吠える柴犬」「頬袋を膨らませたハムスター」「図鑑風の番号つきモンスター」）
- 迷ったら結線しない。無理なこじつけはゼロ個でよい

# 出力形式（このJSONのみをコードフェンスで出力）
```json
{{"links": [{{"node": "枝ラベルまたはcenter", "anchor": "台帳名またはnull",
  "related_card": "既習カード名またはnull", "reason": "1文", "visual": "挿絵の描写"}}]}}
```"""
    response = _client().messages.create(
        model=anthropic_model(),
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    data = _extract_json(_response_text(response))
    links = [x for x in (data.get("links") or []) if isinstance(x, dict)]
    return links[:MAX_LINKS]


def static_check_links(
    links: list[dict],
    mindmap: dict,
    anchors: list[Anchor],
    other_cards: list[MemoryCard],
) -> tuple[list[dict], list[str]]:
    """結線案の決定論チェック。合格した結線と、除外理由を返す（純関数・テスト可能）。"""
    by_name = {a.name: a for a in anchors}
    labels = {str(b.get("label", "")).strip() for b in mindmap.get("branches") or []}
    labels.add("center")
    card_titles = {c.title for c in other_cards}
    # 禁止語は種別を問わず**全アンカー**の名前から集める。
    # 属性アンカーにもペット名・家族名（例: 「銀ちゃん（柴）」）が登録されるため、
    # 人物/感情に限定すると固有名が画像プロンプトへ漏れる（CLAUDE.md v3 の静的遮断の約束）。
    forbidden_words: set[str] = set()
    for a in anchors:
        for variant in _name_variants(a.name):
            if len(variant) >= 2:
                forbidden_words.add(variant)

    valid: list[dict] = []
    issues: list[str] = []
    for link in links:
        node = str(link.get("node") or "").strip()
        anchor_name = link.get("anchor") or None
        related = link.get("related_card") or None
        visual = str(link.get("visual") or "")
        if node not in labels:
            issues.append(f"結線除外: ノード「{node}」がマップに存在しません")
            continue
        if not anchor_name and not related:
            issues.append(f"結線除外: 「{node}」への結線にアンカーもカードも指定がありません")
            continue
        if anchor_name:
            anchor = by_name.get(str(anchor_name))
            if anchor is None:
                issues.append(f"結線除外: 台帳にないアンカー「{anchor_name}」（ルール#1）")
                continue
            if "感情" in anchor.kinds and anchor.used_by:
                issues.append(
                    f"結線除外: 感情アンカー「{anchor_name}」は使用済み（1項目専有）"
                )
                continue
        if related and str(related) not in card_titles:
            issues.append(f"結線除外: 既習カード「{related}」が見つかりません")
            continue
        leaked = [w for w in forbidden_words if w in visual]
        if leaked:
            issues.append(
                f"結線除外: 「{node}」の挿絵描写に個人的な名前が含まれています（絵はイメージのみ）"
            )
            continue
        # 既習カードのタイトルが個人語（アンカー名と一致・包含）の場合、結線（relation・本文記録）は
        # 許可しつつ、絵の道標「関連: カード名」の描画だけ抑止する（エピソード文字を画像APIへ送らない）。
        if related and any(w in str(related) for w in forbidden_words):
            link = {**link, "suppress_signpost": True}
            issues.append(
                f"道標抑止: 「{node}」の関連カード名に個人的な名前が含まれるため、"
                "絵の道標は描きません（結線は保持）"
            )
        valid.append(link)
    if len(valid) > MAX_LINKS:
        issues.append(f"結線は最大{MAX_LINKS}個のため超過分を除外しました")
        valid = valid[:MAX_LINKS]
    return valid, issues


def verify_link_claims(links: list[dict], center: str) -> tuple[list[dict], list[str]]:
    """結線の reason に含まれる技術的断定を審査し、誤りのある結線だけ除外する。

    失敗時は素通しにせず全結線を外す（結線なしでもマップ自体は成立する）。
    """
    if not links:
        return [], []
    try:
        numbered = "\n".join(
            f"{i}: {link.get('reason', '')}" for i, link in enumerate(links, 1)
        )
        prompt = f"""あなたは CCNP ENCOR(350-401) の技術審査官です。「{center}」に関する以下の記憶用の連想文について、
技術的な断定が誤っている場合のみ、その番号を指摘してください。

{numbered}

# 審査基準
- 個人的な記憶とのこじつけは記憶術として正当。審査しない
- 比喩が技術的な因果・理由として断定され、それが誤りの場合のみ指摘
- 省略・不完全は指摘しない
- 問題がなければ issues は空配列

# 出力形式（このJSONのみをコードフェンスで出力）
```json
{{"issues": [{{"number": 1, "issue": "指摘内容"}}]}}
```"""
        response = _client().messages.create(
            model=anthropic_model(),
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _extract_json(_response_text(response))
        bad: dict[int, str] = {}
        for item in data.get("issues") or []:
            number = item.get("number") if isinstance(item, dict) else None
            text = str(item.get("issue") or "") if isinstance(item, dict) else str(item)
            if isinstance(number, (int, float)) and 1 <= int(number) <= len(links):
                bad[int(number)] = text
            elif text:
                # 番号が不正・範囲外でも「指摘あり」を素通しにしない（gate と同じ失敗ポリシー）
                return [], [f"結線の審査結果を対応付けできないため結線なしで続行します: {text}"]
        kept = [link for i, link in enumerate(links, 1) if i not in bad]
        issues = [f"結線除外（技術的誤り）: {text}" for text in bad.values()]
        return kept, issues
    except Exception as e:  # noqa: BLE001 - 失敗=素通し禁止。結線なしで続行
        return [], [f"結線の事実照合を実行できなかったため結線なしで続行します: {e}"]


def links_body_lines(links: list[dict]) -> list[str]:
    """Notion 本文に記録する結線の説明行（人名可・本人だけが読む）。"""
    lines = []
    for link in links:
        target = link.get("anchor") or link.get("related_card") or ""
        lines.append(f"🔗 {link.get('node')} ← {target}: {link.get('reason', '')}")
    return lines
