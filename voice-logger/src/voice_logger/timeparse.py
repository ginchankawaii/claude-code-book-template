"""録音ファイル名から録音開始日時を推定する。

対応パターン（レコーダー/スマホアプリの一般的な命名）:
  20260827_091500 / 2026-08-27_09-15-00 / 2026-08-27 09.15.00 / 260827-0915 など。
どれにも合致しない場合はファイルの更新時刻(mtime)にフォールバックする
（多くのレコーダーは録音終了時にmtimeが付くため、duration を引いて開始時刻とする）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

# (正規表現, strptimeフォーマット) の順に試す
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})[T _-]+(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})"),
     "%Y%m%d%H%M%S"),
    (re.compile(r"(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})[T _-]+(\d{2})[-_.:]?(\d{2})"),
     "%Y%m%d%H%M"),
    (re.compile(r"(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})"),
     "%Y%m%d"),
]


def parse_start_time(path: Path, duration_sec: float = 0.0) -> tuple[datetime, str]:
    """録音開始日時と推定方法 ("filename" / "mtime") を返す。"""
    name = path.stem
    for pattern, fmt in _PATTERNS:
        m = pattern.search(name)
        if not m:
            continue
        digits = "".join(m.groups())
        try:
            dt = datetime.strptime(digits, fmt)
        except ValueError:
            continue
        if 2000 <= dt.year <= 2100:
            return dt, "filename"
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return mtime - timedelta(seconds=duration_sec), "mtime"
