"""統計。"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from erb.metrics import _required_n, classify_net_edge, split_halves, summarize


def _trades(returns, start=date(2024, 1, 2), step_days=7):
    rows = []
    d = start
    for r in returns:
        rows.append({"gross_return": r, "excess_return": r, "net_excess_return": r,
                     "entry_date": d, "exit_date": d + timedelta(days=5)})
        d += timedelta(days=step_days)
    return pd.DataFrame(rows)


def test_required_n_matches_design_numbers():
    # sigma=5%, 平均0.5% -> 400件
    assert _required_n(5.0, 0.5, 2.0) == 400
    # sigma=8%, 平均0.5% -> 1024件
    assert _required_n(8.0, 0.5, 2.0) == 1024
    # sigma=8%, 平均0.3% -> 2845件（切り上げ）
    assert _required_n(8.0, 0.3, 2.0) == pytest.approx(2845, abs=1)


def test_required_n_undefined_for_non_positive_mean():
    assert np.isnan(_required_n(5.0, -0.1, 2.0))


def test_insufficient_sample_is_flagged_unjudgeable():
    rng = np.random.default_rng(0)
    t = _trades(rng.normal(0.005, 0.05, 30))
    s = summarize(t, bootstrap_iterations=200)
    assert "判定不能" in s["verdict"]


def test_cluster_bootstrap_widens_ci_versus_naive():
    """同一週に固まったトレードは、クラスタ再抽出だと信頼区間が広くなる。"""
    rng = np.random.default_rng(1)
    rows = []
    # 20週 x 各週10件。週ごとに共通のショックを与える（決算集中期の相関を模す）
    for w in range(20):
        shock = rng.normal(0, 0.04)
        d = date(2024, 1, 1) + timedelta(days=7 * w)
        for _ in range(10):
            r = 0.005 + shock + rng.normal(0, 0.01)
            rows.append({"gross_return": r, "excess_return": r, "net_excess_return": r,
                         "entry_date": d, "exit_date": d + timedelta(days=5)})
    t = pd.DataFrame(rows)
    s = summarize(t, bootstrap_iterations=2000, cluster_by="week")
    width = s["cluster_ci_high_pct"] - s["cluster_ci_low_pct"]
    naive_se = t["net_excess_return"].std(ddof=1) / np.sqrt(len(t)) * 100
    assert width > 2 * 1.96 * naive_se


def test_split_halves_partitions_all_rows():
    t = _trades([0.01] * 20, start=date(2023, 1, 2), step_days=30)
    a, b = split_halves(t, date(2024, 4, 1))
    assert len(a) + len(b) == len(t)
    assert a["entry_date"].max() < date(2024, 4, 1)
    assert b["entry_date"].min() >= date(2024, 4, 1)


@pytest.mark.parametrize("edge,expected", [
    (0.0, "打ち切り"), (0.049, "打ち切り"),
    (0.05, "ペーパートレード3か月"), (0.34, "ペーパートレード3か月"),
    (0.35, "少額実弾"), (1.0, "少額実弾"),
])
def test_net_edge_classification(edge, expected):
    assert classify_net_edge(edge, 0.05, 0.35) == expected


def test_empty_cell_is_unjudgeable():
    s = summarize(pd.DataFrame(columns=["gross_return", "excess_return",
                                        "net_excess_return", "entry_date", "exit_date"]))
    assert s["trades"] == 0
    assert "判定不能" in s["verdict"]
