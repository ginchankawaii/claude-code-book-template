"""イベント構築の境界条件。"""

from datetime import date

import pandas as pd
import pytest

from erb.data import normalize
from erb.events import build_events, build_forecast_timeline, compute_revision_rate


def _summary_rows():
    """A0001 の1事業年度分の開示。

    2024-11-01 本決算(FY2024/3期ではなくテスト用の並び) -> 翌期予想 1000
    2024-11-11 業績予想修正                              -> 予想 1300 (+30%)
    2024-11-18 業績予想修正                              -> 予想 1560 (+20%)
    """
    return [
        {"DiscDate": "2024-11-01", "DiscTime": "15:30:00", "Code": "A0001", "DiscNo": "1",
         "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY",
         "CurFYSt": "2023-04-01", "CurFYEn": "2024-03-31",
         "OP": 900, "FOP": 900, "NxFOP": 1000, "FOP2Q": None,
         "ShOutFY": 20_000_000, "TrShFY": 0},
        {"DiscDate": "2024-11-11", "DiscTime": "15:30:00", "Code": "A0001", "DiscNo": "2",
         "DocType": "EarnForecastRevision", "CurPerType": "FY",
         "CurFYSt": "2024-04-01", "CurFYEn": "2025-03-31",
         "OP": None, "FOP": 1300, "NxFOP": None, "FOP2Q": None,
         "ShOutFY": 20_000_000, "TrShFY": 0},
        {"DiscDate": "2024-11-18", "DiscTime": "12:00:00", "Code": "A0001", "DiscNo": "3",
         "DocType": "EarnForecastRevision", "CurPerType": "FY",
         "CurFYSt": "2024-04-01", "CurFYEn": "2025-03-31",
         "OP": None, "FOP": 1560, "NxFOP": None, "FOP2Q": None,
         "ShOutFY": 20_000_000, "TrShFY": 0},
    ]


def test_fy_closing_seeds_next_year_forecast(cfg):
    summary = normalize(cfg, "summary", pd.DataFrame(_summary_rows()))
    tl = build_forecast_timeline(summary)
    seeded = tl[(tl["fy_end"] == date(2025, 3, 31)) & tl["is_seed"]]
    assert len(seeded) == 1
    assert seeded.iloc[0]["forecast_op"] == 1000


def test_revision_rate_uses_previous_disclosed_forecast(cfg):
    summary = normalize(cfg, "summary", pd.DataFrame(_summary_rows()))
    tl = compute_revision_rate(build_forecast_timeline(summary))
    fy25 = tl[tl["fy_end"] == date(2025, 3, 31)].sort_values("_order")
    rates = fy25["revision_rate"].tolist()
    assert pd.isna(rates[0])                       # 新年度の初回予想は修正ではない
    assert rates[1] == pytest.approx(0.30)         # 1000 -> 1300
    assert rates[2] == pytest.approx(0.20)         # 1300 -> 1560


def test_initial_forecast_is_flagged_not_dropped(cfg):
    summary = normalize(cfg, "summary", pd.DataFrame(_summary_rows()))
    tl = compute_revision_rate(build_forecast_timeline(summary))
    assert tl["is_initial_forecast"].sum() >= 1


def test_revision_rate_undefined_when_previous_forecast_not_positive(cfg):
    rows = _summary_rows()
    rows[0]["NxFOP"] = -500          # 赤字予想
    summary = normalize(cfg, "summary", pd.DataFrame(rows))
    tl = compute_revision_rate(build_forecast_timeline(summary))
    fy25 = tl[tl["fy_end"] == date(2025, 3, 31)].sort_values("_order")
    assert pd.isna(fy25.iloc[1]["revision_rate"])
    assert bool(fy25.iloc[1]["revision_undefined"])


def test_dividend_only_revision_is_excluded(cfg, daily, calendar, close_schedule):
    rows = _summary_rows()
    rows.append({"DiscDate": "2024-11-20", "DiscTime": "15:30:00", "Code": "A0001",
                 "DiscNo": "4", "DocType": "DividendForecastRevision", "CurPerType": "FY",
                 "CurFYSt": "2024-04-01", "CurFYEn": "2025-03-31",
                 "OP": None, "FOP": 1560, "NxFOP": None, "FOP2Q": None,
                 "ShOutFY": 20_000_000, "TrShFY": 0})
    summary = normalize(cfg, "summary", pd.DataFrame(rows))
    d = normalize(cfg, "daily", daily)
    built = build_events(summary, d, calendar, close_schedule, 1095, 4)
    assert built.diagnostics["dropped_dividend_only"] == 1
    assert "DividendForecastRevision" not in set(built.events["doc_type"].astype(str))


def test_intraday_and_after_close_are_labelled(cfg, daily, calendar, close_schedule):
    summary = normalize(cfg, "summary", pd.DataFrame(_summary_rows()))
    d = normalize(cfg, "daily", daily)
    built = build_events(summary, d, calendar, close_schedule, 1095, 4)
    ev = built.events.set_index("disc_no")
    assert bool(ev.loc["2", "after_close"]) is True     # 15:30 は延長後の引け
    assert bool(ev.loc["3", "after_close"]) is False    # 12:00 は場中


def test_entry_is_next_business_day_for_both_timings(cfg, daily, calendar, close_schedule):
    """場中開示でも引け後開示でも、エントリーは翌営業日の始値で統一する。"""
    summary = normalize(cfg, "summary", pd.DataFrame(_summary_rows()))
    d = normalize(cfg, "daily", daily)
    built = build_events(summary, d, calendar, close_schedule, 1095, 4)
    ev = built.events.set_index("disc_no")
    assert ev.loc["2", "entry_date"] == date(2024, 11, 12)
    assert ev.loc["3", "entry_date"] == date(2024, 11, 19)


def test_habitual_counts_only_prior_disclosures(cfg, daily, calendar, close_schedule):
    """常習フラグはイベント日より前の開示だけで作る（先読み禁止）。"""
    rows = _summary_rows()
    for i, day in enumerate(["2024-11-19", "2024-11-20", "2024-11-21"], start=4):
        rows.append({"DiscDate": day, "DiscTime": "15:30:00", "Code": "A0001",
                     "DiscNo": str(i), "DocType": "EarnForecastRevision", "CurPerType": "FY",
                     "CurFYSt": "2024-04-01", "CurFYEn": "2025-03-31",
                     "OP": None, "FOP": 1560 + i * 100, "NxFOP": None, "FOP2Q": None,
                     "ShOutFY": 20_000_000, "TrShFY": 0})
    summary = normalize(cfg, "summary", pd.DataFrame(rows))
    d = normalize(cfg, "daily", daily)
    built = build_events(summary, d, calendar, close_schedule, 1095, 4)
    ev = built.events.sort_values("disc_date").set_index("disc_no")
    # 最初の修正の時点では過去の修正は0件
    assert int(ev.loc["2", "habitual_count"]) == 0
    assert bool(ev.loc["2", "habitual"]) is False
    # 5回目の開示時点では過去4件が数えられ、常習になる
    assert int(ev.loc["6", "habitual_count"]) >= 4
    assert bool(ev.loc["6", "habitual"]) is True


def test_market_cap_uses_raw_close_not_adjusted(cfg, daily, calendar, close_schedule):
    """時価総額は生値で評価する。調整済み終値だと将来の分割が遡及して混入する。"""
    d = daily.copy()
    # A0001 だけ調整済みを 1/10 にする（将来10分割された想定）
    mask = d["Code"] == "A0001"
    for col in ("AdjO", "AdjH", "AdjL", "AdjC", "MktCap"):
        d[col] = d[col].astype(float)
    for col in ("AdjO", "AdjH", "AdjL", "AdjC"):
        d.loc[mask, col] = d.loc[mask, col] / 10
    d.loc[mask, "MktCap"] = float("nan")
    summary = normalize(cfg, "summary", pd.DataFrame(_summary_rows()))
    dn = normalize(cfg, "daily", d)
    built = build_events(summary, dn, calendar, close_schedule, 1095, 4)
    row = built.events[built.events["disc_no"] == "2"].iloc[0]
    # 20,000,000 株 x 生の終値（約1000円台）= 200億円前後。調整済みなら 20億になってしまう。
    assert row["mkt_cap"] > 1.5e10


def test_excluded_codes_are_flagged(cfg, daily, calendar, close_schedule):
    rows = _summary_rows()
    for r in rows:
        r["Code"] = "80530"
    summary = normalize(cfg, "summary", pd.DataFrame(rows))
    d = normalize(cfg, "daily", daily)
    built = build_events(summary, d, calendar, close_schedule, 1095, 4)
    assert built.events["excluded_by_spec"].all()



def test_disclosure_regime_splits_intraday_by_extension():
    """場中を延伸前 / 延伸後15:00前 / 延伸後15:00〜 に分ける。

    延伸前は 15:00〜15:29 の開示が引け後だったので、延伸後にだけ現れる
    15:00〜15:29 の群が場中セルに混ざる。ここを分けないと、場中の超過が
    構造なのか母集団の入れ替わりなのか判別できない。
    """
    from erb.events import disclosure_regime

    assert disclosure_regime(date(2024, 6, 3), "12:00:00", False) == "intraday_pre_ext"
    assert disclosure_regime(date(2025, 6, 2), "12:00:00", False) == "intraday_post_early"
    assert disclosure_regime(date(2025, 6, 2), "15:10:00", False) == "intraday_post_1500"
    assert disclosure_regime(date(2025, 6, 2), "15:40:00", True) == "after_close"
    assert disclosure_regime(date(2024, 6, 3), "15:10:00", True) == "after_close"


def test_regime_is_attached_to_events(cfg, daily, calendar, close_schedule):
    summary = normalize(cfg, "summary", pd.DataFrame(_summary_rows()))
    d = normalize(cfg, "daily", daily)
    built = build_events(summary, d, calendar, close_schedule, 1095, 4)
    assert "regime" in built.events.columns
    ev = built.events.set_index("disc_no")
    assert ev.loc["3", "regime"] == "intraday_post_early"     # 2024-11-18 12:00
    assert ev.loc["2", "regime"] == "after_close"             # 2024-11-11 15:30


def test_habitual_flag_survives_missing_disclosure_dates(cfg, daily, calendar, close_schedule):
    """開示日が欠けた行があっても落ちない。常習判定は「不明」扱いで残す。"""
    rows = _summary_rows()
    rows.append({**rows[1], "DiscNo": "9", "DiscDate": None})
    summary = normalize(cfg, "summary", pd.DataFrame(rows))
    d = normalize(cfg, "daily", daily)
    built = build_events(summary, d, calendar, close_schedule, 1095, 4)
    assert len(built.events) >= len(rows) - 1
    missing = built.events[built.events["disc_no"] == "9"]
    assert (missing["habitual"] == False).all()
