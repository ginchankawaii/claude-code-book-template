"""売買執行とポートフォリオ計算のコアロジック。"""
from __future__ import annotations

from . import config, market
from .database import connect, now_iso


class TradeError(Exception):
    """資金不足・保有不足など、売買できない場合に送出。"""


# --------------------------------------------------------------------------
# 口座・ポートフォリオ
# --------------------------------------------------------------------------
def get_cash() -> float:
    conn = connect()
    try:
        row = conn.execute("SELECT cash FROM account WHERE id = 1").fetchone()
        return row["cash"] if row else 0.0
    finally:
        conn.close()


def get_portfolio(with_quotes: bool = True) -> dict:
    """ポートフォリオの現在状況を返す。"""
    conn = connect()
    try:
        acc = conn.execute(
            "SELECT cash, starting_cash FROM account WHERE id = 1"
        ).fetchone()
        rows = conn.execute(
            "SELECT code, name, quantity, avg_cost FROM holdings ORDER BY code"
        ).fetchall()
    finally:
        conn.close()

    cash = acc["cash"] if acc else 0.0
    starting = acc["starting_cash"] if acc else config.STARTING_CASH

    holdings = []
    holdings_value = 0.0
    for r in rows:
        h = {
            "code": r["code"],
            "name": r["name"] or market.resolve_name(r["code"]),
            "quantity": r["quantity"],
            "avg_cost": round(r["avg_cost"], 2),
            "cost_basis": round(r["avg_cost"] * r["quantity"], 2),
        }
        if with_quotes:
            try:
                price = market.get_quote(r["code"])["price"]
            except Exception:  # noqa: BLE001
                price = r["avg_cost"]
            value = price * r["quantity"]
            pl = value - r["avg_cost"] * r["quantity"]
            h.update(
                {
                    "current_price": round(price, 2),
                    "market_value": round(value, 2),
                    "unrealized_pl": round(pl, 2),
                    "unrealized_pl_pct": round(
                        pl / (r["avg_cost"] * r["quantity"]) * 100, 2
                    )
                    if r["avg_cost"]
                    else 0.0,
                }
            )
            holdings_value += value
        holdings.append(h)

    total_value = cash + holdings_value
    total_pl = total_value - starting
    return {
        "cash": round(cash, 2),
        "starting_cash": round(starting, 2),
        "holdings_value": round(holdings_value, 2),
        "total_value": round(total_value, 2),
        "total_pl": round(total_pl, 2),
        "total_pl_pct": round(total_pl / starting * 100, 2) if starting else 0.0,
        "holdings": holdings,
    }


# --------------------------------------------------------------------------
# 売買執行
# --------------------------------------------------------------------------
def buy(
    code: str,
    quantity: int,
    price: float | None = None,
    decided_by: str = "manual",
    reason: str | None = None,
) -> dict:
    if quantity <= 0:
        raise TradeError("数量は1以上を指定してください。")
    name = market.resolve_name(code)
    if price is None:
        price = market.get_quote(code)["price"]
    amount = price * quantity

    conn = connect()
    try:
        cash = conn.execute(
            "SELECT cash FROM account WHERE id = 1"
        ).fetchone()["cash"]
        if amount > cash + 1e-6:
            raise TradeError(
                f"資金不足です。必要 {amount:,.0f}円 / 残高 {cash:,.0f}円"
            )

        # 保有更新（平均取得単価を再計算）
        h = conn.execute(
            "SELECT quantity, avg_cost FROM holdings WHERE code = ?", (code,)
        ).fetchone()
        if h:
            new_qty = h["quantity"] + quantity
            new_avg = (h["avg_cost"] * h["quantity"] + amount) / new_qty
            conn.execute(
                "UPDATE holdings SET quantity = ?, avg_cost = ?, name = ? "
                "WHERE code = ?",
                (new_qty, new_avg, name, code),
            )
        else:
            conn.execute(
                "INSERT INTO holdings (code, name, quantity, avg_cost) "
                "VALUES (?, ?, ?, ?)",
                (code, name, quantity, price),
            )

        conn.execute(
            "UPDATE account SET cash = cash - ? WHERE id = 1", (amount,)
        )
        conn.execute(
            "INSERT INTO trades (ts, code, name, side, quantity, price, amount, "
            "realized_pl, decided_by, reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (now_iso(), code, name, "BUY", quantity, price, amount, None,
             decided_by, reason),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "side": "BUY",
        "code": code,
        "name": name,
        "quantity": quantity,
        "price": round(price, 2),
        "amount": round(amount, 2),
    }


def sell(
    code: str,
    quantity: int,
    price: float | None = None,
    decided_by: str = "manual",
    reason: str | None = None,
) -> dict:
    if quantity <= 0:
        raise TradeError("数量は1以上を指定してください。")
    name = market.resolve_name(code)
    if price is None:
        price = market.get_quote(code)["price"]
    amount = price * quantity

    conn = connect()
    try:
        h = conn.execute(
            "SELECT quantity, avg_cost FROM holdings WHERE code = ?", (code,)
        ).fetchone()
        if not h or h["quantity"] < quantity:
            held = h["quantity"] if h else 0
            raise TradeError(
                f"保有数が不足しています。売却 {quantity} / 保有 {held}"
            )

        realized = (price - h["avg_cost"]) * quantity
        new_qty = h["quantity"] - quantity
        if new_qty == 0:
            conn.execute("DELETE FROM holdings WHERE code = ?", (code,))
        else:
            conn.execute(
                "UPDATE holdings SET quantity = ? WHERE code = ?",
                (new_qty, code),
            )

        conn.execute(
            "UPDATE account SET cash = cash + ? WHERE id = 1", (amount,)
        )
        conn.execute(
            "INSERT INTO trades (ts, code, name, side, quantity, price, amount, "
            "realized_pl, decided_by, reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (now_iso(), code, name, "SELL", quantity, price, amount, realized,
             decided_by, reason),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "side": "SELL",
        "code": code,
        "name": name,
        "quantity": quantity,
        "price": round(price, 2),
        "amount": round(amount, 2),
        "realized_pl": round(realized, 2),
    }


def list_trades(limit: int = 200) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
