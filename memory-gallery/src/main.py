"""CLI 入口: python3 -m src.main run [--dry-run] [--card PAGE_ID] [--yes] [--chains]

既定フロー（v2 mindmap モード）:
  記憶カードの素材（テキスト/画像） → 構造化マインドマップ（Claude）
  → 忠実性チェック（素材にない事実は絵にしない） → 手描き風イラスト（Nano Banana / Gemini）
  → Notion カードのカバー＋本文に自動添付 → ギャラリービューで眺める

--chains で v1 の連想鎖モード（アンカー台帳ベース・3案生成）に切り替え。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import traceback

from . import chain, gate, graph, interview, mindmap, render, skeleton
from .models import STATE_ACTIVE, Anchor, MemoryCard
from .notion import NotionClient

OUT_DIR = "out"


def _load_dotenv(path: str = ".env") -> None:
    """カレントの .env を手でパースして環境変数に反映する（python-dotenv 非依存）。"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and value:
                os.environ.setdefault(key, value)


def _safe_filename(title: str) -> str:
    name = re.sub(r"[^\w぀-ヿ一-鿿-]+", "_", title).strip("_")
    return (name or "mindmap")[:60]


def _print_structure(m: dict) -> None:
    print(f"  中央: {m.get('center')}（題材: {m.get('theme')}）")
    for branch in m.get("branches") or []:
        emoji = branch.get("emoji") or ""
        print(f"    {emoji} {branch.get('label')}")
        for child in branch.get("children") or []:
            print(f"       - {child.get('label')}")


# ---------------------------------------------------------------------------
# v2: mindmap モード
# ---------------------------------------------------------------------------

def _propose_links(structure: dict, card: MemoryCard, anchors: list,
                   all_cards: list, args: argparse.Namespace) -> tuple[list[dict], list[str]]:
    """結線（アンカー・既習カード）を提案し、チェックと本人確認を通す。失敗しても結線なしで続行。"""
    try:
        others = [c for c in all_cards if c.page_id != card.page_id]  # 自己結線防止
        raw = graph.propose_links(structure, card, anchors, others)
        links, notes = graph.static_check_links(raw, structure, anchors, others)
        links, claim_notes = graph.verify_link_claims(links, structure.get("center", ""))
        notes += claim_notes
        if links:
            print("  記憶フックの結線案:")
            for link in links:
                target = link.get("anchor") or link.get("related_card") or ""
                print(f"    🔗 {link.get('node')} ← {target}")
                print(f"       {link.get('reason', '')}")
                print(f"       挿絵: {link.get('visual', '')}")
            if not args.yes and not args.dry_run:
                answer = input("  この結線を使いますか? [y=使う / n=結線なしで続行] > ").strip().lower()
                if answer != "y":
                    return [], notes
        else:
            print("  結線なし（効くアンカー・既習カードが見つかりませんでした）")
        return links, notes
    except Exception as e:  # 結線は付加機能。失敗してもマップ生成は止めない
        print(f"  ⚠ 結線エンジンをスキップ: {e}")
        return [], []


def _interview_anchor(notion: NotionClient, structure: dict, card: MemoryCard,
                      anchors: list, links: list[dict],
                      args: argparse.Namespace) -> tuple[list[dict], list[str]]:
    """台帳に効くアンカー結線が無かったとき、本人に質問して新アンカーを引き出す（v3.1）。

    対話モード限定（--yes / --dry-run では発動しない）。本人がその場で語り y 確認した
    記憶は 状態=採用 で台帳に追加して即結線する（機械の自動提案ではなく本人の口述の
    ため「候補どまり」規約の対象外）。曖昧な回答・チェックNGは何も書かない（fail-closed）。
    """
    if args.yes or args.dry_run:
        return links, []
    if any(l.get("anchor") for l in links) or len(links) >= graph.MAX_LINKS:
        return links, []
    try:
        q = interview.propose_question(structure, card, anchors)
    except Exception as e:  # インタビューは付加機能。失敗してもマップ生成は止めない
        print(f"  ⚠ インタビューをスキップ: {e}")
        return links, []
    if not q:
        return links, []
    print("\n  💬 台帳に効くアンカーが見つかりませんでした。あなたの記憶から新アンカーを作れます。")
    print(f"  Q. {q['question']}")
    if q.get("hints"):
        print(f"     （例えばこんな方向: {' / '.join(q['hints'])}）")
    answer = input("  A. 思い浮かんだ体験をひと言（Enterのみ=スキップ） > ").strip()
    if not answer:
        print("  スキップしました（台帳はそのまま）。")
        return links, []
    try:
        row = interview.anchor_from_answer(q["node"], q["question"], answer, card)
    except Exception as e:
        print(f"  ⚠ アンカー化に失敗したためスキップ: {e}")
        return links, []
    if row is None:
        print("  回答からアンカーを作れませんでした（曖昧な場合は無理に作りません）。")
        return links, []
    print("  新アンカー案:")
    kinds_label = "/".join(row["kinds"]) + (f" / 感情: {row['emotion']}" if row["emotion"] else "")
    print(f"    アンカー: {row['name']}（{kinds_label}）")
    print(f"    中身:     {row['body']}")
    print(f"    接続先:   {row['connection']}")
    print(f"    結線先:   {q['node']} — {row['reason']}")
    print(f"    挿絵:     {row['visual']}")
    confirm = input("  この記憶を台帳に追加（状態=採用）して結線しますか? [y/n] > ").strip().lower()
    if confirm != "y":
        print("  追加しませんでした。")
        return links, []
    new_anchor = Anchor(page_id="", name=row["name"], kinds=row["kinds"], body=row["body"],
                        emotion=row["emotion"], connection=row["connection"], status="採用")
    link = {"node": q["node"], "anchor": row["name"], "related_card": None,
            "reason": row["reason"], "visual": row["visual"]}
    # 新アンカー名込みで静的チェック（挿絵への人名混入をここでも遮断）→ 技術的断定の審査
    checked, notes = graph.static_check_links([link], structure, anchors + [new_anchor], [])
    kept, claim_notes = graph.verify_link_claims(checked, structure.get("center", ""))
    notes += claim_notes
    if not kept:
        print("  ✗ チェックNGのため台帳追加も結線も行いません:")
        for note in notes:
            print(f"    - {note}")
        return links, []
    try:
        new_anchor.page_id = notion.create_anchor(
            row["name"], row["kinds"], row["body"], row["emotion"], row["connection"]
        )
    except Exception as e:
        print(f"  ✗ 台帳への追加に失敗したため結線しません（ルール#1: 台帳外は使わない）: {e}")
        return links, []
    anchors.append(new_anchor)  # mark_anchors_used と同一バッチ内の専有チェック用
    notes.append(f"🆕 インタビューで新アンカー「{row['name']}」を台帳に追加（状態=採用）")
    print(f"  ✓ 台帳に追加しました。この結線を絵に反映します。")
    return links + kept, notes


def process_card_mindmap(notion: NotionClient, card: MemoryCard, anchors: list,
                         all_cards: list, args: argparse.Namespace, stats: dict) -> None:
    card.images = notion.fetch_card_images(card.page_id)
    if card.images:
        print(f"  画像添付 {len(card.images)} 枚を取得")
    card.source_text = notion.fetch_card_text(card.page_id)
    if card.source_text:
        print("  本文のテキスト素材を取得")
    if not card.images and not card.source_text.strip():
        # 素材が項目名しかない＝「素材に書かれていることだけを使う」が成立しない。
        # 無人モードでは作画しない（一般知識の補完＝ハルシネーション経路を塞ぐ）。
        print("  ⚠ 素材がありません（本文にテキストも画像もなし。項目名のみ）")
        if args.yes and not args.dry_run:
            stats["skipped"] += 1
            print("  無人モードでは素材なしカードを処理しません。"
                  "カード本文に素材（テキスト or 画像）を貼ってから再実行してください。")
            return

    print("  構造を抽出中...")
    structure = mindmap.build_mindmap(card)
    _print_structure(structure)

    if not args.yes and not args.dry_run:
        answer = input("  この構造で作画しますか? [y=作画 / n=スキップ] > ").strip().lower()
        if answer != "y":
            stats["skipped"] += 1
            print("  スキップしました。")
            return

    issues = mindmap.verify_mindmap(structure, card)
    if issues:
        stats["gate_ng"] += 1
        print("  ✗ 忠実性チェックNG。作画しません（誤りを絵にしない）:")
        for issue in issues:
            print(f"    - {issue}")
        return

    links, link_notes = _propose_links(structure, card, anchors, all_cards, args)
    links, interview_notes = _interview_anchor(notion, structure, card, anchors, links, args)
    link_notes += interview_notes
    mermaid = mindmap.to_mermaid_mindmap(structure)

    if args.dry_run:
        print("  [dry-run] 作画・書き込みは行いません。Mermaid:")
        print("  " + mermaid.replace("\n", "\n  "))
        if links:
            print("  結線:")
            for line in graph.links_body_lines(links):
                print(f"    {line}")
        return

    leaks = graph.mindmap_label_leaks(structure, anchors)
    if leaks:
        stats["gate_ng"] += 1
        print("  ✗ マップのラベルに絵に出せない個人的な名前が含まれるため作画を中止します（fail-closed）:")
        for label in leaks:
            print(f"    - {label}")
        print("    素材から名前を外す（または台帳の「絵に出してOK」をチェックする）と作画できます。")
        return

    print(f"  Nano Banana ({render.gemini_image_model()}) で作画中...（数十秒かかります）")
    image_bytes, mime = render.render_mindmap_image(structure, links)
    ext = "png" if "png" in mime else mime.split("/")[-1]
    os.makedirs(OUT_DIR, exist_ok=True)
    filename = f"{_safe_filename(card.title)}.{ext}"
    local_path = os.path.join(OUT_DIR, filename)
    with open(local_path, "wb") as f:
        f.write(image_bytes)
    print(f"  画像を保存: {local_path}")

    print("  Notion へアップロード中...")
    upload_id = notion.upload_file(filename, image_bytes, content_type=mime)
    notion.set_cover(card.page_id, upload_id)
    # カバーと本文は同じ file_upload id を使い回せない場合に備え、本文用に再アップロード
    upload_id_body = notion.upload_file(filename, image_bytes, content_type=mime)
    notion.append_image(card.page_id, upload_id_body, caption=card.title)
    linked_anchor_names = [l["anchor"] for l in links if l.get("anchor")]
    chain_text = " ／ ".join(
        str(l.get("reason") or "").strip() for l in links if str(l.get("reason") or "").strip()
    )
    notion.write_mindmap_result(
        card, mermaid, mindmap.summary_line(structure),
        issues=link_notes, state=STATE_ACTIVE,
        anchor_names=linked_anchor_names,
        link_lines=graph.links_body_lines(links),
        chain_text=chain_text or None,
    )
    if links:
        if linked_anchor_names:
            notion.mark_anchors_used(linked_anchor_names, card, anchors)
        related_ids = [
            c.page_id for c in all_cards
            if c.title in {l.get("related_card") for l in links if l.get("related_card")}
        ]
        notion.set_related_cards(card.page_id, related_ids)
    stats["written"] += 1
    print("  ✓ 完了。カバー画像つきでカードに添付しました（ギャラリービューで見えます）。")


# ---------------------------------------------------------------------------
# v1: 連想鎖モード（--chains）
# ---------------------------------------------------------------------------

def _confirm_fact(fact: str) -> str | None:
    print(f"\n  抽出した『覚えたい事実』:\n    {fact}")
    while True:
        answer = input("  この事実で正しいですか? [y=採用 / e=修正 / n=スキップ] > ").strip().lower()
        if answer == "y":
            return fact
        if answer == "n":
            return None
        if answer == "e":
            edited = input("  正しい事実を入力してください > ").strip()
            if edited:
                return edited


def process_card_chains(notion: NotionClient, card: MemoryCard, anchors: list,
                        args: argparse.Namespace, stats: dict) -> None:
    card.images = notion.fetch_card_images(card.page_id)
    if card.images:
        print(f"  画像添付 {len(card.images)} 枚を取得")

    fact = chain.extract_fact(card)
    if card.images and not args.yes:
        confirmed = _confirm_fact(fact)
        if confirmed is None:
            stats["skipped"] += 1
            print("  スキップしました。")
            return
        fact = confirmed
    else:
        print(f"  覚えたい事実: {fact}")

    proposals = chain.generate_chains(fact, card, anchors)
    result = gate.verify(fact, proposals, anchors, has_images=bool(card.images))

    if not result.ok:
        stats["gate_ng"] += 1
        print("  ✗ 事実照合ゲートNG。書き込みません（何も作らないほうがマシ）:")
        for issue in result.issues:
            print(f"    - {issue}")
        return

    kept = [proposals[i] for i in result.kept_indices] or proposals
    if len(kept) < len(proposals):
        print(f"  ⚠ {len(proposals) - len(kept)} 案は技術的誤りのため除外:")
        for issue in result.issues:
            print(f"    - {issue}")
    proposals = kept

    mermaids = [skeleton.to_mermaid(p) for p in proposals]

    if args.dry_run:
        print("  [dry-run] 書き込みは行いません。生成結果:")
        for i, (p, mm) in enumerate(zip(proposals, mermaids), 1):
            print(f"\n  --- 案{i} ---")
            print(f"  アンカー: {' / '.join(p.anchors)}")
            print(f"  連想鎖:   {p.chain}")
            if p.rationale:
                print(f"  根拠:     {p.rationale}")
            print("  " + mm.replace("\n", "\n  "))
        return

    notion.write_result(card, fact, proposals, mermaids, result)
    notion.mark_anchors_used(proposals[0].anchors, card, anchors)
    stats["written"] += 1
    note = "（⚠️ 事実は要目視確認の注記つき）" if result.needs_human else ""
    print(f"  ✓ 書き込み完了{note}。状態=一言待ち。")
    print("    →「自分の一言」を Notion で手書きしたら状態を「運用中」にして、Ping-t へ戻ってください。")


# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    _load_dotenv()

    # 既定（v2）フローは作画に GEMINI_API_KEY が必須。構造抽出（Claude API 課金）や
    # 本人確認を消費した後に落ちないよう、最初に fail-fast する。
    if not args.chains and not args.dry_run:
        try:
            render.gemini_api_key()
        except RuntimeError as e:
            print(f"✗ {e}")
            print("  既定の作画フロー（v2）には GEMINI_API_KEY が必要です。"
                  "--dry-run なら未設定でも構造抽出まで確認できます。")
            return 1

    notion = NotionClient()

    print("アンカー台帳を取得中...")
    anchors = notion.fetch_anchors()
    usable = [a for a in anchors if not a.used_by]
    print(f"  採用アンカー {len(anchors)} 件（うち未使用 {len(usable)} 件）")

    if args.chains:
        # v1 連想鎖モードの静的ゲートは各案に属性1＋感情1を要求する。台帳が足りないと
        # extract_fact（課金）後に全カードが必ず失敗するため、カード処理前に fail-fast する。
        usable_kinds: set[str] = set()
        for a in usable:
            usable_kinds.update(a.kinds)
        if not usable or "属性" not in usable_kinds or "感情" not in usable_kinds:
            print("アンカー台帳に使えるアンカーが足りません。")
            print("  --chains には「状態=採用 かつ 未使用」の属性アンカー1件＋感情アンカー1件以上が必要です。")
            print("  アンカー台帳DBに行を足す（または使用済みを整理する）→ 状態を「採用」にしてから再実行してください。")
            return 0

    all_cards = [] if args.chains else notion.fetch_all_cards()

    if args.card:
        cards = [notion.fetch_card(args.card)]
    else:
        print("未処理カード（連想鎖が空）を取得中...")
        cards = notion.fetch_pending_cards()
    if not cards:
        print("未処理のカードはありません。")
        return 0
    print(f"  対象カード {len(cards)} 件")

    stats = {"processed": 0, "written": 0, "skipped": 0, "gate_ng": 0}
    for card in cards:
        stats["processed"] += 1
        print(f"\n=== {card.title} ===")
        try:
            if args.chains:
                process_card_chains(notion, card, anchors, args, stats)
            else:
                process_card_mindmap(notion, card, anchors, all_cards, args, stats)
        except KeyboardInterrupt:
            print("\n中断しました。")
            break
        except Exception as e:  # カード単位で隔離して次へ
            stats["skipped"] += 1
            print(f"  ✗ エラー（このカードは飛ばします）: {e}")
            if os.environ.get("MEMORY_GALLERY_DEBUG"):
                traceback.print_exc()

    print(
        f"\n処理 {stats['processed']} / 書込 {stats['written']} / "
        f"スキップ {stats['skipped']} / ゲートNG {stats['gate_ng']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="memory-gallery",
        description="覚えたい素材を手描き風マインドマップ画像にして Notion ギャラリーに貯める",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="連想鎖が空の記憶カードを処理する")
    run_parser.add_argument("--dry-run", action="store_true",
                            help="構造抽出まで（作画・書き込みなし）")
    run_parser.add_argument("--card", metavar="PAGE_ID", help="特定カードだけ処理")
    run_parser.add_argument("--yes", action="store_true",
                            help="無人バッチ（確認プロンプトなし）")
    run_parser.add_argument("--chains", action="store_true",
                            help="v1 連想鎖モード（アンカー台帳ベース）")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
