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
    return (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")


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


@app.get("/api/runs/{run_id}/adjustments")
def get_adjustments(run_id: int) -> list[dict]:
    rows = db.load_adjustments(run_id)
    for r in rows:
        if r.get("metrics"):
            try:
                r["metrics"] = json.loads(r["metrics"])
            except (json.JSONDecodeError, TypeError):
                pass
    return rows


@app.get("/live", response_class=HTMLResponse)
def live_page() -> str:
    return (STATIC_DIR / "live.html").read_text(encoding="utf-8")


@app.get("/api/live")
def get_live(run_id: int | None = None, kind: str | None = None) -> dict:
    """Everything the live view needs for the latest (or given) run.

    kind="fx" or "stocks" picks the latest run of that system so the FX and
    margin-stock dashboards don't overwrite each other."""
    rid = run_id or db.latest_run_id(kind)
    if not rid:
        return {"run": None, "kind": kind}
    run = db.get_run(rid)
    equity = db.load_equity(rid)
    trades = db.list_trades(rid)
    adjustments = db.load_adjustments(rid)
    closed = [t for t in trades if t["status"] == "CLOSED"]
    open_db = [t for t in trades if t["status"] == "OPEN"]

    eq_vals = [e["equity"] for e in equity]
    cur_eq = eq_vals[-1] if eq_vals else (run["initial_balance"] if run else 0)
    peak = max(eq_vals) if eq_vals else cur_eq
    drawdown = (peak - cur_eq) / peak * 100 if peak else 0.0
    params = {}
    try:
        params = json.loads(run["params"]) if run and run.get("params") else {}
    except (json.JSONDecodeError, TypeError):
        params = {}
    base_risk = params.get("base_risk") or params.get("max_risk")
    cur_risk = adjustments[-1]["new_val"] if adjustments else base_risk
    wins = [t for t in closed if (t["pnl"] or 0) > 0]

    # Live truth from the EA status file (the bridge persists trades in MT5, not
    # our DB), so prefer it for current equity + open position when available.
    # Only for FX runs — the MT5 bridge has nothing to do with the stock system.
    is_fx = bool(run and run.get("instrument") != "JP-STOCKS")
    open_pos = None
    try:
        from . import bridge as _bridge
        live = _bridge.read_status() if is_fx else None
    except Exception:
        live = None
    if live and live.get("equity", 0) > 0:
        cur_eq = live["equity"]
        peak = max(peak, cur_eq)
        drawdown = (peak - cur_eq) / peak * 100 if peak else 0.0
        pl = live.get("position_lots", 0.0)
        if abs(pl) > 1e-9:
            open_pos = {"side": "LONG" if pl > 0 else "SHORT", "units": pl * 100000}
    if open_pos is None and open_db:
        open_pos = open_db[0]

    return {
        "run": run,
        "status": "running" if run and not run.get("ended_at") else "finished",
        "current_equity": cur_eq,
        "initial_balance": run["initial_balance"] if run else 0,
        "return_pct": (cur_eq / run["initial_balance"] - 1) * 100 if run else 0,
        "drawdown_pct": drawdown,
        "base_risk": base_risk,
        "current_risk": cur_risk,
        "open_position": open_pos,
        "n_trades": len(closed),
        "win_rate": (len(wins) / len(closed) * 100) if closed else 0,
        "equity": [{"time": e["time"], "equity": e["equity"]} for e in equity],
        "recent_trades": closed[-10:][::-1],
        "recent_adjustments": adjustments[-12:][::-1],
        "decisions": _recent_decisions(rid),
        "holdings": _latest_holdings(rid),
        "last_price": equity[-1]["price"] if equity else None,
    }


def _latest_holdings(run_id: int) -> list | None:
    """Most recent portfolio snapshot (stock system writes one per cycle)."""
    latest = None
    for s in db.load_signals(run_id):
        if s.get("source") == "portfolio":
            latest = s
    if not latest or not latest.get("components"):
        return None
    try:
        return json.loads(latest["components"]).get("holdings")
    except (json.JSONDecodeError, TypeError):
        return None


def _recent_decisions(run_id: int, limit: int = 15) -> list[dict]:
    """AI decision log (reason / factors / hold-plan) for the live view."""
    out = []
    for s in db.load_signals(run_id):
        if s.get("source") != "combined":
            continue
        comp = {}
        if s.get("components"):
            try:
                comp = json.loads(s["components"])
            except (json.JSONDecodeError, TypeError):
                comp = {}
        out.append({
            "time": s["time"],
            "symbol": s.get("instrument", ""),
            "action": comp.get("action", "FLAT"),
            "conviction": comp.get("conviction", 0.0),
            "target_lots": comp.get("target_lots", 0.0),
            "target_shares": comp.get("target_shares", 0),
            "risk_used": comp.get("risk_used", 0.0),
            "reason": s.get("reason", ""),
            "factors": comp.get("factors", []),
            "plan": comp.get("plan", ""),
            "trigger": comp.get("trigger", ""),
        })
    return out[-limit:][::-1]


# static assets (chart.js, css, js)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
