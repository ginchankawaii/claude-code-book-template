"""auカブコム証券 kabuステーションAPI adapter (Japanese stocks, margin/信用).

The kabuステーション Windows app exposes a LOCAL REST API on localhost when API
mode is enabled. Python talks to it the same way the MT5 bridge talks to MT5.

  prod  : http://localhost:18080/kabusapi
  test  : http://localhost:18081/kabusapi   (検証環境 — use this first!)

Auth: POST /token with the API password -> a token used as the X-API-KEY header.
Orders also need the trade password (注文パスワード).

This adapter is LONG-ONLY margin (信用買い新規 / 返済売り), per the chosen design.
dry_run defaults True (logs intended orders, sends nothing); hard caps live in
the caller. Untested without a running kabuステーション — verify in 検証環境 first.

Docs: https://kabucom.github.io/kabusapi/reference/index.html
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests

EXCHANGE_TSE = 1          # 東証
SEC_STOCK = 1            # 株式
SIDE_BUY = "2"
SIDE_SELL = "1"
CASHMARGIN_NEW = 2       # 信用新規
CASHMARGIN_CLOSE = 3     # 信用返済
MARGIN_SEIDO = 1         # 制度信用
DELIV_NEW = 0            # 新規時
DELIV_CLOSE = 2          # 返済時: お預り金
FRONT_MARKET = 10        # 成行
ACCOUNT_TOKUTEI = 4      # 特定口座
PRODUCT_MARGIN = 2       # 信用ポジション

# ランキング種別
RANK_PRICE_UP = "1"      # 値上がり率
RANK_TURNOVER = "3"      # 売買代金


@dataclass
class StockPosition:
    symbol: str
    qty: float            # signed-ish; long margin => positive
    price: float
    hold_id: str


class KabuStation:
    def __init__(self, api_password: Optional[str] = None,
                 order_password: Optional[str] = None,
                 host: Optional[str] = None, live: bool = False,
                 dry_run: bool = True, account: int = ACCOUNT_TOKUTEI) -> None:
        self.api_password = api_password or os.getenv("KABU_API_PASSWORD", "")
        self.order_password = order_password or os.getenv("KABU_ORDER_PASSWORD", "")
        port = 18080 if live else 18081
        self.base = (host or os.getenv("KABU_HOST") or f"http://localhost:{port}/kabusapi").rstrip("/")
        self.dry_run = dry_run
        self.account = account
        self._token: Optional[str] = None

    # ------------------------------------------------------------------ #
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["X-API-KEY"] = self._token
        return h

    def connect(self) -> None:
        if not self.api_password:
            raise RuntimeError("KABU_API_PASSWORD not set (kabuステーション API password)")
        r = requests.post(f"{self.base}/token", json={"APIPassword": self.api_password},
                          headers={"Content-Type": "application/json"}, timeout=10)
        r.raise_for_status()
        self._token = r.json()["Token"]
        mode = "DRY-RUN" if self.dry_run else "LIVE ORDERS"
        print(f"[kabu] connected: {self.base} :: {mode}", flush=True)

    def _get(self, path: str) -> dict:
        r = requests.get(f"{self.base}{path}", headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ #
    def board(self, symbol: str, exchange: int = EXCHANGE_TSE) -> dict:
        return self._get(f"/board/{symbol}@{exchange}")

    def price(self, symbol: str, exchange: int = EXCHANGE_TSE) -> Optional[float]:
        b = self.board(symbol, exchange)
        return b.get("CurrentPrice")

    def trading_unit(self, symbol: str, exchange: int = EXCHANGE_TSE) -> int:
        info = self._get(f"/symbol/{symbol}@{exchange}")
        return int(info.get("TradingUnit", 100) or 100)

    def margin_power(self) -> float:
        """信用新規建可能額 (yen)."""
        w = self._get("/wallet/margin")
        return float(w.get("MarginAccountWallet", 0) or 0)

    def total_assets(self) -> float:
        try:
            return float(self._get("/wallet/cash").get("StockAccountWallet", 0) or 0)
        except Exception:
            return 0.0

    def positions(self) -> list[StockPosition]:
        rows = self._get(f"/positions?product={PRODUCT_MARGIN}")
        out = []
        for p in rows or []:
            qty = float(p.get("LeavesQty", p.get("Qty", 0)) or 0)
            out.append(StockPosition(symbol=str(p.get("Symbol")), qty=qty,
                                     price=float(p.get("Price", 0) or 0),
                                     hold_id=str(p.get("ExecutionID", p.get("HoldID", "")))))
        return out

    def ranking(self, kind: str = RANK_TURNOVER, exchange: str = "ALL", limit: int = 30) -> list[str]:
        """Candidate pool: top symbols by turnover / price-rise."""
        try:
            data = self._get(f"/ranking?Type={kind}&ExchangeDivision={exchange}")
            rows = data.get("Ranking", data) if isinstance(data, dict) else data
            syms = [str(r.get("Symbol")) for r in (rows or []) if r.get("Symbol")]
            return syms[:limit]
        except Exception as exc:
            print(f"[kabu] ranking failed: {exc}", flush=True)
            return []

    # ------------------------------------------------------------------ #
    def _send(self, payload: dict, label: str) -> Optional[dict]:
        if self.dry_run:
            print(f"[kabu][DRY] would order: {label} {payload.get('Symbol')} x{payload.get('Qty')}",
                  flush=True)
            return None
        r = requests.post(f"{self.base}/sendorder", json=payload, headers=self._headers(), timeout=15)
        if r.status_code != 200:
            print(f"[kabu] order FAILED {label}: {r.status_code} {r.text}", flush=True)
            return None
        res = r.json()
        print(f"[kabu] {label} {payload.get('Symbol')} x{payload.get('Qty')} -> "
              f"OrderId {res.get('OrderId')} result {res.get('Result')}", flush=True)
        return res

    def margin_buy(self, symbol: str, qty: int, exchange: int = EXCHANGE_TSE) -> Optional[dict]:
        """信用新規買い (成行)."""
        payload = {
            "Password": self.order_password, "Symbol": symbol, "Exchange": exchange,
            "SecurityType": SEC_STOCK, "Side": SIDE_BUY, "CashMargin": CASHMARGIN_NEW,
            "MarginTradeType": MARGIN_SEIDO, "DelivType": DELIV_NEW,
            "AccountType": self.account, "Qty": int(qty),
            "FrontOrderType": FRONT_MARKET, "Price": 0, "ExpireDay": 0,
        }
        return self._send(payload, "MARGIN-BUY")

    def margin_close_long(self, symbol: str, qty: int, exchange: int = EXCHANGE_TSE) -> Optional[dict]:
        """信用返済売り (成行) — closes the oldest long lots first."""
        payload = {
            "Password": self.order_password, "Symbol": symbol, "Exchange": exchange,
            "SecurityType": SEC_STOCK, "Side": SIDE_SELL, "CashMargin": CASHMARGIN_CLOSE,
            "MarginTradeType": MARGIN_SEIDO, "DelivType": DELIV_CLOSE,
            "AccountType": self.account, "Qty": int(qty),
            "FrontOrderType": FRONT_MARKET, "Price": 0, "ExpireDay": 0,
            "ClosePositionOrder": 0,   # 0 = 損益順/古い順に返済
        }
        return self._send(payload, "MARGIN-CLOSE")
