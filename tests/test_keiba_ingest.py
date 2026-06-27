"""keiba M5: JV-Data → スキーマ 取り込み(ingest)のテスト。"""

import numpy as np
import pandas as pd
import pytest

from keiba.features import build_features
from keiba.ingest import normalize, validate_runners


def _jv_frames():
    """小さな JV-Data 風 SE/RA/O1(2レース×3頭)。"""
    rows = []
    se = pd.DataFrame({
        "Year": ["2020"] * 6,
        "MonthDay": ["0105"] * 3 + ["0106"] * 3,
        "JyoCD": ["05"] * 6, "Kaiji": ["01"] * 6, "Nichiji": ["01"] * 6,
        "RaceNum": ["01"] * 3 + ["02"] * 3,
        "KettoNum": ["A", "B", "C", "A", "B", "C"],
        "Umaban": [1, 2, 3, 1, 2, 3],
        "KisyuCode": [10, 20, 30, 10, 20, 30],
        "ChokyosiCode": [1, 2, 3, 1, 2, 3],
        "Futan": [55.0, 55.5, 54.0, 55.0, 55.5, 54.0],   # jrvltsql は実数kg
        "BaTaijyu": [480, 500, 470, 482, 498, 472],
        "ZogenSa": [2, 4, 0, 2, 2, 2], "ZogenFugo": ["+", "-", "+", "+", "-", "+"],
        "KakuteiJyuni": [1, 2, 3, 3, 1, 2],
        "Time": [70.1, 70.4, 70.8, 71.0, 70.2, 70.5],
        "HaronTimeL3": [34.1, 34.4, 34.8, 35.0, 34.0, 34.3],
        "Jyuni3c": [1, 2, 3, 3, 1, 2], "Barei": [4, 5, 3, 4, 5, 3],
        "SexCD": [0, 1, 0, 0, 1, 0], "Ninki": [1, 2, 3, 2, 1, 3],
    })
    ra = pd.DataFrame({
        "Year": ["2020", "2020"], "MonthDay": ["0105", "0106"],
        "JyoCD": ["05", "05"], "Kaiji": ["01", "01"], "Nichiji": ["01", "01"],
        "RaceNum": ["01", "02"], "Kyori": [1600, 2000],
        "TrackCD": [11, 23], "SibaBabaCD": [1, 2], "DirtBabaCD": [2, 3],
        "GradeCD": [2, 3], "SyussoTosu": [3, 3],
    })
    o1 = pd.DataFrame({
        "Year": ["2020"] * 6, "MonthDay": ["0105"] * 3 + ["0106"] * 3,
        "JyoCD": ["05"] * 6, "Kaiji": ["01"] * 6, "Nichiji": ["01"] * 6,
        "RaceNum": ["01"] * 3 + ["02"] * 3, "Umaban": [1, 2, 3, 1, 2, 3],
        "TanOdds": [2.1, 3.5, 8.0, 4.0, 1.8, 6.0],   # jrvltsql は実数倍率
        "TanNinki": [1, 2, 3, 2, 1, 3],
    })
    return se, ra, o1


def test_normalize_derived_fields():
    se, ra, o1 = _jv_frames()
    runners, races = normalize(se, ra, o1)
    assert len(runners) == 6 and len(races) == 2
    r0 = runners.sort_values(["race_id", "post_position"]).reset_index(drop=True)
    # 斤量スケール 550→55.0
    assert abs(r0.loc[0, "carried_weight"] - 55.0) < 1e-9
    # オッズスケール 21→2.1
    assert abs(r0.loc[0, "final_odds"] - 2.1) < 1e-9
    # 着順→is_win/is_top3
    assert r0.loc[0, "is_win"] == 1.0 and r0.loc[2, "is_win"] == 0.0
    # 増減符号
    assert r0.loc[1, "weight_diff"] == -4
    # surface: race1=芝(0), race2=ダ(1)
    surf = runners.groupby("race_id")["surface"].first().to_numpy()
    assert set(surf) == {0.0, 1.0}


def test_one_winner_per_race():
    se, ra, o1 = _jv_frames()
    runners, _ = normalize(se, ra, o1)
    w = runners[runners.is_win == 1].groupby("race_id").size()
    assert (w == 1).all()


def test_validate_clean():
    se, ra, o1 = _jv_frames()
    runners, _ = normalize(se, ra, o1)
    assert validate_runners(runners) == []


def test_validate_catches_duplicate_winner():
    se, ra, o1 = _jv_frames()
    runners, _ = normalize(se, ra, o1)
    # race_id 衝突を模擬: 1レース内で着順表が丸ごと2重化(1着も2着も重複)。
    rid = runners["race_id"].iloc[0]
    g = runners[runners["race_id"] == rid].head(2).copy()
    g["finish_pos"] = [1.0, 2.0]
    runners = pd.concat([runners, g], ignore_index=True)
    base = runners[runners["race_id"] == rid]
    runners.loc[base.index[:2], "finish_pos"] = [1.0, 2.0]
    issues = validate_runners(runners)
    assert any("1着が複数" in s for s in issues)


def test_validate_allows_dead_heat():
    se, ra, o1 = _jv_frames()
    runners, _ = normalize(se, ra, o1)
    # 正規の同着: 1着が2頭(1着以外は重複しない) → 警告しない。
    rid = runners["race_id"].iloc[0]
    idx = runners[runners["race_id"] == rid].index[:2]
    runners.loc[idx, "finish_pos"] = 1.0
    issues = validate_runners(runners)
    assert not any("1着が複数" in s for s in issues)


def test_o1_multiple_snapshots_no_fanout():
    # NL_O1 が同一(レース,馬番)に複数スナップショットを持っても runners は増殖しない
    se, ra, o1 = _jv_frames()
    o1_mid = o1.copy()
    o1_mid["TanOdds"] = o1_mid["TanOdds"] * 1.5      # 中間オッズ(別スナップショット)
    o1_dup = pd.concat([o1_mid, o1], ignore_index=True)  # 中間+確定の2スナップショット
    runners, _ = normalize(se, ra, o1_dup)
    assert len(runners) == 6                          # 増殖していない(各馬1行)
    # 着順表の重複(誤検知)も起きない
    assert not any("1着が複数" in s for s in validate_runners(runners))
    # final_odds は確定(最後)の値が採用される
    r = runners.sort_values(["race_id", "post_position"]).reset_index(drop=True)
    assert abs(r.loc[0, "final_odds"] - 2.1) < 1e-9


def test_validate_catches_odds_scale():
    se, ra, o1 = _jv_frames()
    runners, _ = normalize(se, ra, o1)
    runners["final_odds"] = runners["final_odds"] / 100.0  # わざと <1 に
    issues = validate_runners(runners)
    assert any("odds_scale" in s for s in issues)


def test_from_sqlite_roundtrip(tmp_path):
    import sqlite3
    from keiba.ingest import from_sqlite
    se, ra, o1 = _jv_frames()
    p = tmp_path / "keiba.db"
    con = sqlite3.connect(str(p))
    se.to_sql("NL_SE", con, index=False)
    ra.to_sql("NL_RA", con, index=False)
    o1.to_sql("NL_O1", con, index=False)
    con.close()
    runners, races = from_sqlite(p)
    assert len(runners) == 6
    assert validate_runners(runners) == []


def test_validate_flags_column_name_mismatch():
    se, ra, o1 = _jv_frames()
    se2 = se.rename(columns={"KettoNum": "Ketto_Num", "Umaban": "Uma_Ban"})
    runners, _ = normalize(se2, ra, o1)
    issues = validate_runners(runners)
    assert any("horse_id が全て NaN" in s for s in issues)
    assert any("post_position が全て NaN" in s for s in issues)


def test_features_run_on_normalized_with_missing_optional_cols():
    se, ra, o1 = _jv_frames()
    runners, _ = normalize(se, ra, o1)
    # running_style/moisture/sire_id 等は無いが build_features は通る
    feat = build_features(runners)
    assert len(feat) == len(runners)
    assert "running_style" in feat.columns  # NaN 補完される


def test_ingest_backend_load(tmp_path):
    import sqlite3
    from keiba.ingest import IngestBackend
    se, ra, o1 = _jv_frames()
    p = tmp_path / "keiba.db"
    con = sqlite3.connect(str(p))
    se.to_sql("NL_SE", con, index=False)
    ra.to_sql("NL_RA", con, index=False)
    o1.to_sql("NL_O1", con, index=False)
    con.close()
    runners, races = IngestBackend(str(p), kind="sqlite").load()
    assert len(runners) == 6 and validate_runners(runners) == []
