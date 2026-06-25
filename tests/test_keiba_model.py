"""keiba M2/M4: モデル・較正・ブレンドのテスト。"""

import numpy as np
import pytest

from keiba.blend import (
    benter_blend,
    fit_blend_weight,
    harville_top3_prob,
    harville_trifecta,
    market_implied_prob,
)
from keiba.calibration import (
    Calibrator,
    brier_score,
    expected_calibration_error,
    log_loss,
    race_normalize,
)
from keiba.features import build_features
from keiba.model import KeibaModel, ModelConfig
from keiba.synth import SyntheticConfig, generate_dataset

FAST = ModelConfig(num_boost_round=120, min_data_in_leaf=40)


@pytest.fixture(scope="module")
def split():
    runners, _ = generate_dataset(SyntheticConfig(n_days=220, seed=5))
    feat = build_features(runners)
    tr = feat[feat.race_date < 150]
    va = feat[(feat.race_date >= 150) & (feat.race_date < 185)]
    te = feat[feat.race_date >= 185]
    return tr, va, te


def _race_sums_to_one(df, probs):
    s = np.asarray(probs)
    totals = df.assign(p=s).groupby("race_id")["p"].sum().to_numpy()
    return np.allclose(totals, 1.0, atol=1e-6)


def test_binary_predict_normalized(split):
    tr, va, te = split
    m = KeibaModel(ModelConfig(objective="binary", **_fast_kwargs())).fit(tr, va)
    p = m.predict_proba(te)
    assert _race_sums_to_one(te, p)
    assert (p >= 0).all() and (p <= 1).all()


def test_lambdarank_predict_normalized(split):
    tr, va, te = split
    m = KeibaModel(ModelConfig(objective="lambdarank", **_fast_kwargs())).fit(tr, va)
    p = m.predict_proba(te)
    assert _race_sums_to_one(te, p)


def test_calibration_reduces_ece(split):
    tr, va, te = split
    m = KeibaModel(ModelConfig(objective="binary", **_fast_kwargs())).fit(tr, va)
    p_raw = m.predict_proba(te)
    pv = m.predict_proba(va)
    cal = Calibrator("isotonic").fit(pv, va.is_win.to_numpy())
    p_cal = race_normalize(te, cal.transform(p_raw))
    y = te.is_win.to_numpy()
    # 較正後 ECE は十分小さい
    assert expected_calibration_error(p_cal, y) < 0.03


def test_metrics_sane():
    y = np.array([1, 0, 1, 0, 1.0])
    perfect = np.array([1, 0, 1, 0, 1.0]) * 0.999 + 0.0005
    bad = np.array([0, 1, 0, 1, 0.0]) * 0.999 + 0.0005
    assert brier_score(perfect, y) < brier_score(bad, y)
    assert log_loss(perfect, y) < log_loss(bad, y)


def test_blend_sums_to_one_and_weight_in_range(split):
    tr, va, te = split
    m = KeibaModel(ModelConfig(objective="binary", **_fast_kwargs())).fit(tr, va)
    pv = race_normalize(va, m.predict_proba(va))
    qv = market_implied_prob(va, "intermediate_odds")
    w, ll = fit_blend_weight(va, pv, qv, va.is_win.to_numpy())
    assert 0.0 <= w <= 1.0
    blended = benter_blend(te, race_normalize(te, m.predict_proba(te)),
                           market_implied_prob(te, "intermediate_odds"), w)
    assert _race_sums_to_one(te, blended)


def test_market_implied_prob_normalized(split):
    _, _, te = split
    q = market_implied_prob(te, "final_odds")
    assert _race_sums_to_one(te, q)


def test_harville_probabilities_valid():
    wp = np.array([0.4, 0.3, 0.2, 0.1])
    # 三連単の全順列確率は1に近い(同着なしのHarville)
    total = 0.0
    n = len(wp)
    for i in range(n):
        for j in range(n):
            for k in range(n):
                if len({i, j, k}) == 3:
                    total += harville_trifecta(wp, i, j, k)
    assert abs(total - 1.0) < 1e-6
    # 各馬の3着内確率は[0,1]
    for i in range(n):
        p3 = harville_top3_prob(wp, i)
        assert 0.0 <= p3 <= 1.0 + 1e-9


def _fast_kwargs():
    return dict(num_boost_round=120, min_data_in_leaf=40)
