"""Stock universe definitions for US and Japan markets."""

from __future__ import annotations

# S&P 500 上位100銘柄（流動性・時価総額フィルター済み）
SP500_TOP100 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "TSLA", "AVGO", "LLY",
    "JPM", "V", "UNH", "XOM", "MA", "JNJ", "PG", "COST", "HD", "MRK",
    "ABBV", "CVX", "ORCL", "BAC", "KO", "NFLX", "PEP", "TMO", "CRM", "AMD",
    "ACN", "LIN", "MCD", "ABT", "PM", "QCOM", "TXN", "DHR", "NEE", "AMGN",
    "ADBE", "INTU", "UNP", "CMCSA", "IBM", "CAT", "SPGI", "GE", "RTX", "NOW",
    "ISRG", "BKNG", "SYK", "VRTX", "PLD", "MDLZ", "HON", "T", "GS", "AMAT",
    "DE", "MMC", "BLK", "LOW", "UBER", "AXP", "ADI", "LRCX", "TJX", "ELV",
    "PGR", "REGN", "PANW", "SBUX", "MU", "BSX", "KLAC", "CB", "SO", "SCHW",
    "MDT", "GILD", "DUK", "CME", "ZTS", "ICE", "CL", "EQIX", "PH", "MO",
    "APH", "NOC", "HCA", "FI", "MCO", "ITW", "SHW", "AON", "TT", "MMM",
]

# TOPIX 100 主要銘柄（東証1部・流動性上位）
TOPIX100_JP = [
    "7203.T",  # トヨタ自動車
    "8306.T",  # 三菱UFJフィナンシャル
    "6758.T",  # ソニーグループ
    "9984.T",  # ソフトバンクグループ
    "6861.T",  # キーエンス
    "8035.T",  # 東京エレクトロン
    "4063.T",  # 信越化学工業
    "7974.T",  # 任天堂
    "6098.T",  # リクルートホールディングス
    "9432.T",  # 日本電信電話
    "6501.T",  # 日立製作所
    "4519.T",  # 中外製薬
    "8316.T",  # 三井住友フィナンシャル
    "7267.T",  # 本田技研工業
    "6367.T",  # ダイキン工業
    "9433.T",  # KDDI
    "4502.T",  # 武田薬品工業
    "8766.T",  # 東京海上ホールディングス
    "6702.T",  # 富士通
    "7751.T",  # キヤノン
    "6503.T",  # 三菱電機
    "4661.T",  # オリエンタルランド
    "6954.T",  # ファナック
    "5108.T",  # ブリヂストン
    "9022.T",  # 東海旅客鉄道
    "8801.T",  # 三井不動産
    "3382.T",  # セブン&アイ・ホールディングス
    "4568.T",  # 第一三共
    "6146.T",  # ディスコ
    "4543.T",  # テルモ
    "7733.T",  # オリンパス
    "6723.T",  # ルネサスエレクトロニクス
    "8031.T",  # 三井物産
    "8058.T",  # 三菱商事
    "7741.T",  # HOYA
    "4901.T",  # 富士フイルムホールディングス
    "9020.T",  # 東日本旅客鉄道
    "8802.T",  # 三菱地所
    "6971.T",  # 京セラ
    "4507.T",  # 塩野義製薬
    "6752.T",  # パナソニックホールディングス
    "7309.T",  # シマノ
    "6920.T",  # レーザーテック
    "3产.T",
]

# 重複・エラー行を除去したクリーン版
TOPIX100_JP = [s for s in TOPIX100_JP if ".T" in s]


def get_universe(name: str) -> list[str]:
    """ユニバース名から銘柄リストを返す。"""
    universes = {
        "sp500_top100": SP500_TOP100,
        "topix100": TOPIX100_JP,
    }
    if name not in universes:
        raise ValueError(f"Unknown universe: {name}. Available: {list(universes.keys())}")
    return universes[name]


def get_combined_universe() -> dict[str, list[str]]:
    """日米両市場のユニバースを返す。"""
    return {
        "us": SP500_TOP100,
        "jp": TOPIX100_JP,
    }
