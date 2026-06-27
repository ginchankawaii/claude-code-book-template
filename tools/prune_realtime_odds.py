"""realtime 速報オッズの剪定: 単勝の時系列(TS_SOKUHO_O1)を別DBへ退避し、
本体DBの TS_SOKUHO_O1..O6 を一掃する。

なぜ必要か
----------
realtime の 0B30(全賭式リアルタイムオッズ)は単複だけでなく三連単まで全部の
中間オッズを書き込む。三連単(O6)の5分刻みスナップショットは1開催で数百万行=
数百MB〜GB に達する「容量爆弾」。一方、賢い金(スマートマネー)シグナルに必要なのは
**単勝の時系列だけ**。

そこで毎セッション後にこのスクリプトを呼び、
  1) 単勝(TS_SOKUHO_O1)を小さな odds_history.db に積み増し(退避)
  2) 本体の TS_SOKUHO_O1..O6 を全削除(本体DBの肥大を断つ)
を行う。

VACUUM はしない
---------------
本体 keiba.db は約21GB。SQLite の VACUUM は元サイズと同等の一時領域(≒21GB)を要し、
Cドライブの空き(約19GB)では失敗してディスクを溢れさせる危険がある。DELETE は
ファイルを縮めないが、空きページは翌週の取得で再利用されるため、本体は高々
「1開催分」だけ増えて頭打ちになる。これが容量安全のための意図的な設計。

使い方
------
    python tools/prune_realtime_odds.py --db C:\\keiba_ateru\\jrvltsql\\data\\keiba.db \\
                                        --archive C:\\keiba_ateru\\jrvltsql\\data\\odds_history.db

realtime プロセスを**停止した後**に実行すること(書き込み中に走らせない)。
"""

from __future__ import annotations

import argparse
import sqlite3

# 速報オッズ各賭式(O1=単複, O2=馬連, O3=ワイド, O4=馬単, O5=三連複, O6=三連単)
TS_TABLES = [f"TS_SOKUHO_O{i}" for i in range(1, 7)]
KEEP = "TS_SOKUHO_O1"   # これだけ退避して残す(賢い金=単勝の動き)


def _exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name]
    ).fetchone()
    return row is not None


def prune(main_db: str, archive_db: str) -> dict:
    """単勝軌跡を archive へ退避し、本体の TS_SOKUHO_* を一掃する。

    退避(commit)→ 一掃(commit) の順。退避に失敗したら一掃しない(データを失わない)。
    返り値 {"archived": 退避行数, "cleared": {table: 削除行数}}。
    """
    con = sqlite3.connect(str(main_db))
    try:
        con.execute("ATTACH ? AS arch", [str(archive_db)])
        archived = 0
        if _exists(con, KEEP):
            # 退避先テーブルを本体と同じ列構成で用意(無ければ作る)
            con.execute(
                f'CREATE TABLE IF NOT EXISTS arch."{KEEP}" AS SELECT * FROM "{KEEP}" WHERE 0'
            )
            before = con.execute(f'SELECT COUNT(*) FROM arch."{KEEP}"').fetchone()[0]
            con.execute(f'INSERT INTO arch."{KEEP}" SELECT * FROM "{KEEP}"')
            con.commit()   # 先に退避を確定させてから削除に進む
            after = con.execute(f'SELECT COUNT(*) FROM arch."{KEEP}"').fetchone()[0]
            archived = after - before

        cleared: dict[str, int] = {}
        for t in TS_TABLES:
            if _exists(con, t):
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                con.execute(f'DELETE FROM "{t}"')
                cleared[t] = int(n)
        con.commit()
        return {"archived": int(archived), "cleared": cleared}
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="realtime速報オッズの剪定(単勝軌跡を退避し本体TS_SOKUHOを一掃)")
    p.add_argument("--db", required=True, help="本体DB(jltsqlが書く keiba.db)")
    p.add_argument("--archive", required=True,
                   help="単勝軌跡の蓄積先(無ければ作成。例 odds_history.db)")
    args = p.parse_args(argv)
    res = prune(args.db, args.archive)
    print(f"退避 TS_SOKUHO_O1: +{res['archived']:,} 行 → {args.archive}")
    if res["cleared"]:
        for t, n in res["cleared"].items():
            print(f"  一掃 {t}: {n:,} 行 削除")
    else:
        print("  (TS_SOKUHO_* が無い=この開催はオッズ未取得。空振りでOK)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
