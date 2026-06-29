"""keiba: 連系オッズ(O2〜O6)ローダのテスト。"""

import datetime as dt
import sqlite3

from keiba.exotic_odds import load_exotic_odds_for_day, load_exotic_odds_for_days


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


def test_load_for_days_bulk_filters_kinds_and_days(tmp_path):
    # 年単位一括ローダ: 既定で馬連/ワイド/三連複のみ(三連単O6は読まない)、
    # かつ ordinals に含む開催日だけを返す。
    db = tmp_path / "k.db"
    _make_db(db)
    ord_605 = dt.date(2026, 6, 5).toordinal()   # 605 の race だけ欲しい(606は除外)
    odds = load_exotic_odds_for_days(db, [ord_605])
    rid_605 = 202602010501
    rid_606 = 202602010601
    assert rid_605 in odds
    assert rid_606 not in odds                  # 指定日でない開催は混ざらない
    assert odds[rid_605]["馬連"][(1, 2)] == 12.3
    assert odds[rid_605]["ワイド"][(1, 2)] == 4.0
    # 既定 kinds は三連単(O6)を含まない=巨大表を読まない
    assert "三連単" not in odds[rid_605]


def test_load_for_days_prunes_to_cheapest(tmp_path):
    # max_combos_per_race で人気上位(低オッズ)の組だけ残す。
    db = tmp_path / "k.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE NL_O2(Year,MonthDay,JyoCD,Kaiji,Nichiji,RaceNum,Kumi,Odds,MakeDate)")
    con.executemany("INSERT INTO NL_O2 VALUES(?,?,?,?,?,?,?,?,?)", [
        (2026, 605, "02", 1, 5, 1, "0102", 5.0, 20260605),
        (2026, 605, "02", 1, 5, 1, "0103", 9.0, 20260605),
        (2026, 605, "02", 1, 5, 1, "0104", 2.0, 20260605),
    ])
    con.commit()
    con.close()
    ord_605 = dt.date(2026, 6, 5).toordinal()
    odds = load_exotic_odds_for_days(db, [ord_605], max_combos_per_race=2)
    rid = 202602010501
    keep = odds[rid]["馬連"]
    assert len(keep) == 2                        # 上限2組に剪定
    assert set(keep) == {(1, 4), (1, 2)}         # 低オッズ2組(2.0, 5.0)が残る
    assert (1, 3) not in keep                    # 高オッズ(9.0)は落ちる
