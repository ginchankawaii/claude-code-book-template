"""フィルタの境界条件。"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from erb import filters
from erb.metrics import classify_net_edge
from erb.simulate import apply_costs


def _t(**cols) -> pd.DataFrame:
    n = len(next(iter(cols.values())))
    base = {
        "status": ["ok"] * n,
        "revision_rate": [0.4] * n,
        "mkt_cap": [2e10] * n,
        "habitual": [False] * n,
        "habitual_window_complete": [True] * n,
        "after_close": [True] * n,
        "excluded_by_spec": [False] * n,
        "turnover_avg": [1e9] * n,
        "entry_date": [date(2024, 11, 12)] * n,
    }
    base.update(cols)
    return pd.DataFrame(base)


def test_threshold_boundary_survives_float_error():
    """分位点を丸めた閾値で、境界の値が浮動小数点誤差で落ちないこと。"""
    exact = 1540 / 1100 - 1          # = 0.39999999999999991
    t = _t(revision_rate=[exact, 0.5, 0.2])
    kept = filters.apply_revision(t, 0.4)
    assert len(kept) == 2


def test_negative_threshold_selects_downward_revisions():
    t = _t(revision_rate=[-0.35, -0.30, -0.25, 0.4])
    kept = filters.apply_revision(t, -0.30)
    assert len(kept) == 2


def test_none_threshold_keeps_everything():
    t = _t(revision_rate=[-0.9, 0.0, 0.4])
    assert len(filters.apply_revision(t, None)) == 3


def test_quantile_thresholds_are_deduplicated():
    """分布が離散的だと分位点が重複する。重複セルは情報を増やさない。"""
    t = _t(revision_rate=[0.4] * 50)
    assert filters.revision_quantile_thresholds(t) == [0.4]


def test_turnover_filter_requires_liquidity():
    """1本50万が平均売買代金の1%を超える銘柄は約定不能とみなす。"""
    t = _t(turnover_avg=[1e9, 4e7, np.nan])
    kept = filters.apply_turnover(t, True, 500_000, 0.01)
    # 必要な売買代金は 50万/0.01 = 5,000万。4,000万は不足。欠損も保守的に除外。
    assert len(kept) == 1


def test_turnover_filter_disabled_keeps_all():
    t = _t(turnover_avg=[1e9, 4e7, np.nan])
    assert len(filters.apply_turnover(t, False, 500_000, 0.01)) == 3


def test_exclusion_list_can_be_turned_off_for_comparison():
    """除外自体が軽度の先読みなので、除外なしの結果も出せること。"""
    t = _t(excluded_by_spec=[True, False, False])
    assert len(filters.apply_exclusion_list(t, True)) == 2
    assert len(filters.apply_exclusion_list(t, False)) == 3


def test_habitual_incomplete_window_can_be_dropped():
    t = _t(habitual=[False, False], habitual_window_complete=[True, False])
    assert len(filters.apply_habitual(t, True, require_complete_window=True)) == 1
    assert len(filters.apply_habitual(t, True, require_complete_window=False)) == 2


def test_timing_split_is_exhaustive():
    t = _t(after_close=[True, True, False])
    a = filters.apply_timing(t, "after_close")
    b = filters.apply_timing(t, "intraday")
    assert len(a) + len(b) == len(t)


def test_gross_edge_above_threshold_can_still_be_a_loss():
    """設計の核心。粗エッジ 0.52% は N=5・滑り0.4% では赤字になる。

    粗エッジ単独の閾値（0.5%）で採否を決めてはいけない、という回帰テスト。
    """
    trades = pd.DataFrame([
        {"gross_return": 0.0052, "topix_return": 0.0019, "holding_calendar_days": 7}
    ])
    priced = apply_costs(trades, 0.4, 2.80, 0, 500_000)
    net_edge_pct = float(priced["net_excess_return"].iloc[0] * 100)
    assert net_edge_pct < 0
    assert classify_net_edge(net_edge_pct, 0.05, 0.35) == "打ち切り"
