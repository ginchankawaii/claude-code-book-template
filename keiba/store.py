"""取得層と分析層の境界となる DuckDB 永続化レイヤ。

取得層(JV-Link/Windows)が正規化済みの runners/races を DuckDB ファイルに
書き出し、分析層(本パッケージ/Linux)はそのファイルを読むだけで完結する。
これにより両層を物理的に疎結合にし、サンドボックスでも分析層を実行できる。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    import duckdb
except Exception as exc:  # pragma: no cover
    duckdb = None
    _DUCKDB_ERR = exc

from .reader import JVLinkReader


def save_dataset(runners: pd.DataFrame, races: pd.DataFrame, path: str | Path) -> Path:
    """runners/races を DuckDB ファイルに保存する。"""
    if duckdb is None:  # pragma: no cover
        raise ImportError(f"duckdb が必要です: {_DUCKDB_ERR}")
    path = Path(path)
    con = duckdb.connect(str(path))
    try:
        con.register("runners_df", runners)
        con.register("races_df", races)
        con.execute("CREATE OR REPLACE TABLE runners AS SELECT * FROM runners_df")
        con.execute("CREATE OR REPLACE TABLE races AS SELECT * FROM races_df")
    finally:
        con.close()
    return path


def load_dataset(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DuckDB ファイルから (runners, races) を読み込む。"""
    if duckdb is None:  # pragma: no cover
        raise ImportError(f"duckdb が必要です: {_DUCKDB_ERR}")
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    con = duckdb.connect(str(path), read_only=True)
    try:
        runners = con.execute("SELECT * FROM runners").fetchdf()
        races = con.execute("SELECT * FROM races").fetchdf()
    finally:
        con.close()
    return runners, races


class DuckDBBackend(JVLinkReader):
    """DuckDB ファイルを読み込むバックエンド(取得層が書き出した境界を読む)。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        return load_dataset(self.path)
