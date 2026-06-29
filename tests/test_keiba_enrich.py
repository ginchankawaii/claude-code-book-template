"""keiba: 特徴量強化(血統 / データマイニング / オッズ時系列)のテスト。"""

import sqlite3

import numpy as np
import pandas as pd

from keiba.enrich import enrich_runners
from keiba.features import FEATURE_COLUMNS, build_features
from keiba.ingest import from_sqlite, normalize


def _jv_frames():
    se = pd.DataFrame({
        "Year": ["2020"] * 6,
        "MonthDay": ["0105"] * 3 + ["0106"] * 3,
        "JyoCD": ["05"] * 6, "Kaiji": ["01"] * 6, "Nichiji": ["01"] * 6,
        "RaceNum": ["01"] * 3 + ["02"] * 3,
        "KettoNum": ["A", "B", "C", "A", "B", "C"],
        "Umaban": [1, 2, 3, 1, 2, 3],
        "KisyuCode": [10, 20, 30, 10, 20, 30],
        "ChokyosiCode": [1, 2, 3, 1, 2, 3],
        "Futan": [55.0, 55.5, 54.0, 55.0, 55.5, 54.0],
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
        "TanOdds": [2.1, 3.5, 8.0, 4.0, 1.8, 6.0], "TanNinki": [1, 2, 3, 2, 1, 3],
    })
    return se, ra, o1


def _um():
    # 競走馬マスタ: A,B は父/母父あり、C は欠損(=結合されないことを確認)
    return pd.DataFrame({
        "KettoNum": ["A", "B"],
        "Ketto3InfoHansyokuNum1": [1001, 1002],   # 父
        "Ketto3InfoHansyokuNum5": [2001, 2002],   # 母父
    })


def _dm():
    return pd.DataFrame({
        "Year": ["2020"] * 3, "MonthDay": ["0105"] * 3, "JyoCD": ["05"] * 3,
        "Kaiji": ["01"] * 3, "Nichiji": ["01"] * 3, "RaceNum": ["01"] * 3,
        "Umaban": [1, 2, 3], "DMTime": [70.0, 70.5, 71.2],
    })


def _ts_odds():
    # 寄りつき→直近 の2スナップショット。馬1は人気化(オッズ低下=drift>0)。
    rows = []
    snaps = [("0900", [3.0, 3.0, 9.0]), ("1100", [2.0, 3.2, 9.0])]
    for t, odds in snaps:
        for ub, o in zip([1, 2, 3], odds):
            rows.append({"Year": "2020", "MonthDay": "0105", "JyoCD": "05",
                         "Kaiji": "01", "Nichiji": "01", "RaceNum": "01",
                         "Umaban": ub, "TanOdds": o, "CollectedAt": t})
    return pd.DataFrame(rows)


def _build_db(path, extra: dict):
    se, ra, o1 = _jv_frames()
    con = sqlite3.connect(str(path))
    se.to_sql("NL_SE", con, index=False)
    ra.to_sql("NL_RA", con, index=False)
    o1.to_sql("NL_O1", con, index=False)
    for name, df in extra.items():
        df.to_sql(name, con, index=False)
    con.close()


def test_enrich_graceful_when_tables_absent(tmp_path):
    # 追加テーブルが無くても落ちない・列はNaNで埋まる
    p = tmp_path / "k.db"
    _build_db(p, {})
    runners, _ = from_sqlite(p)
    assert len(runners) == 6
    feats = build_features(runners)
    for c in ["sire_id", "bms_id", "dm_score", "tm_score"]:
        assert c not in runners.columns or runners[c].isna().all()
    # 強化系特徴も列としては存在(NaN)
    for c in ["t_starts", "bms_win_rate", "dm_rank", "tm_score"]:
        assert c in feats.columns


def test_pedigree_populates_sire_and_bms(tmp_path):
    p = tmp_path / "k.db"
    _build_db(p, {"NL_UM": _um()})
    runners, _ = from_sqlite(p)
    by = runners.set_index("horse_id")
    assert by.loc["A", "sire_id"].iloc[0] == 1001
    assert by.loc["A", "bms_id"].iloc[0] == 2001
    # C は UM に無い → NaN
    assert pd.isna(by.loc["C", "sire_id"].iloc[0])


def test_mining_score_and_rank(tmp_path):
    p = tmp_path / "k.db"
    _build_db(p, {"NL_DM": _dm()})
    runners, _ = from_sqlite(p)
    feats = build_features(runners).sort_values(["race_id", "post_position"])
    r1 = feats[feats["race_id"] == feats["race_id"].min()]
    # race1 の dm_score が結合されている
    assert r1["dm_score"].notna().all()
    # 予想タイム最小(馬1=70.0)が dm_rank=1
    top = r1.sort_values("post_position").iloc[0]
    assert top["dm_rank"] == 1.0


def test_odds_timeseries_morning_and_drift(tmp_path):
    p = tmp_path / "k.db"
    _build_db(p, {"TS_SOKUHO_O1": _ts_odds()})
    runners, _ = from_sqlite(p)
    r1 = runners[runners["post_position"] == 1].sort_values("race_id").iloc[0]
    # 寄りつき 3.0 が morning_odds
    assert abs(r1["morning_odds"] - 3.0) < 1e-9
    # 3.0→2.0 に人気化 → drift = log(3/2) > 0
    assert r1["odds_drift"] > 0


def test_enrich_runners_direct_call():
    # reader を関数で差し替えて enrich 単体を検証
    se, ra, o1 = _jv_frames()
    runners, _ = normalize(se, ra, o1)
    tables = {"NL_UM": _um(), "NL_DM": _dm()}
    reader = lambda name: tables.get(name)
    out = enrich_runners(runners, reader, {})
    assert "sire_id" in out.columns and out["sire_id"].notna().any()
    assert "dm_score" in out.columns and out["dm_score"].notna().any()


def test_new_features_in_feature_columns():
    for c in ["t_starts", "t_win_rate", "t_surface_win",
              "bms_win_rate", "bms_avg_relfinish", "dm_score", "dm_rank", "tm_score"]:
        assert c in FEATURE_COLUMNS
