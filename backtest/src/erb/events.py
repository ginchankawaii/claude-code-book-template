"""イベント表の構築。

1イベント = 財務サマリーの1開示行。営業利益の会社予想がその開示で
どれだけ変わったか（修正率）を、イベント時点で開示済みの情報だけから計算する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .calendar import CloseTimeSchedule, TradingCalendar
from .constants import is_excluded

#: DocType の分類。2026-09-02 の probe で実データの値を確認済み。
#:
#:   EarnForecastRevision                        業績予想の修正
#:   DividendForecastRevision                    配当予想の修正（対象外）
#:   {1Q,2Q,3Q,FY}FinancialStatements_{Consolidated,NonConsolidated}_{JP,US,IFRS,Foreign,REIT}
#:
#: 判定は上から順に行う。"DividendForecastRevision" も "forecastrevision" を
#: 含むため、配当の判定を業績より先に置くこと（順序に意味がある）。
DOC_TYPE_RULES = (
    ("dividend_forecast_revision", ("dividendforecast",)),
    ("earn_forecast_revision", ("earnforecast", "forecastrevision")),
    ("financial_statements", ("financialstatements",)),
)

#: REIT（投資法人）の開示。事業会社と決算・予想の性質が異なるため既定で除外する。
#: 実データには2つの形が現れる。区切り文字を当てにしてはいけない。
#:   FYFinancialStatements_Consolidated_REIT   末尾に付く形
#:   REITEarnForecastRevision                  先頭に付く形（アンダースコアなし）
REIT_MARKER = "reit"

REVISION_EPS = 1e-9


@dataclass
class EventBuildResult:
    events: pd.DataFrame
    diagnostics: dict


def classify_doc_type(value: object) -> str:
    s = str(value).lower()
    for label, needles in DOC_TYPE_RULES:
        if any(n in s for n in needles):
            return label
    return "other"


def is_reit(value: object) -> bool:
    """REIT の開示か。

    DocType のどこかに REIT が入っていれば REIT とみなす。
    末尾に付く形（..._Consolidated_REIT）と先頭に付く形
    （REITEarnForecastRevision）の両方があるため、位置を決め打ちしない。
    """
    return REIT_MARKER in str(value).lower()


def is_fy_closing(cur_per_type: object) -> bool:
    """本決算（通期）の行か。"""
    s = str(cur_per_type).strip().upper()
    return s in {"FY", "4Q", "ANNUAL", "通期"}


def build_forecast_timeline(summary: pd.DataFrame) -> pd.DataFrame:
    """(銘柄, 事業年度) ごとの会社予想の時系列を作る。

    1行の開示は最大2つの予想点を生む:
      - 当期の通期予想 FOP  -> (code, cur_fy_end)
      - 本決算行の翌期予想 NxFOP -> (code, 翌事業年度) の初回予想（＝修正ではない）

    これにより「本決算で出た新年度予想」が、その後の修正率の分母になる。
    """
    rows = []
    for rec in summary.to_dict("records"):
        code = rec.get("code")
        fy_end = rec.get("cur_fy_end")
        base = {
            "code": code,
            "disc_date": rec.get("disc_date"),
            "disc_time": rec.get("disc_time"),
            "disc_no": rec.get("disc_no"),
            "doc_type": rec.get("doc_type"),
            "doc_class": classify_doc_type(rec.get("doc_type")),
            "is_reit": is_reit(rec.get("doc_type")),
            "cur_per_type": rec.get("cur_per_type"),
            "op_actual": rec.get("op_actual"),
            "shares_out": rec.get("shares_out"),
            "treasury_shares": rec.get("treasury_shares"),
        }
        fop = rec.get("fop")
        if fy_end is not None and pd.notna(fy_end) and pd.notna(fop):
            rows.append({**base, "fy_end": fy_end, "forecast_op": float(fop), "is_seed": False})
        nxfop = rec.get("nxfop")
        if is_fy_closing(rec.get("cur_per_type")) and fy_end is not None and pd.notna(fy_end) and pd.notna(nxfop):
            rows.append(
                {**base, "fy_end": _add_one_year(fy_end), "forecast_op": float(nxfop), "is_seed": True}
            )
    if not rows:
        return pd.DataFrame(
            columns=["code", "fy_end", "disc_date", "disc_time", "disc_no", "doc_type",
                     "doc_class", "cur_per_type", "forecast_op", "is_seed",
                     "_order", "prev_forecast_op"]
        )
    tl = pd.DataFrame(rows)
    tl = pd.concat([tl, _sort_components(tl)], axis=1)
    tl = tl.sort_values(["code", "fy_end", "_d", "_t", "_n"]).reset_index(drop=True)
    tl["_order"] = np.arange(len(tl))
    tl["prev_forecast_op"] = tl.groupby(["code", "fy_end"], observed=True)["forecast_op"].shift(1)
    return tl.drop(columns=["_d", "_t", "_n"])


def compute_revision_rate(tl: pd.DataFrame) -> pd.DataFrame:
    """修正率。分母は直前に開示済みの会社予想。

    分母が 0 以下（赤字予想からの転換など）は率が定義できないため NaN にし、
    件数だけ diagnostics で数える。
    """
    out = tl.copy()
    prev = out["prev_forecast_op"]
    valid = prev.notna() & (prev > 0) & out["forecast_op"].notna()
    out["revision_rate"] = np.where(valid, out["forecast_op"] / prev - 1.0, np.nan)
    out["revision_undefined"] = out["prev_forecast_op"].notna() & (out["prev_forecast_op"] <= 0)
    out["is_initial_forecast"] = out["prev_forecast_op"].isna()
    return out


def add_habitual_flag(tl: pd.DataFrame, lookback_days: int, min_revisions: int,
                      data_start: date) -> pd.DataFrame:
    """修正常習フラグ。

    イベント日より前 lookback_days 暦日に、同一銘柄で会社予想が実際に
    変わった開示が min_revisions 件以上あれば常習とする。
    上方・下方の両方を数える（Q4）。

    データ開始から lookback_days 未満のイベントは窓が欠けるため、
    habitual_window_complete=False を立てて別集計できるようにする。
    """
    sort_cols = ["code", "_order"] if "_order" in tl.columns else ["code", "disc_date"]
    out = tl.sort_values(sort_cols).reset_index(drop=True)
    changed = out["revision_rate"].notna() & (out["revision_rate"].abs() > REVISION_EPS)
    out["_is_change"] = changed

    counts = []
    complete = []
    for code, grp in out.groupby("code", observed=True, sort=False):
        dates = pd.to_datetime(pd.Series(list(grp["disc_date"]))).to_numpy()
        flags = grp["_is_change"].to_numpy()
        cum = np.cumsum(flags.astype(int))
        window = np.timedelta64(lookback_days, "D")
        for i in range(len(dates)):
            # dates は銘柄内で昇順。開始位置は「イベント日 - lookback」以降の最初
            lo = int(np.searchsorted(dates, dates[i] - window, side="left"))
            # 自分自身は数えない（イベント時点では未開示）
            n = int(cum[i - 1] - (cum[lo - 1] if lo > 0 else 0)) if i > 0 else 0
            counts.append(n)
            ev_date = pd.Timestamp(dates[i]).date()
            complete.append((ev_date - pd.Timedelta(days=lookback_days).to_pytimedelta()) >= data_start)
    out["habitual_count"] = counts
    out["habitual"] = out["habitual_count"] >= min_revisions
    out["habitual_window_complete"] = complete
    return out.drop(columns=["_is_change"])


def attach_timing(tl: pd.DataFrame, close_schedule: CloseTimeSchedule,
                  calendar: TradingCalendar) -> pd.DataFrame:
    """引け後/場中の分類と、エントリー営業日 t0 を付ける。

    開示が引け後でも場中でも、エントリーは翌営業日の始値で統一する（仕様）。
    ただし内訳を必ず別掲できるよう after_close フラグを残す。
    """
    out = tl.copy()
    after = []
    for d, t in zip(out["disc_date"], out["disc_time"]):
        if d is None or pd.isna(d):
            after.append(True)
            continue
        if not calendar.is_business_day(d):
            after.append(True)  # 休業日の開示は必ず翌営業日扱い
            continue
        try:
            after.append(close_schedule.is_after_close(d, t))
        except ValueError:
            after.append(True)  # 時刻不明は保守的に引け後
    out["after_close"] = after
    out["entry_date"] = [
        calendar.next_business_day(d) if d is not None and not pd.isna(d) else None
        for d in out["disc_date"]
    ]
    return out


def attach_market_cap(tl: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """イベント時点の時価総額。

    現在値ではなく開示日時点で評価する。MktCap 列があればそれを使い、
    無ければ (発行済株式数 - 自己株式数) x その日の終値（生値）で代替する。
    調整済み終値を使うと将来の分割が遡及して混入するため、必ず生値を使う。
    開示日が休業日・売買停止の場合は、その日以前の直近の終値を使う。
    """
    out = tl.copy()
    out["_row"] = np.arange(len(out))

    cols = ["code", "date", "close"]
    if "mkt_cap" in daily.columns:
        cols.append("mkt_cap")
    px = daily.loc[daily["date"].notna(), cols].copy()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values("date")  # merge_asof は on キーで全体がソートされている必要がある

    left = out.loc[out["disc_date"].notna(), ["_row", "code", "disc_date"]].copy()
    left["date"] = pd.to_datetime(left["disc_date"])
    left = left.sort_values("date")

    if left.empty or px.empty:
        out["close_at_disclosure"] = np.nan
        if "mkt_cap" not in out.columns:
            out["mkt_cap"] = np.nan
    else:
        merged = pd.merge_asof(
            left[["_row", "code", "date"]], px, on="date", by="code", direction="backward"
        ).set_index("_row")
        out["close_at_disclosure"] = out["_row"].map(merged["close"])
        if "mkt_cap" in merged.columns:
            out["mkt_cap"] = out["_row"].map(merged["mkt_cap"])
        else:
            out["mkt_cap"] = np.nan

    out["mkt_cap"] = pd.to_numeric(out["mkt_cap"], errors="coerce")
    out["close_at_disclosure"] = pd.to_numeric(out["close_at_disclosure"], errors="coerce")

    shares = out["shares_out"] if "shares_out" in out.columns else None
    if shares is not None:
        treasury = out["treasury_shares"] if "treasury_shares" in out.columns else None
        net_shares = pd.to_numeric(shares, errors="coerce").fillna(0)
        if treasury is not None:
            net_shares = net_shares - pd.to_numeric(treasury, errors="coerce").fillna(0)
        fallback = net_shares * out["close_at_disclosure"]
        usable = out["mkt_cap"].notna() & (out["mkt_cap"] > 0)
        out["mkt_cap"] = out["mkt_cap"].where(usable, fallback)

    out["mkt_cap_source"] = np.where(out["mkt_cap"].notna() & (out["mkt_cap"] > 0),
                                     "value", "missing")
    return out.drop(columns=["_row"])


def build_events(summary: pd.DataFrame, daily: pd.DataFrame, calendar: TradingCalendar,
                 close_schedule: CloseTimeSchedule, lookback_days: int,
                 min_revisions: int, exclude_reit: bool = True) -> EventBuildResult:
    """イベント表を組み立てる。"""
    diag: dict = {"summary_rows": len(summary)}

    tl = build_forecast_timeline(summary)
    diag["forecast_points"] = len(tl)

    tl = compute_revision_rate(tl)
    diag["undefined_revision_rate"] = int(tl["revision_undefined"].sum())
    diag["initial_forecasts"] = int(tl["is_initial_forecast"].sum())

    # 配当予想修正のみの開示は対象外（仕様）
    before = len(tl)
    tl = tl[tl["doc_class"] != "dividend_forecast_revision"].copy()
    diag["dropped_dividend_only"] = before - len(tl)

    if exclude_reit:
        before = len(tl)
        tl = tl[~tl["is_reit"]].copy()
        diag["dropped_reit"] = before - len(tl)

    data_start = min(d for d in daily["date"] if d is not None) if len(daily) else date(1900, 1, 1)
    tl = add_habitual_flag(tl, lookback_days, min_revisions, data_start)
    tl = attach_timing(tl, close_schedule, calendar)
    tl = attach_market_cap(tl, daily)

    tl["excluded_by_spec"] = tl["code"].map(is_excluded)
    diag["excluded_by_spec"] = int(tl["excluded_by_spec"].sum())
    diag["after_close"] = int(tl["after_close"].sum())
    diag["intraday"] = int((~tl["after_close"]).sum())
    diag["no_entry_date"] = int(tl["entry_date"].isna().sum())

    return EventBuildResult(events=tl.reset_index(drop=True), diagnostics=diag)


def _sort_components(df: pd.DataFrame) -> pd.DataFrame:
    """開示日 -> 開示時刻 -> 開示番号 の順に並べるための列。

    日付を int64 のナノ秒にして桁をずらすと int64 が溢れるため、
    3列に分けて多列ソートする。
    """
    d = pd.to_datetime(df["disc_date"], errors="coerce")
    t = (
        df["disc_time"].astype("string").fillna("00:00:00")
        .str.replace(":", "", regex=False).str.slice(0, 6)
        .str.pad(6, side="right", fillchar="0")
    )
    return pd.DataFrame({
        "_d": d.to_numpy(),
        "_t": pd.to_numeric(t, errors="coerce").fillna(0).astype("int64").to_numpy(),
        "_n": pd.to_numeric(df["disc_no"], errors="coerce").fillna(0).astype("int64").to_numpy(),
    }, index=df.index)


def _add_one_year(d: date) -> date:
    """事業年度末の1年後。2/29 は 2/28 に丸める。"""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)
