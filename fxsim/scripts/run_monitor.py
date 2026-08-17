"""PDCA health check — is the live FX run tracking the backtest?

Reads the live run from SQLite (+ the live H1 bar feed if the EA bridge is up),
runs the validated strategy on the same recent bars to get the CURRENT call,
and prints a health report flagging drawdown breach / overtrading / execution
drift / insufficient data.

  py -3.12 -m scripts.run_monitor              # latest FX run
  py -3.12 -m scripts.run_monitor --run-id 7   # a specific run
  py -3.12 -m scripts.run_monitor --kind stocks

Run it whenever you review the system (the heart of the PDCA loop).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from app import bridge, db, monitor
from app.config import Settings
from app.indicators import candles_to_df, enrich
from app.providers.csv import load_csv_file
from app.strategies.trend import TrendRegimeStrategy


def _actions(run_id: int) -> list[str]:
    out = []
    for s in db.load_signals(run_id):
        if s.get("source") != "combined":
            continue
        comp = {}
        try:
            comp = json.loads(s["components"]) if s.get("components") else {}
        except (json.JSONDecodeError, TypeError):
            comp = {}
        out.append(str(comp.get("action", "FLAT")))
    return out


def _current_strategy_signal(cfg: Settings, instrument: str, history_csv: str) -> str | None:
    """What the trend filter says RIGHT NOW, from the live bar feed (or CSV)."""
    need = cfg.trend_sma + 5
    candles = bridge.read_bars(instrument, cfg.granularity)
    if len(candles) < need:
        try:
            candles = load_csv_file(__import__("pathlib").Path(history_csv), instrument, cfg.granularity)
        except Exception:
            return None
    if len(candles) < need:
        return None
    df = enrich(candles_to_df(candles))
    sig = TrendRegimeStrategy(sma=cfg.trend_sma).generate(instrument, df)
    return "LONG" if sig.direction > 0 else "FLAT"


def _live_position() -> str | None:
    try:
        s = bridge.read_status()
    except Exception:
        s = None
    if not s:
        return None
    lots = s.get("position_lots", 0.0) or 0.0
    return "LONG" if lots > 1e-9 else "FLAT"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--kind", default="fx", choices=["fx", "stocks"])
    ap.add_argument("--instrument", default="USD_JPY")
    ap.add_argument("--granularity", default="H1")
    ap.add_argument("--sma", type=int, default=2400)
    ap.add_argument("--history", default="data/USD_JPY_H1.csv")
    args = ap.parse_args()

    db.init_db()
    rid = args.run_id or db.latest_run_id(args.kind)
    if not rid:
        print(f"[monitor] {args.kind} のrunがまだありません。"); return
    run = db.get_run(rid)
    equity = db.load_equity(rid)
    if len(equity) < 2:
        print(f"[monitor] run #{rid}: エクイティ記録が少なすぎます（判断にはもう少し稼働が必要）。"); return

    eq_vals = [e["equity"] for e in equity]
    span = monitor.span_days_between(equity[0]["time"], equity[-1]["time"])
    staleness = monitor.span_days_between(equity[-1]["time"], datetime.now(timezone.utc))
    actions = _actions(rid)

    trend_basis = live_pos = None
    if args.kind == "fx":
        cfg = Settings(granularity=args.granularity, trend_sma=args.sma)
        trend_basis = _current_strategy_signal(cfg, args.instrument, args.history)
        live_pos = _live_position()

    rep = monitor.build_report(
        initial_balance=run["initial_balance"], equity_values=eq_vals,
        span_days=span, actions=actions, live_position=live_pos,
        trend_basis=trend_basis, staleness_days=staleness)

    bal0 = rep["initial_balance"]; eq = rep["current_equity"]; s = rep["stats"]
    print("=" * 60)
    print(f" PDCA健康診断  run #{rid} · {run['instrument']} {run['granularity']}")
    print("=" * 60)
    print(f" 稼働 {span:.0f}日 ｜ 初期 ¥{bal0:,.0f} → 現在 ¥{eq:,.0f} ({s['return_pct']:+.1f}%)")
    print(f" 現在DD {s['cur_dd_pct']:.1f}% ｜ 期間中最大DD {s['max_dd_pct']:.1f}%")
    if rep["trades_per_year"] is not None:
        print(f" 建玉変化 {rep['n_position_changes']}回（年率 {rep['trades_per_year']:.0f}回）")
    print("-" * 60)
    print(" 基準（バックテスト H1/SMA2400/5x）: "
          f"CAGR+{monitor.EXP_CAGR_PCT:.0f}% / 最大DD {monitor.EXP_MAXDD_PCT:.0f}% / "
          f"取引 約{monitor.EXP_TRADES_PER_YEAR:.0f}回/年")
    print("-" * 60)
    for c in rep["checks"]:
        print(f"  {c['flag']} {c['name']:<6} {c['msg']}")
    print("-" * 60)
    print(f" 総合判定： {rep['verdict']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
