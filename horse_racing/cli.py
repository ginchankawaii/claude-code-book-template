"""コマンドラインインターフェース。

使い方:
    python -m horse_racing                # サンプルレースを予想
    python -m horse_racing race.csv       # CSV を読み込んで予想
    python -m horse_racing --write-sample data/sample_race.csv
"""

from __future__ import annotations

import argparse
import sys

from .data import load_horses_csv, sample_race, write_sample_csv
from .model import Prediction, predict_race


def _format_table(preds: list[Prediction]) -> str:
    header = f"{'着':>2} {'馬名':<18} {'勝率':>7} {'スコア':>7}"
    lines = [header, "-" * len(header)]
    for p in preds:
        lines.append(
            f"{p.rank:>2} {p.horse.name:<18} {p.win_probability * 100:>6.1f}% {p.score:>7.3f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="horse_racing", description="競馬の着順・勝率を予想する"
    )
    parser.add_argument(
        "csv", nargs="?", help="出走馬データの CSV (省略時はサンプルレース)"
    )
    parser.add_argument(
        "-t",
        "--temperature",
        type=float,
        default=0.35,
        help="勝率分布の温度。小さいほど本命寄り (既定 0.35)",
    )
    parser.add_argument(
        "--write-sample",
        metavar="PATH",
        help="サンプルレースを CSV に書き出して終了する",
    )
    args = parser.parse_args(argv)

    if args.write_sample:
        path = write_sample_csv(args.write_sample)
        print(f"サンプル CSV を書き出しました: {path}")
        return 0

    try:
        horses = load_horses_csv(args.csv) if args.csv else sample_race()
        preds = predict_race(horses, temperature=args.temperature)
    except (ValueError, FileNotFoundError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    print(_format_table(preds))
    best = preds[0]
    print(f"\n◎ 本命: {best.horse.name} (勝率 {best.win_probability * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
