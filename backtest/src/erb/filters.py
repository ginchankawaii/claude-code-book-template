"""グリッド各次元のフィルタ。

すべて「イベント時点で分かっている情報」だけを使う。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def apply_exclusion_list(trades: pd.DataFrame, applied: bool) -> pd.DataFrame:
    """仕様でハードコードされた除外銘柄。

    除外そのものが軽度の先読みなので、applied=False の結果も必ず併記する。
    """
    if not applied:
        return trades
    return trades[~trades["excluded_by_spec"].fillna(False)]


def apply_mktcap(trades: pd.DataFrame, cap_jpy: float | None) -> pd.DataFrame:
    if cap_jpy is None:
        return trades
    return trades[trades["mkt_cap"].notna() & (trades["mkt_cap"] <= cap_jpy)]


#: 閾値は分位点を丸めて作るため、境界の値が浮動小数点の誤差で
#: 落ちないよう、比較にわずかな許容を持たせる。
THRESHOLD_TOLERANCE = 1e-9


def apply_revision(trades: pd.DataFrame, threshold: float | None) -> pd.DataFrame:
    """修正率フィルタ。

    threshold > 0 : 上方修正が threshold 以上
    threshold < 0 : 下方修正が threshold 以下（対照群）
    threshold None: フィルタなし（対照群）
    """
    if threshold is None:
        return trades
    r = trades["revision_rate"]
    if threshold >= 0:
        return trades[r.notna() & (r >= threshold - THRESHOLD_TOLERANCE)]
    return trades[r.notna() & (r <= threshold + THRESHOLD_TOLERANCE)]


def apply_habitual(trades: pd.DataFrame, excluded: bool,
                   require_complete_window: bool = False) -> pd.DataFrame:
    """修正常習企業の除外。

    require_complete_window=True にすると、3年窓がデータ開始で欠けている
    イベントを落とす（窓が欠けたままの集計と比較するため）。
    """
    out = trades
    if require_complete_window:
        out = out[out["habitual_window_complete"].fillna(False)]
    if not excluded:
        return out
    return out[~out["habitual"].fillna(False)]


def apply_turnover(trades: pd.DataFrame, enabled: bool, position_size_jpy: int,
                   max_share: float) -> pd.DataFrame:
    """約定可能性フィルタ。

    1本の建玉が直近平均売買代金の max_share を超える銘柄は、
    寄付の成行では想定どおりに約定しないとみなして除外する。
    売買代金が取れない行は保守的に除外する。
    """
    if not enabled:
        return trades
    need = position_size_jpy / max_share
    return trades[trades["turnover_avg"].notna() & (trades["turnover_avg"] >= need)]


def apply_timing(trades: pd.DataFrame, timing: str) -> pd.DataFrame:
    """all / after_close / intraday"""
    if timing == "all":
        return trades
    if timing == "after_close":
        return trades[trades["after_close"].fillna(False)]
    if timing == "intraday":
        return trades[~trades["after_close"].fillna(True)]
    raise ValueError(f"未知のタイミング指定: {timing}")


def executable(trades: pd.DataFrame) -> pd.DataFrame:
    """約定できたトレードだけを残す。"""
    return trades[trades["status"] == "ok"]


def skip_counts(trades: pd.DataFrame) -> dict[str, int]:
    """約定できなかった理由の内訳。"""
    counts = trades["status"].value_counts(dropna=False).to_dict()
    return {str(k): int(v) for k, v in counts.items()}


def revision_quantile_thresholds(trades: pd.DataFrame,
                                 quantiles: tuple[float, ...] = (0.5, 0.75, 0.9)) -> list[float]:
    """修正率の分位点を閾値の候補として返す。

    東証の適時開示基準では営業利益の修正は原則 +-30% 超でないと開示義務が
    生じないため、固定の 5% / 10% / 20% では母集団がほぼ同じになりうる。
    実データの分布から閾値を決めるための下ごしらえ。
    """
    up = trades.loc[trades["revision_rate"] > 0, "revision_rate"]
    if up.empty:
        return []
    out: list[float] = []
    for q in quantiles:
        v = float(np.round(up.quantile(q), 4))
        # 分布が離散的だと分位点が重複する。重複したセルは情報を増やさない。
        if v > 0 and all(abs(v - existing) > THRESHOLD_TOLERANCE for existing in out):
            out.append(v)
    return out
