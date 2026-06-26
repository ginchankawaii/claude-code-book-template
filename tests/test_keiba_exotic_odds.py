"""keiba: 連系オッズ(O2〜O6)ローダのテスト。"""

import sqlite3

from keiba.exotic_odds import load_exotic_odds_for_day


def _make_db(path):
    con = sqlite3.connect(str(path))
    cur = con.cursor()
    # 馬連(O2): 順不問・Odds
    cur.execute("CREATE TABLE NL_O2(Year,MonthDay,JyoCD,Kaiji,Nichiji,RaceNum,Kumi,Odds,MakeDate)")
    cur.executemany("INSERT INTO NL_O2 VALUES(?,?,?,?,?,?,?,?,?)", [
        (2026, 605, "02", 1, 5, 1, "0102", 12.3, 20260605),
        (2026, 605, "02", 1, 5, 1, "0203", 45.6, 20260605),
        # 別日(無視されるべき)
        (2026, 606, "02", 1, 6, 1, "0102", 99.9, 20260606),
    ])
    # ワイド(O3): OddsLow/High → 中央値
    cur.execute("CREATE TABLE NL_O3(Year,MonthDay,JyoCD,Kaiji,Nichiji,RaceNum,Kumi,OddsLow,OddsHigh,MakeDate)")
    cur.executemany("INSERT INTO NL_O3 VALUES(?,?,?,?,?,?,?,?,?,?)", [
        (2026, 605, "02", 1, 5, 1, "0102", 3.0, 5.0, 20260605),
    ])
    # 三連単(O6): 順序保持
    cur.execute("CREATE TABLE NL_O6(Year,MonthDay,JyoCD,Kaiji,Nichiji,RaceNum,Kumi,Odds,MakeDate)")
    cur.executemany("INSERT INTO NL_O6 VALUES(?,?,?,?,?,?,?,?,?)", [
        (2026, 605, "02", 1, 5, 1, "010203", 321.0, 20260605),
    ])
    con.commit()
    con.close()


def test_load_for_day(tmp_path):
    db = tmp_path / "k.db"
    _make_db(db)
    odds = load_exotic_odds_for_day(db, 2026, 605)
    rid = 202602010501
    assert rid in odds
    # 馬連: ソート済キー、別日は混ざらない
    assert odds[rid]["馬連"][(1, 2)] == 12.3
    assert odds[rid]["馬連"][(2, 3)] == 45.6
    # ワイドは中央値(3.0,5.0)→4.0
    assert odds[rid]["ワイド"][(1, 2)] == 4.0
    # 三連単は順序保持
    assert odds[rid]["三連単"][(1, 2, 3)] == 321.0


def test_other_day_empty(tmp_path):
    db = tmp_path / "k.db"
    _make_db(db)
    assert load_exotic_odds_for_day(db, 2026, 701) == {}
