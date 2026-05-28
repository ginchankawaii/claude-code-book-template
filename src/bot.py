"""Main trading bot orchestrator: scans universe, generates signals, executes orders."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

from .data.fetcher import MarketDataFetcher
from .data.universe import get_universe
from .indicators.technical import add_all_indicators
from .strategy.signals import SignalGenerator
from .strategy.risk_manager import RiskManager
from .strategy.portfolio import Portfolio, Position
from .strategy.ml_filter import MLFilter
from .execution.paper_broker import PaperBroker
from .execution.alpaca_broker import AlpacaBroker

load_dotenv()

CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


class TradingBot:
    """
    スイングトレード自動売買ボット。
    日次スキャン → ML フィルター → シグナル生成 → リスク管理 → 注文執行。
    """

    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self._setup_logger()

        trading_cfg = self.config["trading"]
        self.capital = trading_cfg["initial_capital"]
        self.mode = os.getenv("TRADING_MODE", trading_cfg.get("mode", "paper"))

        self.fetcher = MarketDataFetcher()
        self.signal_gen = SignalGenerator(self.config)
        self.risk_mgr = RiskManager(self.config)
        self.ml_filter = MLFilter(self.config)
        self.portfolio = Portfolio(self.capital)

        # ブローカー選択
        if self.mode == "live":
            self.us_broker = AlpacaBroker()
            logger.warning("ライブトレードモード — 実資金を使用します！")
        else:
            self.us_broker = PaperBroker()
            logger.info("ペーパートレードモード")

        self.jp_broker = PaperBroker()  # 日本株は常にペーパー（kabu.com 統合前）

        # ML モデル読み込み試行
        for market in ["us", "jp"]:
            self.ml_filter.load(market)

        logger.info(f"TradingBot 初期化完了 (モード:{self.mode}, 資本:{self.capital:,})")

    def _setup_logger(self) -> None:
        log_level = os.getenv("LOG_LEVEL", "INFO")
        logger.remove()
        logger.add(
            "logs/trading_{time:YYYY-MM-DD}.log",
            rotation="1 day",
            retention="30 days",
            level=log_level,
            format="{time:HH:mm:ss} | {level:<8} | {message}",
        )
        logger.add(lambda msg: print(msg, end=""), level=log_level, colorize=True)
        Path("logs").mkdir(exist_ok=True)

    def run_scan(self, market: str = "us") -> list[dict]:
        """指定市場のユニバーススキャンを実行し、シグナルリストを返す。"""
        market_cfg = self.config["markets"][market]
        if not market_cfg.get("enabled", True):
            return []

        universe_name = market_cfg["universe"]
        symbols = get_universe(universe_name)
        lookback = self.config["strategy"]["lookback_days"]

        logger.info(f"[{market.upper()}] {len(symbols)}銘柄をスキャン中...")

        # データ取得
        data = self.fetcher.fetch(symbols, days=lookback + 60)

        # ML 再学習（週次）
        if self.config["ml"]["enabled"]:
            processed_for_ml = {}
            for sym, df in data.items():
                try:
                    processed_for_ml[sym] = add_all_indicators(df)
                except Exception:
                    pass
            self.ml_filter.maybe_retrain(market, processed_for_ml)

        # ベンチマーク確認（市場フィルター）
        market_ok = self._check_market_trend(market)
        if not market_ok:
            logger.warning(f"[{market.upper()}] 市場トレンドフィルター: 新規エントリー抑制中")

        signals = []
        for sym, df in data.items():
            try:
                df_ind = add_all_indicators(df)
            except Exception:
                continue

            ml_prob = None
            if self.config["ml"]["enabled"]:
                ml_prob = self.ml_filter.predict(market, df_ind)

            signal = self.signal_gen.generate(sym, df_ind, ml_prob)

            if signal.action == "BUY" and market_ok:
                signals.append({
                    "symbol": sym,
                    "score": signal.score,
                    "reasons": signal.reasons,
                    "stop_loss": signal.stop_loss,
                    "take_profit_1": signal.take_profit_1,
                    "take_profit_2": signal.take_profit_2,
                    "ml_prob": ml_prob,
                    "market": market,
                    "price": df_ind["close"].iloc[-1],
                })
        signals.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"[{market.upper()}] スキャン完了: {len(signals)}件のBUYシグナル")
        return signals

    def _check_market_trend(self, market: str) -> bool:
        """ベンチマーク ETF が SMA200 を上回っているか確認。"""
        try:
            bench = self.fetcher.fetch_benchmark(market)
            if bench is None or len(bench) < 200:
                return True
            bench_ind = add_all_indicators(bench)
            last = bench_ind.iloc[-1]
            return float(last["close"]) > float(last["sma200"])
        except Exception:
            return True

    def execute_signals(self, signals: list[dict]) -> None:
        """シグナルリストから注文を執行。"""
        for sig in signals:
            sym = sig["symbol"]
            price = sig["price"]
            market = sig["market"]
            broker = self.us_broker if market == "us" else self.jp_broker

            if sym in self.portfolio.positions:
                continue

            total_val = self.portfolio.total_value(
                {sym: price for sym in self.portfolio.positions}
            ) + self.portfolio.cash

            qty = self.risk_mgr.calc_position_size(total_val, price, sig["stop_loss"])
            if qty == 0:
                continue

            can_open, reason = self.risk_mgr.can_open_position(
                self.portfolio.position_count,
                self.portfolio.cash,
                total_val,
                price * qty,
            )
            if not can_open:
                logger.debug(f"スキップ {sym}: {reason}")
                continue

            order = broker.buy(sym, qty, price)
            if order and order.status in ("filled", "submitted"):
                filled_price = order.filled_price or price
                pos = Position(
                    symbol=sym,
                    shares=qty,
                    entry_price=filled_price,
                    entry_date=datetime.now(),
                    stop_loss=sig["stop_loss"],
                    take_profit_1=sig["take_profit_1"],
                    take_profit_2=sig["take_profit_2"],
                    trailing_high=filled_price,
                    market=market,
                )
                self.portfolio.open_position(pos)

    def check_exits(self, market: str = "us") -> None:
        """保有ポジションの決済条件を確認。"""
        symbols_to_check = [
            sym for sym, pos in self.portfolio.positions.items()
            if pos.market == market
        ]
        if not symbols_to_check:
            return

        data = self.fetcher.fetch(symbols_to_check, days=60)

        for sym in symbols_to_check:
            if sym not in data:
                continue

            pos = self.portfolio.positions.get(sym)
            if pos is None:
                continue

            df = data[sym]
            try:
                df_ind = add_all_indicators(df)
            except Exception:
                continue

            price = float(df_ind["close"].iloc[-1])
            atr = float(df_ind["atr"].iloc[-1]) if "atr" in df_ind.columns else price * 0.02

            pos.trailing_high, pos.trailing_active = self.risk_mgr.update_trailing_stop(
                pos.entry_price, price, pos.trailing_high, pos.trailing_active, atr
            )

            action, reason = self.signal_gen.check_exit(
                sym, df_ind, pos.entry_price, pos.stop_loss, pos.trailing_high, pos.trailing_active
            )

            broker = self.us_broker if market == "us" else self.jp_broker

            if action == "SELL_ALL":
                broker.sell(sym, pos.shares, price)
                self.portfolio.close_position(sym, price, datetime.now(), reason)
            elif action == "SELL_HALF" and not pos.partial_exited:
                qty = pos.shares // 2 or pos.shares
                broker.sell(sym, qty, price)
                self.portfolio.close_position(sym, price, datetime.now(), reason, partial=True)

    def print_status(self) -> None:
        """現在のポートフォリオ状況を表示。"""
        prices = {}
        for sym in self.portfolio.positions:
            p = self.fetcher.get_latest_price(sym)
            if p:
                prices[sym] = p

        summary = self.portfolio.summary(prices)
        print("\n" + "=" * 50)
        print(f"  ポートフォリオ状況  [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
        print("=" * 50)
        print(f"  総資産      : {summary['total_value']:>12,.0f}")
        print(f"  現金        : {summary['cash']:>12,.0f}")
        print(f"  保有ポジション: {summary['positions']}")
        print(f"  累計損益    : {summary['total_pnl']:>+12,.0f} ({summary['total_pnl_pct']:+.2%})")
        print(f"  確定損益    : {summary['closed_pnl']:>+12,.0f}")
        print(f"  取引回数    : {summary['closed_trades']}")
        print(f"  勝率        : {summary['win_rate']:.1%}")
        print(f"  ドローダウン: {summary['drawdown']:.2%}")
        print("=" * 50 + "\n")

    def run_daily(self) -> None:
        """日次処理: 決済チェック → 新規スキャン → 注文執行。"""
        logger.info(f"=== 日次処理開始 {datetime.now().strftime('%Y-%m-%d')} ===")

        for market in ["us", "jp"]:
            if self.config["markets"][market].get("enabled", True):
                self.check_exits(market)

        for market in ["us", "jp"]:
            if self.config["markets"][market].get("enabled", True):
                signals = self.run_scan(market)
                self.execute_signals(signals[:5])  # 上位5シグナルまで

        self.print_status()
        logger.info("=== 日次処理完了 ===")
