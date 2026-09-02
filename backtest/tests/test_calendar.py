from datetime import date, time

import pytest

from erb.calendar import CloseTimeSchedule, TradingCalendar


def test_next_business_day_skips_weekend(calendar):
    # 2024-10-25 は金曜。翌営業日は月曜 10-28。
    assert calendar.next_business_day(date(2024, 10, 25)) == date(2024, 10, 28)


def test_next_business_day_excludes_self(calendar):
    d = date(2024, 10, 22)
    assert calendar.next_business_day(d) == date(2024, 10, 23)


def test_shift_counts_business_days(calendar):
    # 金曜から5営業日後は翌週金曜
    assert calendar.shift(date(2024, 10, 25), 5) == date(2024, 11, 1)


def test_shift_rejects_non_business_day(calendar):
    with pytest.raises(ValueError):
        calendar.shift(date(2024, 10, 26), 1)  # 土曜


def test_shift_past_end_returns_none(calendar):
    assert calendar.shift(calendar.days[-1], 1) is None


def test_calendar_days_between_is_inclusive(calendar):
    # 金曜に建てて翌週金曜に返済 = 8 暦日（両端入れ）
    assert calendar.calendar_days_between(date(2024, 10, 25), date(2024, 11, 1)) == 8


def test_close_time_switches_on_2024_11_05(close_schedule):
    assert close_schedule.close_time(date(2024, 11, 1)) == time(15, 0)
    assert close_schedule.close_time(date(2024, 11, 5)) == time(15, 30)


def test_after_close_boundary_before_change(close_schedule):
    d = date(2024, 11, 1)
    assert close_schedule.is_after_close(d, "15:00:00") is True
    assert close_schedule.is_after_close(d, "14:59:00") is False


def test_after_close_boundary_after_change(close_schedule):
    d = date(2024, 11, 5)
    # 15:10 は延長前なら引け後だが、延長後は場中
    assert close_schedule.is_after_close(d, "15:10:00") is False
    assert close_schedule.is_after_close(d, "15:30:00") is True


def test_missing_time_is_treated_as_after_close(close_schedule):
    assert close_schedule.is_after_close(date(2024, 11, 5), None) is True


def test_calendar_can_be_derived_from_daily_prices(daily, days):
    """取引カレンダーが取れない契約でも、日足から営業日を復元できること。"""
    import pandas as pd

    from erb.config import Config
    from erb.data import normalize

    d = normalize(Config.load("config.yaml"), "daily", daily)
    cal = TradingCalendar.from_daily_prices(d)
    assert list(cal.days) == days
    assert cal.next_business_day(date(2024, 10, 25)) == date(2024, 10, 28)


def test_derived_calendar_ignores_gaps_in_a_single_stock(daily):
    """1銘柄のデータが尽きても、他の銘柄が取引していれば営業日として残る。"""
    import pandas as pd

    from erb.config import Config
    from erb.data import normalize

    d = normalize(Config.load("config.yaml"), "daily", daily)
    n_all = len(TradingCalendar.from_daily_prices(d).days)
    # C0003 は最後の5営業日のデータが無いが、営業日の数は変わらない
    n_without_c = len(TradingCalendar.from_daily_prices(d[d["code"] != "C0003"]).days)
    assert n_all == n_without_c
