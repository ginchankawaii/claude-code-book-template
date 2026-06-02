"""SQLite persistence layer.

Schema (kept intentionally small/simple per the brief):
  candles  – cached OHLCV bars
  runs     – one backtest or live session
  trades   – closed & open positions with realized P&L
  equity   – equity-curve snapshots over time
  signals  – per-step strategy output (technical / fundamental / combined)
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional

from .config import settings
from .models import Candle

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    instrument  TEXT NOT NULL,
    granularity TEXT NOT NULL,
    time        TEXT NOT NULL,
    open        REAL NOT NULL,
    high        REAL NOT NULL,
    low         REAL NOT NULL,
    close       REAL NOT NULL,
    volume      REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (instrument, granularity, time)
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mode        TEXT NOT NULL,            -- 'backtest' | 'live'
    instrument  TEXT NOT NULL,
    granularity TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    initial_balance REAL NOT NULL,
    params      TEXT                      -- json blob of settings used
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    instrument  TEXT NOT NULL,
    side        TEXT NOT NULL,            -- 'LONG' | 'SHORT'
    units       INTEGER NOT NULL,
    entry_time  TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_time   TEXT,
    exit_price  REAL,
    pnl         REAL,
    status      TEXT NOT NULL,            -- 'OPEN' | 'CLOSED'
    reason      TEXT
);

CREATE TABLE IF NOT EXISTS equity (
    run_id  INTEGER NOT NULL REFERENCES runs(id),
    time    TEXT NOT NULL,
    balance REAL NOT NULL,
    equity  REAL NOT NULL,
    price   REAL,
    PRIMARY KEY (run_id, time)
);

CREATE TABLE IF NOT EXISTS signals (
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    time       TEXT NOT NULL,
    instrument TEXT NOT NULL,
    source     TEXT NOT NULL,            -- 'technical' | 'fundamental' | 'combined'
    direction  INTEGER NOT NULL,
    score      REAL NOT NULL,
    reason     TEXT,
    components TEXT,
    PRIMARY KEY (run_id, time, source)
);

CREATE INDEX IF NOT EXISTS idx_trades_run ON trades(run_id);
CREATE INDEX IF NOT EXISTS idx_equity_run ON equity(run_id);
CREATE INDEX IF NOT EXISTS idx_signals_run ON signals(run_id);
"""


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


@contextmanager
def connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path or settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------- #
# candles
# --------------------------------------------------------------------------- #
def upsert_candles(candles: Iterable[Candle], db_path: Optional[str] = None) -> int:
    rows = [
        (c.instrument, c.granularity, _iso(c.time), c.open, c.high, c.low, c.close, c.volume)
        for c in candles
    ]
    if not rows:
        return 0
    with connect(db_path) as conn:
        conn.executemany(
            """INSERT INTO candles(instrument,granularity,time,open,high,low,close,volume)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(instrument,granularity,time) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume""",
            rows,
        )
    return len(rows)


def load_candles(
    instrument: str, granularity: str, db_path: Optional[str] = None
) -> list[Candle]:
    with connect(db_path) as conn:
        cur = conn.execute(
            """SELECT * FROM candles WHERE instrument=? AND granularity=?
               ORDER BY time ASC""",
            (instrument, granularity),
        )
        return [
            Candle(
                instrument=r["instrument"],
                granularity=r["granularity"],
                time=_parse(r["time"]),
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
            )
            for r in cur.fetchall()
        ]


# --------------------------------------------------------------------------- #
# runs
# --------------------------------------------------------------------------- #
def create_run(
    mode: str,
    instrument: str,
    granularity: str,
    initial_balance: float,
    params: dict,
    db_path: Optional[str] = None,
) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO runs(mode,instrument,granularity,started_at,initial_balance,params)
               VALUES (?,?,?,?,?,?)""",
            (
                mode,
                instrument,
                granularity,
                _iso(datetime.now(timezone.utc)),
                initial_balance,
                json.dumps(params, default=str),
            ),
        )
        return int(cur.lastrowid)


def finish_run(run_id: int, db_path: Optional[str] = None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET ended_at=? WHERE id=?",
            (_iso(datetime.now(timezone.utc)), run_id),
        )


def list_runs(db_path: Optional[str] = None) -> list[dict]:
    with connect(db_path) as conn:
        cur = conn.execute("SELECT * FROM runs ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]


def get_run(run_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    with connect(db_path) as conn:
        cur = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def latest_run_id(db_path: Optional[str] = None) -> Optional[int]:
    with connect(db_path) as conn:
        cur = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return int(row["id"]) if row else None


# --------------------------------------------------------------------------- #
# trades
# --------------------------------------------------------------------------- #
def open_trade(
    run_id: int,
    instrument: str,
    side: str,
    units: int,
    entry_time: datetime,
    entry_price: float,
    reason: str,
    db_path: Optional[str] = None,
) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO trades(run_id,instrument,side,units,entry_time,entry_price,status,reason)
               VALUES (?,?,?,?,?,?, 'OPEN', ?)""",
            (run_id, instrument, side, units, _iso(entry_time), entry_price, reason),
        )
        return int(cur.lastrowid)


def close_trade(
    trade_id: int,
    exit_time: datetime,
    exit_price: float,
    pnl: float,
    reason: str,
    db_path: Optional[str] = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """UPDATE trades SET exit_time=?, exit_price=?, pnl=?, status='CLOSED', reason=?
               WHERE id=?""",
            (_iso(exit_time), exit_price, pnl, reason, trade_id),
        )


def list_trades(run_id: int, db_path: Optional[str] = None) -> list[dict]:
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM trades WHERE run_id=? ORDER BY id ASC", (run_id,)
        )
        return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# equity & signals
# --------------------------------------------------------------------------- #
def record_equity(
    run_id: int,
    time: datetime,
    balance: float,
    equity: float,
    price: float,
    db_path: Optional[str] = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO equity(run_id,time,balance,equity,price) VALUES (?,?,?,?,?)
               ON CONFLICT(run_id,time) DO UPDATE SET
                 balance=excluded.balance, equity=excluded.equity, price=excluded.price""",
            (run_id, _iso(time), balance, equity, price),
        )


def load_equity(run_id: int, db_path: Optional[str] = None) -> list[dict]:
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM equity WHERE run_id=? ORDER BY time ASC", (run_id,)
        )
        return [dict(r) for r in cur.fetchall()]


def record_signal(
    run_id: int,
    time: datetime,
    instrument: str,
    source: str,
    direction: int,
    score: float,
    reason: str,
    components: dict,
    db_path: Optional[str] = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO signals(run_id,time,instrument,source,direction,score,reason,components)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(run_id,time,source) DO UPDATE SET
                 direction=excluded.direction, score=excluded.score,
                 reason=excluded.reason, components=excluded.components""",
            (
                run_id,
                _iso(time),
                instrument,
                source,
                direction,
                score,
                reason,
                json.dumps(components, default=str),
            ),
        )


def load_signals(run_id: int, db_path: Optional[str] = None) -> list[dict]:
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM signals WHERE run_id=? ORDER BY time ASC", (run_id,)
        )
        return [dict(r) for r in cur.fetchall()]
