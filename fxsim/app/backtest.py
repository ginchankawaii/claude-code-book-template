"""Backtest runner + performance metrics.

Walks the enriched candle history bar-by-bar (no look-ahead: the strategy only
ever sees rows up to the current index) and feeds each bar to the engine.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

from . import db
from .config import Settings, settings as default_settings
from .engine import PaperTradingEngine, enrich_candles
from .indicators import candles_to_df, enrich
from .models import Candle
from .strategies import build_strategy
from .strategies.base import Strategy

WARMUP = 35  # bars needed before indicators are valid


@dataclass
class BacktestStats:
    run_id: int
    instrument: str
    bars: int
    initial_balance: float
    final_equity: float
    total_return_pct: float
    num_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe: float
    avg_win: float
    avg_loss: float


def compute_stats(
    run_id: str | int,
    instrument: str,
    initial_balance: float,
    equity_curve: list[tuple],
    trades: list,
) -> BacktestStats:
    final_eq = equity_curve[-1][2] if equity_curve else initial_balance
    total_return = (final_eq / initial_balance - 1.0) * 100.0

    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    num = len(trades)
    win_rate = (len(wins) / num * 100.0) if num else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (math.inf if gross_win else 0.0)

    # max drawdown on the equity curve
    peak = -math.inf
    max_dd = 0.0
    for _, _, eq, _ in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100.0)

    # Sharpe from per-bar equity returns (annualisation left simple/relative)
    eqs = [row[2] for row in equity_curve]
    rets = [
        (eqs[i] / eqs[i - 1] - 1.0)
        for i in range(1, len(eqs))
        if eqs[i - 1] > 0
    ]
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std * math.sqrt(len(rets))) if std > 0 else 0.0
    else:
        sharpe = 0.0

    return BacktestStats(
        run_id=run_id if isinstance(run_id, int) else 0,
        instrument=instrument,
        bars=len(equity_curve),
        initial_balance=initial_balance,
        final_equity=final_eq,
        total_return_pct=total_return,
        num_trades=num,
        win_rate=win_rate,
        profit_factor=profit_factor if profit_factor != math.inf else 999.0,
        max_drawdown_pct=max_dd,
        sharpe=sharpe,
        avg_win=(gross_win / len(wins)) if wins else 0.0,
        avg_loss=(-gross_loss / len(losses)) if losses else 0.0,
    )


def run_backtest(
    candles: list[Candle],
    instrument: str,
    cfg: Settings | None = None,
    persist: bool = True,
    strategy: Strategy | None = None,
) -> BacktestStats:
    cfg = cfg or default_settings
    strategy = strategy or build_strategy(cfg)

    df_full = enrich(candles_to_df(candles))
    run_id = 0
    if persist:
        db.init_db()
        run_id = db.create_run(
            mode="backtest",
            instrument=instrument,
            granularity=cfg.granularity,
            initial_balance=cfg.initial_balance,
            params={
                "risk_per_trade": cfg.risk_per_trade,
                "technical_weight": strategy.w_tech,
                "fundamental_weight": strategy.w_fund,
                "entry_threshold": cfg.entry_threshold,
                "exit_threshold": cfg.exit_threshold,
                "spread_pips": cfg.spread_pips,
            },
        )
        db.upsert_candles(candles)

    engine = PaperTradingEngine(run_id, instrument, strategy, cfg, persist=persist)

    for i in range(WARMUP, len(df_full)):
        window = df_full.iloc[: i + 1]
        signal = strategy.generate(instrument, window)
        if persist:
            t = window.iloc[-1]["time"]
            t = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
            db.record_signal(
                run_id, t, instrument, "technical",
                strategy.last_technical.direction, strategy.last_technical.score,
                strategy.last_technical.reason, strategy.last_technical.components,
            )
            db.record_signal(
                run_id, t, instrument, "fundamental",
                strategy.last_fundamental.direction, strategy.last_fundamental.score,
                strategy.last_fundamental.reason, strategy.last_fundamental.components,
            )
            db.record_signal(
                run_id, t, instrument, "combined",
                signal.direction, signal.score, signal.reason, signal.components,
            )
        engine.step(window, signal)

    engine.force_close(df_full)
    if persist:
        db.finish_run(run_id)

    return compute_stats(
        run_id, instrument, cfg.initial_balance, engine.equity_curve, engine.closed_trades
    )


def stats_dict(stats: BacktestStats) -> dict:
    return asdict(stats)
