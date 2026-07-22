"""CLI 入口: python3 -m src.main run [--dry-run] [--card PAGE_ID] [--yes]

フロー（CLAUDE.md 5章。順序を死守: 入力画像 → 事実の確認 → 連想鎖）:
  1. 未処理カード（連想鎖が空）とアンカー台帳を Notion から取得
  2. 画像添付があれば取得し、Claude が「覚えたい事実」を抽出
  3. 画像入力カードは事実を確認（対話: 人間 / --yes: gate照合が代替）
  4. 連想鎖3案を生成 → 事実照合ゲート
  5. ゲートNGなら書き込まない（何も作らないほうがマシ）
  6. OKなら Mermaid 化して書き戻し（状態=一言待ち）＋使用済みアンカー更新

「自分の一言」は絶対に自動記入しない（生成効果）。
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

from . import chain, gate, skeleton
from .notion import NotionClient


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


def _confirm_fact(fact: str) -> str | None:
    """画像入力カードの事実確認（対話モード）。y=採用 / e=修正 / n=スキップ。"""
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


def run(args: argparse.Namespace) -> int:
    _load_dotenv()
    notion = NotionClient()

    print("アンカー台帳を取得中...")
    anchors = notion.fetch_anchors()
    usable = [a for a in anchors if not a.used_by]
    print(f"  採用アンカー {len(anchors)} 件（うち未使用 {len(usable)} 件）")

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
            card.images = notion.fetch_card_images(card.page_id)
            if card.images:
                print(f"  画像添付 {len(card.images)} 枚を取得")

            fact = chain.extract_fact(card)

            # 画像入力の事実確認（CLAUDE.md「順序を死守」）。
            # --yes（無人バッチ）では確認せず、後段の gate 照合が代替になる。
            if card.images and not args.yes:
                confirmed = _confirm_fact(fact)
                if confirmed is None:
                    stats["skipped"] += 1
                    print("  スキップしました。")
                    continue
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
                continue

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
                continue

            notion.write_result(card, fact, proposals, mermaids, result)
            notion.mark_anchors_used(proposals[0].anchors, card, anchors)
            stats["written"] += 1
            note = "（⚠️ 事実は要目視確認の注記つき）" if result.needs_human else ""
            print(f"  ✓ 書き込み完了{note}。状態=一言待ち。")
            print("    →「自分の一言」を Notion で手書きしたら状態を「運用中」にして、Ping-t へ戻ってください。")

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
        description="記憶カードに連想鎖3案＋Mermaidを生成して書き戻す（v1: 画像生成なし）",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="連想鎖が空の記憶カードを処理する")
    run_parser.add_argument("--dry-run", action="store_true", help="書き込みなしで生成結果を表示")
    run_parser.add_argument("--card", metavar="PAGE_ID", help="特定カードだけ処理")
    run_parser.add_argument(
        "--yes", action="store_true",
        help="無人バッチ（確認プロンプトなし。画像入力はgate照合を通った場合のみ書き込み）",
    )
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
