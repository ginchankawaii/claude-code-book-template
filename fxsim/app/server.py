"""FastAPI dashboard + JSON API.

Run:  python -m app.server      (serves http://localhost:8000)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .backtest import compute_stats, run_backtest, stats_dict
from .config import settings
from .fundamental import get_analyzer
from .models import TradeResult
from .providers import get_provider

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="FX Paper-Trading Simulator")
_backtest_lock = threading.Lock()


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "dashboard.html").read_text()


@app.get("/api/config")
def get_config() -> dict:
    return {
        "provider": settings.data_provider,
        "instruments": settings.instruments,
        "granularity": settings.granularity,
        "initial_balance": settings.initial_balance,
        "fundamental_mode": settings.fundamental_mode,
        "technical_weight": settings.technical_weight,
        "fundamental_weight": settings.fundamental_weight,
    }


@app.get("/api/runs")
def get_runs() -> list[dict]:
    return db.list_runs()


def _run_stats(run_id: int) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, f"run {run_id} not found")
    equity = db.load_equity(run_id)
    trades_raw = db.list_trades(run_id)
    closed = [t for t in trades_raw if t["status"] == "CLOSED"]

    # adapt to compute_stats' expected shapes
    equity_curve = [(e["time"], e["balance"], e["equity"], e["price"]) for e in equity]
    trade_objs = [
        TradeResult(
            instrument=t["instrument"], side=t["side"], units=t["units"],
            entry_time=t["entry_time"], entry_price=t["entry_price"],
            exit_time=t["exit_time"], exit_price=t["exit_price"],
            pnl=t["pnl"] or 0.0, reason=t["reason"] or "",
        )
        for t in closed
    ]
    stats = compute_stats(
        run_id, run["instrument"], run["initial_balance"], equity_curve, trade_objs
    )
    return stats_dict(stats)


@app.get("/api/runs/{run_id}")
def get_run_detail(run_id: int) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, f"run {run_id} not found")
    return {"run": run, "stats": _run_stats(run_id)}


@app.get("/api/runs/{run_id}/equity")
def get_equity(run_id: int) -> list[dict]:
    return db.load_equity(run_id)


@app.get("/api/runs/{run_id}/trades")
def get_trades(run_id: int) -> list[dict]:
    return db.list_trades(run_id)


@app.get("/api/runs/{run_id}/signals")
def get_signals(run_id: int, source: str | None = None) -> list[dict]:
    rows = db.load_signals(run_id)
    if source:
        rows = [r for r in rows if r["source"] == source]
    for r in rows:
        if r.get("components"):
            try:
                r["components"] = json.loads(r["components"])
            except (json.JSONDecodeError, TypeError):
                pass
    return rows


@app.get("/api/runs/{run_id}/candles")
def get_run_candles(run_id: int) -> list[dict]:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, f"run {run_id} not found")
    candles = db.load_candles(run["instrument"], run["granularity"])
    return [
        {
            "time": c.time.isoformat(), "open": c.open, "high": c.high,
            "low": c.low, "close": c.close, "volume": c.volume,
        }
        for c in candles
    ]


@app.get("/api/fundamental")
def get_fundamental() -> list[dict]:
    analyzer = get_analyzer("file")  # always read the cached file for display
    out = []
    for inst in settings.instruments:
        v = analyzer.view(inst)
        out.append(
            {
                "instrument": inst, "bias": v.bias, "decayed": v.decayed_bias(),
                "reason": v.reason, "asof": v.asof.isoformat(),
            }
        )
    return out


@app.post("/api/backtest")
def trigger_backtest(payload: dict) -> dict:
    instrument = payload.get("instrument", settings.instruments[0])
    granularity = payload.get("granularity", settings.granularity)
    bars = int(payload.get("bars", 1500))
    provider_name = payload.get("provider", settings.data_provider)

    if not _backtest_lock.acquire(blocking=False):
        raise HTTPException(409, "a backtest is already running")
    try:
        settings.granularity = granularity
        provider = get_provider(provider_name)
        candles = provider.history(instrument, granularity, bars)
        if not candles:
            raise HTTPException(400, "no candles returned by provider")
        stats = run_backtest(candles, instrument, persist=True)
        return {"run_id": stats.run_id, "stats": stats_dict(stats)}
    except HTTPException:
        raise
    except Exception as exc:  # surface provider/network errors to the UI
        raise HTTPException(500, f"backtest failed: {exc}") from exc
    finally:
        _backtest_lock.release()


# static assets (chart.js, css, js)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
