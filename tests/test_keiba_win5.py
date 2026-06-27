"""keiba: WIN5 買い目最適化のテスト。"""

from keiba import win5


def test_single_point_all_one():
    legs = [[0.5, 0.3, 0.2]] * 5
    r = win5.optimize(legs, max_points=1)
    assert r["points"] == 1
    assert r["counts"] == [1, 1, 1, 1, 1]
    # 全部本命1頭 → 的中確率 = Π(各本命勝率) = 0.5^5
    assert abs(r["hit_prob"] - 0.5 ** 5) < 1e-9


def test_singles_dominant_spreads_flat():
    dominant = [0.8, 0.1, 0.05, 0.05]      # 1頭堅い
    flat = [0.25, 0.25, 0.25, 0.25]        # 混戦
    legs = [dominant, flat, flat, flat, flat]
    r = win5.optimize(legs, max_points=16)
    assert r["points"] <= 16
    # 堅いレースは1頭固定、混戦レースは手広く
    assert r["counts"][0] == 1
    assert all(r["counts"][j] >= 2 for j in range(1, 5))
    # 予算を使うほど的中確率は上がる
    base = win5.optimize(legs, max_points=1)["hit_prob"]
    assert r["hit_prob"] > base


def test_budget_respected_and_fair_odds():
    legs = [[0.4, 0.3, 0.2, 0.1]] * 5
    r = win5.optimize(legs, max_points=72)
    assert r["points"] <= 72
    assert r["cost_yen"] == r["points"] * 100
    # フェア配当 = (1-0.30)/的中確率 > 1
    assert r["fair_odds"] > 1.0
    assert abs(r["fair_odds"] - 0.7 / r["hit_prob"]) < 1e-6


def test_plans_increasing_coverage():
    legs = [[0.45, 0.25, 0.18, 0.12]] * 5
    ps = win5.plans(legs, budgets=(1, 32, 243))
    # 予算が増えるほど点数・的中確率は単調増加(以上)
    assert ps[0]["points"] <= ps[1]["points"] <= ps[2]["points"]
    assert ps[0]["hit_prob"] <= ps[1]["hit_prob"] <= ps[2]["hit_prob"]
