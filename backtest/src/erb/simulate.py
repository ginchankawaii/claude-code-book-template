"""約定モデルとポートフォリオ・シミュレーション。

価格の使い分け（先読みバイアスの回避）:
  リターンの計算  -> 調整済み価格（分割を跨ぐリターンが正しくなる）
  価格水準の判断  -> 生の価格（当時その値段で買えたのか）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .calendar import TradingCalendar
from .constants import SHARES_PER_LOT

#: 寄らずの扱い
NO_OPEN_SKIP = "skip"
NO_OPEN_NEXT = "next_open"
NO_OPEN_EXCLUDE_LIMIT_UP = "exclude_limit_up"


@dataclass
class PriceIndex:
    """銘柄ごとの日足を位置引きできる形に持つ。"""

    frames: dict[str, dict]

    @classmethod
    def build(cls, daily: pd.DataFrame) -> "PriceIndex":
        frames: dict[str, dict] = {}
        cols = ["date", "open", "close", "adj_open", "adj_close", "volume"]
        optional = ["upper_limit", "lower_limit", "turnover_avg", "turnover"]
        for code, grp in daily.sort_values(["code", "date"]).groupby("code", observed=True, sort=False):
            entry = {c: grp[c].to_numpy() for c in cols if c in grp.columns}
            for c in optional:
                if c in grp.columns:
                    entry[c] = grp[c].to_numpy()
            entry["_dates64"] = pd.to_datetime(grp["date"]).to_numpy()
            entry["_pos"] = {d: i for i, d in enumerate(grp["date"].tolist())}
            frames[code] = entry
        return cls(frames=frames)

    def has(self, code: str) -> bool:
        return code in self.frames

    def position(self, code: str, d: date) -> int | None:
        f = self.frames.get(code)
        if f is None:
            return None
        return f["_pos"].get(d)

    def position_on_or_before(self, code: str, d: date) -> int | None:
        f = self.frames.get(code)
        if f is None:
            return None
        i = int(np.searchsorted(f["_dates64"], np.datetime64(d), side="right")) - 1
        return i if i >= 0 else None

    def field(self, code: str, i: int, name: str):
        f = self.frames.get(code)
        if f is None or name not in f:
            return np.nan
        arr = f[name]
        if i < 0 or i >= len(arr):
            return np.nan
        return arr[i]

    def last_position(self, code: str) -> int:
        return len(self.frames[code]["_dates64"]) - 1

    def date_at(self, code: str, i: int) -> date:
        return pd.Timestamp(self.frames[code]["_dates64"][i]).date()


def simulate_trades(
    events: pd.DataFrame,
    prices: PriceIndex,
    calendar: TradingCalendar,
    holding_days: int,
    *,
    position_size_jpy: int,
    no_open_policy: str = NO_OPEN_SKIP,
    topix: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """イベント1件を1トレードに変換する。

    スリッページと金利はここでは引かない（Nと滑りの組み合わせで後から引くため）。
    返すのは粗リターンと、コスト計算に必要な保有暦日数。
    """
    topix_lookup = _topix_lookup(topix)
    rows = []

    for ev in events.to_dict("records"):
        code = ev["code"]
        entry_date = ev.get("entry_date")
        row = {
            "code": code,
            "disc_date": ev.get("disc_date"),
            "entry_date": entry_date,
            "revision_rate": ev.get("revision_rate"),
            "mkt_cap": ev.get("mkt_cap"),
            "habitual": ev.get("habitual"),
            "habitual_window_complete": ev.get("habitual_window_complete"),
            "after_close": ev.get("after_close"),
            "excluded_by_spec": ev.get("excluded_by_spec"),
            "doc_class": ev.get("doc_class"),
            "is_initial_forecast": ev.get("is_initial_forecast"),
            "status": None,
            "gross_return": np.nan,
            "topix_return": np.nan,
            "holding_calendar_days": np.nan,
            "entry_limit_up": False,
            "turnover_avg": np.nan,
            "raw_entry_price": np.nan,
        }

        if entry_date is None or pd.isna(entry_date):
            row["status"] = "no_entry_date"
            rows.append(row)
            continue
        if not prices.has(code):
            row["status"] = "no_price_data"
            rows.append(row)
            continue

        i = prices.position(code, entry_date)
        i = _resolve_entry(prices, code, entry_date, i, no_open_policy)
        if i is None:
            row["status"] = "no_open"
            rows.append(row)
            continue

        limit_up = bool(prices.field(code, i, "upper_limit"))
        row["entry_limit_up"] = limit_up
        if no_open_policy == NO_OPEN_EXCLUDE_LIMIT_UP and limit_up:
            row["status"] = "excluded_limit_up"
            rows.append(row)
            continue

        raw_open = prices.field(code, i, "open")
        adj_entry = prices.field(code, i, "adj_open")
        row["raw_entry_price"] = raw_open
        row["turnover_avg"] = prices.field(code, i, "turnover_avg")

        if not _positive(adj_entry) or not _positive(raw_open):
            row["status"] = "no_open"
            rows.append(row)
            continue

        # 単元は生値で判定する（調整済みだと将来の分割が遡及して安く見える）
        if raw_open * SHARES_PER_LOT > position_size_jpy:
            row["status"] = "lot_too_large"
            rows.append(row)
            continue

        actual_entry_date = prices.date_at(code, i)
        exit_date = calendar.shift(actual_entry_date, holding_days)
        if exit_date is None:
            row["status"] = "exit_beyond_data"
            rows.append(row)
            continue

        j = prices.position(code, exit_date)
        if j is not None:
            adj_exit = prices.field(code, j, "adj_open")
            exit_kind = "open"
            actual_exit_date = exit_date
            if not _positive(adj_exit):
                adj_exit = prices.field(code, j, "adj_close")
                exit_kind = "close_fallback"
        else:
            # tN に値がない: 上場廃止・売買停止。最終取引日の終値で手仕舞う
            j = prices.position_on_or_before(code, exit_date)
            if j is None or j <= i:
                row["status"] = "no_exit"
                rows.append(row)
                continue
            adj_exit = prices.field(code, j, "adj_close")
            exit_kind = "delisted_or_halted"
            actual_exit_date = prices.date_at(code, j)

        if not _positive(adj_exit):
            row["status"] = "no_exit"
            rows.append(row)
            continue

        row["status"] = "ok"
        row["exit_kind"] = exit_kind
        row["exit_date"] = actual_exit_date
        row["entry_date"] = actual_entry_date
        row["gross_return"] = float(adj_exit) / float(adj_entry) - 1.0
        row["holding_calendar_days"] = calendar.calendar_days_between(actual_entry_date, actual_exit_date)
        row["topix_return"] = _topix_return(topix_lookup, actual_entry_date, actual_exit_date)
        rows.append(row)

    out = pd.DataFrame(rows)
    if "exit_date" not in out.columns:
        out["exit_date"] = pd.NaT
    if "exit_kind" not in out.columns:
        out["exit_kind"] = None
    return out


def apply_costs(trades: pd.DataFrame, slippage_round_trip_pct: float,
                margin_interest_annual_pct: float,
                commission_jpy_per_trade: int = 0,
                position_size_jpy: int = 500_000) -> pd.DataFrame:
    """スリッページ・金利・手数料を引いて純リターンを出す。

    金利は建玉に対して 年率 x 暦日/365。建日・返済日は両端入れ。
    """
    out = trades.copy()
    slip = slippage_round_trip_pct / 100.0
    interest = (
        margin_interest_annual_pct / 100.0
        * out["holding_calendar_days"].astype(float)
        / 365.0
    )
    commission = (commission_jpy_per_trade * 2) / position_size_jpy if position_size_jpy else 0.0
    out["interest_cost"] = interest
    out["slippage_cost"] = slip
    out["commission_cost"] = commission
    out["net_return"] = out["gross_return"] - slip - interest - commission
    out["excess_return"] = out["gross_return"] - out["topix_return"]
    out["net_excess_return"] = out["excess_return"] - slip - interest - commission
    return out


def simulate_portfolio(trades: pd.DataFrame, *, position_size_jpy: int, max_concurrent: int,
                       equity_jpy: int, maintenance_margin_ratio: float,
                       prices: PriceIndex, calendar: TradingCalendar | None = None) -> dict:
    """同時保有本数の制約を入れた日次シミュレーション。

    - 建玉は建てた順に保有し、返済日に決済する
    - 空き枠がない日のシグナルは見送り、件数を記録する
    - 毎日、含み損益から維持率を計算し、割れた日を追証として数える

    維持率は保有期間中の**全営業日**で評価する。建てた日と返済日だけを見ると、
    2024-08-05（日経 -12.4%）のような保有途中の急落を取りこぼす。
    calendar を渡さない場合は建玉の出入りがあった日しか見られないため、
    追証の件数を過小評価する。
    """
    ok = trades[(trades["status"] == "ok")].copy()
    if ok.empty:
        return {
            "equity_curve": pd.DataFrame(columns=["date", "equity", "maintenance_ratio"]),
            "taken": 0, "skipped_no_slot": 0, "margin_call_days": 0,
            "max_drawdown_pct": 0.0, "realized_pnl_jpy": 0.0, "by_year": {},
        }

    ok = ok.sort_values(["entry_date", "revision_rate", "mkt_cap"],
                        ascending=[True, False, True]).reset_index(drop=True)

    open_positions: list[dict] = []
    taken = 0
    skipped_no_slot = 0
    realized = 0.0
    daily_rows = []
    margin_call_days = 0

    by_entry: dict[date, list[dict]] = {}
    for rec in ok.to_dict("records"):
        by_entry.setdefault(rec["entry_date"], []).append(rec)

    all_dates = sorted({d for d in ok["entry_date"]} | {d for d in ok["exit_date"] if d is not None})
    if not all_dates:
        all_dates = sorted(by_entry.keys())
    start, end = all_dates[0], all_dates[-1]

    if calendar is not None:
        # 保有期間中の全営業日を走査する。途中の急落で追証が出るため。
        scan_dates = [d for d in calendar.days if start <= d <= end]
    else:
        scan_dates = sorted({d for d in all_dates if start <= d <= end})

    for d in scan_dates:
        # 1) 返済
        still_open = []
        for p in open_positions:
            if p["exit_date"] is not None and p["exit_date"] <= d:
                realized += p["net_return"] * position_size_jpy
            else:
                still_open.append(p)
        open_positions = still_open

        # 2) 新規建て
        for rec in by_entry.get(d, []):
            if len(open_positions) < max_concurrent:
                open_positions.append(rec)
                taken += 1
            else:
                skipped_no_slot += 1

        # 3) 維持率（含み損益は当日終値ベース）
        unrealized = 0.0
        gross_position = 0.0
        for p in open_positions:
            i = prices.position_on_or_before(p["code"], d)
            entry_i = prices.position(p["code"], p["entry_date"])
            if i is None or entry_i is None:
                continue
            px_now = prices.field(p["code"], i, "adj_close")
            px_in = prices.field(p["code"], entry_i, "adj_open")
            if _positive(px_now) and _positive(px_in):
                unrealized += (float(px_now) / float(px_in) - 1.0) * position_size_jpy
            gross_position += position_size_jpy

        equity = equity_jpy + realized + unrealized
        ratio = (equity / gross_position) if gross_position > 0 else float("inf")
        if gross_position > 0 and ratio < maintenance_margin_ratio:
            margin_call_days += 1
        daily_rows.append({"date": d, "equity": equity, "maintenance_ratio": ratio,
                           "open_positions": len(open_positions)})

    # 残った建玉を最終日に決済
    for p in open_positions:
        realized += p["net_return"] * position_size_jpy

    curve = pd.DataFrame(daily_rows)
    max_dd = _max_drawdown(curve["equity"]) if not curve.empty else 0.0

    by_year: dict[int, float] = {}
    for rec in ok.to_dict("records"):
        y = rec["exit_date"].year if rec["exit_date"] is not None else rec["entry_date"].year
        by_year[y] = by_year.get(y, 0.0) + rec["net_return"] * position_size_jpy

    return {
        "equity_curve": curve,
        "taken": taken,
        "skipped_no_slot": skipped_no_slot,
        "margin_call_days": margin_call_days,
        "max_drawdown_pct": max_dd * 100.0,
        "realized_pnl_jpy": realized,
        "by_year": by_year,
    }


def _resolve_entry(prices: PriceIndex, code: str, entry_date: date, i: int | None,
                   policy: str) -> int | None:
    """エントリー日に売買が成立していたか判定する。

    寄らず（出来高0・始値なし）の扱いは policy に従う。
    """
    if i is None:
        if policy != NO_OPEN_NEXT:
            return None
        i = prices.position_on_or_before(code, entry_date)
        if i is None:
            return None
        i += 1
        if i > prices.last_position(code):
            return None

    for _ in range(10):
        vol = prices.field(code, i, "volume")
        op = prices.field(code, i, "open")
        traded = _positive(op) and (pd.isna(vol) or float(vol) > 0)
        if traded:
            return i
        if policy != NO_OPEN_NEXT:
            return None
        if i >= prices.last_position(code):
            return None
        i += 1
    return None


def _topix_lookup(topix: pd.DataFrame | None):
    if topix is None or topix.empty:
        return None
    t = topix.sort_values("date")
    return {d: o for d, o in zip(t["date"], t["open"])}


def _topix_return(lookup, a: date, b: date) -> float:
    if lookup is None:
        return np.nan
    pa, pb = lookup.get(a), lookup.get(b)
    if not _positive(pa) or not _positive(pb):
        return np.nan
    return float(pb) / float(pa) - 1.0


def _positive(x) -> bool:
    try:
        return x is not None and not pd.isna(x) and float(x) > 0
    except (TypeError, ValueError):
        return False


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)
    return float(dd.min()) if dd.notna().any() else 0.0
