"""検品レポート。異常を見逃さないことを固定する。"""

from datetime import date

import pandas as pd
import pytest

from erb import verify as verify_mod


def _daily(codes, days, mkt_cap=5e10, last_day_by_code=None):
    rows = []
    for c in codes:
        stop = (last_day_by_code or {}).get(c)
        for d in days:
            if stop is not None and d > stop:
                continue
            rows.append({"code": c, "date": d, "open": 1000.0, "close": 1005.0,
                         "adj_open": 1000.0, "adj_close": 1005.0,
                         "volume": 1000.0, "turnover": 1e8, "mkt_cap": mkt_cap})
    return pd.DataFrame(rows)


def test_flags_market_cap_left_in_millions():
    """円に直し忘れた時価総額を「おかしい」と言うこと。

    百万円のまま（例 54050）だと 5.4万円になり、
    時価総額フィルタが全銘柄を通してしまう。
    """
    days = [date(2024, 1, 4), date(2024, 1, 5)]
    text = "\n".join(verify_mod._section_daily(
        _daily(["10000"], days, mkt_cap=54050.0), _Cal(days)))
    assert "おかしい" in text


def test_accepts_market_cap_in_yen():
    days = [date(2024, 1, 4)]
    text = "\n".join(verify_mod._section_daily(
        _daily(["10000"], days, mkt_cap=54_050_000_000.0), _Cal(days)))
    assert "妥当" in text


def test_reports_missing_business_days():
    days = [date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 9)]
    daily = _daily(["10000"], days[:2])          # 1/9 が欠けている
    text = "\n".join(verify_mod._section_daily(daily, _Cal(days)))
    assert "日足が無い営業日: 1日" in text
    assert "2024-01-09" in text


def test_survivorship_warns_when_every_issue_survives():
    """全銘柄が最終日まで残っているのは、上場廃止が落ちている兆候。"""
    days = [date(2024, 1, 4), date(2024, 1, 5)]
    text = "\n".join(verify_mod._section_survivorship(_daily(["10000", "10010"], days)))
    assert "0 / 2" in text
    assert "7518 が見つかりません" in text


def test_survivorship_recognises_the_delisted_probe_code():
    days = [date(2025, 3, 14), date(2025, 3, 17), date(2025, 3, 18)]
    daily = _daily(["75180", "10000"], days,
                   last_day_by_code={"75180": date(2025, 3, 17)})
    text = "\n".join(verify_mod._section_survivorship(daily))
    assert "回避できている" in text
    assert "2025-03-17" in text


def test_missing_topix_is_called_out():
    text = "\n".join(verify_mod._section_topix(None, _Cal([date(2024, 1, 4)])))
    assert "超過リターンで判定できません" in text


def test_excluded_codes_are_reported_when_present():
    days = [date(2024, 1, 4)]
    text = "\n".join(verify_mod._section_survivorship(_daily(["80530", "10000"], days)))
    assert "80530" in text


class _Cal:
    def __init__(self, days):
        self.days = list(days)
