"""Offline simulator for the kabuステーション broker — watch the stock system work
WITHOUT an auカブコム account / kabuステーション (e.g. while the account is 審査待ち).

Same interface as KabuStation, but prices are a synthetic seeded random walk over
a universe of REAL TSE tickers, the margin book is held in memory, and orders are
"executed" into that book (no network, no real money). Opus (with a key) can pick
real names against this sim; without a key use RuleStockTrader. It is a MECHANICS
demo — selection -> sizing -> orders -> portfolio -> dashboard — not real data.
"""
from __future__ import annotations

import hashlib
import random
from typing import Optional

from .kabu import RANK_PRICE_UP, RANK_TURNOVER, KabuStation, StockPosition

# (code, name, base price ¥) — liquid TSE large caps, roughly in descending
# share-turnover order (most-traded, affordable mega caps first; the high-priced
# names like キーエンス/ファストリ trade fewer shares so they sit lower).
_UNIVERSE: list[tuple[str, str, float]] = [
    ("8306", "三菱UFJ", 1700.0), ("7203", "トヨタ自動車", 3000.0),
    ("6758", "ソニーG", 3300.0), ("8316", "三井住友FG", 3400.0),
    ("7267", "ホンダ", 1700.0), ("9434", "ソフトバンク", 1900.0),
    ("8058", "三菱商事", 3300.0), ("6501", "日立製作所", 3800.0),
    ("9984", "ソフトバンクG", 9000.0), ("9433", "KDDI", 4800.0),
    ("4568", "第一三共", 4500.0), ("6902", "デンソー", 2400.0),
    ("6981", "村田製作所", 2800.0), ("6594", "ニデック", 3000.0),
    ("4063", "信越化学", 5000.0), ("6098", "リクルートHD", 9000.0),
    ("7974", "任天堂", 8000.0), ("8035", "東京エレクトロン", 28000.0),
    ("9983", "ファーストリテイリング", 45000.0), ("6861", "キーエンス", 65000.0),
]


class SimKabuStation(KabuStation):
    """Drop-in offline replacement for KabuStation (no network)."""

    def __init__(self, start_cash: float = 3_000_000.0, seed: int = 7,
                 leverage: float = 3.3, dry_run: bool = True, **_: object) -> None:
        super().__init__(api_password="sim", order_password="sim", dry_run=dry_run)
        self._rng = random.Random(seed)
        self.cash = start_cash
        self.start_cash = start_cash
        self.leverage = leverage
        self._px = {c: p for c, _n, p in _UNIVERSE}
        self._name = {c: n for c, n, _p in _UNIVERSE}
        self._ret = {c: self._rng.uniform(-0.02, 0.03) for c in self._px}
        self._pos: dict[str, list] = {}   # symbol -> [qty, avg_entry]

    # --- lifecycle ---------------------------------------------------------
    def connect(self) -> None:
        print(f"[kabu-sim] OFFLINE SIMULATOR (no account needed) :: cash ¥{self.cash:,.0f}", flush=True)

    def step(self) -> None:
        """Advance one synthetic bar (seeded geometric random walk)."""
        for c in list(self._px):
            shock = self._rng.gauss(0.0004, 0.015)
            self._ret[c] = shock
            self._px[c] = max(50.0, self._px[c] * (1 + shock))

    def _ensure(self, symbol: str) -> None:
        if symbol not in self._px:   # Opus may pick a name outside the seed universe
            h = int(hashlib.md5(symbol.encode()).hexdigest(), 16)
            self._px[symbol] = 800.0 + (h % 9000)
            self._ret[symbol] = ((h >> 8) % 500) / 10000.0 - 0.02
            self._name[symbol] = f"銘柄{symbol}"

    # --- market data -------------------------------------------------------
    def price(self, symbol: str, exchange: int = 1) -> Optional[float]:
        self._ensure(symbol)
        return round(self._px[symbol], 1)

    def trading_unit(self, symbol: str, exchange: int = 1) -> int:
        return 100

    def ranking(self, kind: str = RANK_TURNOVER, exchange: str = "ALL", limit: int = 30) -> list[str]:
        syms = list(self._px)   # insertion order = descending turnover (see _UNIVERSE)
        if kind == RANK_PRICE_UP:
            syms = sorted(syms, key=lambda c: self._ret[c], reverse=True)   # momentum
        return syms[:limit]

    def name(self, symbol: str) -> str:
        self._ensure(symbol)
        return self._name.get(symbol, symbol)

    # --- account -----------------------------------------------------------
    def margin_power(self) -> float:
        used = sum(q * ep for q, ep in self._pos.values())
        return max(0.0, self.cash * self.leverage - used)

    def total_assets(self) -> float:
        unreal = sum(q * (self._px[s] - ep) for s, (q, ep) in self._pos.items())
        return self.cash + unreal

    def positions(self) -> list[StockPosition]:
        return [StockPosition(symbol=s, qty=q, price=ep, hold_id=f"sim-{s}")
                for s, (q, ep) in self._pos.items() if q > 0]

    # --- orders (always execute into the in-memory book; it's all simulated) #
    def margin_buy(self, symbol: str, qty: int, exchange: int = 1) -> Optional[dict]:
        self._ensure(symbol)
        px = self._px[symbol]
        if symbol in self._pos:
            q0, e0 = self._pos[symbol]
            nq = q0 + qty
            self._pos[symbol] = [nq, (q0 * e0 + qty * px) / nq]
        else:
            self._pos[symbol] = [qty, px]
        print(f"[kabu-sim] BUY  {symbol} {self.name(symbol)} x{qty} @ ¥{px:,.1f}", flush=True)
        return {"OrderId": f"sim-{symbol}", "Result": 0}

    def margin_close_long(self, symbol: str, qty: int, exchange: int = 1) -> Optional[dict]:
        if symbol not in self._pos:
            return None
        q0, e0 = self._pos[symbol]
        q = min(qty, q0)
        px = self._px[symbol]
        self.cash += q * (px - e0)            # realize PnL into cash
        nq = q0 - q
        if nq <= 0:
            del self._pos[symbol]
        else:
            self._pos[symbol] = [nq, e0]
        print(f"[kabu-sim] SELL {symbol} {self.name(symbol)} x{q} @ ¥{px:,.1f} "
              f"(損益 {q*(px-e0):+,.0f})", flush=True)
        return {"OrderId": f"sim-{symbol}", "Result": 0}
