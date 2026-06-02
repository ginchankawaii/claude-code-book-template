"""CSV data provider — broker-agnostic historical data loader.

Lets you backtest on REAL data exported from any broker (e.g. セントラル短資FX
のヒストリカルデータ, MT4/MT5 export, Dukascopy, etc.) with no API or network
allow-listing required.

The loader is deliberately forgiving:
  * delimiter auto-detected (comma / tab / semicolon)
  * encoding tried in order: utf-8-sig, utf-8, cp932 (Shift-JIS for JP brokers)
  * column names matched case-insensitively against many common aliases
  * datetime accepted either as one column or as separate date + time columns

Place files at  data/<INSTRUMENT>.csv  (e.g. data/USD_JPY.csv) or pass an
explicit path. Use FXSIM_PROVIDER=csv.
"""
from __future__ import annotations

import csv as _csv
import io
from datetime import datetime, timezone
from pathlib import Path

from ..config import DATA_DIR
from ..models import Candle
from .base import DataProvider

_TIME_ALIASES = ["time", "datetime", "date_time", "timestamp", "日時", "日付時刻", "日付"]
_DATE_ALIASES = ["date", "日付", "年月日"]
_CLOCK_ALIASES = ["time", "時刻", "時間"]
_OPEN_ALIASES = ["open", "o", "始値", "open price"]
_HIGH_ALIASES = ["high", "h", "高値", "high price"]
_LOW_ALIASES = ["low", "l", "安値", "low price"]
_CLOSE_ALIASES = ["close", "c", "終値", "close price", "終値(bid)", "終値（bid）"]
_VOL_ALIASES = ["volume", "vol", "v", "出来高", "tickvol", "tick_volume"]

_DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y%m%d %H%M%S", "%Y%m%d",
    "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S",
]


class CsvProvider(DataProvider):
    name = "csv"

    def __init__(self, base_dir: Path = DATA_DIR) -> None:
        self.base_dir = Path(base_dir)

    def _resolve(self, instrument: str) -> Path:
        # try a few common file-name spellings
        candidates = [
            self.base_dir / f"{instrument}.csv",
            self.base_dir / f"{instrument.replace('_', '')}.csv",
            self.base_dir / f"{instrument.replace('_', '-')}.csv",
            self.base_dir / f"{instrument.lower()}.csv",
        ]
        for c in candidates:
            if c.exists():
                return c
        raise FileNotFoundError(
            f"No CSV for {instrument}. Looked for: "
            + ", ".join(str(c.name) for c in candidates)
            + f" under {self.base_dir}/"
        )

    def history(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        path = self._resolve(instrument)
        candles = load_csv_file(path, instrument, granularity)
        return candles[-count:] if count else candles


def _read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_text(errors="replace")


def _sniff_delimiter(sample: str) -> str:
    try:
        return _csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except _csv.Error:
        return ","


def _find(header: list[str], aliases: list[str]) -> int | None:
    norm = [h.strip().lower() for h in header]
    for alias in aliases:
        a = alias.lower()
        for i, h in enumerate(norm):
            if h == a:
                return i
    # fall back to substring match
    for alias in aliases:
        a = alias.lower()
        for i, h in enumerate(norm):
            if a in h:
                return i
    return None


def _parse_dt(value: str) -> datetime:
    value = value.strip().strip('"')
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:  # last resort: ISO
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Unrecognised datetime: {value!r}") from exc


def load_csv_file(path: Path, instrument: str, granularity: str) -> list[Candle]:
    text = _read_text(Path(path))
    sample = "\n".join(text.splitlines()[:5])
    delim = _sniff_delimiter(sample)
    reader = _csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if r and any(cell.strip() for cell in r)]
    if not rows:
        return []

    header = rows[0]
    has_header = any(_find(header, _OPEN_ALIASES + _CLOSE_ALIASES) is not None for _ in [0]) and \
        not _looks_numeric(header)
    if has_header:
        body = rows[1:]
        i_dt = _find(header, _TIME_ALIASES)
        i_date = _find(header, _DATE_ALIASES)
        i_clock = _find(header, _CLOCK_ALIASES)
        # Separate date + time columns (e.g. "Date","Time") must not be
        # mistaken for one combined datetime column.
        if i_date is not None and i_clock is not None and i_date != i_clock:
            i_dt = None
        i_o = _find(header, _OPEN_ALIASES)
        i_h = _find(header, _HIGH_ALIASES)
        i_l = _find(header, _LOW_ALIASES)
        i_c = _find(header, _CLOSE_ALIASES)
        i_v = _find(header, _VOL_ALIASES)
    else:
        # assume MT-style: date,time,open,high,low,close,volume  OR  dt,o,h,l,c
        body = rows
        ncol = len(rows[0])
        if ncol >= 6:
            i_date, i_clock, i_o, i_h, i_l, i_c = 0, 1, 2, 3, 4, 5
            i_dt = None
            i_v = 6 if ncol >= 7 else None
        else:
            i_dt, i_o, i_h, i_l, i_c = 0, 1, 2, 3, 4
            i_date = i_clock = None
            i_v = 5 if ncol >= 6 else None

    if i_c is None or i_o is None:
        raise ValueError(f"Could not locate OHLC columns in {path}")

    candles: list[Candle] = []
    for r in body:
        try:
            if i_dt is not None:
                t = _parse_dt(r[i_dt])
            elif i_date is not None and i_clock is not None and i_clock != i_date:
                t = _parse_dt(f"{r[i_date].strip()} {r[i_clock].strip()}")
            elif i_date is not None:
                t = _parse_dt(r[i_date])
            else:
                continue
            candles.append(
                Candle(
                    instrument=instrument,
                    granularity=granularity,
                    time=t,
                    open=float(r[i_o]),
                    high=float(r[i_h if i_h is not None else i_o]),
                    low=float(r[i_l if i_l is not None else i_o]),
                    close=float(r[i_c]),
                    volume=float(r[i_v]) if i_v is not None and i_v < len(r) and r[i_v].strip() else 0.0,
                )
            )
        except (ValueError, IndexError):
            continue  # skip malformed / footer rows
    candles.sort(key=lambda c: c.time)
    return candles


def _looks_numeric(row: list[str]) -> bool:
    """A header row should not be parseable as numbers."""
    numeric = 0
    for cell in row:
        try:
            float(cell)
            numeric += 1
        except ValueError:
            pass
    return numeric >= max(1, len(row) - 1)
