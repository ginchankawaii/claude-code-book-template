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
from .exotic import ExoticConfig
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
                   help="市場の form 読みのノイズ。0=予測エッジ無(ブレンドは市場のlog-lossを"
                        "下回らない)〜大=非効率(エッジ大)。myopia=0 でも EVフィルタは較正"
                        "ノイズで少数ベットを出し回収率は払戻率(~80%)±選択分散に収束する")
    p.add_argument("--ev", type=float, default=1.12, help="EV購入閾値")
    p.add_argument("--kelly", type=float, default=0.25, help="分数ケリー係数")
    p.add_argument("--exotic", action="store_true", help="連系券種(馬連/ワイド/三連複)EVも評価")
    p.add_argument("--db", metavar="PATH",
                   help="実データの JV-Data DB(jrvltsql の keiba.db 等)。指定時は合成でなく実データを使う")
    p.add_argument("--db-kind", choices=["sqlite", "duckdb"], default="sqlite",
                   help="--db のファイル種別(既定 sqlite)")
    p.add_argument("--immutable", action="store_true",
                   help="取得層(realtime)が DB に書き込み中でも読めるよう immutable で開く")
    p.add_argument("--no-enrich", action="store_true",
                   help="血統/データマイニング/オッズ時系列の強化を無効化(効果のA/B比較用)")
    p.add_argument("--no-audit", action="store_true", help="リーク監査をスキップ(高速)")
    p.add_argument("--segments", action="store_true",
                   help="C1エッジ探索: 条件別(人気帯/頭数)の回収率を輪切り表示")
    p.add_argument("--quiet", action="store_true", help="フォールド毎の進捗を出さない")
    args = p.parse_args(argv)

    if args.db:
        from .ingest import IngestBackend, IngestConfig, validate_runners
        reader = IngestBackend(args.db, kind=args.db_kind, immutable=args.immutable,
                               config=IngestConfig(enrich=not args.no_enrich))
        runners, _ = reader.load()
        issues = validate_runners(runners)
        print(f"取り込み: {len(runners)} 出走 / {runners['race_id'].nunique()} レース")
        if issues:
            print("⚠ バリデーション警告:")
            for s in issues:
                print(f"  - {s}")
            print("  → 列名違いの可能性。keiba.ingest の *_FIELDS を DB に合わせて調整してください。")
        else:
            print("バリデーション: クリーン")
    else:
        reader = SyntheticBackend(SyntheticConfig(n_days=args.days, seed=args.seed,
                                                  market_myopia=args.myopia))
    result = run_pipeline(
        reader=reader,
        model_config=ModelConfig(objective=args.objective),
        betting_config=BettingConfig(ev_threshold=args.ev, kelly_fraction=args.kelly),
        wf_config=WalkForwardConfig(),
        exotic_config=ExoticConfig() if args.exotic else None,
        run_leak_audit=not args.no_audit,
        verbose=not args.quiet,
    )
    print(format_report(result))
    if args.segments:
        from .segments import segment_report
        print(segment_report(result.backtest.get("preds"), ev_threshold=args.ev))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
