"""Vectorized backtesting engine using historical OHLCV data."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from ..indicators.technical import add_all_indicators
from ..strategy.signals import SignalGenerator
from ..strategy.risk_manager import RiskManager
from ..strategy.portfolio import Portfolio, Position


class Backtester:
    """
    デイリー足バックテストエンジン。
    各日付ごとにシグナル生成→注文処理→P&L更新を実施。
    """

    def __init__(self, config: dict, initial_capital: float | None = None):
        self.config = config
        capital = initial_capital or config["trading"]["initial_capital"]
        self.portfolio = Portfolio(capital)
        self.signal_gen = SignalGenerator(config)
        self.risk_mgr = RiskManager(config)
        self._equity_curve: list[dict] = []

    def run(
        self,
        data: dict[str, pd.DataFrame],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """
        バックテスト実行。
        data: {symbol: DataFrame with OHLCV + indicators}
        """
        # 全データにインジケーターを追加
        processed: dict[str, pd.DataFrame] = {}
        for sym, df in data.items():
            try:
                processed[sym] = add_all_indicators(df)
            except Exception as e:
                logger.debug(f"インジケーター計算失敗 {sym}: {e}")

        if not processed:
            return {"error": "有効なデータがありません"}

        # 共通の日付リストを作成
        all_dates = sorted(
            set(
                date
                for df in processed.values()
                for date in df.index
            )
        )

        if start_date:
            all_dates = [d for d in all_dates if str(d)[:10] >= start_date]
        if end_date:
            all_dates = [d for d in all_dates if str(d)[:10] <= end_date]

        logger.info(f"バックテスト開始: {len(all_dates)}日間, {len(processed)}銘柄")

        for date in all_dates:
            self._process_day(date, processed)

        return self._compile_results(processed)

    def _process_day(self, date, data: dict[str, pd.DataFrame]) -> None:
        """1日分の処理: 決済チェック → 新規エントリー。"""
        prices = {}
        for sym, df in data.items():
            if date in df.index:
                prices[sym] = float(df.loc[date, "close"])

        if not prices:
            return

        total_val = self.portfolio.total_value(prices)
        self.portfolio.update_peak(total_val)

        # ドローダウン停止チェック
        if self.risk_mgr.check_drawdown_halt(self.portfolio.peak_value, total_val):
            self._record_equity(date, total_val)
            return

        # --- 既存ポジションの決済チェック ---
        for sym in list(self.portfolio.positions.keys()):
            if sym not in data or date not in data[sym].index:
                continue

            pos = self.portfolio.positions[sym]
            df_slice = data[sym].loc[:date]

            pos.trailing_high, pos.trailing_active = self.risk_mgr.update_trailing_stop(
                pos.entry_price,
                prices[sym],
                pos.trailing_high,
                pos.trailing_active,
                atr=float(df_slice.iloc[-1].get("atr", pos.entry_price * 0.02)),
            )

            action, reason = self.signal_gen.check_exit(
                sym,
                df_slice,
                pos.entry_price,
                pos.stop_loss,
                pos.trailing_high,
                pos.trailing_active,
            )

            if action == "SELL_ALL":
                self.portfolio.close_position(sym, prices[sym], date, reason)
            elif action == "SELL_HALF" and not pos.partial_exited:
                self.portfolio.close_position(sym, prices[sym], date, reason, partial=True)

        # --- 新規エントリー探索 ---
        candidates = []
        for sym, df in data.items():
            if sym in self.portfolio.positions:
                continue
            if date not in df.index:
                continue

            df_slice = df.loc[:date]
            signal = self.signal_gen.generate(sym, df_slice)

            if signal.action == "BUY":
                candidates.append((signal.score, sym, signal, prices.get(sym, 0)))

        # スコア降順で注文
        candidates.sort(reverse=True)
        for _, sym, signal, price in candidates:
            if price <= 0:
                continue

            qty = self.risk_mgr.calc_position_size(
                self.portfolio.total_value(prices),
                price,
                signal.stop_loss,
            )
            if qty == 0:
                continue

            can_open, reason = self.risk_mgr.can_open_position(
                self.portfolio.position_count,
                self.portfolio.cash,
                self.portfolio.total_value(prices),
                price * qty,
            )
            if not can_open:
                continue

            pos = Position(
                symbol=sym,
                shares=qty,
                entry_price=price,
                entry_date=date,
                stop_loss=signal.stop_loss,
                take_profit_1=signal.take_profit_1,
                take_profit_2=signal.take_profit_2,
                trailing_high=price,
            )
            self.portfolio.open_position(pos)

        self._record_equity(date, self.portfolio.total_value(prices))

    def _record_equity(self, date, value: float) -> None:
        self._equity_curve.append({"date": date, "equity": value})

    def _compile_results(self, data: dict[str, pd.DataFrame]) -> dict:
        from .metrics import calc_metrics

        equity_df = pd.DataFrame(self._equity_curve).set_index("date")
        trades = self.portfolio.closed_trades

        # 最終日の価格で残存ポジションを評価
        final_prices = {}
        for sym, df in data.items():
            if not df.empty:
                final_prices[sym] = float(df["close"].iloc[-1])

        final_value = self.portfolio.total_value(final_prices)
        metrics = calc_metrics(equity_df["equity"], trades, self.portfolio.initial_capital)

        return {
            "metrics": metrics,
            "equity_curve": equity_df,
            "trades": trades,
            "final_value": final_value,
        }
