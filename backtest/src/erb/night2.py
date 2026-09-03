"""2晩目システムの検証（事前登録セルのみ）。

フェーズ1の分解で見えた構造:
  引け後に開示 → 翌日(E+1)の日中はニュースと逆に動き → その夜(E+1引け→E+2始値)にニュース方向へ動く

これを「E+1 の引けでニュース方向に建て、E+2 の寄付で返す」1泊の売買として固定し、
グリッド探索はしない。セルは以下で固定。

  ロング   引け後 / 上方修正 ≥ +18% と ≥ +36% / 常習除外 / 売買代金F / 除外あり
  ショート 引け後 / 下方修正 ≤ −30% / 同上 / 貸借銘柄のみ
  対照     ロング側に下方修正、ショート側に上方修正（符号が逆になるはず）、閾値なし

執行できない日（ストップ高で買えない・ストップ安で売れない）を除いた版を主とし、
除かない版を併記する。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import filters, metrics
from .calendar import TradingCalendar
from .config import Config
from .simulate import (ENTRY_T0_CLOSE, SIDE_LONG, SIDE_SHORT, PriceIndex,
                       apply_costs, simulate_portfolio, simulate_trades)


@dataclass
class Night2Result:
    cells: pd.DataFrame
    pair_portfolio: pd.DataFrame
    legs: dict[str, pd.DataFrame]
    skip_summary: dict


def _executable(t: pd.DataFrame, side: str, require_loanable: bool) -> pd.DataFrame:
    """執行できた日だけに絞る。"""
    # object 型のまま ~ を掛けると -1/-2 になって壊れるので、必ず bool に落とす
    if side == SIDE_LONG:
        return t[~t["entry_limit_up"].fillna(False).astype(bool)]
    out = t[~t["entry_limit_down"].fillna(False).astype(bool)]
    if require_loanable and "loanable" in out.columns:
        out = out[out["loanable"].fillna(False).astype(bool)]
    return out


def run(events: pd.DataFrame, prices: PriceIndex, calendar: TradingCalendar,
        topix: pd.DataFrame | None, cfg: Config) -> Night2Result:
    n2 = cfg["night2"]
    costs = cfg["costs"]
    filt = cfg["filters"]
    stat = cfg["statistics"]
    position = int(n2["position_size_jpy"])
    n = int(n2["holding_days"])

    # 引け後開示に限定（事前登録）。場中開示は別の構造なので混ぜない
    ev = events[events["after_close"].fillna(False)].copy()

    legs: dict[str, pd.DataFrame] = {}
    skip: dict = {}
    for side in (SIDE_LONG, SIDE_SHORT):
        t = simulate_trades(ev, prices, calendar, n, position_size_jpy=position,
                            topix=topix, entry_mode=ENTRY_T0_CLOSE, side=side)
        legs[side] = t
        skip[side] = filters.skip_counts(t)

    cells = []
    specs = [
        # (label, side, threshold, is_control)
        ("long_up18", SIDE_LONG, 0.18, False),
        ("long_up36", SIDE_LONG, 0.36, False),
        ("short_dn30", SIDE_SHORT, -0.30, False),
        ("ctrl_long_all", SIDE_LONG, None, True),
        ("ctrl_long_dn30", SIDE_LONG, -0.30, True),     # 符号が逆になるはず
        ("ctrl_short_up18", SIDE_SHORT, 0.18, True),    # 符号が逆になるはず
    ]
    dates = [d for d in ev["entry_date"] if d is not None and not pd.isna(d)]
    split_at = min(dates) + (max(dates) - min(dates)) / 2 if dates else None

    for label, side, thr, is_control in specs:
        base = filters.executable(legs[side])
        base = filters.apply_exclusion_list(base, True)
        base = filters.apply_habitual(base, True)
        base = filters.apply_turnover(base, True, position,
                                      float(filt["max_position_share_of_turnover"]))
        base = filters.apply_revision(base, thr)
        for exec_only in (True, False):
            sub = _executable(base, side, bool(n2.get("require_loanable_for_short", True))) if exec_only else base
            for slip in costs["slippage_round_trip_pct"]:
                priced = apply_costs(
                    sub, float(slip), float(costs["margin_interest_annual_pct"]),
                    int(costs["commission_jpy_per_trade"]), position,
                    short_borrow_annual_pct=float(n2.get("short_borrow_annual_pct", 1.15)),
                )
                summ = metrics.summarize(
                    priced, bootstrap_iterations=int(stat["bootstrap_iterations"]),
                    cluster_by=str(stat["cluster_by"]), target_t=float(stat["target_t_stat"]),
                )
                row = {"cell": label, "side": side, "threshold": thr, "is_control": is_control,
                       "executable_only": exec_only, "slippage_pct": float(slip),
                       **{k: v for k, v in summ.items() if k != "by_year_gross_pct"}}
                if split_at is not None and len(priced):
                    a, b = metrics.split_halves(priced, split_at)
                    row["h1_trades"], row["h2_trades"] = len(a), len(b)
                    row["h1_excess_pct"] = float(a["excess_return"].mean() * 100) if len(a) else float("nan")
                    row["h2_excess_pct"] = float(b["excess_return"].mean() * 100) if len(b) else float("nan")
                    row["h1_net_edge_pct"] = float(a["net_excess_return"].mean() * 100) if len(a) else float("nan")
                    row["h2_net_edge_pct"] = float(b["net_excess_return"].mean() * 100) if len(b) else float("nan")
                    row["both_halves_positive"] = bool(row["h1_net_edge_pct"] > 0 and row["h2_net_edge_pct"] > 0)
                row["by_year"] = summ.get("by_year_gross_pct", {})
                row["decision"] = metrics.classify_net_edge(
                    summ.get("net_edge_pct", float("nan")),
                    float(cfg["judgement"]["net_edge_abort_below_pct"]),
                    float(cfg["judgement"]["net_edge_paper_trade_below_pct"]))
                cells.append(row)

    # 両建てポートフォリオ（主セル: long_up18 + short_dn30、執行できた日のみ）
    pair_rows = []
    for slip in costs["slippage_round_trip_pct"]:
        parts = []
        for label, side, thr in (("long_up18", SIDE_LONG, 0.18), ("short_dn30", SIDE_SHORT, -0.30)):
            b = filters.executable(legs[side])
            b = filters.apply_exclusion_list(b, True)
            b = filters.apply_habitual(b, True)
            b = filters.apply_turnover(b, True, position, float(filt["max_position_share_of_turnover"]))
            b = filters.apply_revision(b, thr)
            b = _executable(b, side, bool(n2.get("require_loanable_for_short", True)))
            parts.append(b)
        both = pd.concat(parts, ignore_index=True)
        priced = apply_costs(both, float(slip), float(costs["margin_interest_annual_pct"]),
                             int(costs["commission_jpy_per_trade"]), position,
                             short_borrow_annual_pct=float(n2.get("short_borrow_annual_pct", 1.15)))
        for equity in n2["bucket_cases_jpy"]:
            pf = simulate_portfolio(priced, position_size_jpy=position,
                                    max_concurrent=int(n2["max_concurrent"]),
                                    equity_jpy=int(equity),
                                    maintenance_margin_ratio=float(cfg["portfolio"]["maintenance_margin_ratio"]),
                                    prices=prices, calendar=calendar,
                                    slot_rule=str(n2.get("slot_rule", "turnover_desc")))
            pair_rows.append({
                "slippage_pct": float(slip), "bucket_jpy": int(equity),
                "signals": len(priced), "taken": pf["taken"], "skipped_no_slot": pf["skipped_no_slot"],
                "pnl_jpy": round(pf["realized_pnl_jpy"]),
                "return_pct": round(pf["realized_pnl_jpy"] / equity * 100, 2),
                "max_dd_pct": round(pf["max_drawdown_pct"], 2),
                "margin_call_days": pf["margin_call_days"],
                "bankrupt_on": pf["bankrupt_on"].isoformat() if pf["bankrupt_on"] else "",
                "taken_mean_net_pct": round(pf["taken_mean_net_pct"], 4),
                "all_mean_net_pct": round(pf["all_mean_net_pct"], 4),
            })

    return Night2Result(cells=pd.DataFrame(cells), pair_portfolio=pd.DataFrame(pair_rows),
                        legs=legs, skip_summary=skip)


def write_report(res: Night2Result, out_dir, generated_at: str) -> list:
    from pathlib import Path

    from .report import _table

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    csv = out_dir / "night2.csv"
    res.cells.drop(columns=["by_year"]).to_csv(csv, index=False)
    written.append(csv)

    md = ["# 2晩目システム 検証結果\n", f"生成: {generated_at}\n"]
    md.append("引け後開示 → E+1 引けでニュース方向に建て → E+2 寄付で返す（1泊）。事前登録セルのみ。\n")

    cols = ["cell", "executable_only", "slippage_pct", "trades", "gross_pct", "excess_topix_pct",
            "net_edge_pct", "stdev_pct", "t_stat", "cluster_ci_low_pct", "cluster_ci_high_pct",
            "required_n", "h1_net_edge_pct", "h2_net_edge_pct", "both_halves_positive",
            "verdict", "decision"]
    cols = [c for c in cols if c in res.cells.columns]

    md.append("## 1. 主セル（執行できた日のみ・滑り0.4%）\n")
    main = res.cells[(~res.cells["is_control"]) & res.cells["executable_only"] & (res.cells["slippage_pct"] == 0.4)]
    md.append(_table(main[cols]))
    md.append("")
    md.append("判定: 純エッジ = TOPIX超過 − 滑り − 金利/貸株料。0.05%未満 打ち切り / 0.35%超 少額実弾。"
              "3セル同時なので α=0.05/3。\n")

    md.append("## 2. 対照群（符号が逆になっていなければ、拾っているのはニュースの方向ではない）\n")
    ctrl = res.cells[res.cells["is_control"] & res.cells["executable_only"] & (res.cells["slippage_pct"] == 0.4)]
    md.append(_table(ctrl[cols]))
    md.append("")

    md.append("## 3. 執行できない日を含めた場合（ストップ高/安の張り付き・貸借以外）\n")
    md.append("差が大きいほど、リターンが『執行できない日』に依存していたことになる。\n")
    allx = res.cells[(~res.cells["is_control"]) & (~res.cells["executable_only"]) & (res.cells["slippage_pct"] == 0.4)]
    md.append(_table(allx[cols]))
    md.append("")

    md.append("## 4. 滑り感度（主セル・執行できた日のみ）\n")
    sens = res.cells[(~res.cells["is_control"]) & res.cells["executable_only"]]
    md.append(_table(sens[["cell", "slippage_pct", "trades", "net_edge_pct",
                           "cluster_ci_low_pct", "cluster_ci_high_pct", "verdict"]]))
    md.append("")

    md.append("## 5. 年別（主セル・粗リターン%）\n")
    yr_rows = []
    for _, r in res.cells[(~res.cells["is_control"]) & res.cells["executable_only"]
                           & (res.cells["slippage_pct"] == 0.4)].iterrows():
        yr_rows.append({"cell": r["cell"], **{str(k): round(v, 3) for k, v in (r["by_year"] or {}).items()}})
    if yr_rows:
        md.append(_table(pd.DataFrame(yr_rows)))
    md.append("")

    md.append("## 6. 両建てポートフォリオ（long_up18 + short_dn30・執行できた日のみ）\n")
    md.append(_table(res.pair_portfolio))
    md.append("")
    md.append("## 7. 約定できなかった件数\n```")
    for side, counts in res.skip_summary.items():
        md.append(f"{side}: {counts}")
    md.append("```\n")

    p = out_dir / "night2.md"
    p.write_text("\n".join(md), encoding="utf-8")
    written.append(p)
    return written
