"""Position sizing and portfolio-level risk management."""

from __future__ import annotations

from loguru import logger


class RiskManager:
    """
    固定フラクショナル法によるポジションサイジング。
    1トレードあたりのリスクをポートフォリオの一定割合に制限。
    """

    def __init__(self, config: dict):
        trading = config.get("trading", {})
        risk = config.get("risk", {})

        self.risk_per_trade: float = trading.get("risk_per_trade", 0.015)
        self.max_position_pct: float = trading.get("max_position_pct", 0.15)
        self.max_positions: int = trading.get("max_positions", 8)
        self.min_cash_reserve: float = trading.get("min_cash_reserve", 0.10)
        self.max_drawdown_halt: float = risk.get("max_drawdown_halt", 0.10)
        self.trailing_trigger_pct: float = risk.get("trailing_stop_trigger_pct", 0.04)

    def calc_position_size(
        self,
        portfolio_value: float,
        entry_price: float,
        stop_loss: float,
    ) -> int:
        """
        ポジションサイズ（株数）を計算。
        リスク額 = portfolio_value × risk_per_trade
        株数 = リスク額 / (entry_price - stop_loss)
        """
        if entry_price <= stop_loss or entry_price <= 0:
            logger.warning(f"Invalid entry/stop: {entry_price}/{stop_loss}")
            return 0

        risk_amount = portfolio_value * self.risk_per_trade
        risk_per_share = entry_price - stop_loss

        shares = int(risk_amount / risk_per_share)
        max_shares_by_pct = int((portfolio_value * self.max_position_pct) / entry_price)

        shares = min(shares, max_shares_by_pct)
        return max(shares, 0)

    def can_open_position(
        self,
        current_positions: int,
        cash: float,
        portfolio_value: float,
        required_cash: float,
    ) -> tuple[bool, str]:
        """新規ポジション開設可否を判定。"""
        if current_positions >= self.max_positions:
            return False, f"最大ポジション数到達({current_positions}/{self.max_positions})"

        min_cash = portfolio_value * self.min_cash_reserve
        if cash - required_cash < min_cash:
            return False, f"キャッシュ不足(必要:{required_cash:.0f}, 余裕:{cash-min_cash:.0f})"

        return True, ""

    def check_drawdown_halt(
        self,
        peak_value: float,
        current_value: float,
    ) -> bool:
        """最大ドローダウン超過で取引停止すべきか判定。"""
        if peak_value <= 0:
            return False
        drawdown = (peak_value - current_value) / peak_value
        if drawdown >= self.max_drawdown_halt:
            logger.warning(
                f"ドローダウン {drawdown:.1%} が閾値 {self.max_drawdown_halt:.1%} を超過 — 取引停止"
            )
            return True
        return False

    def update_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        trailing_high: float,
        trailing_active: bool,
        atr: float,
        atr_multiplier: float = 2.0,
    ) -> tuple[float, bool]:
        """
        トレーリングストップの高値とアクティブフラグを更新。
        Returns: (new_trailing_high, trailing_active)
        """
        new_high = max(trailing_high, current_price)

        if not trailing_active:
            ret = (current_price - entry_price) / entry_price
            if ret >= self.trailing_trigger_pct:
                trailing_active = True
                logger.debug(f"トレーリングストップ発動: +{ret:.1%}")

        return new_high, trailing_active
