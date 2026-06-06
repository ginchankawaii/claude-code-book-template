"""AI Japanese-stock margin-long trader via kabuステーションAPI.

Opus scans a candidate pool (kabu ranking + watchlist + held), web-searches each
name's 決算/news + the macro backdrop, and picks margin longs (買いのみ) with
conviction -> size. Orders go through kabuステーション; everything is persisted to
SQLite for the /live dashboard decision log.

  python -m scripts.run_stock_ai --once --dry            # one cycle, no orders
  python -m scripts.run_stock_ai --once --live           # send real (試験は検証環境で)
  python -m scripts.run_stock_ai                          # resident (daily)

Requires kabuステーション running with API enabled + KABU_API_PASSWORD /
KABU_ORDER_PASSWORD + ANTHROPIC_API_KEY in fxsim/.env. See docs/STOCK_AI.md.
USE THE 検証環境 (test port 18081) FIRST.
"""
from __future__ import annotations

import argparse
import time as _time
from datetime import datetime, timezone

from app import db
from app.adaptive import AdaptiveConfig, AdaptiveController
from app.ai_stock_trader import AIStockTrader, size_shares
from app.brokers.kabu import KabuStation, RANK_PRICE_UP, RANK_TURNOVER


def _ongoing_run(balance: float, model: str, max_risk: float) -> int:
    for r in db.list_runs():
        if not r.get("ended_at") and "stock-ai" in (r.get("params") or ""):
            return r["id"]
    return db.create_run(mode="live", instrument="JP-STOCKS", granularity="D",
                         initial_balance=balance,
                         params={"system": "stock-ai", "model": model, "max_risk": max_risk})


def build_candidates(kabu: KabuStation, watch: list[str], held: list[str],
                     n: int, exclude: set[str]) -> list[dict]:
    pool: list[str] = []
    for s in (kabu.ranking(RANK_TURNOVER, limit=n) + kabu.ranking(RANK_PRICE_UP, limit=n)
              + watch + held):
        if s and s not in pool and s not in exclude:
            pool.append(s)
    cands = []
    for s in pool[: n]:
        try:
            cands.append({"symbol": s, "price": kabu.price(s),
                          "unit": kabu.trading_unit(s)})
        except Exception:
            continue
    return cands


def cycle(kabu: KabuStation, trader: AIStockTrader, max_risk: float, max_positions: int,
          watch: list[str], n_candidates: int, exclude: set[str], trigger: str) -> bool:
    balance = kabu.total_assets()
    margin = kabu.margin_power()
    held = kabu.positions()
    held_syms = [p.symbol for p in held]
    if balance <= 0:
        print("[stock] account balance not available (kabuステーション接続を確認)", flush=True)
        return False

    candidates = build_candidates(kabu, watch, held_syms, n_candidates, exclude)
    ctx = {
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "market": "JP",
        "account": {"balance": balance, "margin_power": margin,
                    "held": [{"symbol": p.symbol, "qty": p.qty, "price": p.price} for p in held]},
        "candidates": candidates,
        "max_positions": max_positions,
        "excluded_symbols": sorted(exclude),
        "note_to_ai": "excluded_symbols はインサイダー規制等で売買禁止。絶対に選ばないこと。",
    }
    print(f"[stock] ({trigger}) consulting Opus... candidates={len(candidates)} held={held_syms}",
          flush=True)
    decision = trader.decide(ctx)
    if not decision.ok:
        print(f"[stock] no decision ({decision.note}); HOLDING everything", flush=True)
        return False

    run_id = _ongoing_run(balance, trader.model, max_risk)
    db.record_equity(run_id, datetime.now(timezone.utc), balance, balance, None)
    eq_hist = [e["equity"] for e in db.load_equity(run_id)] or [balance]
    brake, _, _ = AdaptiveController(AdaptiveConfig(base_risk=1.0, min_risk=0.2)).evaluate(eq_hist, [])

    price_of = {c["symbol"]: c for c in candidates}
    n_held = len(held_syms)
    max_name_notional = balance * 0.34          # ~one slot of a 3-name book
    if decision.note:
        print(f"[stock] 全体観: {decision.note}", flush=True)

    for call in decision.calls:
        if call.symbol in exclude:
            print(f"[stock] {call.symbol} は除外銘柄（インサイダー規制）。スキップ。", flush=True)
            continue
        c = price_of.get(call.symbol, {})
        price = c.get("price"); unit = c.get("unit", 100)
        shares = 0
        if call.action == "buy" and call.symbol not in held_syms and n_held < max_positions and price:
            shares = size_shares(call.conviction, balance, price, unit, max_risk, brake,
                                 max_name_notional=max_name_notional, margin_remaining=margin)
            if shares > 0:
                kabu.margin_buy(call.symbol, shares)
                margin -= shares * price; n_held += 1
        elif call.action == "close" and call.symbol in held_syms:
            qty = int(sum(p.qty for p in held if p.symbol == call.symbol))
            if qty > 0:
                kabu.margin_close_long(call.symbol, qty)
                n_held -= 1

        direction = 1 if call.action in ("buy", "hold") else 0
        db.record_signal(run_id, datetime.now(timezone.utc), call.symbol, "combined",
                         direction, call.conviction * direction, call.reason,
                         {"action": call.action.upper(), "conviction": call.conviction,
                          "target_shares": shares, "price": price, "factors": call.factors,
                          "plan": call.plan, "trigger": trigger, "note": decision.note})
        tag = f"{shares}株" if shares else ""
        print(f"[stock] {call.symbol}: {call.action.upper()} {tag} 確信{call.conviction:.2f} "
              f"| {call.reason}", flush=True)
        for f in call.factors:
            print(f"      - {f}", flush=True)
        if call.plan:
            print(f"      ↳ 保有方針: {call.plan}", flush=True)
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-risk", type=float, default=0.05)
    ap.add_argument("--max-positions", type=int, default=3)
    ap.add_argument("--candidates", type=int, default=20)
    ap.add_argument("--watch", default="", help="comma-separated extra symbols, e.g. 7203,6758")
    ap.add_argument("--exclude", default="", help="NEVER trade these (insider/restricted), e.g. 7518,9719,8053")
    ap.add_argument("--model", default=None)
    ap.add_argument("--poll", type=int, default=3600)
    ap.add_argument("--daily-gap-h", type=float, default=20.0)
    ap.add_argument("--live", action="store_true", help="send REAL orders (default dry-run)")
    ap.add_argument("--prod", action="store_true", help="use kabu PROD port 18080 (default: 18081 test)")
    ap.add_argument("--sim", action="store_true",
                    help="OFFLINE simulator — no account/kabuステーション needed (synthetic data)")
    ap.add_argument("--sim-steps", type=int, default=8, help="how many sim cycles to run (--sim)")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    watch = [s.strip() for s in args.watch.split(",") if s.strip()]
    exclude = {s.strip() for s in args.exclude.split(",") if s.strip()}
    db.init_db()

    if args.sim:
        from app.brokers.kabu_sim import SimKabuStation
        from app.ai_stock_trader import RuleStockTrader
        from app.config import settings
        kabu = SimKabuStation()
        # real Opus selection on the sim if a key is set; else the offline rule picker
        if settings.anthropic_api_key:
            trader = AIStockTrader(model=args.model, max_positions=args.max_positions)
            print("[stock][SIM] Opus selection on simulated prices", flush=True)
        else:
            trader = RuleStockTrader(max_positions=args.max_positions)
            print("[stock][SIM] no API key -> rule-based selection (mechanics demo)", flush=True)
        kabu.connect()
        if exclude:
            print(f"[stock] 除外銘柄（売買禁止）: {sorted(exclude)}", flush=True)
        steps = 1 if args.once else max(1, args.sim_steps)
        for i in range(steps):
            kabu.step()
            cycle(kabu, trader, args.max_risk, args.max_positions, watch,
                  args.candidates, exclude, f"sim-{i + 1}")
        eq = kabu.total_assets()
        print(f"[stock][SIM] done {steps} cycles. equity ¥{eq:,.0f} "
              f"({(eq/kabu.start_cash - 1) * 100:+.2f}%), positions={[p.symbol for p in kabu.positions()]}",
              flush=True)
        print("[stock][SIM] dashboard: py -3.12 -m app.server -> http://localhost:8000/live", flush=True)
        return

    kabu = KabuStation(live=args.prod, dry_run=not args.live)
    trader = AIStockTrader(model=args.model, max_positions=args.max_positions)
    kabu.connect()
    if exclude:
        print(f"[stock] 除外銘柄（売買禁止）: {sorted(exclude)}", flush=True)

    if args.once:
        cycle(kabu, trader, args.max_risk, args.max_positions, watch, args.candidates, exclude, "manual")
        return
    print(f"[stock] resident. daily_gap={args.daily_gap_h}h dry_run={kabu.dry_run}", flush=True)
    last = 0.0
    while True:
        try:
            if (_time.time() - last) >= args.daily_gap_h * 3600:
                if cycle(kabu, trader, args.max_risk, args.max_positions, watch,
                         args.candidates, exclude, "daily"):
                    last = _time.time()
        except Exception as exc:
            print(f"[stock] loop error: {exc}", flush=True)
        _time.sleep(args.poll)


if __name__ == "__main__":
    main()
