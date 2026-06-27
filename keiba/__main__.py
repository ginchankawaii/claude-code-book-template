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
    p.add_argument("--since", metavar="YYYYMMDD",
                   help="この日付以降のレースだけ解析する(高速化。例 20240101)。"
                        "学習履歴も同期間に絞られる点に注意")
    p.add_argument("--no-audit", action="store_true", help="リーク監査をスキップ(高速)")
    p.add_argument("--segments", action="store_true",
                   help="C1エッジ探索: 条件別(人気帯/頭数/オッズの動き)の回収率を輪切り表示")
    p.add_argument("--validate-oos", action="store_true",
                   help="C6: C1候補を前半で発見→後半で残るか out-of-sample 検証")
    p.add_argument("--real-exotic", action="store_true",
                   help="C3: 連系を合成オッズでなく実オッズ(O2/O3/O5)で判定・決済する(--db必須)")
    p.add_argument("--real-exotic-years", type=int, default=2,
                   help="C3: 実オッズで評価する直近年数(既定2。多いほどサンプル増だがメモリ増。"
                        "OOM/遅い時は1に下げる)")
    p.add_argument("--quiet", action="store_true", help="フォールド毎の進捗を出さない")
    args = p.parse_args(argv)

    exotic_odds = None
    if args.db:
        from .ingest import IngestBackend, IngestConfig, validate_runners
        import datetime as _dt
        since_year = since_ord = 0
        if args.since:
            s = "".join(ch for ch in str(args.since) if ch.isdigit())
            since_year = int(s[:4])
            since_ord = _dt.date(int(s[:4]), int(s[4:6]), int(s[6:8])).toordinal()
            print(f"解析期間: {s[:4]}/{s[4:6]}/{s[6:8]} 以降に限定(高速化)")
        reader = IngestBackend(args.db, kind=args.db_kind, immutable=args.immutable,
                               config=IngestConfig(enrich=not args.no_enrich,
                                                   since_year=since_year,
                                                   since_ordinal=since_ord))
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
        if args.real_exotic and args.exotic:
            # C3: 直近N年の連系オッズ(馬連O2/ワイドO3/三連複O5のみ)を読み、実オッズで決済する
            from .exotic_odds import load_exotic_odds_for_days
            import datetime as _dt
            max_ord = int(runners["race_date"].max())
            maxyear = _dt.date.fromordinal(max_ord).year
            ny = max(1, args.real_exotic_years)
            cutoff = _dt.date(maxyear - ny + 1, 1, 1).toordinal()
            evdays = [o for o in runners["race_date"].unique() if o >= cutoff]
            print(f"実連系オッズ読込中… 直近{ny}年(>= {maxyear - ny + 1}年) {len(evdays)}日分 "
                  f"/ 馬連・ワイド・三連複のみ(年単位一括クエリ)")
            exotic_odds = load_exotic_odds_for_days(args.db, evdays, args.db_kind,
                                                    args.immutable)
            nrace = len(exotic_odds)
            ncombo = sum(len(t) for r in exotic_odds.values() for t in r.values())
            print(f"  → 実オッズのある race: {nrace}  保持組数: {ncombo:,}")
            if not exotic_odds:
                print("  ⚠ 実連系オッズ(NL_O2/O3/O5)が見つかりません。合成オッズで継続します。")
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
        exotic_odds=exotic_odds,
    )
    print(format_report(result))
    if args.segments:
        from .segments import segment_report
        print(segment_report(result.backtest.get("preds"), ev_threshold=args.ev))
    if args.validate_oos:
        from .segments import validate_oos
        print(validate_oos(result.backtest.get("preds"), ev_threshold=args.ev))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
