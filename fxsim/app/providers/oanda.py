"""OANDA v20 market-data provider (read-only).

We only READ prices from OANDA; order fills are simulated locally by the paper
trading engine, so this works against a free *practice* account token.

NETWORK NOTE: this environment's network policy must allow-list the OANDA host
before live mode works. Required hosts:
    practice:  api-fxpractice.oanda.com
    live:      api-fxtrade.oanda.com
Until then `FXSIM_PROVIDER=sample` is used for offline backtests.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from ..config import settings
from ..models import Candle
from .base import DataProvider


class OandaProvider(DataProvider):
    name = "oanda"

    def __init__(self, token: str | None = None, host: str | None = None) -> None:
        self.token = token or settings.oanda_token
        self.host = host or settings.oanda_host
        if not self.token:
            raise RuntimeError(
                "OANDA_API_TOKEN is not set. Get a free practice token at "
                "https://www.oanda.com/ and export it before using FXSIM_PROVIDER=oanda."
            )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Accept-Datetime-Format": "RFC3339"}

    def history(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        url = f"{self.host}/v3/instruments/{instrument}/candles"
        params = {
            "granularity": granularity,
            "count": min(count, 5000),
            "price": "M",          # midpoint
            "smooth": "false",
        }
        resp = requests.get(url, headers=self._headers(), params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        candles: list[Candle] = []
        for row in payload.get("candles", []):
            if not row.get("complete", False):
                continue  # skip the still-forming bar
            mid = row["mid"]
            candles.append(
                Candle(
                    instrument=instrument,
                    granularity=granularity,
                    time=_parse_rfc3339(row["time"]),
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=float(row.get("volume", 0)),
                )
            )
        return candles


def _parse_rfc3339(ts: str) -> datetime:
    # OANDA returns e.g. "2024-01-02T15:30:00.000000000Z"; trim ns to us.
    ts = ts.replace("Z", "+00:00")
    if "." in ts:
        head, frac = ts.split(".")
        tz = ""
        for marker in ("+", "-"):
            if marker in frac[1:]:
                idx = frac.index(marker, 1)
                frac, tz = frac[:idx], frac[idx:]
                break
        frac = frac[:6]
        ts = f"{head}.{frac}{tz}"
    dt = datetime.fromisoformat(ts)
    return dt.astimezone(timezone.utc)
