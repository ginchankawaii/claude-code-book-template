"""Alpaca broker integration for US stock live/paper trading."""

from __future__ import annotations

import os
from datetime import datetime

from loguru import logger

from .paper_broker import Order


class AlpacaBroker:
    """
    Alpaca API 経由での米国株注文執行。
    ALPACA_BASE_URL を paper-api に設定するとペーパートレード。
    """

    def __init__(self):
        self._client = None
        self._init()

    def _init(self) -> None:
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            api_key = os.getenv("ALPACA_API_KEY", "")
            secret_key = os.getenv("ALPACA_SECRET_KEY", "")
            base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

            if not api_key or api_key == "your_api_key_here":
                logger.warning("Alpaca API キーが未設定。ペーパーブローカーを使用してください。")
                return

            paper = "paper-api" in base_url
            self._client = TradingClient(api_key, secret_key, paper=paper)
            self._MarketOrderRequest = MarketOrderRequest
            self._OrderSide = OrderSide
            self._TimeInForce = TimeInForce

            account = self._client.get_account()
            logger.info(
                f"Alpaca 接続完了 (paper={paper}) "
                f"残高:{float(account.portfolio_value):,.0f} USD"
            )
        except ImportError:
            logger.warning("alpaca-py が未インストール。pip install alpaca-py")
        except Exception as e:
            logger.error(f"Alpaca 初期化エラー: {e}")

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def get_account(self) -> dict:
        if not self.is_connected:
            return {}
        try:
            acc = self._client.get_account()
            return {
                "cash": float(acc.cash),
                "portfolio_value": float(acc.portfolio_value),
                "buying_power": float(acc.buying_power),
            }
        except Exception as e:
            logger.error(f"口座情報取得エラー: {e}")
            return {}

    def buy(self, symbol: str, qty: int, _price: float = 0) -> Order | None:
        if not self.is_connected:
            logger.error("Alpaca 未接続")
            return None
        try:
            req = self._MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=self._OrderSide.BUY,
                time_in_force=self._TimeInForce.DAY,
            )
            order = self._client.submit_order(req)
            logger.info(f"[ALPACA] BUY {symbol} {qty}株 注文ID:{order.id}")
            return Order(
                symbol=symbol,
                side="buy",
                qty=qty,
                order_type="market",
                limit_price=None,
                status="submitted",
                filled_at=datetime.now(),
                order_id=str(order.id),
            )
        except Exception as e:
            logger.error(f"Alpaca BUY エラー {symbol}: {e}")
            return None

    def sell(self, symbol: str, qty: int, _price: float = 0) -> Order | None:
        if not self.is_connected:
            logger.error("Alpaca 未接続")
            return None
        try:
            req = self._MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=self._OrderSide.SELL,
                time_in_force=self._TimeInForce.DAY,
            )
            order = self._client.submit_order(req)
            logger.info(f"[ALPACA] SELL {symbol} {qty}株 注文ID:{order.id}")
            return Order(
                symbol=symbol,
                side="sell",
                qty=qty,
                order_type="market",
                limit_price=None,
                status="submitted",
                filled_at=datetime.now(),
                order_id=str(order.id),
            )
        except Exception as e:
            logger.error(f"Alpaca SELL エラー {symbol}: {e}")
            return None

    def is_market_open(self) -> bool:
        if not self.is_connected:
            return False
        try:
            clock = self._client.get_clock()
            return clock.is_open
        except Exception:
            return False
