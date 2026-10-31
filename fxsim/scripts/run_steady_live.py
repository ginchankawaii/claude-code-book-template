"""Forward paper-trading on a live OANDA practice feed (real prices, sim fills).

Setup (one time):
  1. Open a FREE OANDA practice (demo) account: https://www.oanda.com/
  2. Generate an API token (Account > Manage API Access).
  3. Export credentials, e.g. in fxsim/.env:
        FXSIM_PROVIDER=oanda
        OANDA_API_TOKEN=xxxxxxxx
        OANDA_ACCOUNT_ID=xxx-xxx-xxxxxxxx-xxx
        OANDA_ENV=practice
        FXSIM_INSTRUMENTS=USD_JPY
        FXSIM_GRANULARITY=D
        FXSIM_STRATEGY=trend
     (the host api-fxpractice.oanda.com must be reachable / allow-listed)

Run resident:    python -m scripts.run_steady_live
Run once (cron): python -m scripts.run_steady_live --once
Watch:           python -m app.server   ->  http://localhost:8000/live
"""
from __future__ import annotations

import argparse

from app.config import Settings
from app.steady_live import SteadyLiveTrader


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default=None)
    ap.add_argument("--granularity", default=None)
    ap.add_argument("--sma", type=int, default=150)
    ap.add_argument("--risk", type=float, default=0.03)
    ap.add_argument("--balance", type=float, default=100000)
    ap.add_argument("--provider", default=None, help="default from FXSIM_PROVIDER (use 'oanda')")
    ap.add_argument("--poll", type=int, default=None, help="seconds between polls")
    ap.add_argument("--once", action="store_true", help="check once and exit (for cron)")
    args = ap.parse_args()

    base = Settings()
    cfg = Settings(
        strategy="trend",
        data_provider=args.provider or base.data_provider,
        instruments=base.instruments,
        granularity=args.granularity or base.granularity,
        trend_sma=args.sma, risk_per_trade=args.risk,
        use_take_profit=False, initial_balance=args.balance,
        max_position_units=10_000_000,
        oanda_token=base.oanda_token, oanda_account=base.oanda_account,
        oanda_env=base.oanda_env,
    )
    instrument = args.instrument or cfg.instruments[0]
    trader = SteadyLiveTrader(instrument, cfg=cfg, provider_name=cfg.data_provider)

    if args.once:
        acted = trader.poll_once()
        print(f"[steady-live] one-shot: {'acted on new bar' if acted else 'no new bar'}")
        import app.db as db
        db.finish_run(trader.run_id)
    else:
        trader.run(poll_seconds=args.poll)


if __name__ == "__main__":
    main()
