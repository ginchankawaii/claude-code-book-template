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
    assert set(by) == {"executable", "limit_up_flagged"}
    assert by["executable"]["trades"] + by["limit_up_flagged"]["trades"] == 4
    assert by["limit_up_flagged"]["trades"] == 1
    assert by["limit_up_flagged"]["excess_topix_pct"] == pytest.approx(5.0)
    assert by["executable"]["excess_sum_share_pct"] + by["limit_up_flagged"]["excess_sum_share_pct"] == pytest.approx(100.0, abs=0.2)


def test_breakdown_splits_flagged_days_into_locked_and_touched():
    # UL=1 でも引けが高値より下なら「触れただけ」。引けで張り付いた日と分ける
    df = _trades([
        {"entry_limit_up": False, "entry_limit_down": False, "loanable": True,
         "entry_limit_up_locked": False, "entry_limit_down_locked": False, "excess_return": 0.001},
        {"entry_limit_up": True, "entry_limit_down": False, "loanable": True,
         "entry_limit_up_locked": True, "entry_limit_down_locked": False, "excess_return": 0.060},
        {"entry_limit_up": True, "entry_limit_down": False, "loanable": True,
         "entry_limit_up_locked": False, "entry_limit_down_locked": False, "excess_return": -0.010},
        {"entry_limit_up": False, "entry_limit_down": True, "loanable": True,
         "entry_limit_up_locked": False, "entry_limit_down_locked": True, "excess_return": 0.030},
        {"entry_limit_up": False, "entry_limit_down": True, "loanable": False,
         "entry_limit_up_locked": False, "entry_limit_down_locked": False, "excess_return": 0.005},
    ])
    long_by = {r["reason"]: r for r in nonexecutable_breakdown(df, SIDE_LONG, True)}
    assert set(long_by) == {"executable", "limit_up_locked_at_close", "limit_up_touched_not_locked"}
    assert long_by["limit_up_locked_at_close"]["trades"] == 1
    assert long_by["limit_up_touched_not_locked"]["trades"] == 1
    assert long_by["limit_up_touched_not_locked"]["excess_topix_pct"] == pytest.approx(-1.0)
    assert sum(r["trades"] for r in long_by.values()) == 5

    short_by = {r["reason"]: r for r in nonexecutable_breakdown(df, SIDE_SHORT, True)}
    assert set(short_by) == {"executable", "limit_down_locked_at_close",
                             "limit_down_touched_not_locked", "not_loanable_only"}
    assert short_by["limit_down_locked_at_close"]["trades"] == 1
    assert short_by["limit_down_touched_not_locked"]["trades"] == 1   # 貸借外でもストップ安側に数える
    assert short_by["not_loanable_only"]["trades"] == 0
    assert short_by["executable"]["trades"] == 3


def test_breakdown_short_three_way_partition(mixed):
    rows = nonexecutable_breakdown(mixed, SIDE_SHORT, True)
    by = {r["reason"]: r for r in rows}
    assert set(by) == {"executable", "limit_down_flagged", "not_loanable_only"}
    assert sum(r["trades"] for r in rows) == 4
    assert by["limit_down_flagged"]["trades"] == 1
    assert by["not_loanable_only"]["trades"] == 1
    assert by["executable"]["trades"] == 2
    assert by["not_loanable_only"]["excess_topix_pct"] == pytest.approx(2.0)


def test_breakdown_empty_is_empty():
    assert nonexecutable_breakdown(pd.DataFrame(), SIDE_LONG, True) == []
