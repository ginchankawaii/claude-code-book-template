"""MetaTrader 5 execution adapter (OANDA証券 MT5, etc.).

Phase 2 of going live: place REAL orders through an MT5 terminal via the
official ``MetaTrader5`` Python package. Works with OANDA証券's free MT5 demo
(no GOLD/REST-API gate) and the same code targets the live account later.

IMPORTANT
  * Windows only — the ``MetaTrader5`` package requires a running MT5 terminal
    on Windows (or Windows VPS). The import is lazy so the rest of the project
    still works on Linux/Mac for backtests.
  * This strategy is LONG-or-FLAT. The broker reconciles the account to a target
    of either a positive position or zero — it never opens shorts.
  * Safety: dry_run defaults True (logs intended orders, sends nothing); a hard
    max-lot cap; a magic number tags our orders so we never touch manual trades.

Lots vs units: FX 1.00 lot = 100,000 units. risk-based sizing produces units;
we convert to lots and round to the symbol's volume step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Candle

# MT5 timeframe names resolved at runtime (constants only exist once imported)
_TF_NAMES = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
             "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
             "D": "TIMEFRAME_D1"}

UNITS_PER_LOT = 100_000.0


def to_mt5_symbol(instrument: str) -> str:
    """USD_JPY -> USDJPY (MT5 symbol convention)."""
    return instrument.replace("_", "").replace("/", "")


@dataclass
class AccountState:
    balance: float
    equity: float
    position_units: float          # signed net units (+long / -short / 0)
    avg_price: float


class MT5Broker:
    def __init__(
        self,
        instrument: str,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        terminal_path: Optional[str] = None,
        magic: int = 770077,
        dry_run: bool = True,
        max_lots: float = 5.0,
        deviation: int = 20,
    ) -> None:
        self.instrument = instrument
        self.symbol = to_mt5_symbol(instrument)
        self.login = login
        self.password = password
        self.server = server
        self.terminal_path = terminal_path
        self.magic = magic
        self.dry_run = dry_run
        self.max_lots = max_lots
        self.deviation = deviation
        self._mt5 = None

    # ------------------------------------------------------------------ #
    def _api(self):
        if self._mt5 is None:
            import MetaTrader5 as mt5  # lazy: Windows + installed only
            self._mt5 = mt5
        return self._mt5

    def connect(self) -> None:
        import time
        mt5 = self._api()
        kwargs = {"timeout": 60000, "portable": False}
        if self.terminal_path:
            kwargs["path"] = self.terminal_path
        if self.login:
            kwargs.update(login=int(self.login), password=self.password, server=self.server)
        last_err = None
        for attempt in range(1, 4):
            if mt5.initialize(**kwargs):
                last_err = None
                break
            last_err = mt5.last_error()
            print(f"[mt5] initialize attempt {attempt}/3 failed: {last_err}", flush=True)
            mt5.shutdown()
            time.sleep(3)
        if last_err is not None:
            raise RuntimeError(
                f"MT5 initialize failed: {last_err}\n"
                "  Checklist:\n"
                "   1) The MT5 terminal is OPEN and logged in to the demo account.\n"
                "   2) MT5: ツール>オプション>エキスパートアドバイザー>『アルゴリズム取引を許可する』ON,\n"
                "      and the toolbar 'アルゴ取引' button is green.\n"
                "   3) Same privilege level: do NOT run PowerShell as Administrator if MT5 is normal.\n"
                "   4) Set the terminal path, e.g. in PowerShell:\n"
                "      $env:MT5_PATH='C:\\Program Files\\OANDA MetaTrader 5\\terminal64.exe'"
            )
        if not mt5.symbol_select(self.symbol, True):
            raise RuntimeError(
                f"symbol_select({self.symbol}) failed: {mt5.last_error()} — "
                f"check the exact symbol name in MT5 'Market Watch' (e.g. USDJPY vs USDJPY.sml)")
        info = mt5.account_info()
        mode = "DRY-RUN (no orders sent)" if self.dry_run else "LIVE ORDERS"
        print(f"[mt5] connected: account {getattr(info,'login','?')} "
              f"balance {getattr(info,'balance','?')} server {getattr(info,'server','?')} :: {mode}",
              flush=True)

    def shutdown(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()

    # ------------------------------------------------------------------ #
    def history(self, granularity: str, count: int) -> list[Candle]:
        mt5 = self._api()
        tf = getattr(mt5, _TF_NAMES.get(granularity, "TIMEFRAME_D1"))
        rates = mt5.copy_rates_from_pos(self.symbol, tf, 0, count)
        if rates is None:
            raise RuntimeError(f"copy_rates failed: {mt5.last_error()}")
        from datetime import datetime, timezone
        out: list[Candle] = []
        for r in rates:
            out.append(Candle(
                instrument=self.instrument, granularity=granularity,
                time=datetime.fromtimestamp(int(r["time"]), tz=timezone.utc),
                open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                close=float(r["close"]), volume=float(r["tick_volume"]),
            ))
        return out

    def account(self) -> AccountState:
        mt5 = self._api()
        info = mt5.account_info()
        pos = mt5.positions_get(symbol=self.symbol) or []
        net = 0.0; wsum = 0.0
        for p in pos:
            sign = 1.0 if p.type == mt5.POSITION_TYPE_BUY else -1.0
            u = sign * p.volume * UNITS_PER_LOT
            net += u; wsum += u * p.price_open
        avg = (wsum / net) if net else 0.0
        return AccountState(balance=float(info.balance), equity=float(info.equity),
                            position_units=net, avg_price=avg)

    # ------------------------------------------------------------------ #
    def _round_lots(self, lots: float) -> float:
        mt5 = self._api()
        si = mt5.symbol_info(self.symbol)
        step = getattr(si, "volume_step", 0.01) or 0.01
        vmin = getattr(si, "volume_min", 0.01) or 0.01
        lots = round(round(lots / step) * step, 4)
        lots = min(lots, self.max_lots)
        return lots if lots >= vmin else 0.0

    def _market_order(self, side: str, lots: float, reason: str) -> None:
        mt5 = self._api()
        if lots <= 0:
            return
        if self.dry_run:
            print(f"[mt5][DRY] would {side} {lots} lots {self.symbol} ({reason})", flush=True)
            return
        tick = mt5.symbol_info_tick(self.symbol)
        price = tick.ask if side == "BUY" else tick.bid
        otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(lots),
            "type": otype, "price": price, "deviation": self.deviation,
            "magic": self.magic, "comment": f"steady:{reason}"[:31],
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"[mt5] order FAILED {side} {lots}: {getattr(res,'retcode','?')} "
                  f"{getattr(res,'comment','')} :: {mt5.last_error()}", flush=True)
        else:
            print(f"[mt5] {side} {lots} lots @ {res.price} done (ticket {res.order})", flush=True)

    def set_target_units(self, target_units: float, reason: str = "") -> None:
        """Reconcile the live net position to `target_units` (long-or-flat).
        Negative targets are clamped to 0 (this system never shorts)."""
        target_units = max(0.0, target_units)
        cur = self.account().position_units
        diff = target_units - cur
        lots = self._round_lots(abs(diff) / UNITS_PER_LOT)
        if lots <= 0:
            return
        self._market_order("BUY" if diff > 0 else "SELL", lots, reason or "rebalance")
