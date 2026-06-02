"""アプリケーション設定。

環境変数（任意で .env ファイル）から設定を読み込む。
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 未インストールでも動作させる
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# --- データベース ---
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "data" / "simulator.db"))

# --- シミュレーション初期設定 ---
# 仮想資金（日本円）。デフォルト100万円。
STARTING_CASH = float(os.getenv("STARTING_CASH", "1000000"))

# 日本株の単元株数（通常100株単位）
TRADE_UNIT = int(os.getenv("TRADE_UNIT", "100"))

# --- 株価データソース: yahoo | stooq | mock ---
# yahoo / stooq は実際の株価を取得（要ネットワーク）。
# mock はオフラインでも動く擬似データ（ネットワーク不要・再現性あり）。
MARKET_DATA_SOURCE = os.getenv("MARKET_DATA_SOURCE", "yahoo").lower()

# 実データ取得に失敗したら mock に自動フォールバックするか
MARKET_FALLBACK_TO_MOCK = os.getenv("MARKET_FALLBACK_TO_MOCK", "true").lower() == "true"

# --- Claude API（売買判断） ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ADVISOR_MODEL = os.getenv("ADVISOR_MODEL", "claude-sonnet-4-6")

# --- 初期ウォッチリスト（証券コード） ---
DEFAULT_WATCHLIST = [
    c.strip()
    for c in os.getenv(
        "DEFAULT_WATCHLIST", "7203,6758,9984,7974,9432,8306"
    ).split(",")
    if c.strip()
]

# よく使う日本株の銘柄名（API名称が取れない場合のフォールバック）
KNOWN_NAMES = {
    "7203": "トヨタ自動車",
    "6758": "ソニーグループ",
    "9984": "ソフトバンクグループ",
    "7974": "任天堂",
    "9432": "日本電信電話(NTT)",
    "8306": "三菱UFJフィナンシャル・グループ",
    "6861": "キーエンス",
    "6098": "リクルートホールディングス",
    "8035": "東京エレクトロン",
    "9983": "ファーストリテイリング",
    "6501": "日立製作所",
    "4063": "信越化学工業",
}
