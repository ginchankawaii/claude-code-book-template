"""keiba M0/M1: 合成データと PiT 特徴量・リーク監査のテスト。"""

import numpy as np
import pytest

from keiba import schema
from keiba.features import FEATURE_COLUMNS, build_features
import keiba.leakage as L
from keiba.leakage import (
    assert_no_post_race_features,
    audit_outcome_independence,
    audit_temporal_invariance,
)
from keiba.synth import SyntheticConfig, generate_dataset


@pytest.fixture(scope="module")
def small_data():
    return generate_dataset(SyntheticConfig(n_days=120, seed=3))


def test_one_winner_per_race(small_data):
    runners, _ = small_data
    w = runners.groupby("race_id")["is_win"].sum()
    assert (w == 1).all()


def test_market_overround_matches_takeout(small_data):
    runners, _ = small_data
    inv = (1.0 / runners["final_odds"]).groupby(runners["race_id"]).sum()
    # sum(1/odds) ≈ 1/(1-takeout) = 1/0.8 = 1.25
    assert abs(inv.mean() - 1.25) < 0.03


def test_reproducible_seed():
    a, _ = generate_dataset(SyntheticConfig(n_days=40, seed=1))
    b, _ = generate_dataset(SyntheticConfig(n_days=40, seed=1))
    assert a.equals(b)
    c, _ = generate_dataset(SyntheticConfig(n_days=40, seed=2))
    assert not a.equals(c)


def test_no_post_race_features_static():
    assert_no_post_race_features()
    assert set(FEATURE_COLUMNS) & schema.post_race_columns() == set()


def test_feature_builder_keeps_keys_and_labels(small_data):
    runners, _ = small_data
    feat = build_features(runners)
    for col in ["race_id", "race_date", "is_win", "is_top3", "final_odds", "intermediate_odds"]:
        assert col in feat.columns
    for col in FEATURE_COLUMNS:
        assert col in feat.columns


def test_temporal_invariance_no_leakage(small_data):
    runners, _ = small_data
    audit = audit_temporal_invariance(runners, n_sample_races=15, seed=0)
    assert audit["ok"], f"PiTリーク検出: {audit['mismatches']}"


def test_outcome_independence_no_leakage(small_data):
    """当該レース自身の確定後情報に特徴量が依存していないこと。"""
    runners, _ = small_data
    audit = audit_outcome_independence(runners, n_sample_races=15, seed=0)
    assert audit["ok"], f"自レース結果リーク検出: {audit['mismatches']}"


def test_outcome_independence_catches_injected_own_race_leak(small_data):
    """自レースの着順を特徴量に混入させたら、結果独立性監査が検出すること
    (時間不変性監査では捉えられない種類のリークを補完する)。"""
    runners, _ = small_data
    orig = L.build_features

    def leaky(r, config=None):
        df = orig(r, config).copy()
        base = r.sort_values(["race_date", "race_id"]).reset_index(drop=True)
        df["h_avg_relfinish"] = (base["field_size"] - base["finish_pos"]).to_numpy()
        return df

    L.build_features = leaky
    try:
        ti = audit_temporal_invariance(runners, n_sample_races=12, seed=1)
        oi = audit_outcome_independence(runners, n_sample_races=12, seed=1)
    finally:
        L.build_features = orig
    assert ti["ok"]          # 時間不変性は自レースリークを捉えられない(既知の限界)
    assert not oi["ok"]      # 結果独立性が捉える


def test_pit_aggregates_use_only_past(small_data):
    """馬の通算出走数(h_starts)は、その馬の過去出走数と一致するはず。"""
    runners, _ = small_data
    feat = build_features(runners)
    merged = feat[["race_id", "race_date", "h_starts"]].copy()
    merged["horse_id"] = runners.sort_values(["race_date", "race_id"]).reset_index(drop=True)["horse_id"]
    # 各馬の最初の出走では h_starts==0
    first_rows = merged.sort_values("race_date").groupby("horse_id").head(1)
    assert (first_rows["h_starts"] == 0).all()
