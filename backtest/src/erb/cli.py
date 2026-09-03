"""コマンドライン。

  erb probe             実データと config.yaml の列名を突き合わせる（最初にこれ）
  erb histogram         修正率の分布を出す（閾値を決める前に必ず見る）
  erb run               グリッドを回して results/ に書く
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import data as data_mod
from . import download as download_mod
from . import events as events_mod
from . import fetch as fetch_mod
from . import filters, grid, report
from . import verify as verify_mod
from . import night2 as night2_mod
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

    fetch_p = sub.add_parser("fetch", help="J-Quants から5年分を落とす（中断しても再開できる）")
    fetch_p.add_argument("--from", dest="date_from", default=None,
                         help="開始日 YYYY-MM-DD（既定: 今日から5年前）")
    fetch_p.add_argument("--to", dest="date_to", default=None,
                         help="終了日 YYYY-MM-DD（既定: 昨日）")
    fetch_p.add_argument("--tables", nargs="*", default=None,
                         choices=["daily", "summary", "master", "topix"],
                         help="取る表を限定する（既定: 全部）")
    sub.add_parser("verify", help="落としたデータの検品（グリッドの前にこれ）")
    n2_p = sub.add_parser("night2", help="2晩目システムの事前登録セルを検証する")
    n2_p.add_argument("--from", dest="ev_from", default=None)
    n2_p.add_argument("--to", dest="ev_to", default=None)
    sub.add_parser("histogram", help="修正率の分布を出す")
    run_p = sub.add_parser("run", help="グリッドを回す")
    run_p.add_argument("--holding-days", type=int, nargs="*", default=None,
                       help="config の grid.holding_days を上書きする")
    run_p.add_argument("--from", dest="ev_from", default=None,
                       help="開示日がこの日以降のイベントだけを使う（YYYY-MM-DD）。OOS 判定用")
    run_p.add_argument("--to", dest="ev_to", default=None,
                       help="開示日がこの日以前のイベントだけを使う（YYYY-MM-DD）")

    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    data_dir = Path(args.data_dir)
    results_dir = Path(args.results_dir)

    if args.command == "probe":
        text = fetch_mod.probe(cfg, results_dir / "probe.md")
        print(text)
        return 0

    if args.command == "fetch":
        today = datetime.now(timezone.utc).date()
        start = (date.fromisoformat(args.date_from) if args.date_from
                 else today.replace(year=today.year - 5))
        end = date.fromisoformat(args.date_to) if args.date_to else today - timedelta(days=1)
        if start >= end:
            parser.error(f"期間が不正です: {start} 〜 {end}")
        prog = download_mod.run(cfg, data_dir, start, end,
                                tuple(args.tables) if args.tables else None)
        return 1 if prog.errors else 0

    bundle = _load_bundle(cfg, data_dir)

    if args.command == "verify":
        built = _build_events(cfg, bundle)
        text = verify_mod.verify(cfg, bundle, built.events, built.diagnostics)
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "verify.md").write_text(text, encoding="utf-8")
        print(text)
        print(f"書き出し: {results_dir / 'verify.md'}")
        return 0

    if args.command == "night2":
        built = _build_events(cfg, bundle)
        events = built.events
        if args.ev_from or args.ev_to:
            lo = date.fromisoformat(args.ev_from) if args.ev_from else date.min
            hi = date.fromisoformat(args.ev_to) if args.ev_to else date.max
            d = pd.to_datetime(pd.Series(list(events["disc_date"])), errors="coerce").dt.date
            events = events[(d >= lo) & (d <= hi)].reset_index(drop=True)
            print(f"イベントを {lo} 〜 {hi} に限定: {len(events):,}件")
        events = _attach_loanable(events, bundle.get("master"))
        res = night2_mod.run(events, bundle["prices"], bundle["calendar"], bundle.get("topix"), cfg)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for p in night2_mod.write_report(res, results_dir, stamp):
            print(f"書き出し: {p}")
        main = res.cells[(~res.cells["is_control"]) & res.cells["executable_only"]
                         & (res.cells["slippage_pct"] == 0.4)]
        print(main[["cell", "trades", "excess_topix_pct", "net_edge_pct",
                    "cluster_ci_low_pct", "verdict", "decision"]].to_string(index=False))
        return 0

    if args.command == "histogram":
        built = _build_events(cfg, bundle)
        path = report.write_histogram(built.events, results_dir)
        print(path.read_text(encoding="utf-8"))
        return 0

    if args.command == "run":
        if args.holding_days:
            cfg.raw["grid"]["holding_days"] = args.holding_days
        built = _build_events(cfg, bundle)
        events = built.events
        if args.ev_from or args.ev_to:
            # 期間で切るのは「イベントの開示日」だけ。常習フラグや前回予想は
            # 全期間のデータから作ってあるので、OOS 側でも窓が欠けない。
            lo = date.fromisoformat(args.ev_from) if args.ev_from else date.min
            hi = date.fromisoformat(args.ev_to) if args.ev_to else date.max
            d = pd.to_datetime(pd.Series(list(events["disc_date"])), errors="coerce").dt.date
            events = events[(d >= lo) & (d <= hi)].reset_index(drop=True)
            print(f"イベントを {lo} 〜 {hi} に限定: {len(events):,}件")
        report.write_histogram(events, results_dir)
        result = grid.run_grid(events, bundle["prices"], bundle["calendar"],
                               bundle.get("topix"), cfg)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        written = report.write_results(result, cfg, results_dir, built.diagnostics, stamp,
                                       decomposition=result.decomposition)
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
    bundle_master = master
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
        "prices": PriceIndex.build(daily), "master": bundle_master,
    }


def _attach_loanable(events: pd.DataFrame, master: pd.DataFrame | None) -> pd.DataFrame:
    """貸借銘柄かどうか（空売りできるか）をイベントに付ける。

    銘柄マスタの Mrgn=2（貸借）を貸借とみなす。マスタが無ければ全部 False。
    """
    out = events.copy()
    if master is None or "margin_class" not in master.columns:
        out["loanable"] = False
        return out
    latest = master.sort_values("date").groupby("code", observed=True).tail(1)
    cls = latest["margin_class"].astype(str).str.strip()
    name = latest["margin_class_name"].astype(str) if "margin_class_name" in latest.columns else cls
    loan = set(latest.loc[(cls == "2") | name.str.contains("貸借", na=False), "code"])
    out["loanable"] = out["code"].isin(loan)
    return out


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
