"""追加 JV-Data レコードによる特徴量強化(血統 / データマイニング / オッズ時系列)。

`ingest.normalize` 済みの runners に、**発走前(リーク安全)** な強化列を左結合する:

  - sire_id, bms_id           : 血統(競走馬マスタ UM の 父 / 母父)。
                                これで features 側の s_*(種牡馬)集計が初めて生きる。
  - dm_score, tm_score        : JRA-VAN データマイニング(タイム型 DM / 対戦型 TM)の
                                予想値。JRA-VAN が発走前に算出 → そのまま当該レースの
                                特徴量に使える(リークしない)。
  - morning_odds(実値), odds_drift : 速報単勝オッズ(TS_SOKUHO_O1)の時系列から
                                寄りつき→直近の動き。締切後の final_odds は使わない。

設計方針(既存 ingest と同じ):
  * テーブルが無ければ列を作らない = 下流が NaN として吸収。**何も壊れない。**
  * 実テーブル/列名は構築ツールで異なるため **設定駆動**。*_FIELDS / TABLE 名を
    上書きすれば合わせられる。既定は jrvltsql 風。
  * race_id の作り方は ingest._race_key と一致させる(Year+Jyo+Kaiji+Nichiji+RaceNum)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .ingest import _col, _race_key

# --- 競走馬マスタ UM: 血統(3代血統の繁殖登録番号) ---
# JV-Data の Ketto3Info は 父=1, 母=2, 母父=5(構築ツールにより列名が異なる)。
UM_FIELDS = {
    "horse_id": "KettoNum",
    "sire": "Ketto3InfoHansyokuNum1",   # 父
    "bms": "Ketto3InfoHansyokuNum5",    # 母父(母の父)
}

# --- タイム型データマイニング DM: 馬ごとの予想走破タイム(小さいほど速い) ---
DM_FIELDS = {
    "year": "Year", "monthday": "MonthDay", "jyo": "JyoCD", "kaiji": "Kaiji",
    "nichiji": "Nichiji", "racenum": "RaceNum", "umaban": "Umaban",
    "score": "DMTime",   # 予想タイム。無ければ NaN
}

# --- 対戦型データマイニング TM: 馬ごとの予想スコア(大きいほど上位想定) ---
TM_FIELDS = {
    "year": "Year", "monthday": "MonthDay", "jyo": "JyoCD", "kaiji": "Kaiji",
    "nichiji": "Nichiji", "racenum": "RaceNum", "umaban": "Umaban",
    "score": "TMScore",
}

ENRICH_TABLES = {"um": "NL_UM", "dm": "NL_DM", "tm": "NL_TM",
                 "rt_odds": "TS_SOKUHO_O1"}


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def load_pedigree(reader, table: str, f: dict) -> pd.DataFrame | None:
    """競走馬マスタから (horse_id, sire_id, bms_id) を返す。無ければ None。"""
    um = reader(table)
    if um is None or len(um) == 0 or f["horse_id"] not in um.columns:
        return None
    out = pd.DataFrame({"horse_id": _col(um, f["horse_id"]).astype(str)})
    out["sire_id"] = _num(_col(um, f.get("sire", "")))
    out["bms_id"] = _num(_col(um, f.get("bms", "")))
    out = out.dropna(subset=["horse_id"]).drop_duplicates("horse_id")
    # 父・母父が両方 NaN の行は情報ゼロなので落とす
    out = out[out[["sire_id", "bms_id"]].notna().any(axis=1)]
    return out if len(out) else None


def load_mining(reader, table: str, f: dict, col_out: str) -> pd.DataFrame | None:
    """データマイニング表から (race_id, post_position, <col_out>) を返す。無ければ None。

    1行=1馬(long)形式を前提。score 列が無ければ None(graceful)。
    """
    dm = reader(table)
    if dm is None or len(dm) == 0:
        return None
    if f.get("score") not in dm.columns or f.get("umaban") not in dm.columns:
        return None
    out = pd.DataFrame({"race_id": _race_key(dm, f)})
    out["post_position"] = _num(_col(dm, f["umaban"]))
    out[col_out] = _num(_col(dm, f["score"]))
    out = out.dropna(subset=["post_position", col_out])
    if not len(out):
        return None
    # 同一(race,馬)に複数(更新)があれば最後(最新)を採用
    return out.drop_duplicates(["race_id", "post_position"], keep="last")


def load_odds_timeseries(reader, table: str, of: dict) -> pd.DataFrame | None:
    """速報単勝オッズの時系列から (race_id, post_position, morning_odds, odds_drift)。

    morning_odds = 寄りつき(最古スナップショット)。
    odds_drift   = log(寄りつき / 直近) … 直近で人気化(オッズ低下)なら正。
    どちらも発走前情報のみ(締切後 final は使わない)→ リーク安全。
    """
    ts = reader(table)
    if ts is None or len(ts) == 0:
        return None
    need = of.get("umaban")
    odds_col = of.get("tan_odds")
    if need not in ts.columns or odds_col not in ts.columns:
        return None
    ts = ts.copy()
    ts["race_id"] = _race_key(ts, of)
    ts["post_position"] = _num(_col(ts, need))
    ts["odds"] = _num(_col(ts, odds_col))
    # 収集時刻でソート(無ければ MakeDate、それも無ければ取得順)
    tcol = next((c for c in ("CollectedAt", "MakeDate") if c in ts.columns), None)
    if tcol is not None:
        ts = ts.sort_values(tcol)
    ts = ts.dropna(subset=["post_position", "odds"])
    ts = ts[ts["odds"] > 0]
    if not len(ts):
        return None
    g = ts.groupby(["race_id", "post_position"])
    out = g.agg(morning_odds=("odds", "first"),
                _last=("odds", "last")).reset_index()
    with np.errstate(invalid="ignore", divide="ignore"):
        out["odds_drift"] = np.log(out["morning_odds"] / out["_last"])
    return out[["race_id", "post_position", "morning_odds", "odds_drift"]]


def enrich_runners(runners: pd.DataFrame, reader, table_map: dict,
                   cfg=None) -> pd.DataFrame:
    """normalize 済み runners に血統 / マイニング / オッズ時系列の発走前列を結合。"""
    tm = {**ENRICH_TABLES, **(table_map or {})}
    um_f = getattr(cfg, "um_fields", None) or UM_FIELDS
    dm_f = getattr(cfg, "dm_fields", None) or DM_FIELDS
    tm_f = getattr(cfg, "tm_fields", None) or TM_FIELDS
    o1_f = getattr(cfg, "o1_fields", None) or {
        "year": "Year", "monthday": "MonthDay", "jyo": "JyoCD", "kaiji": "Kaiji",
        "nichiji": "Nichiji", "racenum": "RaceNum", "umaban": "Umaban",
        "tan_odds": "TanOdds"}

    out = runners.copy()
    out["race_id"] = out["race_id"].astype(str)

    # 血統: horse_id で結合(sire_id/bms_id を新設)
    ped = load_pedigree(reader, tm["um"], um_f)
    if ped is not None:
        out["horse_id"] = out["horse_id"].astype(str)
        out = out.drop(columns=[c for c in ("sire_id", "bms_id") if c in out.columns])
        out = out.merge(ped, on="horse_id", how="left")

    # データマイニング: (race_id, 馬番) で結合
    for tbl_key, fmap, col in (("dm", dm_f, "dm_score"), ("tm", tm_f, "tm_score")):
        mining = load_mining(reader, tm[tbl_key], fmap, col)
        if mining is not None:
            out = out.drop(columns=[col] if col in out.columns else [])
            out = out.merge(mining, on=["race_id", "post_position"], how="left")

    # オッズ時系列: morning_odds(実値) / odds_drift を上書き
    ots = load_odds_timeseries(reader, tm["rt_odds"], o1_f)
    if ots is not None:
        out = out.drop(columns=[c for c in ("morning_odds", "odds_drift")
                                if c in out.columns])
        out = out.merge(ots, on=["race_id", "post_position"], how="left")

    return out
