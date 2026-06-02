"""FastAPI アプリケーション本体（REST API + 静的フロントエンド配信）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import advisor, config, database, engine, indicators, market

app = FastAPI(title="日本株 投資シミュレーター", version="1.0.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.on_event("startup")
def _startup() -> None:
    database.init_db()


# --------------------------------------------------------------------------
# リクエストモデル
# --------------------------------------------------------------------------
class TradeRequest(BaseModel):
    code: str
    quantity: int
    price: float | None = None


class WatchlistRequest(BaseModel):
    code: str


class AdvisorRequest(BaseModel):
    code: str
    auto_execute: bool = False


class AdvisorBatchRequest(BaseModel):
    auto_execute: bool = False
    codes: list[str] | None = None


# --------------------------------------------------------------------------
# システム情報
# --------------------------------------------------------------------------
@app.get("/api/status")
def status() -> dict:
    return {
        "data_source": config.MARKET_DATA_SOURCE,
        "fallback_to_mock": config.MARKET_FALLBACK_TO_MOCK,
        "advisor_enabled": bool(config.ANTHROPIC_API_KEY),
        "advisor_model": config.ADVISOR_MODEL,
        "starting_cash": config.STARTING_CASH,
        "trade_unit": config.TRADE_UNIT,
    }


# --------------------------------------------------------------------------
# ポートフォリオ / 取引
# --------------------------------------------------------------------------
@app.get("/api/portfolio")
def portfolio() -> dict:
    return engine.get_portfolio()


@app.get("/api/trades")
def trades(limit: int = 200) -> list[dict]:
    return engine.list_trades(limit)


@app.post("/api/trade/buy")
def trade_buy(req: TradeRequest) -> dict:
    try:
        return engine.buy(req.code, req.quantity, req.price, decided_by="manual")
    except engine.TradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except market.MarketError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/trade/sell")
def trade_sell(req: TradeRequest) -> dict:
    try:
        return engine.sell(req.code, req.quantity, req.price, decided_by="manual")
    except engine.TradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except market.MarketError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/reset")
def reset() -> dict:
    database.reset_db()
    return {"ok": True}


# --------------------------------------------------------------------------
# マーケットデータ
# --------------------------------------------------------------------------
@app.get("/api/quote/{code}")
def quote(code: str) -> dict:
    try:
        return market.get_quote(code)
    except market.MarketError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/history/{code}")
def history(code: str, days: int = 120) -> dict:
    try:
        hist = market.get_history(code, days)
    except market.MarketError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        "code": code,
        "name": market.resolve_name(code),
        "history": hist,
        "indicators": indicators.summarize(hist),
    }


# --------------------------------------------------------------------------
# ウォッチリスト
# --------------------------------------------------------------------------
@app.get("/api/watchlist")
def get_watchlist() -> list[dict]:
    conn = database.connect()
    try:
        rows = conn.execute(
            "SELECT code, name FROM watchlist ORDER BY code"
        ).fetchall()
        codes = [dict(r) for r in rows]
    finally:
        conn.close()
    for c in codes:
        try:
            q = market.get_quote(c["code"])
            c.update(
                {
                    "price": q["price"],
                    "change": q["change"],
                    "change_pct": q["change_pct"],
                    "source": q["source"],
                }
            )
        except Exception:  # noqa: BLE001
            c.update({"price": None, "change": None, "change_pct": None})
    return codes


@app.post("/api/watchlist")
def add_watchlist(req: WatchlistRequest) -> dict:
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="証券コードを指定してください。")
    conn = database.connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (code, name, added_at) "
            "VALUES (?, ?, ?)",
            (code, market.resolve_name(code), database.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "code": code}


@app.delete("/api/watchlist/{code}")
def remove_watchlist(code: str) -> dict:
    conn = database.connect()
    try:
        conn.execute("DELETE FROM watchlist WHERE code = ?", (code,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# --------------------------------------------------------------------------
# AIアドバイザー（Claude）
# --------------------------------------------------------------------------
@app.post("/api/advisor/decide")
def advisor_decide(req: AdvisorRequest) -> dict:
    try:
        return advisor.decide_and_maybe_execute(req.code, req.auto_execute)
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except market.MarketError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/advisor/run-all")
def advisor_run_all(req: AdvisorBatchRequest) -> dict:
    codes = req.codes
    if not codes:
        conn = database.connect()
        try:
            codes = [
                r["code"]
                for r in conn.execute("SELECT code FROM watchlist").fetchall()
            ]
        finally:
            conn.close()
    results = []
    for code in codes:
        try:
            results.append(
                advisor.decide_and_maybe_execute(code, req.auto_execute)
            )
        except (advisor.AdvisorError, market.MarketError) as exc:
            results.append({"code": code, "error": str(exc)})
    return {"results": results}


@app.get("/api/decisions")
def decisions(limit: int = 100) -> list[dict]:
    return advisor.list_decisions(limit)


# --------------------------------------------------------------------------
# 静的フロントエンド
# --------------------------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
