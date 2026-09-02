"""コマンドライン。

  erb probe             実データと config.yaml の列名を突き合わせる（最初にこれ）
  erb histogram         修正率の分布を出す（閾値を決める前に必ず見る）
  erb run               グリッドを回して results/ に書く
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import data as data_mod
from . import events as events_mod
from . import fetch as fetch_mod
from . import filters, grid, report
from .calendar import CloseTimeSchedule, TradingCalendar
from .config import Config
from .simulate import PriceIndex, apply_costs, simulate_trades

DEFAULT_DATA = Path("data")
DEFAULT_RESULTS = Path("results")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="erb", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="実データと設定の列名を突き合わせる")
    sub.add_parser("histogram", help="修正率の分布を出す")
    run_p = sub.add_parser("run", help="グリッドを回す")
    run_p.add_argument("--holding-days", type=int, nargs="*", default=None,
                       help="config の grid.holding_days を上書きする")

    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    data_dir = Path(args.data_dir)
    results_dir = Path(args.results_dir)

    if args.command == "probe":
        text = fetch_mod.probe(cfg, results_dir / "probe.md")
        print(text)
        return 0

    bundle = _load_bundle(cfg, data_dir)

    if args.command == "histogram":
        built = _build_events(cfg, bundle)
        path = report.write_histogram(built.events, results_dir)
        print(path.read_text(encoding="utf-8"))
        return 0

    if args.command == "run":
        if args.holding_days:
            cfg.raw["grid"]["holding_days"] = args.holding_days
        built = _build_events(cfg, bundle)
        report.write_histogram(built.events, results_dir)
        result = grid.run_grid(built.events, bundle["prices"], bundle["calendar"],
                               bundle.get("topix"), cfg)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        written = report.write_results(result, cfg, results_dir, built.diagnostics, stamp)
        for p in written:
            print(f"書き出し: {p}")
        primary = grid.primary_cell(result.cells, cfg)
        if not primary.empty:
            print("\n--- 主条件 ---")
            print(primary[["holding_days", "revision_threshold", "trades",
                           "gross_pct", "excess_topix_pct", "net_edge_pct",
                           "verdict", "decision"]].to_string(index=False))
        return 0

    parser.error(f"未知のコマンド: {args.command}")
    return 2


def _load_bundle(cfg: Config, data_dir: Path) -> dict:
    """必要なテーブルを読み込む。"""
    paths = {
        "summary": _find(data_dir, "summary"),
        "daily": _find(data_dir, "daily"),
        "calendar": _find(data_dir, "calendar", required=False),
    }
    optional = {"master": _find(data_dir, "master", required=False),
                "topix": _find(data_dir, "topix", required=False)}

    summary = data_mod.load_table(cfg, "summary", paths["summary"])
    daily = data_mod.load_table(cfg, "daily", paths["daily"])
    cal_df = (data_mod.load_table(cfg, "calendar", paths["calendar"])
              if paths["calendar"] else None)

    daily = data_mod.daily_with_turnover_average(
        daily, int(cfg["filters"]["turnover_lookback_days"]))

    master = (data_mod.load_table(cfg, "master", optional["master"])
              if optional["master"] else None)
    if master is not None and cfg["filters"].get("require_margin_eligible"):
        daily = _restrict_to_margin_eligible(daily, master)

    topix = (data_mod.load_table(cfg, "topix", optional["topix"])
             if optional["topix"] else None)

    if cal_df is not None:
        calendar = TradingCalendar.from_frame(cal_df)
    else:
        # 取引カレンダーが無い契約でも動くよう、日足から営業日を導出する
        print("警告: data/calendar が見つかりません。日足から営業日を導出します。")
        calendar = TradingCalendar.from_daily_prices(daily)
    close_schedule = CloseTimeSchedule(cfg["market"]["close_time_changes"])

    return {
        "summary": summary, "daily": daily, "topix": topix,
        "calendar": calendar, "close_schedule": close_schedule,
        "prices": PriceIndex.build(daily),
    }


def _build_events(cfg: Config, bundle: dict) -> events_mod.EventBuildResult:
    return events_mod.build_events(
        bundle["summary"], bundle["daily"], bundle["calendar"], bundle["close_schedule"],
        int(cfg["habitual"]["lookback_days"]), int(cfg["habitual"]["min_revisions"]),
        exclude_reit=bool(cfg["filters"].get("exclude_reit", True)),
    )


def _restrict_to_margin_eligible(daily: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """制度信用で買える銘柄に限定する。

    銘柄マスタの信用区分が「非対象」の銘柄は信用買いできないため、
    そもそもこの戦略の対象外。
    """
    if "margin_class" not in master.columns:
        return daily
    latest = master.sort_values("date").groupby("code", observed=True).tail(1)
    eligible = set(
        latest.loc[~latest["margin_class"].astype(str).str.strip().isin(["", "0", "nan", "None"]), "code"]
    )
    if not eligible:
        return daily
    return daily[daily["code"].isin(eligible)]


def _find(data_dir: Path, stem: str, required: bool = True) -> Path | None:
    for ext in (".parquet", ".csv", ".csv.gz", ".jsonl"):
        p = data_dir / f"{stem}{ext}"
        if p.exists():
            return p
    matches = sorted(data_dir.glob(f"{stem}*"))
    if matches:
        return matches[0]
    if required:
        raise FileNotFoundError(
            f"{data_dir}/{stem}.(parquet|csv) が見つかりません。"
            "README の手順でローカルにデータを置いてください。"
        )
    return None


if __name__ == "__main__":
    sys.exit(main())
