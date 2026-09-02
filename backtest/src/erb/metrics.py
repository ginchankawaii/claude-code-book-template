"""集計・統計。

決算発表は 2月/5月/8月/11月 に集中するため、同じ週のトレードは市場全体の
動きを共有し独立ではない。単純な t 検定は有意性を過大評価するので、
日付クラスターでのブートストラップを併記する。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def summarize(trades: pd.DataFrame, *, return_col: str = "gross_return",
              excess_col: str = "excess_return", net_col: str = "net_excess_return",
              bootstrap_iterations: int = 5000, cluster_by: str = "week",
              target_t: float = 2.0, seed: int = 20260902) -> dict:
    """1セル分の集計。"""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "verdict": "判定不能(0件)"}

    gross = trades[return_col].dropna()
    excess = trades[excess_col].dropna() if excess_col in trades.columns else pd.Series(dtype=float)
    net = trades[net_col].dropna() if net_col in trades.columns else pd.Series(dtype=float)

    out: dict = {
        "trades": n,
        "gross_pct": _mean_pct(gross),
        "median_pct": float(gross.median() * 100) if not gross.empty else np.nan,
        "stdev_pct": float(gross.std(ddof=1) * 100) if len(gross) > 1 else np.nan,
        "win_rate": float((gross > 0).mean()) if not gross.empty else np.nan,
        "excess_topix_pct": _mean_pct(excess),
        "net_edge_pct": _mean_pct(net),
        "topix_coverage": float(excess.notna().mean()) if n else 0.0,
    }

    base = net if not net.empty else (excess if not excess.empty else gross)
    out["t_stat"] = _t_stat(base)

    lo, hi = _cluster_bootstrap_ci(trades, base.name or net_col, cluster_by,
                                   bootstrap_iterations, seed)
    out["cluster_ci_low_pct"] = lo
    out["cluster_ci_high_pct"] = hi

    # 必要件数: (2 sigma / 目標平均)^2
    sigma = out["stdev_pct"]
    mean = out["net_edge_pct"] if not np.isnan(out.get("net_edge_pct", np.nan)) else out["gross_pct"]
    out["required_n"] = _required_n(sigma, mean, target_t)
    out["verdict"] = _verdict(n, out["required_n"], out["cluster_ci_low_pct"])

    by_year = {}
    if "exit_date" in trades.columns:
        years = pd.Series([d.year if d is not None and not pd.isna(d) else None
                           for d in trades["exit_date"]], index=trades.index)
        for y, grp in trades.groupby(years, observed=True):
            if y is None:
                continue
            by_year[int(y)] = _mean_pct(grp[return_col].dropna())
    out["by_year_gross_pct"] = by_year

    return out


def split_halves(trades: pd.DataFrame, cutoff) -> tuple[pd.DataFrame, pd.DataFrame]:
    """前半 / 後半の時間分割。両方プラスでなければ採用しない。"""
    d = pd.to_datetime(pd.Series(list(trades["entry_date"])), errors="coerce")
    mask = (d < pd.Timestamp(cutoff)).to_numpy()
    return trades[mask], trades[~mask]


def _mean_pct(s: pd.Series) -> float:
    return float(s.mean() * 100) if s is not None and len(s) else np.nan


def _t_stat(s: pd.Series) -> float:
    if s is None or len(s) < 2:
        return np.nan
    sd = s.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return np.nan
    return float(s.mean() / (sd / np.sqrt(len(s))))


def _cluster_key(trades: pd.DataFrame, cluster_by: str) -> pd.Series:
    d = pd.to_datetime(pd.Series(list(trades["entry_date"])), errors="coerce")
    if cluster_by == "week":
        return d.dt.strftime("%G-W%V")
    if cluster_by == "month":
        return d.dt.strftime("%Y-%m")
    if cluster_by == "day":
        return d.dt.strftime("%Y-%m-%d")
    raise ValueError(f"未知のクラスタ単位: {cluster_by}")


def _cluster_bootstrap_ci(trades: pd.DataFrame, col: str, cluster_by: str,
                          iterations: int, seed: int) -> tuple[float, float]:
    """同じ週のトレードをまとめて再抽出する。

    トレード単位で再抽出すると、決算集中期の相関を無視して
    信頼区間が不当に狭くなる。
    """
    if col not in trades.columns:
        return (np.nan, np.nan)
    df = trades[[col]].copy()
    df["_cluster"] = _cluster_key(trades, cluster_by).to_numpy()
    df = df.dropna(subset=[col])
    if df.empty:
        return (np.nan, np.nan)

    groups = [g[col].to_numpy() for _, g in df.groupby("_cluster", observed=True, sort=False)]
    k = len(groups)
    if k < 2:
        return (np.nan, np.nan)

    rng = np.random.default_rng(seed)
    means = np.empty(iterations, dtype=float)
    for it in range(iterations):
        idx = rng.integers(0, k, size=k)
        sample = np.concatenate([groups[i] for i in idx])
        means[it] = sample.mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return (float(lo * 100), float(hi * 100))


def _required_n(sigma_pct: float, mean_pct: float, target_t: float) -> float:
    """目標 t 値に必要なトレード数。"""
    if (sigma_pct is None or np.isnan(sigma_pct) or mean_pct is None
            or np.isnan(mean_pct) or mean_pct <= 0):
        return np.nan
    return float(np.ceil((target_t * sigma_pct / mean_pct) ** 2))


def _verdict(n: int, required_n: float, ci_low_pct: float) -> str:
    if required_n is None or np.isnan(required_n):
        return "判定不能(平均が0以下)"
    if n < required_n:
        return f"判定不能(件数不足 {n}/{int(required_n)})"
    if ci_low_pct is not None and not np.isnan(ci_low_pct) and ci_low_pct <= 0:
        return "判定不能(信頼区間が0を跨ぐ)"
    return "判定可"


def classify_net_edge(net_edge_pct: float, abort_below: float, paper_below: float) -> str:
    """純エッジによる採否。"""
    if net_edge_pct is None or np.isnan(net_edge_pct):
        return "算出不能"
    if net_edge_pct < abort_below:
        return "打ち切り"
    if net_edge_pct < paper_below:
        return "ペーパートレード3か月"
    return "少額実弾"
