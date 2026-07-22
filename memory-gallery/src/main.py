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

from . import chain, gate, graph, mindmap, render, skeleton
from .models import STATE_ACTIVE, MemoryCard
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
        raw = graph.propose_links(structure, card, anchors, all_cards)
        links, notes = graph.static_check_links(raw, structure, anchors, all_cards)
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


def process_card_mindmap(notion: NotionClient, card: MemoryCard, anchors: list,
                         all_cards: list, args: argparse.Namespace, stats: dict) -> None:
    card.images = notion.fetch_card_images(card.page_id)
    if card.images:
        print(f"  画像添付 {len(card.images)} 枚を取得")

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
    mermaid = mindmap.to_mermaid_mindmap(structure)

    if args.dry_run:
        print("  [dry-run] 作画・書き込みは行いません。Mermaid:")
        print("  " + mermaid.replace("\n", "\n  "))
        if links:
            print("  結線:")
            for line in graph.links_body_lines(links):
                print(f"    {line}")
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
    notion.write_mindmap_result(
        card, mermaid, mindmap.summary_line(structure),
        issues=graph.links_body_lines(links) + link_notes, state=STATE_ACTIVE,
    )
    if links:
        linked_anchor_names = [l["anchor"] for l in links if l.get("anchor")]
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
    notion = NotionClient()

    print("アンカー台帳を取得中...")
    anchors = notion.fetch_anchors()
    usable = [a for a in anchors if not a.used_by]
    print(f"  採用アンカー {len(anchors)} 件（うち未使用 {len(usable)} 件）")
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
