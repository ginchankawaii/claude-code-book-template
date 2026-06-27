"""keiba: 連系券種(Harville 展開)のテスト。"""

from itertools import combinations

import numpy as np
import pandas as pd
import pytest

from keiba.exotic import (
    ExoticConfig,
    sanrenpuku_prob,
    select_exotic_bets,
    summarize_exotic,
    umaren_prob,
    wide_prob,
)


def test_umaren_pairs_sum_to_one():
    p = np.array([0.4, 0.3, 0.2, 0.1])
    s = sum(umaren_prob(p, i, j) for i, j in combinations(range(4), 2))
    assert abs(s - 1.0) < 1e-9


def test_sanrenpuku_triples_sum_to_one():
    p = np.array([0.35, 0.25, 0.2, 0.12, 0.08])
    s = sum(sanrenpuku_prob(p, i, j, k) for i, j, k in combinations(range(5), 3))
    assert abs(s - 1.0) < 1e-9


def test_wide_at_least_umaren_and_bounded():
    p = np.array([0.4, 0.3, 0.2, 0.1])
    pool = [0, 1, 2, 3]
    for i, j in combinations(range(4), 2):
        w = wide_prob(p, i, j, pool)
        assert umaren_prob(p, i, j) - 1e-12 <= w <= 1.0 + 1e-9


def _toy_race():
    n = 8
    return pd.DataFrame({
        "race_id": [1] * n,
        "race_date": [10] * n,
        "post_position": list(range(1, n + 1)),
        "finish_pos": [1, 2, 3, 4, 5, 6, 7, 8],
    })


def test_select_exotic_bets_settles_correctly():
    race = _toy_race()
    n = len(race)
    # モデルが本命に強い確率、市場はフラットに近い → エッジが出る
    model_p = np.array([0.5, 0.2, 0.12, 0.06, 0.05, 0.03, 0.02, 0.02])
    market_p = np.full(n, 1.0 / n)
    bets = select_exotic_bets(race, model_p, market_p, ExoticConfig(ev_threshold=1.0, edge_ratio=1.0))
    assert len(bets) > 0
    # is_win は実着順に整合(馬連は1-2着, 三連複は1-3着, ワイドは双方3着内)
    top2 = {0, 1}
    top3 = {0, 1, 2}
    # 1着2着(index0,1)の馬連は当たり
    um = bets[(bets.bet_type == "umaren")]
    # combo は post_position("1-2"等)。少なくとも1つは的中があるはず(本命決着)
    assert um["is_win"].sum() >= 1
    summ = summarize_exotic(bets)
    for bt in summ:
        assert summ[bt]["roi"] >= 0


def test_select_exotic_empty_for_small_field():
    race = _toy_race().head(2)
    bets = select_exotic_bets(race, np.array([0.6, 0.4]), np.array([0.5, 0.5]))
    assert len(bets) == 0


def test_real_odds_override_synthetic():
    # C3: 実オッズを与えると、その組は合成でなく実オッズで決済(odds_source=real)
    race = _toy_race()
    n = len(race)
    model_p = np.array([0.5, 0.2, 0.12, 0.06, 0.05, 0.03, 0.02, 0.02])
    market_p = np.full(n, 1.0 / n)
    # 1-2番の馬連に高い実オッズ(50倍)を与える
    real = {"馬連": {(1, 2): 50.0}}
    bets = select_exotic_bets(race, model_p, market_p,
                              ExoticConfig(ev_threshold=1.0, edge_ratio=1.0, max_odds=999),
                              real_odds=real)
    um12 = bets[(bets.bet_type == "umaren") & (bets.combo == "1-2")]
    assert len(um12) == 1
    assert um12.iloc[0]["odds_source"] == "real"
    assert abs(um12.iloc[0]["final_odds"] - 50.0) < 1e-9   # 実オッズで決済
    # 実オッズ割合が summarize に出る
    summ = summarize_exotic(bets)
    assert summ["umaren"]["real_frac"] > 0
    # C3: 実オッズのみの別建て集計(合成の希釈を除いた本物の指標)
    assert summ["umaren"]["real_n"] >= 1
    assert summ["umaren"]["real_n"] <= summ["umaren"]["n_bets"]
    # 1-2が的中(本命決着)かつ 50倍なので、実オッズのみ ROI は正
    assert summ["umaren"]["real_roi"] > 0
    # ブートストラップCIと的中本数も付く
    assert summ["umaren"]["real_wins"] >= 1
    assert "real_roi_lo" in summ["umaren"] and "real_roi_hi" in summ["umaren"]
    assert summ["umaren"]["real_roi_lo"] <= summ["umaren"]["real_roi_hi"]
