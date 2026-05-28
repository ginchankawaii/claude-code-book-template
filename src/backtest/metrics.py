"""Performance metrics for backtesting: Sharpe, drawdown, win rate, etc."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calc_metrics(
    equity: pd.Series,
    trades: list,
    initial_capital: float,
) -> dict:
    """バックテスト結果の主要指標を計算。"""
    if len(equity) < 2:
        return {}

    returns = equity.pct_change().dropna()
    total_return = (equity.iloc[-1] - initial_capital) / initial_capital
    ann_return = _annualized_return(equity)
    ann_vol = float(returns.std() * np.sqrt(252))
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0
    max_dd, max_dd_pct = _max_drawdown(equity)
    calmar = ann_return / abs(max_dd_pct) if max_dd_pct < 0 else float("inf")

    win_trades = [t for t in trades if t.pnl > 0]
    loss_trades = [t for t in trades if t.pnl <= 0]
    win_rate = len(win_trades) / len(trades) if trades else 0.0

    avg_win = np.mean([t.pnl_pct for t in win_trades]) if win_trades else 0.0
    avg_loss = np.mean([t.pnl_pct for t in loss_trades]) if loss_trades else 0.0
    profit_factor = (
        sum(t.pnl for t in win_trades) / abs(sum(t.pnl for t in loss_trades))
        if loss_trades and sum(t.pnl for t in loss_trades) != 0
        else float("inf")
    )

    return {
        "total_return_pct": total_return * 100,
        "annual_return_pct": ann_return * 100,
        "annual_volatility_pct": ann_vol * 100,
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": max_dd_pct * 100,
        "max_drawdown_abs": max_dd,
        "calmar_ratio": round(calmar, 2),
        "total_trades": len(trades),
        "win_rate_pct": win_rate * 100,
        "avg_win_pct": avg_win * 100,
        "avg_loss_pct": avg_loss * 100,
        "profit_factor": round(profit_factor, 2),
        "trading_days": len(equity),
    }


def _annualized_return(equity: pd.Series) -> float:
    years = len(equity) / 252
    if years == 0:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    return float(total ** (1 / years) - 1)


def _max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.expanding().max()
    drawdown = equity - peak
    max_dd_abs = float(drawdown.min())
    max_dd_pct = float((drawdown / peak).min())
    return max_dd_abs, max_dd_pct


def print_report(results: dict) -> None:
    """バックテスト結果をコンソール表示。"""
    m = results.get("metrics", {})
    if not m:
        print("結果なし")
        return

    print("\n" + "=" * 55)
    print("  バックテスト結果サマリー")
    print("=" * 55)
    print(f"  総リターン       : {m.get('total_return_pct', 0):+.2f}%")
    print(f"  年率リターン     : {m.get('annual_return_pct', 0):+.2f}%")
    print(f"  年率ボラティリティ: {m.get('annual_volatility_pct', 0):.2f}%")
    print(f"  シャープレシオ   : {m.get('sharpe_ratio', 0):.2f}")
    print(f"  最大ドローダウン : {m.get('max_drawdown_pct', 0):.2f}%")
    print(f"  カルマーレシオ   : {m.get('calmar_ratio', 0):.2f}")
    print("-" * 55)
    print(f"  総取引回数       : {m.get('total_trades', 0)}")
    print(f"  勝率             : {m.get('win_rate_pct', 0):.1f}%")
    print(f"  平均利益         : {m.get('avg_win_pct', 0):+.2f}%")
    print(f"  平均損失         : {m.get('avg_loss_pct', 0):+.2f}%")
    print(f"  プロフィットファクター: {m.get('profit_factor', 0):.2f}")
    print("=" * 55 + "\n")
