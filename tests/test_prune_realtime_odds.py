"""tools/prune_realtime_odds.py のテスト(単勝退避＋本体一掃)。"""

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


def _make_main(path):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE TS_SOKUHO_O1(Year,MonthDay,JyoCD,RaceNum,Umaban,Odds,CollectedAt)")
    con.executemany("INSERT INTO TS_SOKUHO_O1 VALUES(?,?,?,?,?,?,?)", [
        (2026, "0704", "05", 11, 1, 3.2, "20260704101500"),
        (2026, "0704", "05", 11, 1, 2.8, "20260704102000"),  # 同じ馬の別時刻=軌跡
        (2026, "0704", "05", 11, 2, 9.9, "20260704102000"),
    ])
    # 容量爆弾(三連単)も入れておく → 一掃対象
    con.execute("CREATE TABLE TS_SOKUHO_O6(Year,MonthDay,JyoCD,RaceNum,Kumi,Odds,CollectedAt)")
    con.executemany("INSERT INTO TS_SOKUHO_O6 VALUES(?,?,?,?,?,?,?)", [
        (2026, "0704", "05", 11, "010203", 321.0, "20260704102000"),
        (2026, "0704", "05", 11, "010204", 998.0, "20260704102000"),
    ])
    con.commit()
    con.close()


def test_prune_archives_o1_and_clears_all(tmp_path):
    main = tmp_path / "keiba.db"
    arch = tmp_path / "odds_history.db"
    _make_main(main)

    res = prune(str(main), str(arch))

    assert res["archived"] == 3
    assert res["cleared"]["TS_SOKUHO_O1"] == 3
    assert res["cleared"]["TS_SOKUHO_O6"] == 2

    # 退避先に単勝の時系列が残っている(同一馬の複数CollectedAt=軌跡)
    a = sqlite3.connect(str(arch))
    assert a.execute("SELECT COUNT(*) FROM TS_SOKUHO_O1").fetchone()[0] == 3
    snaps = a.execute(
        "SELECT COUNT(*) FROM TS_SOKUHO_O1 WHERE Umaban=1").fetchone()[0]
    assert snaps == 2   # 1番の馬は2スナップショット = 軌跡が取れている
    a.close()

    # 本体は一掃済み(O1もO6も0行)
    m = sqlite3.connect(str(main))
    assert m.execute("SELECT COUNT(*) FROM TS_SOKUHO_O1").fetchone()[0] == 0
    assert m.execute("SELECT COUNT(*) FROM TS_SOKUHO_O6").fetchone()[0] == 0
    m.close()


def test_prune_accumulates_across_sessions(tmp_path):
    # 2回目の取得分も退避先に積み増される(消えない)
    main = tmp_path / "keiba.db"
    arch = tmp_path / "odds_history.db"
    _make_main(main)
    prune(str(main), str(arch))

    # 別開催の取得をシミュレート(本体に再投入)
    con = sqlite3.connect(str(main))
    con.executemany("INSERT INTO TS_SOKUHO_O1 VALUES(?,?,?,?,?,?,?)", [
        (2026, "0705", "05", 11, 1, 4.0, "20260705101500"),
    ])
    con.commit()
    con.close()
    res2 = prune(str(main), str(arch))

    assert res2["archived"] == 1
    a = sqlite3.connect(str(arch))
    assert a.execute("SELECT COUNT(*) FROM TS_SOKUHO_O1").fetchone()[0] == 4  # 3 + 1
    a.close()


def test_prune_no_tables_is_noop(tmp_path):
    # 開催が無くTS_SOKUHOが存在しない日でも落ちない
    main = tmp_path / "empty.db"
    sqlite3.connect(str(main)).close()
    res = prune(str(main), str(tmp_path / "arch.db"))
    assert res == {"archived": 0, "cleared": {}}
