"""株価の補完取得。

CSVに現在値が載っていれば基本はそれを使う。載っていない・古いときだけ
stooq の無料CSVエンドポイントを叩く（APIキー不要）。
ネットワークが無い環境でも動くことを優先し、失敗は例外にせず None を返す。
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from .config import Config
from .models import AssetClass, Portfolio

STOOQ_URL = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
TIMEOUT_SEC = 8


def stooq_symbol(symbol: str, asset_class: AssetClass) -> Optional[str]:
    """銘柄コードを stooq の表記に変換する。投信・債券は対象外。"""
    s = symbol.strip().lower()
    if not s:
        return None
    if asset_class is AssetClass.JP_STOCK:
        return f"{s}.jp"
    if asset_class is AssetClass.US_STOCK:
        return f"{s}.us"
    return None


class PriceCache:
    """取得結果のファイルキャッシュ。連続実行で毎回叩かないためのもの。"""

    def __init__(self, path: Path, ttl_sec: int) -> None:
        self.path = path
        self.ttl = ttl_sec
        self._data: dict[str, dict] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, key: str) -> Optional[float]:
        entry = self._data.get(key)
        if not entry:
            return None
        if time.time() - entry.get("ts", 0) > self.ttl:
            return None
        return entry.get("price")

    def set(self, key: str, price: float) -> None:
        self._data[key] = {"price": price, "ts": time.time()}

    def flush(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass  # キャッシュが書けなくても本処理は続ける


def _fetch_stooq(symbol: str) -> Optional[float]:
    url = STOOQ_URL.format(symbol=symbol)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    rows = list(csv.DictReader(io.StringIO(body)))
    if not rows:
        return None
    close = rows[0].get("Close")
    if close in (None, "", "N/D"):
        return None
    try:
        return float(close)
    except ValueError:
        return None


def fetch_prices(
    symbols: list[tuple[str, AssetClass]], cfg: Config, force: bool = False
) -> tuple[dict[str, float], list[str]]:
    """(取得できた価格, 取得できなかった銘柄) を返す。"""
    if cfg.price_source == "none":
        return {}, [s for s, _ in symbols]

    cache = PriceCache(cfg.cache_dir / "prices.json", cfg.price_cache_ttl_sec)
    prices: dict[str, float] = {}
    failed: list[str] = []

    for symbol, ac in symbols:
        key = stooq_symbol(symbol, ac)
        if key is None:
            failed.append(symbol)
            continue
        price = None if force else cache.get(key)
        if price is None:
            price = _fetch_stooq(key)
            if price is not None:
                cache.set(key, price)
        if price is None:
            failed.append(symbol)
        else:
            prices[symbol] = price

    cache.flush()
    return prices, failed


def usdjpy_rate(cfg: Config) -> Optional[float]:
    """USD/JPY を取得する。設定に固定値があればそれを優先。"""
    if cfg.usdjpy > 0:
        return cfg.usdjpy
    cache = PriceCache(cfg.cache_dir / "prices.json", cfg.price_cache_ttl_sec)
    rate = cache.get("usdjpy")
    if rate is None and cfg.price_source != "none":
        rate = _fetch_stooq("usdjpy")
        if rate is not None:
            cache.set("usdjpy", rate)
            cache.flush()
    return rate


def convert_to_jpy(pf: Portfolio, cfg: Config) -> Portfolio:
    """外貨建てポジションを円換算する。

    以降の集中度・維持率計算を全部JPY前提で書けるようにするための前処理。
    レートが取れない場合は換算せず警告だけ出す（誤ったレートで数字を作らない）。
    """
    foreign = [p for p in pf.spot if p.currency and p.currency != "JPY"]
    if not foreign:
        return pf

    rate = usdjpy_rate(cfg)
    if rate is None:
        pf.warnings.append(
            "USD/JPYレートを取得できなかったため、外貨建て銘柄は現地通貨のまま集計している。"
            "RPM_USDJPY にレートを設定すると円換算する。"
        )
        return pf

    for p in foreign:
        if p.currency != "USD":
            continue
        p.avg_cost *= rate
        if p.last_price is not None:
            p.last_price *= rate
        p.currency = "JPY"
    pf.warnings.append(f"外貨建て銘柄を USD/JPY={rate:.2f} で円換算した。")
    return pf


def enrich(pf: Portfolio, cfg: Config, force: bool = False) -> Portfolio:
    """現在値が欠けているポジションを埋める。force=True なら全件を取り直す。"""
    targets: dict[str, AssetClass] = {}
    for p in pf.spot:
        if force or p.last_price is None:
            targets.setdefault(p.symbol, p.asset_class)
    for m in pf.margin:
        if force or m.last_price is None:
            targets.setdefault(m.symbol, AssetClass.JP_STOCK)

    if not targets:
        return pf

    prices, failed = fetch_prices(list(targets.items()), cfg, force=force)

    for p in pf.spot:
        if p.symbol in prices and (force or p.last_price is None):
            p.last_price = prices[p.symbol]
            p.price_asof = "stooq"
    for m in pf.margin:
        if m.symbol in prices and (force or m.last_price is None):
            m.last_price = prices[m.symbol]

    if failed:
        pf.warnings.append(
            "株価を取得できなかった銘柄: "
            + ", ".join(sorted(set(failed))[:20])
            + "。取得単価ベースで計算しているので評価損益は実態とずれる。"
        )
    return pf
