"""取引カレンダー。

「翌営業日」は銘柄ごとの取引日ではなく、取引所の営業日で数える。
売買が成立しなかった日（寄らず）も営業日は営業日であり、そこは
約定モデル(simulate)側で扱う。
"""

from __future__ import annotations

import bisect
from datetime import date, datetime, time
from typing import Iterable, Sequence

import pandas as pd


class TradingCalendar:
    """営業日のみを昇順で保持する。"""

    def __init__(self, business_days: Iterable[date]) -> None:
        self._days: list[date] = sorted({_as_date(d) for d in business_days})
        self._pos: dict[date, int] = {d: i for i, d in enumerate(self._days)}

    @classmethod
    def from_frame(cls, df: pd.DataFrame) -> "TradingCalendar":
        """mkt calendar の DataFrame から作る。HolDiv=0 が営業日。"""
        col = "holiday_div"
        if col not in df.columns:
            raise KeyError(f"取引カレンダーに {col} 列がありません: {list(df.columns)}")
        # HolDiv は文字列で来ることがある
        div = df[col].astype(str).str.strip()
        business = df.loc[div == "0", "date"]
        if business.empty:
            raise ValueError("営業日が1日も見つかりません。HolDiv の値を確認してください。")
        return cls(business.tolist())

    @property
    def days(self) -> Sequence[date]:
        return self._days

    def is_business_day(self, d: date | str) -> bool:
        return _as_date(d) in self._pos

    def next_business_day(self, d: date | str) -> date | None:
        """d より後の最初の営業日。d 自身は含まない。"""
        dd = _as_date(d)
        i = bisect.bisect_right(self._days, dd)
        return self._days[i] if i < len(self._days) else None

    def shift(self, d: date | str, n: int) -> date | None:
        """営業日 d から n 営業日後。d が営業日でなければ ValueError。"""
        dd = _as_date(d)
        if dd not in self._pos:
            raise ValueError(f"{dd} は営業日ではありません")
        i = self._pos[dd] + n
        if i < 0 or i >= len(self._days):
            return None
        return self._days[i]

    def calendar_days_between(self, a: date | str, b: date | str) -> int:
        """暦日数（両端入れ）。信用金利の計算に使う。"""
        aa, bb = _as_date(a), _as_date(b)
        return (bb - aa).days + 1


class CloseTimeSchedule:
    """大引け時刻の履歴。

    東証は 2024-11-05 から 15:00 -> 15:30 に延長された。
    「引け後開示」の判定閾値はこの日で切り替わる。
    """

    def __init__(self, changes: list[dict]) -> None:
        parsed = []
        for c in changes:
            parsed.append((_as_date(c["from"]), _parse_time(c["close"])))
        self._changes = sorted(parsed)
        if not self._changes:
            raise ValueError("大引け時刻の設定が空です")

    def close_time(self, d: date | str) -> time:
        dd = _as_date(d)
        result = self._changes[0][1]
        for start, t in self._changes:
            if dd >= start:
                result = t
            else:
                break
        return result

    def is_after_close(self, d: date | str, t: time | str | None) -> bool:
        """開示時刻が大引け以降か。時刻が欠損なら引け後とみなす（保守的）。"""
        if t is None or (isinstance(t, float) and pd.isna(t)):
            return True
        tt = _parse_time(t) if not isinstance(t, time) else t
        return tt >= self.close_time(d)


def _as_date(d: object) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, pd.Timestamp):
        return d.date()
    return pd.Timestamp(str(d)).date()


def _parse_time(t: object) -> time:
    if isinstance(t, time):
        return t
    s = str(t).strip()
    if not s or s.lower() in {"nan", "none", "nat"}:
        raise ValueError(f"時刻として解釈できません: {t!r}")
    parts = s.split(":")
    hh = int(parts[0])
    mm = int(parts[1]) if len(parts) > 1 else 0
    ss = int(float(parts[2])) if len(parts) > 2 else 0
    return time(hh, mm, ss)
