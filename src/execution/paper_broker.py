"""Paper trading broker - simulates order execution without real money."""

from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass

from loguru import logger


@dataclass
class Order:
    symbol: str
    side: str           # "buy" or "sell"
    qty: int
    order_type: str     # "market" or "limit"
    limit_price: float | None
    filled_price: float | None = None
    status: str = "pending"  # pending, filled, cancelled
    filled_at: datetime | None = None
    order_id: str = ""


class PaperBroker:
    """
    ペーパートレーディング（模擬売買）ブローカー。
    スリッページをシミュレートして実環境に近い挙動を再現。
    """

    SLIPPAGE_PCT = 0.001  # 0.1% スリッページ

    def __init__(self):
        self._orders: list[Order] = []
        self._order_counter = 0

    def _next_id(self) -> str:
        self._order_counter += 1
        return f"PAPER-{self._order_counter:06d}"

    def buy(self, symbol: str, qty: int, price: float) -> Order:
        """成行買い注文（スリッページ込み）。"""
        filled_price = price * (1 + self.SLIPPAGE_PCT)
        order = Order(
            symbol=symbol,
            side="buy",
            qty=qty,
            order_type="market",
            limit_price=None,
            filled_price=filled_price,
            status="filled",
            filled_at=datetime.now(),
            order_id=self._next_id(),
        )
        self._orders.append(order)
        logger.info(f"[PAPER] BUY {symbol} {qty}株 @{filled_price:.2f}")
        return order

    def sell(self, symbol: str, qty: int, price: float) -> Order:
        """成行売り注文（スリッページ込み）。"""
        filled_price = price * (1 - self.SLIPPAGE_PCT)
        order = Order(
            symbol=symbol,
            side="sell",
            qty=qty,
            order_type="market",
            limit_price=None,
            filled_price=filled_price,
            status="filled",
            filled_at=datetime.now(),
            order_id=self._next_id(),
        )
        self._orders.append(order)
        logger.info(f"[PAPER] SELL {symbol} {qty}株 @{filled_price:.2f}")
        return order

    def get_orders(self) -> list[Order]:
        return self._orders.copy()
