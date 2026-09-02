"""グリッド実行。

粗エッジ自体は N とスリッページに依存しないので、
トレード表は N ごとに1回だけ作り、コストは後から差し引く。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import pandas as pd

from . import filters, metrics
from .calendar import TradingCalendar
from .config import Config
from .simulate import PriceIndex, apply_costs, simulate_portfolio, simulate_trades


@dataclass
class GridResult:
    cells: pd.DataFrame
    skip_summary: dict
    thresholds_used: list[float | None] = field(default_factory=list)
    decomposition: pd.DataFrame | None = None


def run_grid(events: pd.DataFrame, prices: PriceIndex, calendar: TradingCalendar,
             topix: pd.DataFrame | None, cfg: Config) -> GridResult:
    grid = cfg["grid"]
    costs = cfg["costs"]
    port = cfg["portfolio"]
    filt = cfg["filters"]
    stat = cfg["statistics"]

    position_size = int(port["position_size_jpy"])

    # 購読料を按分するための検証期間（年）
    dates = [d for d in events["entry_date"] if d is not None and not pd.isna(d)]
    years = max((max(dates) - min(dates)).days / 365.25, 1e-9) if dates else 0.0

    # N ごとのトレード表（コスト控除前）
    trades_by_n: dict[int, pd.DataFrame] = {}
    skip_summary: dict[int, dict] = {}
    for n in grid["holding_days"]:
        t = simulate_trades(
            events, prices, calendar, int(n),
            position_size_jpy=position_size,
            no_open_policy=filt["no_open_policy"],
            topix=topix,
        )
        trades_by_n[int(n)] = t
        skip_summary[int(n)] = filters.skip_counts(t)

    # 前半・後半の境目。検証期間のちょうど真ん中で切る。
    split_at = min(dates) + (max(dates) - min(dates)) / 2 if dates else None

    # 修正率の閾値。config が null なら実データの分位点から決める。
    thresholds = grid.get("revision_thresholds")
    if not thresholds:
        base = filters.executable(trades_by_n[min(trades_by_n)])
        thresholds = filters.revision_quantile_thresholds(base)
    # 重複した閾値はセルを増やすだけで情報を増やさないので落とす
    deduped: list[float] = []
    for t in thresholds:
        if all(abs(float(t) - e) > 1e-9 for e in deduped):
            deduped.append(float(t))
    cells_thresholds: list[float | None] = [None] + deduped + [-0.30]

    rows = []
    combos = itertools.product(
        sorted(trades_by_n),
        grid["mktcap_caps_jpy"],
        cells_thresholds,
        grid["habitual_excluded"],
        grid["turnover_filter"],
        grid["exclusion_list_applied"],
        ("all", "after_close", "intraday"),
    )

    for n, cap, thr, hab, turn, excl, timing in combos:
        sub = filters.executable(trades_by_n[n])
        sub = filters.apply_exclusion_list(sub, excl)
        sub = filters.apply_mktcap(sub, cap)
        sub = filters.apply_revision(sub, thr)
        sub = filters.apply_habitual(sub, hab)
        sub = filters.apply_turnover(sub, turn, position_size,
                                     float(filt["max_position_share_of_turnover"]))
        sub = filters.apply_timing(sub, timing)

        for slip in costs["slippage_round_trip_pct"]:
            priced = apply_costs(
                sub, float(slip),
                float(costs["margin_interest_annual_pct"]),
                int(costs["commission_jpy_per_trade"]),
                position_size,
                day_trade_interest_annual_pct=float(
                    costs.get("day_trade_interest_annual_pct", 0.0)),
            )
            summary = metrics.summarize(
                priced,
                bootstrap_iterations=int(stat["bootstrap_iterations"]),
                cluster_by=str(stat["cluster_by"]),
                target_t=float(stat["target_t_stat"]),
            )

            # 事前登録した採用条件のひとつ:
            # 前半・後半の両方でプラスでなければ採用しない。
            # 相場つきが変わっても残る効果かどうかを見る。
            first, second = metrics.split_halves(priced, split_at)
            for tag, part in (("h1", first), ("h2", second)):
                if len(part) == 0:
                    summary[f"{tag}_trades"] = 0
                    summary[f"{tag}_net_edge_pct"] = float("nan")
                    summary[f"{tag}_excess_pct"] = float("nan")
                    continue
                summary[f"{tag}_trades"] = len(part)
                summary[f"{tag}_net_edge_pct"] = float(
                    part["net_excess_return"].mean() * 100)
                summary[f"{tag}_excess_pct"] = float(
                    part["excess_return"].mean() * 100)
            summary["both_halves_positive"] = bool(
                (summary.get("h1_net_edge_pct", float("nan")) > 0)
                and (summary.get("h2_net_edge_pct", float("nan")) > 0)
            )
            row = {
                "holding_days": n,
                "mktcap_cap_jpy": cap,
                "revision_threshold": thr,
                "habitual_excluded": hab,
                "turnover_filter": turn,
                "exclusion_list_applied": excl,
                "timing": timing,
                "slippage_pct": float(slip),
                **{k: v for k, v in summary.items() if k != "by_year_gross_pct"},
            }
            row["decision"] = metrics.classify_net_edge(
                summary.get("net_edge_pct", float("nan")),
                float(cfg["judgement"]["net_edge_abort_below_pct"]),
                float(cfg["judgement"]["net_edge_paper_trade_below_pct"]),
            )
            row["is_control"] = thr is None or (thr is not None and thr < 0)

            if timing == "all" and summary.get("trades", 0) > 0:
                for equity in port["equity_cases_jpy"]:
                    pf = simulate_portfolio(
                        priced,
                        position_size_jpy=position_size,
                        max_concurrent=int(port["max_concurrent"]),
                        equity_jpy=int(equity),
                        maintenance_margin_ratio=float(port["maintenance_margin_ratio"]),
                        prices=prices,
                        calendar=calendar,
                    )
                    tag = f"eq{int(equity) // 10000}"
                    # 購読料は年間の固定費。検証期間の年数ぶんを引く。
                    subscription = (
                        float(costs.get("data_subscription_jpy_per_month", 0)) * 12 * years
                    )
                    net_of_fees = pf["realized_pnl_jpy"] - subscription
                    row["subscription_jpy"] = round(subscription)
                    row[f"{tag}_pnl_jpy"] = round(pf["realized_pnl_jpy"])
                    row[f"{tag}_pnl_after_fees_jpy"] = round(net_of_fees)
                    row[f"{tag}_return_pct"] = round(pf["realized_pnl_jpy"] / equity * 100, 2)
                    row[f"{tag}_return_after_fees_pct"] = round(net_of_fees / equity * 100, 2)
                    row[f"{tag}_max_dd_pct"] = round(pf["max_drawdown_pct"], 2)
                    row[f"{tag}_margin_call_days"] = pf["margin_call_days"]
                    row[f"{tag}_bankrupt_on"] = (
                        pf["bankrupt_on"].isoformat() if pf["bankrupt_on"] else "")
                    row["taken"] = pf["taken"]
                    row["skipped_no_slot"] = pf["skipped_no_slot"]

            rows.append(row)

    decomposition = day0_decomposition(trades_by_n, cells_thresholds, position_size, filt)
    return GridResult(cells=pd.DataFrame(rows), skip_summary=skip_summary,
                      thresholds_used=cells_thresholds, decomposition=decomposition)


def day0_decomposition(trades_by_n: dict, thresholds: list, position_size: int,
                       filt: dict) -> pd.DataFrame:
    """初日の「始値→引け」「引け→翌始値」を、閾値 x タイミング別に集計する。

    どの N のトレード表でも初日の分解は同じなので、最小の N の表を使う。
    フィルタは主条件に合わせる（常習除外・売買代金あり・除外あり・時価総額なし）。
    """
    n0 = min(trades_by_n)
    base = filters.executable(trades_by_n[n0])
    base = filters.apply_exclusion_list(base, True)
    base = filters.apply_habitual(base, True)
    base = filters.apply_turnover(base, True, position_size,
                                  float(filt["max_position_share_of_turnover"]))
    rows = []
    for thr in thresholds:
        sub = filters.apply_revision(base, thr)
        for timing in ("all", "after_close", "intraday"):
            t = filters.apply_timing(sub, timing)
            if t.empty:
                continue
            oc = t["d0_open_to_close"]
            cn = t["d0_close_to_next_open"]
            oc_x = oc - t["d0_topix_open_to_close"]
            cn_x = cn - t["d0_topix_close_to_next_open"]
            rows.append({
                "revision_threshold": thr,
                "timing": timing,
                "trades": int(oc.notna().sum()),
                "open_to_close_pct": float(oc.mean() * 100),
                "open_to_close_excess_pct": float(oc_x.mean() * 100),
                "close_to_next_open_pct": float(cn.mean() * 100),
                "close_to_next_open_excess_pct": float(cn_x.mean() * 100),
                "open_to_close_win_rate": float((oc > 0).mean()),
                "open_to_close_stdev_pct": float(oc.std(ddof=1) * 100) if oc.notna().sum() > 1 else float("nan"),
            })
    return pd.DataFrame(rows)


def primary_cell(cells: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """事前登録した主条件のセル。判定はここで行う。"""
    p = cfg["judgement"]["primary_cell"]
    m = (
        (cells["holding_days"] == p["holding_days"])
        & (cells["habitual_excluded"] == p["habitual_excluded"])
        & (cells["turnover_filter"] == p["turnover_filter"])
        & (cells["exclusion_list_applied"] == p["exclusion_list_applied"])
        & (cells["slippage_pct"] == p["slippage_round_trip_pct"])
        & (cells["timing"] == "all")
    )
    cap = p["mktcap_cap_jpy"]
    m &= cells["mktcap_cap_jpy"].isna() if cap is None else (cells["mktcap_cap_jpy"] == cap)
    thr = p.get("revision_threshold")
    if thr is not None:
        m &= cells["revision_threshold"] == thr
    else:
        # 閾値未確定のときは、対照群を除いた最小の閾値を主条件とみなす
        candidates = cells.loc[m & (~cells["is_control"]), "revision_threshold"]
        if not candidates.empty:
            m &= cells["revision_threshold"] == candidates.min()
    return cells[m]


def stability_check(cells: pd.DataFrame) -> dict:
    """「全条件で安定してプラス」の機械的な判定。"""
    real = cells[~cells["is_control"] & (cells["timing"] == "all")]
    if real.empty:
        return {"all_positive": False, "reason": "対象セルなし"}
    positive = (real["net_edge_pct"] > 0).all()
    judged = real[real["verdict"] == "判定可"]
    out = {
        "all_positive": bool(positive),
        "cells": int(len(real)),
        "judgeable_cells": int(len(judged)),
        "negative_cells": int((real["net_edge_pct"] <= 0).sum()),
        "min_net_edge_pct": float(real["net_edge_pct"].min()),
    }
    if "both_halves_positive" in real.columns:
        out["both_halves_positive_cells"] = int(real["both_halves_positive"].sum())
    return out
