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
from .reader import JVLinkReader

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
TABLE_MAP = {"se": "NL_SE", "ra": "NL_RA", "o1": "NL_O1", "hr": "NL_HR",
             "rt_se": "RT_SE", "rt_ra": "RT_RA", "rt_odds": "TS_SOKUHO_O1",
             # 特徴量強化(enrich)で使う追加レコード(無ければ自動スキップ)
             "um": "NL_UM", "dm": "NL_DM", "tm": "NL_TM"}

# 中央競馬(JRA)の競馬場コード。これ以外(30番台〜=地方NAR, 50番台〜=海外)は除外する。
CENTRAL_JYO = {f"{i:02d}" for i in range(1, 11)}  # 01..10 札幌〜小倉


@dataclass
class IngestConfig:
    se_fields: dict = field(default_factory=lambda: dict(SE_FIELDS))
    ra_fields: dict = field(default_factory=lambda: dict(RA_FIELDS))
    o1_fields: dict = field(default_factory=lambda: dict(O1_FIELDS))
    # jrvltsql は TanOdds/Futan を「実数(小数)」で格納する(例 1.5倍, 55.0kg)。
    # 生の JV-Data 整数(×0.1)を読む実装に差し替える場合は 10.0 にする。
    odds_scale: float = 1.0
    futan_scale: float = 1.0
    # 中央競馬(JRA)のみに絞る。地方競馬(NAR)・海外を学習/予測から除外する。
    central_only: bool = True
    # 特徴量強化(血統 UM / データマイニング DM・TM / オッズ時系列)を結合する。
    # 該当テーブルが無ければ自動でスキップ(列は NaN のまま)。
    enrich: bool = True
    um_fields: dict | None = None  # None で enrich.UM_FIELDS 既定を使う
    dm_fields: dict | None = None
    tm_fields: dict | None = None


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

    # JV-Data は同一(レース,馬)に複数レコード(出馬表/速報/確定など DataKubun 違い)を
    # 持つため、確定(着順あり)を優先して 1 件に重複排除する。
    out["_has_finish"] = out["finish_pos"].notna().astype(int)
    out = (
        out.sort_values(["race_id", "horse_id", "_has_finish"])
        .drop_duplicates(["race_id", "horse_id"], keep="last")
        .drop(columns="_has_finish")
        .reset_index(drop=True)
    )

    out = out.merge(ra_attr, on="race_id", how="left")

    # 単勝オッズ(O1)を (race_id, umaban) で join
    if o1 is not None and len(o1):
        of = cfg.o1_fields
        o1 = o1.copy()
        o1["race_id"] = _race_key(o1, of)
        o1["post_position"] = pd.to_numeric(_col(o1, of["umaban"]), errors="coerce")
        o1["final_odds"] = pd.to_numeric(_col(o1, of["tan_odds"]), errors="coerce") / cfg.odds_scale
        # NL_O1 は同一(レース,馬番)に複数スナップショット(中間/確定の DataKubun 違い)を
        # 持つ。1件に集約せず結合すると runners が増殖し、着順表が重複して見える(誤検知)
        # うえ学習データに同一馬が二重計上される。確定=最新の1件に絞ってから結合する。
        _sort = [c for c in ("MakeDate", "MakeHM", "HappyoTime") if c in o1.columns]
        if _sort:
            o1 = o1.sort_values(_sort)
        o1 = o1.dropna(subset=["post_position"]).drop_duplicates(
            ["race_id", "post_position"], keep="last")
        out = out.merge(o1[["race_id", "post_position", "final_odds"]],
                        on=["race_id", "post_position"], how="left")
        # 賭け判定用の発走前オッズ。時系列オッズ未取得なら確定で代用(要・後段拡充)。
        out["intermediate_odds"] = out["final_odds"]
        out["morning_odds"] = out["final_odds"]

    races = ra_attr.copy()
    races["race_date"] = se.groupby("race_id")["race_date"].first().reindex(races["race_id"]).to_numpy()

    # 中央競馬(JRA)のみに絞る: race_id の [4:6] が競馬場コード。
    # 地方(NAR)が混ざると学習が薄まり、race_id 衝突で「1着が複数」も起きるため除外。
    if cfg.central_only:
        out = out[out["race_id"].astype(str).str[4:6].isin(CENTRAL_JYO)]
        races = races[races["race_id"].astype(str).str[4:6].isin(CENTRAL_JYO)]

    return out.reset_index(drop=True), races.reset_index(drop=True)


def validate_runners(df: pd.DataFrame) -> list[str]:
    """正規化済み runners が分析層に必要な最低条件を満たすか検査し、問題を列挙する。"""
    issues = []
    required = ["race_id", "race_date", "horse_id", "post_position", "finish_pos"]
    for c in required:
        if c not in df.columns:
            issues.append(f"必須列が無い: {c}")
    # 全行 NaN のキー列 = 元の JV-Data 列名が既定と違う可能性(マッピング要修正)
    for c in ["horse_id", "post_position", "jockey_id", "final_odds"]:
        if c in df.columns and df[c].isna().all():
            issues.append(f"{c} が全て NaN(元の列名が *_FIELDS の既定と異なる可能性)")
    if "race_date" in df and df["race_date"].le(0).any():
        issues.append("race_date に不正値(<=0)がある(日付パース失敗 or Year/MonthDay 列名違い)")
    if "finish_pos" in df and df["finish_pos"].notna().any():
        fin = df[df["finish_pos"].notna()]
        multi_win = fin[fin["finish_pos"] == 1].groupby("race_id").size()
        # 1着が2頭=JRAで稀に起きる正規の「同着」。これ自体は異常ではない。
        # race_id 衝突なら別レースの着順表が丸ごと混ざるので 2着以降も重複する——
        # 1着以外の着順も重複しているレースだけを「不整合」として警告する。
        structural = [
            rid for rid in multi_win[multi_win > 1].index
            if (fin.loc[fin["race_id"] == rid, "finish_pos"]
                .value_counts().drop(index=1, errors="ignore") > 1).any()
        ]
        if structural:
            n_races = int(fin["race_id"].nunique())
            issues.append(
                f"1着が複数あるレースがある({len(structural)}/{n_races}レース: "
                "race_id 構成 or 着順の不整合)")
    if "final_odds" in df and df["final_odds"].notna().any():
        if (df["final_odds"] < 1.0).mean() > 0.5:
            issues.append("final_odds の多くが 1.0 未満(odds_scale の見直しが必要かも)")
    return issues


def _ingest_tables(reader, table_map: dict | None, config: IngestConfig | None,
                   include_realtime: bool = False):
    cfg = config or IngestConfig()
    tm = {**TABLE_MAP, **(table_map or {})}
    se = reader(tm["se"]); ra = reader(tm["ra"])
    o1 = reader(tm.get("o1", "")); hr = reader(tm.get("hr", ""))
    if se is None or ra is None:
        raise ValueError(f"必須テーブル {tm['se']}/{tm['ra']} が見つかりません")
    if include_realtime:
        # 当日の出馬表(まだ着順が出ていないレース)は速報系 RT_ テーブルにある。
        # 履歴(NL_)に結合すると、出馬各馬の PiT 特徴量が過去走から計算される。
        rt_se = reader(tm.get("rt_se", "RT_SE"))
        rt_ra = reader(tm.get("rt_ra", "RT_RA"))
        if rt_se is not None and len(rt_se):
            se = pd.concat([se, rt_se], ignore_index=True)
        if rt_ra is not None and len(rt_ra):
            ra = pd.concat([ra, rt_ra], ignore_index=True)
        # 当日の速報オッズ(TS_SOKUHO_O1)の最新スナップショットを O1 に足す。
        rt_odds = reader(tm.get("rt_odds", "TS_SOKUHO_O1"))
        if rt_odds is not None and len(rt_odds):
            of = cfg.o1_fields
            key_cols = [of[k] for k in ("year", "monthday", "jyo", "kaiji", "nichiji",
                                        "racenum", "umaban") if of.get(k) in rt_odds.columns]
            if "CollectedAt" in rt_odds.columns:
                rt_odds = rt_odds.sort_values("CollectedAt")
            if key_cols:
                rt_odds = rt_odds.drop_duplicates(subset=key_cols, keep="last")
            o1 = pd.concat([o1, rt_odds], ignore_index=True) if (o1 is not None and len(o1)) else rt_odds
    runners, races = normalize(se, ra, o1, hr, cfg)
    if cfg.enrich:
        from . import enrich as _enrich
        try:
            runners = _enrich.enrich_runners(runners, reader, tm, cfg)
        except Exception:
            # 強化は best-effort。失敗しても素の runners で先へ進む。
            pass
    return runners, races


def from_sqlite(path: str | Path, table_map: dict | None = None,
                config: IngestConfig | None = None,
                include_realtime: bool = False,
                immutable: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """SQLite ファイル(jrvltsql の data/keiba.db 等)から読み、正規化して返す。

    include_realtime=True で当日の出馬表(RT_SE/RT_RA)も結合する。
    immutable=True は別プロセス(realtime 取り込み)が DB を排他ロック中でも
    読めるよう immutable オープンする(僅かに古いスナップショットを読む可能性あり)。
    """
    import sqlite3
    if immutable:
        uri = "file:" + str(path).replace("\\", "/") + "?immutable=1"
        con = sqlite3.connect(uri, uri=True)
    else:
        con = sqlite3.connect(str(path))
    try:
        def reader(name):
            if not name:
                return None
            try:
                return pd.read_sql_query(f'SELECT * FROM "{name}"', con)
            except Exception:
                return None
        return _ingest_tables(reader, table_map, config, include_realtime)
    finally:
        con.close()


def from_duckdb(path: str | Path, table_map: dict | None = None,
                config: IngestConfig | None = None,
                include_realtime: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DuckDB ファイルから JV-Data テーブルを読み、正規化して返す。"""
    import duckdb
    con = duckdb.connect(str(path), read_only=True)
    try:
        def reader(name):
            if not name:
                return None
            try:
                return con.execute(f'SELECT * FROM "{name}"').fetchdf()
            except Exception:
                return None
        return _ingest_tables(reader, table_map, config, include_realtime)
    finally:
        con.close()


class IngestBackend(JVLinkReader):
    """JV-Data DB(SQLite/DuckDB)を読み、正規化済み (runners, races) を供給する
    分析層バックエンド。run_pipeline にそのまま渡せる。"""

    def __init__(self, path, kind: str = "sqlite", table_map: dict | None = None,
                 config: IngestConfig | None = None, include_realtime: bool = False,
                 immutable: bool = False):
        self.path = path
        self.kind = kind
        self.table_map = table_map
        self.config = config
        self.include_realtime = include_realtime
        self.immutable = immutable

    def load(self):
        if self.kind == "duckdb":
            return from_duckdb(self.path, self.table_map, self.config, self.include_realtime)
        return from_sqlite(self.path, self.table_map, self.config, self.include_realtime,
                           self.immutable)
