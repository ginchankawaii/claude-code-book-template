import math

import pytest

from horse_racing.model import Horse, predict_race, score_horse


def test_score_monotonic_in_speed():
    slow = Horse("slow", speed=80)
    fast = Horse("fast", speed=110)
    assert score_horse(fast) > score_horse(slow)


def test_lower_odds_scores_higher():
    fav = Horse("fav", odds=2.0)
    longshot = Horse("longshot", odds=50.0)
    assert score_horse(fav) > score_horse(longshot)


def test_lower_recent_form_is_better():
    good = Horse("good", recent_form=1.5)
    bad = Horse("bad", recent_form=9.0)
    assert score_horse(good) > score_horse(bad)


def test_predict_probabilities_sum_to_one():
    horses = [Horse(f"h{i}", speed=80 + i * 5) for i in range(6)]
    preds = predict_race(horses)
    total = sum(p.win_probability for p in preds)
    assert math.isclose(total, 1.0, rel_tol=1e-9)


def test_predict_ranks_are_sequential_and_sorted():
    horses = [
        Horse("a", speed=90, odds=10),
        Horse("b", speed=110, odds=3),
        Horse("c", speed=100, odds=5),
    ]
    preds = predict_race(horses)
    assert [p.rank for p in preds] == [1, 2, 3]
    # スコア降順であること
    scores = [p.score for p in preds]
    assert scores == sorted(scores, reverse=True)
    # 最有力は b
    assert preds[0].horse.name == "b"


def test_temperature_affects_concentration():
    horses = [Horse("strong", speed=115, odds=2), Horse("weak", speed=85, odds=40)]
    sharp = predict_race(horses, temperature=0.1)
    flat = predict_race(horses, temperature=2.0)
    top_sharp = max(p.win_probability for p in sharp)
    top_flat = max(p.win_probability for p in flat)
    assert top_sharp > top_flat


def test_empty_race_raises():
    with pytest.raises(ValueError):
        predict_race([])


def test_duplicate_names_raise():
    with pytest.raises(ValueError):
        predict_race([Horse("x"), Horse("x")])


def test_invalid_horse_attrs():
    with pytest.raises(ValueError):
        Horse("", speed=100)
    with pytest.raises(ValueError):
        Horse("ok", odds=0)
    with pytest.raises(ValueError):
        Horse("ok", weight=-1)


def test_temperature_must_be_positive():
    with pytest.raises(ValueError):
        predict_race([Horse("a")], temperature=0)
