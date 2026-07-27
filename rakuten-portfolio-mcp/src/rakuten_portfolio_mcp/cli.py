"""MCPを立てずに動作確認するためのCLI。

    python -m rakuten_portfolio_mcp.cli brief
    python -m rakuten_portfolio_mcp.cli inspect assetbalance.csv

CSVがちゃんと読めているかは、Claudeに繋ぐ前にここで確認するのが早い。
"""

from __future__ import annotations

import argparse
import json
import sys

from . import service, snapshots
from .analysis import brief, concentration, margin, pnl, risk
from .config import Config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rakuten-portfolio", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sources", help="読み込み対象ファイルの一覧")
    sub.add_parser("portfolio", help="正規化済みポートフォリオ")
    sub.add_parser("margin", help="信用取引の状況")
    sub.add_parser("concentration", help="集中度")
    sub.add_parser("risk", help="ストレステスト")
    sub.add_parser("pnl", help="損益サマリ")
    sub.add_parser("brief", help="全部入り")

    p_inspect = sub.add_parser("inspect", help="CSVの解釈結果を確認")
    p_inspect.add_argument("filename")

    p_snap = sub.add_parser("snapshot", help="スナップショット保存")
    p_snap.add_argument("--label", default="")

    parser.add_argument("--refresh", action="store_true", help="株価を取り直す")
    args = parser.parse_args(argv)

    cfg = Config.from_env()

    if args.command == "sources":
        result = service.list_sources(cfg)
    elif args.command == "inspect":
        result = service.inspect_file(cfg, args.filename)
    else:
        pf = service.load_portfolio(cfg, refresh=args.refresh)
        if args.command == "portfolio":
            result = pf.to_dict()
        elif args.command == "margin":
            result = margin.summarize(pf, cfg)
        elif args.command == "concentration":
            result = concentration.summarize(pf)
        elif args.command == "risk":
            result = risk.summarize(pf, cfg)
        elif args.command == "pnl":
            result = pnl.summarize(pf, cfg)
        elif args.command == "snapshot":
            result = {"saved": str(snapshots.save(pf, cfg, args.label))}
        else:
            result = brief.build(pf, cfg)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
