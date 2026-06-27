"""keiba: C1 エッジ探索(条件別 回収率 輪切り)のテスト。"""

import numpy as np
import pandas as pd

from keiba.segments import (
    drift_segments,
    favorite_longshot,
    overlay_by_band,
    segment_report,
    validate_oos,
)


def _preds(n_races=200, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for rid in range(n_races):
        k = 8
        odds = rng.uniform(1.5, 60.0, k)
        win_idx = rng.integers(0, k)
        for i in range(k):
            rows.append({
                "race_id": rid, "race_date": rid, "is_win": float(i == win_idx),
                "p_model": 1.0 / k, "p_market": 1.0 / odds[i],
                "p_blend": 1.0 / k, "final_odds": float(odds[i]),
            })
    return pd.DataFrame(rows)


def test_roi_math_exact():
    # 2点: 1点的中(オッズ4.0)・1点外れ → ROI = (1*4 + 0)/2 = 2.0(200%)
    df = pd.DataFrame({"race_id": [0, 0], "is_win": [1.0, 0.0],
                       "final_odds": [4.0, 4.5], "p_blend": [0.5, 0.5]})
    rows = favorite_longshot(df)
    band = next(r for r in rows if r["seg"] == "3-5倍")
    assert band["n"] == 2 and abs(band["roi"] - 2.0) < 1e-9
    assert abs(band["hit"] - 0.5) < 1e-9


def test_bands_partition_all_rows():
    p = _preds()
    total = sum(r["n"] for r in favorite_longshot(p))
    assert total == len(p)            # 全行がいずれかの帯に入る(漏れなし)


def test_overlay_subset_of_all():
    p = _preds()
    ov = sum(r["n"] for r in overlay_by_band(p, ev_threshold=1.0))
    alln = sum(r["n"] for r in favorite_longshot(p))
    assert ov <= alln                 # 妙味馬は全体の部分集合


def test_segment_report_renders():
    rep = segment_report(_preds(), ev_threshold=1.0, min_n=50)
    assert "エッジ探索" in rep
    assert "人気帯別" in rep and "回収率" in rep


def test_segment_report_empty():
    assert "空" in segment_report(pd.DataFrame())


def test_drift_segments_none_without_data():
    p = _preds()                       # odds_drift 列なし
    assert drift_segments(p) is None


def test_drift_segments_buckets():
    p = _preds()
    p["odds_drift"] = np.where(p["final_odds"] < 10, 0.5, -0.5)   # 人気化/不人気化
    rows = drift_segments(p)
    assert rows is not None
    labels = {r["seg"] for r in rows}
    assert any("人気化" in s for s in labels)
    assert sum(r["n"] for r in rows) <= len(p)


def test_validate_oos_renders_and_splits():
    p = _preds(n_races=400)
    rep = validate_oos(p, ev_threshold=1.0, min_n=20)
    assert "Out-of-Sample" in rep and "発見ROI" in rep
    assert "発見期" in rep and "検証期" in rep
