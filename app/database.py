"""SQLite データベースの初期化とコネクション管理。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    cash          REAL NOT NULL,
    starting_cash REAL NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holdings (
    code     TEXT PRIMARY KEY,
    name     TEXT,
    quantity INTEGER NOT NULL,
    avg_cost REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    code        TEXT NOT NULL,
    name        TEXT,
    side        TEXT NOT NULL,            -- BUY / SELL
    quantity    INTEGER NOT NULL,
    price       REAL NOT NULL,
    amount      REAL NOT NULL,            -- price * quantity
    realized_pl REAL,                     -- 売却時の実現損益
    decided_by  TEXT NOT NULL,            -- manual / claude
    reason      TEXT
);

CREATE TABLE IF NOT EXISTS watchlist (
    code     TEXT PRIMARY KEY,
    name     TEXT,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    code       TEXT NOT NULL,
    name       TEXT,
    action     TEXT NOT NULL,             -- BUY / SELL / HOLD
    quantity   INTEGER,
    confidence REAL,
    rationale  TEXT,
    executed   INTEGER NOT NULL DEFAULT 0,
    model      TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """スキーマ作成と初期データ投入（口座・ウォッチリスト）。"""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        # 口座が無ければ初期資金で作成
        row = conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO account (id, cash, starting_cash, created_at) "
                "VALUES (1, ?, ?, ?)",
                (config.STARTING_CASH, config.STARTING_CASH, now_iso()),
            )
        # ウォッチリストが空ならデフォルト銘柄を投入
        count = conn.execute("SELECT COUNT(*) AS c FROM watchlist").fetchone()["c"]
        if count == 0:
            for code in config.DEFAULT_WATCHLIST:
                conn.execute(
                    "INSERT OR IGNORE INTO watchlist (code, name, added_at) "
                    "VALUES (?, ?, ?)",
                    (code, config.KNOWN_NAMES.get(code), now_iso()),
                )
        conn.commit()
    finally:
        conn.close()


def reset_db() -> None:
    """シミュレーションを初期状態に戻す（取引・保有・判断履歴を全削除）。"""
    conn = connect()
    try:
        conn.executescript(
            """
            DELETE FROM trades;
            DELETE FROM holdings;
            DELETE FROM decisions;
            """
        )
        conn.execute(
            "UPDATE account SET cash = starting_cash WHERE id = 1"
        )
        conn.commit()
    finally:
        conn.close()
