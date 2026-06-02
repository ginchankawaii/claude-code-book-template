"""株価データ取得モジュール。

データソースを切り替え可能:
  - yahoo : Yahoo Finance (非公式 chart API)。APIキー不要。
  - stooq : Stooq の CSV。APIキー不要。
  - mock  : オフライン用の擬似データ（再現性あり、ネットワーク不要）。

実データソースが失敗した場合、config.MARKET_FALLBACK_TO_MOCK が真なら
自動的に mock にフォールバックする（アプリが必ず動くようにするため）。
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from . import config

_USER_AGENT = "Mozilla/5.0 (compatible; InvestmentSimulator/1.0)"


class MarketError(Exception):
    pass


# --------------------------------------------------------------------------
# 公開 API
# --------------------------------------------------------------------------
def get_history(code: str, days: int = 120) -> list[dict]:
    """日足の価格履歴を返す。

    返り値: [{"date": "YYYY-MM-DD", "open","high","low","close","volume"}, ...]
    （古い順）
    """
    source = config.MARKET_DATA_SOURCE
    try:
        if source == "mock":
            return _mock_history(code, days)
        if source == "stooq":
            return _stooq_history(code, days)
        return _yahoo_history(code, days)
    except Exception as exc:  # noqa: BLE001
        if config.MARKET_FALLBACK_TO_MOCK and source != "mock":
            data = _mock_history(code, days)
            for d in data:
                d["_mock"] = True
            return data
        raise MarketError(str(exc)) from exc


def get_quote(code: str) -> dict:
    """現在値（直近終値ベース）を返す。

    返り値: {"code","name","price","prev_close","change","change_pct",
             "currency","time","source"}
    """
    hist = get_history(code, days=10)
    if not hist:
        raise MarketError(f"価格データを取得できませんでした: {code}")
    last = hist[-1]
    prev = hist[-2] if len(hist) >= 2 else hist[-1]
    price = last["close"]
    prev_close = prev["close"]
    change = price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    mocked = last.get("_mock", config.MARKET_DATA_SOURCE == "mock")
    return {
        "code": code,
        "name": resolve_name(code),
        "price": round(price, 2),
        "prev_close": round(prev_close, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "currency": "JPY",
        "time": last["date"],
        "source": "mock" if mocked else config.MARKET_DATA_SOURCE,
    }


def resolve_name(code: str) -> str:
    return config.KNOWN_NAMES.get(code, f"銘柄 {code}")


# --------------------------------------------------------------------------
# Yahoo Finance
# --------------------------------------------------------------------------
def _yahoo_history(code: str, days: int) -> list[dict]:
    symbol = f"{code}.T"  # 東証銘柄
    rng = "6mo" if days <= 130 else "1y" if days <= 260 else "2y"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": rng, "interval": "1d"}
    with httpx.Client(timeout=15, headers={"User-Agent": _USER_AGENT}) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    out: list[dict] = []
    for i, ts in enumerate(timestamps):
        close = quote["close"][i]
        if close is None:
            continue
        out.append(
            {
                "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                "open": _r(quote["open"][i], close),
                "high": _r(quote["high"][i], close),
                "low": _r(quote["low"][i], close),
                "close": round(close, 2),
                "volume": quote["volume"][i] or 0,
            }
        )
    return out[-days:]


def _r(value: Optional[float], fallback: float) -> float:
    return round(value if value is not None else fallback, 2)


# --------------------------------------------------------------------------
# Stooq
# --------------------------------------------------------------------------
def _stooq_history(code: str, days: int) -> list[dict]:
    url = f"https://stooq.com/q/d/l/?s={code}.jp&i=d"
    with httpx.Client(timeout=15, headers={"User-Agent": _USER_AGENT}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        text = resp.text
    if "Date" not in text:
        raise MarketError(f"Stooq からデータを取得できませんでした: {code}")
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict] = []
    for row in reader:
        try:
            out.append(
                {
                    "date": row["Date"],
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(float(row.get("Volume", 0) or 0)),
                }
            )
        except (ValueError, KeyError):
            continue
    return out[-days:]


# --------------------------------------------------------------------------
# モックデータ（オフライン・再現性あり）
# --------------------------------------------------------------------------
def _mock_history(code: str, days: int) -> list[dict]:
    """証券コードから決定論的に生成する擬似的な株価履歴。

    乱数シードをコードから作るため、同じ銘柄は毎回同じ系列になる。
    """
    seed = int(hashlib.sha256(code.encode()).hexdigest(), 16)
    rng = _Lcg(seed)

    # 銘柄ごとに基準価格をばらつかせる（1,000〜8,000円程度）
    base = 1000 + (seed % 7000)
    price = float(base)
    drift = ((seed >> 8) % 7 - 3) * 0.0004  # わずかな上昇/下降トレンド
    out: list[dict] = []
    today = date.today()
    start = today - timedelta(days=days - 1)
    for i in range(days):
        d = start + timedelta(days=i)
        # 平日のみ（土日はスキップ）
        if d.weekday() >= 5:
            continue
        shock = (rng.next() - 0.5) * 0.03  # ±1.5% 程度の日次変動
        wave = math.sin(i / 9.0) * 0.004
        price = max(50.0, price * (1 + drift + shock + wave))
        open_p = price * (1 + (rng.next() - 0.5) * 0.01)
        high = max(open_p, price) * (1 + rng.next() * 0.008)
        low = min(open_p, price) * (1 - rng.next() * 0.008)
        volume = int(100000 + rng.next() * 2000000)
        out.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "open": round(open_p, 1),
                "high": round(high, 1),
                "low": round(low, 1),
                "close": round(price, 1),
                "volume": volume,
            }
        )
    return out


class _Lcg:
    """簡易な線形合同法による疑似乱数生成器（0..1 を返す）。"""

    def __init__(self, seed: int):
        self.state = seed % (2**31)

    def next(self) -> float:
        self.state = (1103515245 * self.state + 12345) % (2**31)
        return self.state / (2**31)
