"""M5: JV-Data(JRA-VAN)DB → 分析層スキーマ への取り込み(正規化)層。

EveryDB2 / jrvltsql 等が JV-Link から構築した DB(SE=馬毎レース情報・RA=レース詳細・
O1=単複オッズ・HR=払戻 …)を、本システムの runners/races スキーマへマッピングする。
JV-Data のフィールド名はローマ字(KettoNum/Umaban/KakuteiJyuni/Ninki 等)。

★重要: 実際の列名・テーブル名は構築ツール(jrvltsql は NL_SE/NL_RA/NL_O1…、
   EveryDB2 は別名のことがある)で異なる。COLMAP / TABLE_MAP を差し替えるだけで
   合わせられるよう **設定駆動** にしている。利用者の DB スキーマを確認し、
   下の既定値を必要に応じて上書きすること。

未取得の特徴(脚質・含水率・血統・時系列オッズ等)は NaN のままで良い
(features 層が欠損を吸収する)。まず単勝の取得で end-to-end を回し、後段で拡充する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import schema

# --- JV-Data フィールド名(★利用者の DB に合わせて上書き可) ---
RA_FIELDS = {
    "year": "Year", "monthday": "MonthDay", "jyo": "JyoCD", "kaiji": "Kaiji",
    "nichiji": "Nichiji", "racenum": "RaceNum", "distance": "Kyori",
    "trackcd": "TrackCD", "siba_baba": "SibaBabaCD", "dirt_baba": "DirtBabaCD",
    "jyoken": "JyokenCD5", "grade": "GradeCD", "field_size": "SyussoTosu",
}
SE_FIELDS = {
    "year": "Year", "monthday": "MonthDay", "jyo": "JyoCD", "kaiji": "Kaiji",
    "nichiji": "Nichiji", "racenum": "RaceNum", "horse_id": "KettoNum",
    "umaban": "Umaban", "jockey": "KisyuCode", "trainer": "ChokyosiCode",
    "carried_weight": "Futan", "horse_weight": "BaTaijyu", "zogen_sa": "ZogenSa",
    "zogen_fugo": "ZogenFugo", "finish": "KakuteiJyuni", "time": "Time",
    "last3f": "HaronTimeL3", "passing": "Jyuni3c", "age": "Barei", "sex": "SexCD",
    "ninki": "Ninki",
}
O1_FIELDS = {  # 単勝オッズ(馬番別)
    "year": "Year", "monthday": "MonthDay", "jyo": "JyoCD", "kaiji": "Kaiji",
    "nichiji": "Nichiji", "racenum": "RaceNum", "umaban": "Umaban",
    "tan_odds": "TanOdds", "tan_ninki": "TanNinki",
}
TABLE_MAP = {"se": "NL_SE", "ra": "NL_RA", "o1": "NL_O1", "hr": "NL_HR"}


@dataclass
class IngestConfig:
    se_fields: dict = field(default_factory=lambda: dict(SE_FIELDS))
    ra_fields: dict = field(default_factory=lambda: dict(RA_FIELDS))
    o1_fields: dict = field(default_factory=lambda: dict(O1_FIELDS))
    odds_scale: float = 10.0      # JV-Data の単勝オッズは整数×0.1(35→3.5)
    futan_scale: float = 10.0     # 斤量も 0.1kg 単位(550→55.0)のことがある


def _col(df: pd.DataFrame, name: str):
    return df[name] if name in df.columns else pd.Series([np.nan] * len(df), index=df.index)


def _race_key(df: pd.DataFrame, f: dict) -> pd.Series:
    parts = [df[f[k]].astype(str).str.zfill(w) for k, w in
             [("year", 4), ("jyo", 2), ("kaiji", 2), ("nichiji", 2), ("racenum", 2)]
             if f.get(k) in df.columns]
    return parts[0].str.cat(parts[1:], sep="") if parts else pd.Series(range(len(df)), index=df.index).astype(str)


def _race_date_ordinal(year, monthday) -> int:
    try:
        y = int(year); md = str(int(monthday)).zfill(4)
        return date(y, int(md[:2]), int(md[2:])).toordinal()
    except Exception:
        return -1


def _surface_from_track(trackcd) -> float:
    try:
        t = int(trackcd)
    except Exception:
        return np.nan
    if 10 <= t <= 22:
        return 0.0   # 芝
    if 23 <= t <= 29:
        return 1.0   # ダート
    return np.nan    # 障害等は対象外


def normalize(se: pd.DataFrame, ra: pd.DataFrame, o1: pd.DataFrame | None = None,
              hr: pd.DataFrame | None = None, config: IngestConfig | None = None
              ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """JV-Data の SE/RA(+O1/HR)を runners/races スキーマへ正規化する。"""
    cfg = config or IngestConfig()
    sf, rf = cfg.se_fields, cfg.ra_fields

    se = se.copy()
    ra = ra.copy()
    se["race_id"] = _race_key(se, sf)
    ra["race_id"] = _race_key(ra, rf)

    # レース日(序数)。features は race_date の昇順しか見ないので序数で十分。
    se["race_date"] = [
        _race_date_ordinal(y, m) for y, m in zip(_col(se, sf["year"]), _col(se, sf["monthday"]))
    ]

    # レース属性を SE に join
    ra_attr = pd.DataFrame({"race_id": ra["race_id"]})
    ra_attr["distance"] = pd.to_numeric(_col(ra, rf["distance"]), errors="coerce")
    ra_attr["field_size"] = pd.to_numeric(_col(ra, rf["field_size"]), errors="coerce")
    ra_attr["surface"] = _col(ra, rf["trackcd"]).map(_surface_from_track)
    ra_attr["class_level"] = pd.to_numeric(_col(ra, rf["grade"]), errors="coerce")
    # 馬場状態: 芝/ダで参照列が違う。surface に応じて選ぶ。
    siba = pd.to_numeric(_col(ra, rf["siba_baba"]), errors="coerce")
    dirt = pd.to_numeric(_col(ra, rf["dirt_baba"]), errors="coerce")
    ra_attr["going"] = np.where(ra_attr["surface"] == 1, dirt, siba) - 1  # 1良→0
    ra_attr = ra_attr.drop_duplicates("race_id")

    out = pd.DataFrame()
    out["race_id"] = se["race_id"]
    out["race_date"] = se["race_date"]
    out["horse_id"] = _col(se, sf["horse_id"])
    out["jockey_id"] = pd.to_numeric(_col(se, sf["jockey"]), errors="coerce")
    out["trainer_id"] = pd.to_numeric(_col(se, sf["trainer"]), errors="coerce")
    out["post_position"] = pd.to_numeric(_col(se, sf["umaban"]), errors="coerce")
    out["carried_weight"] = pd.to_numeric(_col(se, sf["carried_weight"]), errors="coerce") / cfg.futan_scale
    out["horse_weight"] = pd.to_numeric(_col(se, sf["horse_weight"]), errors="coerce")
    zsa = pd.to_numeric(_col(se, sf["zogen_sa"]), errors="coerce")
    zfugo = _col(se, sf["zogen_fugo"]).astype(str)
    out["weight_diff"] = np.where(zfugo.str.startswith("-"), -zsa, zsa)
    out["age"] = pd.to_numeric(_col(se, sf["age"]), errors="coerce")
    out["sex"] = pd.to_numeric(_col(se, sf["sex"]), errors="coerce")
    finish = pd.to_numeric(_col(se, sf["finish"]), errors="coerce")
    finish = finish.where(finish > 0)   # 0=取消/中止 → NaN
    out["finish_pos"] = finish
    out["finish_time"] = pd.to_numeric(_col(se, sf["time"]), errors="coerce")
    out["last_3f"] = pd.to_numeric(_col(se, sf["last3f"]), errors="coerce")
    out["passing_rank"] = pd.to_numeric(_col(se, sf["passing"]), errors="coerce")
    out["is_win"] = (finish == 1).astype(float)
    out["is_top3"] = ((finish >= 1) & (finish <= 3)).astype(float)
    out["final_popularity"] = pd.to_numeric(_col(se, sf["ninki"]), errors="coerce")

    out = out.merge(ra_attr, on="race_id", how="left")

    # 単勝オッズ(O1)を (race_id, umaban) で join
    if o1 is not None and len(o1):
        of = cfg.o1_fields
        o1 = o1.copy()
        o1["race_id"] = _race_key(o1, of)
        o1["post_position"] = pd.to_numeric(_col(o1, of["umaban"]), errors="coerce")
        o1["final_odds"] = pd.to_numeric(_col(o1, of["tan_odds"]), errors="coerce") / cfg.odds_scale
        out = out.merge(o1[["race_id", "post_position", "final_odds"]],
                        on=["race_id", "post_position"], how="left")
        # 賭け判定用の発走前オッズ。時系列オッズ未取得なら確定で代用(要・後段拡充)。
        out["intermediate_odds"] = out["final_odds"]
        out["morning_odds"] = out["final_odds"]

    races = ra_attr.copy()
    races["race_date"] = se.groupby("race_id")["race_date"].first().reindex(races["race_id"]).to_numpy()
    return out.reset_index(drop=True), races.reset_index(drop=True)


def validate_runners(df: pd.DataFrame) -> list[str]:
    """正規化済み runners が分析層に必要な最低条件を満たすか検査し、問題を列挙する。"""
    issues = []
    required = ["race_id", "race_date", "horse_id", "post_position", "finish_pos"]
    for c in required:
        if c not in df.columns:
            issues.append(f"必須列が無い: {c}")
    if "race_date" in df and df["race_date"].le(0).any():
        issues.append("race_date に不正値(<=0)がある(日付パース失敗の可能性)")
    if "finish_pos" in df and df["finish_pos"].notna().any():
        per_race_winner = df[df.finish_pos == 1].groupby("race_id").size()
        if (per_race_winner > 1).any():
            issues.append("1着が複数あるレースがある(race_id 構成 or 着順の不整合)")
    if "final_odds" in df and df["final_odds"].notna().any():
        if (df["final_odds"] < 1.0).mean() > 0.5:
            issues.append("final_odds の多くが 1.0 未満(odds_scale の見直しが必要かも)")
    return issues


def from_duckdb(path: str | Path, table_map: dict | None = None,
                config: IngestConfig | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DuckDB/SQLite ファイルから JV-Data テーブルを読み、正規化して返す。"""
    import duckdb
    tm = {**TABLE_MAP, **(table_map or {})}
    con = duckdb.connect(str(path), read_only=True)
    try:
        def tbl(name):
            try:
                return con.execute(f'SELECT * FROM "{name}"').fetchdf()
            except Exception:
                return None
        se = tbl(tm["se"]); ra = tbl(tm["ra"])
        o1 = tbl(tm.get("o1", "")); hr = tbl(tm.get("hr", ""))
    finally:
        con.close()
    if se is None or ra is None:
        raise ValueError(f"必須テーブル {tm['se']}/{tm['ra']} が見つかりません")
    return normalize(se, ra, o1, hr, config)
