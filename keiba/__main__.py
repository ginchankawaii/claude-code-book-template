"""CLI: 合成データで分析層パイプラインを実行しダッシュボードを表示する。

使い方:
    python -m keiba                       # 既定設定で実行
    python -m keiba --objective lambdarank
    python -m keiba --days 540 --ev 1.15 --kelly 0.25
    python -m keiba --quiet
"""

from __future__ import annotations

import argparse

from .backtest import WalkForwardConfig
from .betting import BettingConfig
from .model import ModelConfig
from .pipeline import format_report, run_pipeline
from .reader import SyntheticBackend
from .synth import SyntheticConfig


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="keiba", description="競馬予想 分析層パイプライン(合成データ)")
    p.add_argument("--days", type=int, default=600, help="合成データの日数")
    p.add_argument("--seed", type=int, default=7, help="乱数シード")
    p.add_argument("--objective", choices=["binary", "lambdarank"], default="binary")
    p.add_argument("--myopia", type=float, default=0.7,
                   help="市場の form 読みのノイズ。0=効率的(エッジ無)〜大=非効率(エッジ大)")
    p.add_argument("--ev", type=float, default=1.12, help="EV購入閾値")
    p.add_argument("--kelly", type=float, default=0.25, help="分数ケリー係数")
    p.add_argument("--no-audit", action="store_true", help="リーク監査をスキップ(高速)")
    p.add_argument("--quiet", action="store_true", help="フォールド毎の進捗を出さない")
    args = p.parse_args(argv)

    reader = SyntheticBackend(SyntheticConfig(n_days=args.days, seed=args.seed,
                                              market_myopia=args.myopia))
    result = run_pipeline(
        reader=reader,
        model_config=ModelConfig(objective=args.objective),
        betting_config=BettingConfig(ev_threshold=args.ev, kelly_fraction=args.kelly),
        wf_config=WalkForwardConfig(),
        run_leak_audit=not args.no_audit,
        verbose=not args.quiet,
    )
    print(format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
