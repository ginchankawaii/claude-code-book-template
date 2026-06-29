"""tools/prune_realtime_odds.py のテスト。

実物の TS_O1 に合わせ、真の時間軸は HassoTime(発表時刻 MMDDHHMM)。
退避は (レース×馬番×HassoTime) で重複排除し、全スナップショット=軌跡を保持。
集計行(Umaban=0)は退避しない。CollectedAt はバーストで潰れるので軸に使わない。
"""

import importlib.util
import sqlite3
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "prune_realtime_odds",
    Path(__file__).resolve().parent.parent / "tools" / "prune_realtime_odds.py",
)
prune_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prune_mod)
prune = prune_mod.prune

# 実物 TS_O1 の主要列(簡略版)。HassoTime/Umaban/TanOdds/TanVote/CollectedAt を持つ。
_O1_COLS = ("Year", "MonthDay", "JyoCD", "Kaiji", "Nichiji", "RaceNum",
            "Umaban", "HassoTime", "TanOdds", "TanVote", "CollectedAt")

# 全行とも CollectedAt は同じ16秒窓(=取り込み時刻が潰れている実態を再現)
_BURST = "2026-06-27T04:59:51.500000+00:00"


def _row(umaban, hassotime, odds, vote):
    return (2026, 627, "05", 2, 1, 6, umaban, hassotime, odds, vote, _BURST)


def _make_main(path, rows):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE TS_O1(%s)" % ",".join(_O1_COLS))
    con.executemany(
        "INSERT INTO TS_O1 VALUES(%s)" % ",".join("?" * len(_O1_COLS)), rows)
    # 容量爆弾(三連単)も入れておく → 一掃対象
    con.execute("CREATE TABLE TS_O6(Year,MonthDay,JyoCD,RaceNum,Kumi,Odds,CollectedAt)")
    con.executemany("INSERT INTO TS_O6 VALUES(?,?,?,?,?,?,?)", [
        (2026, 627, "05", 6, "010203", 321.0, _BURST),
        (2026, 627, "05", 6, "010204", 998.0, _BURST),
    ])
    con.commit()
    con.close()


def test_prune_keeps_full_trajectory_and_drops_aggregate(tmp_path):
    main = tmp_path / "keiba.db"
    arch = tmp_path / "odds_history.db"
    _make_main(main, [
        # 1番: 3スナップ(発表時刻が違う=軌跡)。票数が増えていく=賢い金
        _row(1, "06262005", 16.2, 1155),
        _row(1, "06270923", 16.2, 38674),
        _row(1, "06271005", 24.5, 298186),
        # 2番: 1スナップ
        _row(2, "06271005", 3.1, 500000),
        # 集計行(Umaban=0)→ 退避されない
        _row(0, "06271005", 0.0, 9999999),
    ])

    res = prune(str(main), str(arch))

    # 実馬の全スナップショット(1番=3, 2番=1)=4 行。Umaban=0 は除外。
    assert res["archived"] == 4
    assert res["cleared"]["TS_O6"] == 2

    a = sqlite3.connect(str(arch))
    # 1番は3スナップショット=軌跡が壊れず保持されている(CollectedAtが同一でも潰れない)
    assert a.execute("SELECT COUNT(*) FROM TS_O1 WHERE Umaban=1").fetchone()[0] == 3
    # 票数の増加(賢い金)がそのまま残る
    votes = [r[0] for r in a.execute(
        "SELECT TanVote FROM TS_O1 WHERE Umaban=1 ORDER BY HassoTime")]
    assert votes == [1155, 38674, 298186]
    # 集計行(Umaban=0)は退避されていない
    assert a.execute("SELECT COUNT(*) FROM TS_O1 WHERE Umaban=0").fetchone()[0] == 0
    a.close()

    # 本体は一掃済み
    m = sqlite3.connect(str(main))
    assert m.execute("SELECT COUNT(*) FROM TS_O1").fetchone()[0] == 0
    assert m.execute("SELECT COUNT(*) FROM TS_O6").fetchone()[0] == 0
    m.close()


def test_prune_is_idempotent_across_sessions(tmp_path):
    # 前週分の再取得(同一スナップショット)は重複しない
    main = tmp_path / "keiba.db"
    arch = tmp_path / "odds_history.db"
    rows = [_row(1, "06271005", 24.5, 298186), _row(2, "06271005", 3.1, 500000)]
    _make_main(main, rows)
    prune(str(main), str(arch))

    con = sqlite3.connect(str(main))
    con.executemany(
        "INSERT INTO TS_O1 VALUES(%s)" % ",".join("?" * len(_O1_COLS)), rows)
    con.commit()
    con.close()
    res2 = prune(str(main), str(arch))

    assert res2["archived"] == 0   # 同一(レース×馬番×発表時刻)は無視
    a = sqlite3.connect(str(arch))
    assert a.execute("SELECT COUNT(*) FROM TS_O1").fetchone()[0] == 2
    a.close()


def test_prune_no_tables_is_noop(tmp_path):
    main = tmp_path / "empty.db"
    sqlite3.connect(str(main)).close()
    res = prune(str(main), str(tmp_path / "arch.db"))
    assert res == {"archived": 0, "cleared": {}}
