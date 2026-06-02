"""価格履歴からテクニカル指標を計算するヘルパー。

Claude へ渡す判断材料、および UI 表示に利用する。
"""
from __future__ import annotations


def sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return round(100 - 100 / (1 + rs), 2)


def summarize(history: list[dict]) -> dict:
    """履歴から主要指標をまとめて返す。"""
    closes = [h["close"] for h in history]
    if not closes:
        return {}
    last = closes[-1]
    sma5 = sma(closes, 5)
    sma25 = sma(closes, 25)
    return {
        "last_close": round(last, 2),
        "sma5": sma5,
        "sma25": sma25,
        "rsi14": rsi(closes, 14),
        "high_60d": round(max(closes[-60:]), 2),
        "low_60d": round(min(closes[-60:]), 2),
        "change_5d_pct": _pct(closes, 5),
        "change_25d_pct": _pct(closes, 25),
        "trend": _trend(sma5, sma25),
    }


def _pct(closes: list[float], n: int) -> float | None:
    if len(closes) <= n or closes[-n - 1] == 0:
        return None
    return round((closes[-1] - closes[-n - 1]) / closes[-n - 1] * 100, 2)


def _trend(sma5: float | None, sma25: float | None) -> str:
    if sma5 is None or sma25 is None:
        return "unknown"
    if sma5 > sma25 * 1.005:
        return "uptrend"
    if sma5 < sma25 * 0.995:
        return "downtrend"
    return "sideways"
