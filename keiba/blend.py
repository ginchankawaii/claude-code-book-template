"""M4: 市場確率ブレンド(Benter 第2段)と連系券種への確率展開。

市場(オッズ由来)確率は最強の予測子。ファンダメンタルモデルの確率と
市場確率を対数線形(重み付き幾何平均)で合成し、レース内で再正規化する。
合成重みは検証データの log-loss 最小化で決める。市場が織り込めていない
残差(本合成データでは form の過小評価)を取りにいく構図(research第5.4章)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .calibration import log_loss, race_normalize


def market_implied_prob(df: pd.DataFrame, odds_col: str = "final_odds") -> np.ndarray:
    """オッズから市場の暗黙確率を求め、控除率分のオーバーラウンドを除いて
    レース内で合計1に正規化する。"""
    inv = 1.0 / np.clip(df[odds_col].to_numpy(), 1e-9, None)
    return race_normalize(df, inv)


def benter_blend(df: pd.DataFrame, model_prob: np.ndarray, market_prob: np.ndarray,
                 w_market: float) -> np.ndarray:
    """対数線形ブレンド: p ∝ model^(1-w) * market^w をレース内で正規化。"""
    m = np.clip(model_prob, 1e-12, 1.0)
    q = np.clip(market_prob, 1e-12, 1.0)
    log_mix = (1.0 - w_market) * np.log(m) + w_market * np.log(q)
    # レース内 softmax(=正規化済み幾何平均)
    mix = np.exp(log_mix)
    return race_normalize(df, mix)


def fit_blend_weight(df: pd.DataFrame, model_prob: np.ndarray, market_prob: np.ndarray,
                     outcomes: np.ndarray, grid: int = 41) -> tuple[float, float]:
    """検証データで log-loss を最小化するブレンド重み w を grid search。

    Returns: (best_w, best_logloss)
    """
    best_w, best_ll = 0.0, np.inf
    for w in np.linspace(0.0, 1.0, grid):
        blended = benter_blend(df, model_prob, market_prob, w)
        ll = log_loss(blended, outcomes)
        if ll < best_ll:
            best_ll, best_w = ll, float(w)
    return best_w, float(best_ll)


# ----------------------------------------------------------------------------
# 連系券種への展開(Harville 1973: 逐次条件付き確率)
# ----------------------------------------------------------------------------

def harville_exacta(win_probs: np.ndarray, i: int, j: int) -> float:
    """馬単 i→j の確率。 P(i1着)*P(j2着|i除外)。"""
    p = np.clip(win_probs, 1e-12, None)
    pi = p[i] / p.sum()
    rest = p.sum() - p[i]
    pj = p[j] / rest if rest > 0 else 0.0
    return float(pi * pj)


def harville_trifecta(win_probs: np.ndarray, i: int, j: int, k: int) -> float:
    """三連単 i→j→k の確率(Harville 展開)。"""
    p = np.clip(win_probs, 1e-12, None)
    total = p.sum()
    pi = p[i] / total
    r1 = total - p[i]
    pj = p[j] / r1 if r1 > 0 else 0.0
    r2 = r1 - p[j]
    pk = p[k] / r2 if r2 > 0 else 0.0
    return float(pi * pj * pk)


def harville_top3_prob(win_probs: np.ndarray, i: int) -> float:
    """馬 i が3着内に入る確率(全順列の Harville 和)。複勝の近似。

    注意: Harville は上位人気を過大評価するバイアスを持つ(research第5.5章)。
    実データでは discounted Harville や複勝直接学習で補正する。
    """
    p = np.clip(win_probs, 1e-12, None)
    n = len(p)
    total = p.sum()
    prob = 0.0
    # i が 1着
    prob += p[i] / total
    # i が 2着
    for a in range(n):
        if a == i:
            continue
        pa = p[a] / total
        r = total - p[a]
        prob += pa * (p[i] / r if r > 0 else 0.0)
    # i が 3着
    for a in range(n):
        if a == i:
            continue
        pa = p[a] / total
        r1 = total - p[a]
        for b in range(n):
            if b == i or b == a:
                continue
            pb = p[b] / r1 if r1 > 0 else 0.0
            r2 = r1 - p[b]
            prob += pa * pb * (p[i] / r2 if r2 > 0 else 0.0)
    return float(prob)
