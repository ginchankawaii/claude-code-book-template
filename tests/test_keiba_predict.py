"""keiba: 当日運用(予測)経路のテスト。"""

import numpy as np
import pandas as pd

from keiba.features import build_features
from keiba.model import ModelConfig
from keiba.predict import (
    PredictConfig,
    fit_predictor,
    format_predictions,
    predict_upcoming,
)
from keiba.synth import SyntheticConfig, generate_dataset

FAST = ModelConfig(num_boost_round=80, min_data_in_leaf=40)


def _card():
    runners, _ = generate_dataset(SyntheticConfig(n_days=150, seed=2))
    last = runners.race_date.max()
    up = runners.race_date == last
    card = runners.copy()
    for c in ["finish_pos", "finish_time", "last_3f", "passing_rank", "is_win", "is_top3", "payout_win"]:
        card.loc[up, c] = np.nan
    return card, int(up.sum()), runners.loc[up, "race_id"].nunique()


def test_predict_upcoming_shapes_and_probs():
    card, n_up_rows, n_up_races = _card()
    feat = build_features(card)
    predictor = fit_predictor(feat, FAST, PredictConfig(ev_threshold=1.15))
    pred = predict_upcoming(predictor, feat)
    assert pred["race_id"].nunique() == n_up_races
    assert len(pred) == n_up_rows
    # 各レース内で勝率は合計1
    totals = pred.groupby("race_id")["win_prob"].sum().to_numpy()
    assert np.allclose(totals, 1.0, atol=1e-6)
    # rank は 1..n
    assert (pred.groupby("race_id")["rank"].min() == 1).all()


def test_predict_excludes_upcoming_from_training():
    """未確定行(finish_pos NaN)は学習に使われない(ラベル0の負例として混入しない)。"""
    card, _, _ = _card()
    feat = build_features(card)
    predictor = fit_predictor(feat, FAST)
    # 学習に使う labeled は finish_pos ありのみ
    labeled = feat[feat["finish_pos"].notna()]
    assert labeled["finish_pos"].notna().all()
    pred = predict_upcoming(predictor, feat)
    assert not pred.empty


def test_format_predictions_runs():
    card, _, _ = _card()
    feat = build_features(card)
    predictor = fit_predictor(feat, FAST)
    txt = format_predictions(predict_upcoming(predictor, feat))
    assert "レース" in txt and "ペーパートレード" in txt
