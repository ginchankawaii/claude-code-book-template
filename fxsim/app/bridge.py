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
                 expires_at: Optional[int] = None, sl: Optional[float] = None,
                 seq: Optional[int] = None) -> Path:
    """Atomically publish the target order ("LONG 0.10" | "FLAT 0").

    Atomic tmp+rename so the EA can never read a half-written line (a torn
    read parsed as lots=0 would flatten a healthy position).

    Optional suffix tokens (older EAs only parse the first two, so all are
    backward-compatible):
      " SEQ <n>"         — order identity. The signal file is a STANDING target
        that the EA re-executes every tick, so without this a heartbeat is
        indistinguishable from a new order and the EA re-buys a position that
        the broker stop just closed (round-5, critical). A sequence-aware EA
        may always reduce or close, but only opens/increases when SEQ changes.
      " EXP <unix-utc>"  — a heartbeat-aware EA treats an expired order as
        FLAT: the fail-safe for a dead (or blind — round-4) Python brain.
      " SL <price>"      — an SL-aware EA mirrors the brain's protective stop
        as a REAL broker stop order (round-4 equivalence: poll-granular Python
        stop fills cost ~3.4pp CAGR that a broker SL recovers for ~0.05% gap
        cost, and a broker SL keeps protecting through brain outages).
    """
    d = base or common_files_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / SIGNAL_FILE
    line = f"{action.upper()} {lots:.2f}"
    if seq:
        line += f" SEQ {int(seq)}"
    if expires_at:
        line += f" EXP {int(expires_at)}"
    if sl and sl > 0:
        line += f" SL {sl:.3f}"
    tmp = path.with_name(SIGNAL_FILE + ".tmp")
    tmp.write_text(line + "\n")
    os.replace(tmp, path)
    return path


def read_signal(base: Optional[Path] = None) -> Optional[dict]:
    """Parse the order currently standing on the bridge, or None.

    The brain reads this back on startup: the live order's SEQ must be REUSED
    by the heartbeat, never re-minted. A restart that minted a fresh SEQ would
    look to the EA like a brand-new order and re-open a position that had been
    stopped out while the brain was down.
    """
    path = (base or common_files_dir()) / SIGNAL_FILE
    try:
        parts = path.read_text().split()
    except (OSError, ValueError):
        return None
    if not parts:
        return None
    out: dict = {"action": parts[0].upper(), "lots": 0.0,
                 "seq": None, "expires_at": None, "sl": None}
    try:
        out["lots"] = float(parts[1]) if len(parts) >= 2 else 0.0
    except ValueError:
        return None
    for i in range(2, len(parts) - 1, 2):
        key, raw = parts[i].upper(), parts[i + 1]
        try:
            if key == "SEQ":
                out["seq"] = int(raw)
            elif key == "EXP":
                out["expires_at"] = int(raw)
            elif key == "SL":
                out["sl"] = float(raw)
        except ValueError:
            continue
    return out
