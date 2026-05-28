"""Backtest runner - test the strategy on historical data before going live."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from dotenv import load_dotenv
from loguru import logger

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from src.data.fetcher import MarketDataFetcher
from src.data.universe import SP500_TOP100, TOPIX100_JP
from src.backtest.engine import Backtester
from src.backtest.metrics import print_report


def run_backtest(
    symbols: list[str],
    initial_capital: float = 3_000_000,
    days: int = 730,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    with open("config/settings.yaml") as f:
        config = yaml.safe_load(f)

    config["trading"]["initial_capital"] = initial_capital

    logger.info(f"データ取得中... ({len(symbols)}銘柄, {days}日間)")
    fetcher = MarketDataFetcher()
    data = fetcher.fetch(symbols, days=days)

    if not data:
        logger.error("データ取得失敗")
        return {}

    logger.info(f"{len(data)}銘柄のデータを取得。バックテスト実行中...")
    backtester = Backtester(config, initial_capital)
    results = backtester.run(data, start_date, end_date)

    print_report(results)
    return results


def plot_equity_curve(results: dict, title: str = "Equity Curve") -> None:
    """エクイティカーブを描画して保存。"""
    equity_df = results.get("equity_curve")
    if equity_df is None or equity_df.empty:
        return

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]})

    # エクイティカーブ
    ax1 = axes[0]
    ax1.plot(equity_df.index, equity_df["equity"], linewidth=1.5, color="#2196F3")
    ax1.fill_between(equity_df.index, equity_df["equity"], alpha=0.1, color="#2196F3")
    ax1.set_title(title, fontsize=14)
    ax1.set_ylabel("Portfolio Value")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax1.grid(True, alpha=0.3)

    # ドローダウン
    ax2 = axes[1]
    peak = equity_df["equity"].expanding().max()
    drawdown = (equity_df["equity"] - peak) / peak * 100
    ax2.fill_between(equity_df.index, drawdown, 0, alpha=0.6, color="#F44336")
    ax2.set_ylabel("Drawdown %")
    ax2.set_xlabel("Date")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    path = "backtest_result.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    logger.info(f"エクイティカーブ保存: {path}")
    plt.show()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="バックテスト実行")
    parser.add_argument("--market", choices=["us", "jp", "both"], default="us")
    parser.add_argument("--capital", type=float, default=3_000_000)
    parser.add_argument("--days", type=int, default=730, help="取得履歴日数")
    parser.add_argument("--symbols", nargs="*", help="個別銘柄指定（省略時はユニバース全体）")
    parser.add_argument("--plot", action="store_true", help="エクイティカーブを表示")
    args = parser.parse_args()

    if args.symbols:
        symbols = args.symbols
    elif args.market == "us":
        symbols = SP500_TOP100[:30]  # 高速化のため上位30銘柄
    elif args.market == "jp":
        symbols = TOPIX100_JP[:20]
    else:
        symbols = SP500_TOP100[:20] + TOPIX100_JP[:10]

    results = run_backtest(
        symbols=symbols,
        initial_capital=args.capital,
        days=args.days,
    )

    if args.plot and results:
        plot_equity_curve(results, title=f"Swing Trade Backtest ({args.market.upper()})")
