"""2晩目システム: 執行可能フィルタと、執行できない日の内訳。"""

import pandas as pd
import pytest

from erb.night2 import _executable, nonexecutable_breakdown
from erb.simulate import SIDE_LONG, SIDE_SHORT


def _trades(rows):
    df = pd.DataFrame(rows)
    df["net_excess_return"] = df["excess_return"] - 0.004
    return df


@pytest.fixture
def mixed():
    # 4件: 通常 / ストップ高 / ストップ安 / 貸借外
    return _trades([
        {"entry_limit_up": False, "entry_limit_down": False, "loanable": True, "excess_return": 0.001},
        {"entry_limit_up": True, "entry_limit_down": False, "loanable": True, "excess_return": 0.050},
        {"entry_limit_up": False, "entry_limit_down": True, "loanable": True, "excess_return": 0.030},
        {"entry_limit_up": False, "entry_limit_down": False, "loanable": False, "excess_return": 0.020},
    ])


def test_executable_long_drops_only_limit_up(mixed):
    out = _executable(mixed, SIDE_LONG, True)
    assert len(out) == 3
    assert not out["entry_limit_up"].any()


def test_executable_short_drops_limit_down_and_not_loanable(mixed):
    out = _executable(mixed, SIDE_SHORT, True)
    assert len(out) == 2
    assert not out["entry_limit_down"].any()
    assert out["loanable"].all()


def test_executable_short_keeps_not_loanable_when_not_required(mixed):
    out = _executable(mixed, SIDE_SHORT, False)
    assert len(out) == 3


def test_executable_handles_object_dtype_with_nulls():
    # object 型に None が混じっても、-1 のような壊れたインデックスにならない
    df = pd.DataFrame({"entry_limit_up": pd.Series([None, True, False], dtype=object),
                       "entry_limit_down": pd.Series([None, None, None], dtype=object),
                       "loanable": [True, True, True]})
    out = _executable(df, SIDE_LONG, True)
    assert list(out.index) == [0, 2]


def test_breakdown_long_partitions_and_shares_sum_to_100(mixed):
    rows = nonexecutable_breakdown(mixed, SIDE_LONG, True)
    by = {r["reason"]: r for r in rows}
    assert set(by) == {"executable", "limit_up_locked"}
    assert by["executable"]["trades"] + by["limit_up_locked"]["trades"] == 4
    assert by["limit_up_locked"]["trades"] == 1
    assert by["limit_up_locked"]["excess_topix_pct"] == pytest.approx(5.0)
    assert by["executable"]["excess_sum_share_pct"] + by["limit_up_locked"]["excess_sum_share_pct"] == pytest.approx(100.0, abs=0.2)


def test_breakdown_short_three_way_partition(mixed):
    rows = nonexecutable_breakdown(mixed, SIDE_SHORT, True)
    by = {r["reason"]: r for r in rows}
    assert set(by) == {"executable", "limit_down_locked", "not_loanable_only"}
    assert sum(r["trades"] for r in rows) == 4
    assert by["limit_down_locked"]["trades"] == 1
    assert by["not_loanable_only"]["trades"] == 1
    assert by["executable"]["trades"] == 2
    assert by["not_loanable_only"]["excess_topix_pct"] == pytest.approx(2.0)


def test_breakdown_empty_is_empty():
    assert nonexecutable_breakdown(pd.DataFrame(), SIDE_LONG, True) == []
