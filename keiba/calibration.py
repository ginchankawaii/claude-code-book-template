"""M2: 確率較正と確率品質メトリクス。

GBDT の生確率は実確率と一致する保証がなく、EV=確率×オッズ の判定が歪む。
学習とは別期間で Isotonic / Platt を当て、Brier・log-loss・ECE・信頼性曲線で
質を確認してから EV 計算に渡す(research第5.3章)。較正後はレース内で
再正規化(合計1)する。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


@dataclass
class Calibrator:
    method: str = "isotonic"   # "isotonic" | "platt" | "none"
    _iso: IsotonicRegression | None = None
    _lr: LogisticRegression | None = None

    def fit(self, probs: np.ndarray, outcomes: np.ndarray) -> "Calibrator":
        probs = np.clip(np.asarray(probs, dtype=float), 1e-9, 1 - 1e-9)
        outcomes = np.asarray(outcomes, dtype=float)
        if self.method == "isotonic":
            self._iso = IsotonicRegression(out_of_bounds="clip")
            self._iso.fit(probs, outcomes)
        elif self.method == "platt":
            self._lr = LogisticRegression(C=1e6, solver="lbfgs")
            self._lr.fit(_logit(probs).reshape(-1, 1), outcomes)
        elif self.method == "none":
            pass
        else:
            raise ValueError(f"未知の較正法: {self.method}")
        return self

    def transform(self, probs: np.ndarray) -> np.ndarray:
        probs = np.clip(np.asarray(probs, dtype=float), 1e-9, 1 - 1e-9)
        if self.method == "isotonic":
            return self._iso.predict(probs)
        if self.method == "platt":
            return self._lr.predict_proba(_logit(probs).reshape(-1, 1))[:, 1]
        return probs


def race_normalize(df: pd.DataFrame, probs: np.ndarray) -> np.ndarray:
    """レース内で確率を合計1に正規化する。"""
    s = pd.Series(probs, index=df.index)
    totals = s.groupby(df["race_id"]).transform("sum")
    return (s / totals.replace(0, np.nan)).fillna(0.0).to_numpy()


# ----------------------------------------------------------------------------
# メトリクス
# ----------------------------------------------------------------------------

def brier_score(probs: np.ndarray, outcomes: np.ndarray) -> float:
    probs = np.asarray(probs, float)
    outcomes = np.asarray(outcomes, float)
    return float(np.mean((probs - outcomes) ** 2))


def log_loss(probs: np.ndarray, outcomes: np.ndarray) -> float:
    p = np.clip(np.asarray(probs, float), 1e-12, 1 - 1e-12)
    y = np.asarray(outcomes, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def expected_calibration_error(probs: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> float:
    """ECE: ビンごとの (平均予測 - 実測) の加重平均絶対値。"""
    probs = np.asarray(probs, float)
    outcomes = np.asarray(outcomes, float)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(probs, bins) - 1, 0, n_bins - 1)
    ece = 0.0
    n = len(probs)
    for b in range(n_bins):
        mask = idx == b
        if not np.any(mask):
            continue
        conf = probs[mask].mean()
        acc = outcomes[mask].mean()
        ece += (mask.sum() / n) * abs(conf - acc)
    return float(ece)


def reliability_curve(probs: np.ndarray, outcomes: np.ndarray, n_bins: int = 10):
    """信頼性曲線データ (bin中心, 平均予測, 実測, 件数) を返す。"""
    probs = np.asarray(probs, float)
    outcomes = np.asarray(outcomes, float)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(probs, bins) - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        mask = idx == b
        if not np.any(mask):
            continue
        rows.append({
            "bin_center": (bins[b] + bins[b + 1]) / 2,
            "mean_pred": float(probs[mask].mean()),
            "observed": float(outcomes[mask].mean()),
            "count": int(mask.sum()),
        })
    return pd.DataFrame(rows)


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))
