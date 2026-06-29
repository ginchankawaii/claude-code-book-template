"""連系オッズ(O2〜O6)の読み込みと「レース×券種×組番→オッズ」辞書化。

  * NL_O2..O6        = 確定(最終)オッズ … 過去レース(バックテスト)用
  * TS_SOKUHO_O2..O6 = 当日のライブ速報オッズ(0B30由来, CollectedAt 付き)

組番(Kumi)は馬番の連結:
  馬連/馬単/ワイド = "0102"(2頭),  三連複/三連単 = "010203"(3頭)。
  馬単・三連単は着順あり(順序保持)、馬連・ワイド・三連複は順不問(ソート)。
  ワイドは OddsLow/OddsHigh の幅 → 中央値を採用。

2026年フルだと三連単だけで数千万行になるため、**日付単位**で必要分だけ読む。
realtime が DB を排他ロック中でも読めるよう immutable オープンに対応。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

# (券種名, (確定テーブル, 速報テーブル), 頭数, 順序あり, オッズ種別)
_SPECS = [
    ("馬連",   ("NL_O2", "TS_SOKUHO_O2"), 2, False, "single"),
    ("ワイド", ("NL_O3", "TS_SOKUHO_O3"), 2, False, "wide"),
    ("馬単",   ("NL_O4", "TS_SOKUHO_O4"), 2, True,  "single"),
    ("三連複", ("NL_O5", "TS_SOKUHO_O5"), 3, False, "single"),
    ("三連単", ("NL_O6", "TS_SOKUHO_O6"), 3, True,  "single"),
]


def _open(path: str | Path, kind: str, immutable: bool):
    if kind == "duckdb":
        import duckdb
        return duckdb.connect(str(path), read_only=True), "duckdb"
    if immutable:
        uri = "file:" + str(path).replace("\\", "/") + "?immutable=1"
        return sqlite3.connect(uri, uri=True), "sqlite"
    return sqlite3.connect(str(path)), "sqlite"


def _read(con, kind: str, sql: str, params: list):
    if kind == "duckdb":
        return con.execute(sql, params).fetchdf()
    return pd.read_sql_query(sql, con, params=params)


def _race_id(df: pd.DataFrame) -> np.ndarray:
    """Year/JyoCD/Kaiji/Nichiji/RaceNum → 12桁 race_id(int)。"""
    y = df["Year"].astype(int).astype(str).str.zfill(4)
    j = df["JyoCD"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(2)
    k = df["Kaiji"].astype(int).astype(str).str.zfill(2)
    n = df["Nichiji"].astype(int).astype(str).str.zfill(2)
    r = df["RaceNum"].astype(int).astype(str).str.zfill(2)
    return (y + j + k + n + r).astype(np.int64).to_numpy()


def _accumulate(out: dict, df: pd.DataFrame, name: str, nh: int,
                ordered: bool, okind: str) -> None:
    if df is None or not len(df) or "Kumi" not in df.columns:
        return
    width = nh * 2
    rid = _race_id(df)
    kumi = (df["Kumi"].astype(str).str.replace(r"\D", "", regex=True)
            .str.zfill(width))
    cols = [kumi.str[i * 2:i * 2 + 2] for i in range(nh)]
    # 数字以外/空は弾く
    valid = np.ones(len(df), dtype=bool)
    nums = []
    for c in cols:
        n = pd.to_numeric(c, errors="coerce")
        valid &= n.notna().to_numpy()
        nums.append(n.fillna(0).astype(int).to_numpy())
    arr = np.stack(nums, axis=1)
    if not ordered:
        arr = np.sort(arr, axis=1)

    if okind == "wide":
        lo = pd.to_numeric(df.get("OddsLow"), errors="coerce")
        hi = pd.to_numeric(df.get("OddsHigh"), errors="coerce")
        odds = ((lo + hi) / 2.0).to_numpy()
    else:
        odds = pd.to_numeric(df.get("Odds"), errors="coerce").to_numpy()

    # 新しい順に最後勝ち: CollectedAt(速報) > MakeDate(確定) で昇順に並べ替えて上書き
    if "CollectedAt" in df.columns:
        order = np.argsort(df["CollectedAt"].astype(str).to_numpy(), kind="stable")
    elif "MakeDate" in df.columns:
        order = np.argsort(df["MakeDate"].astype(str).to_numpy(), kind="stable")
    else:
        order = np.arange(len(df))

    for i in order:
        if not valid[i]:
            continue
        o = odds[i]
        if not np.isfinite(o) or o <= 1.0:   # 1.0倍以下=未確定/無効
            continue
        combo = tuple(int(x) for x in arr[i])
        out.setdefault(int(rid[i]), {}).setdefault(name, {})[combo] = float(o)


# 既定で評価する券種。馬単(O4)・三連単(O6)は評価器(select_exotic_bets)が
# 参照しないため読み込まない=巨大な O6(数千万行)を完全に回避できる。
_DEFAULT_KINDS = ("馬連", "ワイド", "三連複")


def load_exotic_odds_for_days(path: str | Path, ordinals, kind: str = "sqlite",
                              immutable: bool = False,
                              kinds=_DEFAULT_KINDS,
                              max_combos_per_race: int = 200) -> dict:
    """複数日(序数の集合)の連系オッズをまとめて {race_id: {券種: {組: 倍率}}} で返す。

    バックテスト(C3)で test 期間の race を実オッズ決済するために使う。
    **年単位の一括クエリ**(WHERE Year=?)で読むので、日ごとに全表スキャンする旧実装
    より桁違いに速い。kinds で読む券種を絞れる(既定=馬連/ワイド/三連複のみ)。
    max_combos_per_race で各 race×券種の保持組数を人気上位に制限しメモリを抑える。
    """
    import datetime as _dt
    want: dict = {}
    for o in ordinals:
        d = _dt.date.fromordinal(int(o))
        want.setdefault(d.year, set()).add(d.month * 100 + d.day)
    specs = [s for s in _SPECS if s[0] in set(kinds)]

    con, k = _open(path, kind, immutable)
    out: dict = {}
    try:
        for year, mds in sorted(want.items()):
            year_out: dict = {}
            for name, tables, nh, ordered, okind in specs:
                frames = []
                for tbl in tables:
                    try:
                        df = _read(con, k, f'SELECT * FROM "{tbl}" WHERE Year=?',
                                   [int(year)])
                    except Exception:
                        continue
                    if df is None or not len(df):
                        continue
                    md = pd.to_numeric(df.get("MonthDay"), errors="coerce")
                    df = df[md.isin(mds)]
                    if len(df):
                        frames.append(df)
                if frames:
                    _accumulate(year_out, pd.concat(frames, ignore_index=True),
                                name, nh, ordered, okind)
            _prune_combos(year_out, max_combos_per_race)
            out.update(year_out)   # race_id は年内ユニークなので単純結合で良い
    finally:
        con.close()
    return out


def _prune_combos(out: dict, max_combos: int) -> None:
    """各 race×券種で、最も人気(低オッズ)の max_combos 組だけ残す。

    評価器はモデル確率上位の少数組しか買わないため、全 816 組(三連複)を保持する
    のは無駄。低オッズ=人気上位はモデルの買い目とほぼ重なるので、これでメモリを
    数分の一にしても実オッズのカバレッジはほぼ落ちない。
    """
    if not max_combos:
        return
    for kinds in out.values():
        for name, table in list(kinds.items()):
            if len(table) > max_combos:
                keep = sorted(table.items(), key=lambda kv: kv[1])[:max_combos]
                kinds[name] = dict(keep)


def load_exotic_odds_for_day(path: str | Path, year: int, monthday: int,
                             kind: str = "sqlite", immutable: bool = False) -> dict:
    """指定日(year, monthday=月*100+日)の連系オッズを読み、

        { race_id(int): { "馬連": {(1,2): 倍率, ...}, "ワイド": {...}, ... } }

    の辞書で返す。馬連/ワイド/三連複の組番はソート済(順不問)、
    馬単/三連単は順序保持(着順)。当該日のデータが無い券種は欠落する。
    """
    con, k = _open(path, kind, immutable)
    try:
        out: dict = {}
        for name, tables, nh, ordered, okind in _SPECS:
            frames = []
            for tbl in tables:
                try:
                    df = _read(con, k,
                               f'SELECT * FROM "{tbl}" '
                               f'WHERE Year=? AND CAST(MonthDay AS INTEGER)=?',
                               [int(year), int(monthday)])
                except Exception:
                    continue
                if df is not None and len(df):
                    frames.append(df)
            if frames:
                _accumulate(out, pd.concat(frames, ignore_index=True),
                            name, nh, ordered, okind)
        return out
    finally:
        con.close()
