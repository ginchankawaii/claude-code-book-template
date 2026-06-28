"""realtime 速報オッズの剪定: 単勝/複勝の時系列を別DBへ「1分間引き」で退避し、
本体DBの速報オッズ表(TS_O1..O6 / TS_SOKUHO_O1..O6)を一掃する。

実測でわかったこと(2026-06 時点の jrvltsql realtime 0B30)
------------------------------------------------------------
* リアルタイムの単複オッズは **TS_O1** に入る(TS_SOKUHO_O1 ではない)。
  列: RecordSpec.. Year,MonthDay,JyoCD,Kaiji,Nichiji,RaceNum,HassoTime,
      Umaban,TanOdds,TanNinki,FukuOddsLow/High,.. ,CollectedAt(取得時刻)。
* realtime は数秒ごとに再取り込みするため TS_O1 が猛烈に増える(同一馬・同一オッズの
  超細かいスナップショットが大量)。賢い金シグナルに必要なのは秒単位ではないので、
  **(レース×馬番×分) 単位に間引いて**(各分の最後の値だけ)退避する。
* 三連単等(TS_O2..O6)は本実験に不要なので退避せず一掃のみ。

VACUUM はしない
---------------
本体 keiba.db は約21GB。VACUUM は同等の一時領域を要し、空き容量不足で危険。
DELETE は縮めないが空きページは翌週再利用されるため本体は頭打ち。退避先
odds_history.db は1分間引きなので小さい(年200〜400MB程度)。

冪等性
------
退避先に (レース×馬番×CollectedAt) のユニーク索引を張り INSERT OR IGNORE で積む。
realtime の1週間保持で前週分を再取得しても重複しない。

使い方
------
    python tools/prune_realtime_odds.py --db   C:\\keiba_ateru\\jrvltsql\\data\\keiba.db \\
                                        --archive C:\\keiba_ateru\\jrvltsql\\data\\odds_history.db

realtime プロセスを**停止した後**に実行すること。
"""

from __future__ import annotations

import argparse
import sqlite3

KEEP = "TS_O1"   # 退避する実テーブル(単複オッズの時系列)
# 一掃する速報オッズ表(現行 TS_O* と、空のレガシー TS_SOKUHO_O* の両方を防御的に)
CLEAR = [f"TS_O{i}" for i in range(1, 7)] + [f"TS_SOKUHO_O{i}" for i in range(1, 7)]
# レース＋馬番のキー(間引きとユニーク索引に使う)
KEYS = ["Year", "MonthDay", "JyoCD", "Kaiji", "Nichiji", "RaceNum", "Umaban"]


def _exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name]
    ).fetchone() is not None


def _cols(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def prune(main_db: str, archive_db: str) -> dict:
    """単複オッズ(TS_O1)を1分間引きで archive へ退避し、本体の速報オッズ表を一掃。

    退避(commit)→ 一掃(commit) の順。退避に失敗したら一掃しない。
    返り値 {"archived": 退避行数, "cleared": {table: 削除行数}}。
    """
    con = sqlite3.connect(str(main_db))
    try:
        con.execute("ATTACH ? AS arch", [str(archive_db)])
        archived = 0
        if _exists(con, KEEP):
            cols = _cols(con, KEEP)
            collist = ",".join(f'"{c}"' for c in cols)
            keys = [k for k in KEYS if k in cols]
            downsample = ("CollectedAt" in cols) and (len(keys) == len(KEYS))

            con.execute(
                f'CREATE TABLE IF NOT EXISTS arch."{KEEP}" AS SELECT * FROM "{KEEP}" WHERE 0')
            if downsample:
                uniq = ",".join(f'"{c}"' for c in keys + ["CollectedAt"])
                con.execute(
                    f'CREATE UNIQUE INDEX IF NOT EXISTS arch."ux_ts_o1" ON "{KEEP}" ({uniq})')

            before = con.execute(f'SELECT COUNT(*) FROM arch."{KEEP}"').fetchone()[0]
            if downsample:
                keylist = ",".join(f'"{k}"' for k in keys)
                # (レース×馬番×分) ごとに最後の CollectedAt の行だけを退避
                # CollectedAt は ISO形式 "YYYY-MM-DDTHH:MM:SS.ffffff+00:00"。
                # 分バケット = 先頭16文字 "YYYY-MM-DDTHH:MM"。
                con.execute(
                    f'INSERT OR IGNORE INTO arch."{KEEP}" ({collist}) '
                    f'SELECT {collist} FROM "{KEEP}" '
                    f'WHERE ({keylist},"CollectedAt") IN ('
                    f'  SELECT {keylist}, MAX("CollectedAt") FROM "{KEEP}" '
                    f'  GROUP BY {keylist}, substr("CollectedAt",1,16))')
            else:
                # 想定列が無い場合は素直に全行(冪等索引が無いので重複しうる点に注意)
                con.execute(
                    f'INSERT OR IGNORE INTO arch."{KEEP}" ({collist}) '
                    f'SELECT {collist} FROM "{KEEP}"')
            con.commit()
            after = con.execute(f'SELECT COUNT(*) FROM arch."{KEEP}"').fetchone()[0]
            archived = after - before

        cleared: dict[str, int] = {}
        for t in CLEAR:
            if _exists(con, t):
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                if n:
                    con.execute(f'DELETE FROM "{t}"')
                cleared[t] = int(n)
        con.commit()
        return {"archived": int(archived), "cleared": cleared}
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="realtime速報オッズの剪定(単複オッズTS_O1を1分間引きで退避し速報表を一掃)")
    p.add_argument("--db", required=True, help="本体DB(jltsqlが書く keiba.db)")
    p.add_argument("--archive", required=True,
                   help="単複オッズ時系列の蓄積先(無ければ作成。例 odds_history.db)")
    args = p.parse_args(argv)
    res = prune(args.db, args.archive)
    print(f"退避 {KEEP}(1分間引き): +{res['archived']:,} 行 → {args.archive}")
    cleared_nonzero = {t: n for t, n in res["cleared"].items() if n}
    if cleared_nonzero:
        for t, n in cleared_nonzero.items():
            print(f"  一掃 {t}: {n:,} 行 削除")
    else:
        print("  (速報オッズ表に行が無い=この開催は未取得。空振りでOK)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
