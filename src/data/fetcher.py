"""Market data fetcher using yfinance (Japan + US) and Alpaca (US live/paper)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
from loguru import logger


class MarketDataFetcher:
    """OHLCV データを yfinance / Alpaca から取得する。"""

    def __init__(self, use_alpaca: bool = False):
        self.use_alpaca = use_alpaca
        self._alpaca_client = None
        if use_alpaca:
            self._init_alpaca()

    def _init_alpaca(self) -> None:
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame

            self._alpaca_client = StockHistoricalDataClient(
                api_key=os.getenv("ALPACA_API_KEY"),
                secret_key=os.getenv("ALPACA_SECRET_KEY"),
            )
            self._StockBarsRequest = StockBarsRequest
            self._TimeFrame = TimeFrame
            logger.info("Alpaca data client initialized")
        except Exception as e:
            logger.warning(f"Alpaca init failed, falling back to yfinance: {e}")
            self.use_alpaca = False

    def fetch(
        self,
        symbols: list[str],
        days: int = 365,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """複数銘柄の OHLCV データを取得。戻り値: {symbol: DataFrame}"""
        end = datetime.now()
        start = end - timedelta(days=days + 60)  # バッファを追加

        results: dict[str, pd.DataFrame] = {}
        failed: list[str] = []

        for symbol in symbols:
            try:
                df = self._fetch_one(symbol, start, end, interval)
                if df is not None and len(df) >= 20:
                    results[symbol] = df
                else:
                    failed.append(symbol)
            except Exception as e:
                logger.debug(f"Failed to fetch {symbol}: {e}")
                failed.append(symbol)

        if failed:
            logger.warning(f"Failed to fetch {len(failed)} symbols: {failed[:5]}...")
        logger.info(f"Fetched data for {len(results)}/{len(symbols)} symbols")
        return results

    def _fetch_one(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> pd.DataFrame | None:
        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            auto_adjust=True,
            back_adjust=False,
        )
        if df.empty:
            return None

        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.dropna(inplace=True)
        return df

    def fetch_benchmark(self, market: str = "us") -> pd.DataFrame | None:
        """市場全体のトレンド判断用ベンチマーク取得。"""
        benchmarks = {
            "us": "SPY",
            "jp": "1306.T",  # TOPIX ETF
        }
        symbol = benchmarks.get(market, "SPY")
        results = self.fetch([symbol], days=400)
        return results.get(symbol)

    def fetch_vix(self) -> pd.DataFrame | None:
        """VIX（恐怖指数）取得 - US市場フィルター用。"""
        results = self.fetch(["^VIX"], days=60)
        return results.get("^VIX")

    def get_latest_price(self, symbol: str) -> float | None:
        """最新終値を返す（注文価格推定用）。"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return None
