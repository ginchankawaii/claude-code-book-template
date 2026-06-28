"""tools/prune_realtime_odds.py のテスト(TS_O1の1分間引き退避＋速報表一掃)。"""

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

# 実物 TS_O1 の主要列(簡略版)
_O1_COLS = ("Year", "MonthDay", "JyoCD", "Kaiji", "Nichiji", "RaceNum",
            "HassoTime", "Umaban", "TanOdds", "CollectedAt")


def _make_main(path, rows):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE TS_O1(%s)" % ",".join(_O1_COLS))
    con.executemany(
        "INSERT INTO TS_O1 VALUES(%s)" % ",".join("?" * len(_O1_COLS)), rows)
    # 容量爆弾(三連単)も入れておく → 一掃対象
    con.execute("CREATE TABLE TS_O6(Year,MonthDay,JyoCD,RaceNum,Kumi,Odds,CollectedAt)")
    con.executemany("INSERT INTO TS_O6 VALUES(?,?,?,?,?,?,?)", [
        (2026, 628, "05", 11, "010203", 321.0, "20260628102001"),
        (2026, 628, "05", 11, "010204", 998.0, "20260628102002"),
    ])
    con.commit()
    con.close()


def _row(umaban, odds, collected):
    return (2026, 628, "05", 1, 5, 11, "1500", umaban, odds, collected)


def test_prune_downsamples_to_per_minute_and_clears(tmp_path):
    main = tmp_path / "keiba.db"
    arch = tmp_path / "odds_history.db"
    # 1番: 同じ分(10:15)に3スナップ + 別の分(10:20)に1スナップ → 間引きで 2 行
    # 2番: 10:15 に1スナップ → 1 行
    _make_main(main, [
        _row(1, 3.4, "20260628101501"),
        _row(1, 3.2, "20260628101533"),
        _row(1, 3.0, "20260628101559"),   # 10:15 の最後 → これだけ残る(3.0)
        _row(1, 2.6, "20260628102004"),   # 10:20 → 残る
        _row(2, 9.9, "20260628101510"),
    ])

    res = prune(str(main), str(arch))

    # 退避は (馬×分) 単位に間引かれて 3 行(1番=2, 2番=1)
    assert res["archived"] == 3
    assert res["cleared"]["TS_O6"] == 2

    a = sqlite3.connect(str(arch))
    # 1番は2スナップショット=軌跡が取れている
    assert a.execute("SELECT COUNT(*) FROM TS_O1 WHERE Umaban=1").fetchone()[0] == 2
    # 10:15 帯は最後の値(3.0)が残る(3.4/3.2は間引かれる)
    got = a.execute(
        "SELECT TanOdds FROM TS_O1 WHERE Umaban=1 AND substr(CollectedAt,1,12)='202606281015'"
    ).fetchall()
    assert got == [(3.0,)]
    a.close()

    # 本体は一掃済み
    m = sqlite3.connect(str(main))
    assert m.execute("SELECT COUNT(*) FROM TS_O1").fetchone()[0] == 0
    assert m.execute("SELECT COUNT(*) FROM TS_O6").fetchone()[0] == 0
    m.close()


def test_prune_is_idempotent_across_sessions(tmp_path):
    # 前週分を再取得しても重複しない(ユニーク索引 + INSERT OR IGNORE)
    main = tmp_path / "keiba.db"
    arch = tmp_path / "odds_history.db"
    rows = [_row(1, 3.0, "20260628101559"), _row(2, 9.9, "20260628101510")]
    _make_main(main, rows)
    prune(str(main), str(arch))

    # まったく同じ行を再投入(本体テーブルは prune後も残り空になっている)してもう一度剪定
    con = sqlite3.connect(str(main))
    con.executemany(
        "INSERT INTO TS_O1 VALUES(%s)" % ",".join("?" * len(_O1_COLS)), rows)
    con.commit()
    con.close()
    res2 = prune(str(main), str(arch))

    assert res2["archived"] == 0   # 重複は無視される
    a = sqlite3.connect(str(arch))
    assert a.execute("SELECT COUNT(*) FROM TS_O1").fetchone()[0] == 2
    a.close()


def test_prune_no_tables_is_noop(tmp_path):
    main = tmp_path / "empty.db"
    sqlite3.connect(str(main)).close()
    res = prune(str(main), str(tmp_path / "arch.db"))
    assert res == {"archived": 0, "cleared": {}}
