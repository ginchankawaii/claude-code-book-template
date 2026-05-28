"""Entry point for the trading bot - scheduled daily execution."""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import schedule
import yaml
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
from src.bot import TradingBot, load_config


def run_us_session(bot: TradingBot) -> None:
    logger.info("米国市場セッション開始")
    bot.check_exits("us")
    signals = bot.run_scan("us")
    bot.execute_signals(signals[:5])
    bot.print_status()


def run_jp_session(bot: TradingBot) -> None:
    logger.info("日本市場セッション開始")
    bot.check_exits("jp")
    signals = bot.run_scan("jp")
    bot.execute_signals(signals[:5])


def run_once(bot: TradingBot) -> None:
    """即時実行モード（テスト・手動実行用）。"""
    bot.run_daily()


def run_scheduled(bot: TradingBot) -> None:
    """スケジュール実行モード（毎日自動実行）。"""
    cfg = bot.config["scheduler"]

    schedule.every().monday.at(cfg["scan_time_us"]).do(run_us_session, bot)
    schedule.every().tuesday.at(cfg["scan_time_us"]).do(run_us_session, bot)
    schedule.every().wednesday.at(cfg["scan_time_us"]).do(run_us_session, bot)
    schedule.every().thursday.at(cfg["scan_time_us"]).do(run_us_session, bot)
    schedule.every().friday.at(cfg["scan_time_us"]).do(run_us_session, bot)

    schedule.every().monday.at(cfg["scan_time_jp"]).do(run_jp_session, bot)
    schedule.every().tuesday.at(cfg["scan_time_jp"]).do(run_jp_session, bot)
    schedule.every().wednesday.at(cfg["scan_time_jp"]).do(run_jp_session, bot)
    schedule.every().thursday.at(cfg["scan_time_jp"]).do(run_jp_session, bot)
    schedule.every().friday.at(cfg["scan_time_jp"]).do(run_jp_session, bot)

    logger.info("スケジュール実行モード開始")
    logger.info(f"  米国スキャン: 平日 {cfg['scan_time_us']} ET")
    logger.info(f"  日本スキャン: 平日 {cfg['scan_time_jp']} JST")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="株式自動売買ボット")
    parser.add_argument(
        "--mode",
        choices=["once", "schedule"],
        default="once",
        help="once: 即時実行, schedule: スケジュール実行",
    )
    parser.add_argument(
        "--market",
        choices=["us", "jp", "both"],
        default="both",
        help="対象市場",
    )
    args = parser.parse_args()

    config = load_config()

    # --market フラグで対象市場を上書き
    if args.market == "us":
        config["markets"]["jp"]["enabled"] = False
    elif args.market == "jp":
        config["markets"]["us"]["enabled"] = False

    bot = TradingBot(config)

    if args.mode == "once":
        run_once(bot)
    else:
        run_scheduled(bot)
