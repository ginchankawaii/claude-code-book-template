"""Portfolio state management (positions, cash, P&L tracking)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger


@dataclass
class Position:
    symbol: str
    shares: int
    entry_price: float
    entry_date: datetime
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    trailing_high: float = 0.0
    trailing_active: bool = False
    partial_exited: bool = False   # TP1で半分決済済み
    market: str = "us"             # "us" or "jp"

    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.shares

    def unrealized_pnl_pct(self, current_price: float) -> float:
        if self.entry_price == 0:
            return 0.0
        return (current_price - self.entry_price) / self.entry_price


@dataclass
class ClosedTrade:
    symbol: str
    shares: int
    entry_price: float
    exit_price: float
    entry_date: datetime
    exit_date: datetime
    pnl: float
    pnl_pct: float
    reason: str
    market: str = "us"


class Portfolio:
    """ポートフォリオ状態の管理（残高・ポジション・取引履歴）。"""

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, Position] = {}
        self.closed_trades: list[ClosedTrade] = []
        self.peak_value = initial_capital

    @property
    def position_count(self) -> int:
        return len(self.positions)

    def total_value(self, prices: dict[str, float]) -> float:
        """現在のポートフォリオ総額を計算。"""
        pos_value = sum(
            pos.shares * prices.get(pos.symbol, pos.entry_price)
            for pos in self.positions.values()
        )
        return self.cash + pos_value

    def open_position(self, position: Position) -> bool:
        cost = position.cost_basis
        if cost > self.cash:
            logger.warning(f"資金不足: 必要{cost:.0f} > 手持{self.cash:.0f}")
            return False
        self.positions[position.symbol] = position
        self.cash -= cost
        logger.info(
            f"[BUY] {position.symbol} {position.shares}株 @{position.entry_price:.2f} "
            f"(コスト:{cost:.0f})"
        )
        return True

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_date: datetime,
        reason: str,
        partial: bool = False,
    ) -> ClosedTrade | None:
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]

        if partial and not pos.partial_exited:
            # TP1: 保有の半分を決済
            exit_shares = pos.shares // 2
            if exit_shares == 0:
                exit_shares = pos.shares
            pos.shares -= exit_shares
            pos.partial_exited = True
            proceeds = exit_shares * exit_price
            self.cash += proceeds
        else:
            exit_shares = pos.shares
            proceeds = exit_shares * exit_price
            self.cash += proceeds
            del self.positions[symbol]

        pnl = (exit_price - pos.entry_price) * exit_shares
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price

        trade = ClosedTrade(
            symbol=symbol,
            shares=exit_shares,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_date=pos.entry_date,
            exit_date=exit_date,
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
            market=pos.market,
        )
        self.closed_trades.append(trade)

        logger.info(
            f"[SELL] {symbol} {exit_shares}株 @{exit_price:.2f} "
            f"PnL: {pnl:+.0f}({pnl_pct:+.1%}) 理由:{reason}"
        )
        return trade

    def update_peak(self, current_value: float) -> None:
        if current_value > self.peak_value:
            self.peak_value = current_value

    def summary(self, prices: dict[str, float]) -> dict:
        total = self.total_value(prices)
        total_pnl = total - self.initial_capital
        closed_pnl = sum(t.pnl for t in self.closed_trades)
        win_trades = [t for t in self.closed_trades if t.pnl > 0]
        win_rate = len(win_trades) / len(self.closed_trades) if self.closed_trades else 0.0

        return {
            "total_value": total,
            "cash": self.cash,
            "positions": self.position_count,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl / self.initial_capital,
            "closed_pnl": closed_pnl,
            "closed_trades": len(self.closed_trades),
            "win_rate": win_rate,
            "peak_value": self.peak_value,
            "drawdown": (self.peak_value - total) / self.peak_value if self.peak_value > 0 else 0,
        }
