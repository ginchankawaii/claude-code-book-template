"""keiba M3: ベッティング・バックテストのテスト。

最重要: 「効率的市場では超過エッジが出ない(=リークしていない)」ことの
ガード。リークがあると効率的市場でも高ROIになってしまう。
"""

import numpy as np
import pandas as pd
import pytest

from keiba.backtest import WalkForwardConfig, walk_forward
from keiba.betting import (
    BettingConfig,
    kelly_fraction,
    monte_carlo_ruin,
    select_bets,
    settle_flat,
    settle_kelly,
)
from keiba.features import build_features
from keiba.model import ModelConfig
from keiba.synth import SyntheticConfig, generate_dataset

FAST_MODEL = ModelConfig(num_boost_round=120, min_data_in_leaf=40)
FAST_WF = WalkForwardConfig(train_min_days=110, valid_days=35, test_days=35)


def test_kelly_fraction_formula():
    # p=0.5, odds=3 -> f=(0.5*3-1)/(3-1)=0.25
    assert abs(kelly_fraction(np.array([0.5]), np.array([3.0]))[0] - 0.25) < 1e-9
    # 負期待値はベットしない=0
    assert kelly_fraction(np.array([0.1]), np.array([2.0]))[0] == 0.0


def test_settle_flat_math():
    bets = pd.DataFrame({"is_win": [1, 0, 1, 0], "final_odds": [3.0, 5.0, 2.0, 8.0]})
    r = settle_flat(bets)
    assert r["n_bets"] == 4
    assert abs(r["roi"] - (3.0 + 2.0) / 4) < 1e-9
    assert abs(r["hit_rate"] - 0.5) < 1e-9


def test_select_bets_respects_filters():
    df = pd.DataFrame({
        "race_id": [1, 1, 1],
        "race_date": [10, 10, 10],
        "intermediate_odds": [2.0, 50.0, 4.0],
        "final_odds": [2.0, 50.0, 4.0],
        "is_win": [1, 0, 0],
    })
    prob = np.array([0.6, 0.10, 0.30])
    mkt = np.array([0.5, 0.02, 0.30])
    cfg = BettingConfig(ev_threshold=1.05, edge_ratio=1.25, max_odds=20.0, min_model_prob=0.03)
    bets = select_bets(df, prob, "intermediate_odds", "final_odds", market_prob=mkt, config=cfg)
    # 馬2(odds50>max_odds)は除外。馬1はedge=1.2<1.25で除外。馬3はedge=1.0で除外。
    # → 全部除外されるはず(規律が効いている)
    assert len(bets) == 0
    # edge を緩めると馬1が入る
    cfg2 = BettingConfig(ev_threshold=1.05, edge_ratio=1.15, max_odds=20.0)
    bets2 = select_bets(df, prob, "intermediate_odds", "final_odds", market_prob=mkt, config=cfg2)
    assert (bets2["final_odds"] <= 20.0).all()


def test_monte_carlo_ruin_runs():
    bets = pd.DataFrame({
        "race_id": range(20), "race_date": range(20),
        "final_odds": [3.0] * 20, "is_win": [1, 0] * 10,
        "model_prob": [0.4] * 20, "stake_frac": [0.02] * 20,
    })
    r = monte_carlo_ruin(bets, n_sims=100, seed=1)
    assert 0.0 <= r["ruin_prob"] <= 1.0
    assert r["median_final"] > 0


def test_efficient_market_no_free_lunch():
    """効率的市場(myopia≈0)では、モデル由来の予測エッジは出ないはず。
    主判定は『ブレンドの log-loss が市場を有意に下回らない』(=フリーランチ無し)。
    複数シードで頑健に検証する(単一シードの閾値ピン留めを避ける)。リークがあると
    効率的市場でもブレンドが市場 log-loss を大きく下回り、ここで露見する。"""
    blend_minus_market = []
    blend_w = []
    for seed in (9, 21, 33):
        runners, _ = generate_dataset(SyntheticConfig(n_days=300, market_myopia=0.0,
                                                      market_noise=0.05, seed=seed))
        feat = build_features(runners)
        bt = walk_forward(feat, FAST_MODEL, BettingConfig(), FAST_WF)
        q = bt["quality"]
        blend_minus_market.append(q["blend_logloss"] - q["market_logloss"])
        blend_w.append(bt["avg_blend_w"])
    # ブレンドは市場 log-loss をほとんど下回らない(下回ったらリーク疑い)
    assert max(blend_minus_market) > -0.01, f"効率市場でブレンドが市場に勝ちすぎ(リーク疑い): {blend_minus_market}"
    # 平均ブレンド重みは市場側に寄る
    assert sum(blend_w) / len(blend_w) > 0.7, f"効率市場なのに市場重みが低い: {blend_w}"


def test_myopic_market_yields_capturable_edge():
    """近視眼的市場(myopia大)ではブレンドが市場を上回り、ブレンド重みが下がる。"""
    runners, _ = generate_dataset(SyntheticConfig(n_days=300, market_myopia=0.9,
                                                  w_form=0.7, seed=9))
    feat = build_features(runners)
    bt = walk_forward(feat, FAST_MODEL, BettingConfig(), FAST_WF)
    q = bt["quality"]
    assert q["blend_logloss"] < q["market_logloss"]   # ブレンドが市場に勝つ
    assert bt["avg_blend_w"] < 0.8                      # モデルへの依存が増す
