"""合成データ。実データは一切使わない。

境界条件を固定するために、必要最小限の銘柄と日付だけを持つ。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from erb.calendar import CloseTimeSchedule, TradingCalendar


def business_days(start: date, n: int) -> list[date]:
    """土日を除いた n 営業日。祝日は考慮しない（テスト用）。"""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture
def days() -> list[date]:
    return business_days(date(2024, 10, 21), 40)


@pytest.fixture
def calendar(days) -> TradingCalendar:
    return TradingCalendar(days)


@pytest.fixture
def close_schedule() -> CloseTimeSchedule:
    return CloseTimeSchedule([
        {"from": "2000-01-01", "close": "15:00"},
        {"from": "2024-11-05", "close": "15:30"},
    ])


@pytest.fixture
def daily(days) -> pd.DataFrame:
    """3銘柄。

    A0001: 普通に上昇。株価 1000 円。
    B0002: 値がさ株（株価 8000 円）。単元100株=80万で、建玉50万に収まらない。
    C0003: 途中で上場廃止（最後の5営業日はデータが無い）。
    """
    rows = []
    for i, d in enumerate(days):
        rows.append({"Date": d, "Code": "A0001", "O": 1000 + i, "H": 1010 + i, "L": 990 + i,
                     "C": 1005 + i, "Vo": 100000, "Va": 100_000_000, "UL": "0", "LL": "0",
                     "AdjFactor": 1.0, "AdjO": 1000 + i, "AdjH": 1010 + i, "AdjL": 990 + i,
                     "AdjC": 1005 + i, "AdjVo": 100000, "MktCap": 20_000_000_000})
        rows.append({"Date": d, "Code": "B0002", "O": 8000, "H": 8050, "L": 7950,
                     "C": 8000, "Vo": 50000, "Va": 400_000_000, "UL": "0", "LL": "0",
                     "AdjFactor": 1.0, "AdjO": 8000, "AdjH": 8050, "AdjL": 7950,
                     "AdjC": 8000, "AdjVo": 50000, "MktCap": 600_000_000_000})
        if i < len(days) - 5:
            rows.append({"Date": d, "Code": "C0003", "O": 500, "H": 505, "L": 495,
                         "C": 500, "Vo": 20000, "Va": 10_000_000, "UL": "0", "LL": "0",
                         "AdjFactor": 1.0, "AdjO": 500, "AdjH": 505, "AdjL": 495,
                         "AdjC": 500, "AdjVo": 20000, "MktCap": 10_000_000_000})
    return pd.DataFrame(rows)


@pytest.fixture
def topix(days) -> pd.DataFrame:
    return pd.DataFrame([
        {"Date": d, "O": 2000 + i * 0.5, "C": 2000 + i * 0.5} for i, d in enumerate(days)
    ])
