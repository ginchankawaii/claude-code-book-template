"""JRA 由来の特徴量(jra_bonus)と取り込みアダプタ(load_jra_csv)のテスト。"""

import math

import pytest

from horse_racing.jra import load_jra_csv
from horse_racing.model import Horse, jra_bonus, predict_race, score_horse


def test_jra_bonus_zero_when_no_data():
    # 追加特徴を一切与えなければ補正は 0 (= 既存挙動を壊さない)
    assert jra_bonus(Horse("plain")) == 0.0


def test_time_index_helps():
    base = Horse("a", speed=100)
    strong = Horse("a", speed=100, time_index=90)
    weak = Horse("a", speed=100, time_index=40)
    assert score_horse(strong) > score_horse(base) > score_horse(weak)


def test_large_weight_swing_penalized():
    steady = Horse("a", weight_diff=2)
    blown = Horse("a", weight_diff=30)
    assert jra_bonus(blown) < jra_bonus(steady) == 0.0


def test_inner_draw_slight_edge():
    inner = Horse("a", post_position=1, field_size=18)
    outer = Horse("a", post_position=18, field_size=18)
    assert jra_bonus(inner) > jra_bonus(outer)


def test_distance_aptitude_peaks_at_match():
    matched = Horse("a", distance=2000, best_distance=2000)
    mismatched = Horse("a", distance=2000, best_distance=1200)
    assert jra_bonus(matched) > jra_bonus(mismatched)


def test_class_up_discount():
    assert jra_bonus(Horse("a", class_up=True)) < 0


def test_rotation_extremes_penalized():
    ideal = Horse("a", days_since_last=35)
    too_short = Horse("a", days_since_last=7)
    too_long = Horse("a", days_since_last=300)
    assert jra_bonus(ideal) == 0.0
    assert jra_bonus(too_short) < 0
    assert jra_bonus(too_long) < 0


def test_neutral_jra_data_preserves_probabilities():
    # 全馬に同じ(中立でない)JRA値を与えても、定数シフトは softmax 不変
    plain = [Horse(f"h{i}", speed=80 + i * 5) for i in range(5)]
    enriched = [Horse(f"h{i}", speed=80 + i * 5, time_index=70) for i in range(5)]
    p1 = [p.win_probability for p in predict_race(plain)]
    p2 = [p.win_probability for p in predict_race(enriched)]
    for a, b in zip(p1, p2):
        assert math.isclose(a, b, rel_tol=1e-9)


def test_load_jra_csv_japanese_headers(tmp_path):
    csv_text = (
        "馬番,馬名,斤量,単勝,タイム指数,増減,距離,得意距離,間隔,昇級初戦\n"
        "1,アルファ,57,3.2,82,+2,2000,2000,28,0\n"
        "2,ベータ,55,8.0,60,480(-4),2000,1600,14,1\n"
    )
    p = tmp_path / "race.csv"
    p.write_text(csv_text, encoding="utf-8")
    horses = load_jra_csv(p)
    assert len(horses) == 2
    a = horses[0]
    assert a.name == "アルファ"
    assert a.post_position == 1
    assert a.time_index == 82
    assert a.weight_diff == 2
    assert a.distance == 2000
    # 頭数列が無いので馬番最大値で補完される
    assert a.field_size == 2
    b = horses[1]
    assert b.class_up is True
    assert b.weight_diff == -4  # "480(-4)" のカッコ内を採用


def test_load_jra_csv_requires_name(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("馬番,斤量\n1,57\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_jra_csv(p)


def test_load_jra_csv_with_bom(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_text("﻿馬名,タイム指数\nガンマ,75\n", encoding="utf-8")
    horses = load_jra_csv(p)
    assert horses[0].name == "ガンマ"
    assert horses[0].time_index == 75
