"""File-bridge between the Python brain and an MQL5 EA running inside MT5.

Why: on some MT5 builds the official `MetaTrader5` Python IPC fails (IPC
timeout) even though the terminal itself works fine. This bridge sidesteps the
IPC entirely by exchanging plain files in MT5's shared "Common\\Files" folder:

  EA  -> Python :  steady_bars.csv    (recent daily OHLC)
  EA  -> Python :  steady_status.csv  (balance, equity, position_lots)
  Python -> EA  :  steady_signal.txt  ("LONG <lots>[ EXP <unix>]" | "FLAT 0[ EXP <unix>]")

The EA writes bars/status and executes whatever signal Python last wrote. Python
reads bars/status, runs the trend + adaptive-risk logic, and writes the signal.
Both sides are build-independent and need no network.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .providers.csv import load_csv_file

BARS_FILE = "steady_bars.csv"
STATUS_FILE = "steady_status.csv"
SIGNAL_FILE = "steady_signal.txt"


def common_files_dir() -> Path:
    """MT5 shared files dir: %APPDATA%\\MetaQuotes\\Terminal\\Common\\Files."""
    override = os.getenv("MT5_COMMON_FILES")
    if override:
        return Path(override)
    appdata = os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"


def read_bars(instrument: str = "USD_JPY", granularity: str = "D",
              base: Optional[Path] = None):
    path = (base or common_files_dir()) / BARS_FILE
    if not path.exists():
        return []
    return load_csv_file(path, instrument, granularity)


def read_status(base: Optional[Path] = None) -> Optional[dict]:
    path = (base or common_files_dir()) / STATUS_FILE
    if not path.exists():
        return None
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        row = lines[-1].split(",")
        return {"balance": float(row[0]), "equity": float(row[1]),
                "position_lots": float(row[2])}
    except (ValueError, IndexError, OSError):
        return None


def write_signal(action: str, lots: float, base: Optional[Path] = None,
                 expires_at: Optional[int] = None) -> Path:
    """Atomically publish the target order ("LONG 0.10" | "FLAT 0").

    Atomic tmp+rename so the EA can never read a half-written line (a torn
    read parsed as lots=0 would flatten a healthy position).

    With ``expires_at`` (unix epoch, UTC) an " EXP <epoch>" suffix is appended:
    a heartbeat-aware EA treats an expired order as FLAT — the fail-safe for a
    dead Python brain, which holds the only protective stop. Older EAs ignore
    the extra tokens (they only parse the first two), so the suffix is
    backward-compatible.
    """
    d = base or common_files_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / SIGNAL_FILE
    line = f"{action.upper()} {lots:.2f}"
    if expires_at:
        line += f" EXP {int(expires_at)}"
    tmp = path.with_name(SIGNAL_FILE + ".tmp")
    tmp.write_text(line + "\n")
    os.replace(tmp, path)
    return path
