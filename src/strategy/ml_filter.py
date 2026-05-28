"""LightGBM-based ML filter: predicts 5-day forward return direction."""

from __future__ import annotations

import os
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

try:
    import lightgbm as lgb
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import roc_auc_score
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    logger.warning("LightGBM が見つかりません。pip install lightgbm でインストールしてください。")

MODEL_DIR = Path(__file__).parent.parent.parent / "models"
MODEL_DIR.mkdir(exist_ok=True)

FEATURE_COLS = [
    "rsi", "rsi_slope",
    "macd_hist",
    "bb_pct", "bb_width",
    "atr_pct",
    "adx", "plus_di", "minus_di",
    "vol_ratio",
    "ret5", "ret10", "ret21",
    "pct_from_high52w",
]


class MLFilter:
    """週次再学習する LightGBM 方向性予測モデル。"""

    def __init__(self, config: dict):
        ml_cfg = config.get("ml", {})
        self.forward_days: int = ml_cfg.get("forward_days", 5)
        self.target_return: float = ml_cfg.get("target_return", 0.02)
        self.training_days: int = ml_cfg.get("training_days", 504)
        self.min_probability: float = ml_cfg.get("min_probability", 0.55)
        self.retrain_days: int = ml_cfg.get("retrain_interval_days", 7)
        self.models: dict[str, lgb.Booster | None] = {}
        self._last_trained: dict[str, datetime] = {}

    def _model_path(self, market: str) -> Path:
        return MODEL_DIR / f"ml_filter_{market}.pkl"

    def load(self, market: str) -> bool:
        path = self._model_path(market)
        if path.exists():
            try:
                with open(path, "rb") as f:
                    self.models[market] = pickle.load(f)
                logger.info(f"モデル読み込み完了: {path}")
                return True
            except Exception as e:
                logger.warning(f"モデル読み込み失敗: {e}")
        return False

    def _save(self, market: str) -> None:
        path = self._model_path(market)
        with open(path, "wb") as f:
            pickle.dump(self.models[market], f)

    def _needs_retrain(self, market: str) -> bool:
        last = self._last_trained.get(market)
        if last is None:
            return True
        days_since = (datetime.now() - last).days
        return days_since >= self.retrain_days

    def train(self, market: str, data_dict: dict[str, pd.DataFrame]) -> None:
        """複数銘柄のデータを結合してモデルを学習。"""
        if not HAS_LGB:
            return

        rows = []
        for symbol, df in data_dict.items():
            if len(df) < 60:
                continue
            df = df.copy()
            # ターゲット: forward_days 後のリターン >= target_return
            df["future_ret"] = df["close"].shift(-self.forward_days).pct_change(self.forward_days)
            df["target"] = (df["future_ret"] >= self.target_return).astype(int)
            df.dropna(subset=FEATURE_COLS + ["target"], inplace=True)
            rows.append(df)

        if not rows:
            logger.warning("学習データが不足しています")
            return

        all_data = pd.concat(rows, ignore_index=True)
        available_cols = [c for c in FEATURE_COLS if c in all_data.columns]
        X = all_data[available_cols].values
        y = all_data["target"].values

        if len(X) < 200:
            logger.warning(f"学習サンプル不足: {len(X)}")
            return

        params = {
            "objective": "binary",
            "metric": "auc",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "min_child_samples": 30,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "verbose": -1,
        }

        train_size = int(len(X) * 0.8)
        dtrain = lgb.Dataset(X[:train_size], label=y[:train_size])
        dval = lgb.Dataset(X[train_size:], label=y[train_size:], reference=dtrain)

        model = lgb.train(
            params,
            dtrain,
            num_boost_round=300,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(-1)],
        )

        self.models[market] = model
        self._last_trained[market] = datetime.now()
        self._save(market)

        val_pred = model.predict(X[train_size:])
        auc = roc_auc_score(y[train_size:], val_pred)
        logger.info(f"[ML] {market} モデル学習完了 AUC={auc:.3f} (サンプル数:{len(X)})")

    def predict(self, market: str, df: pd.DataFrame) -> float | None:
        """最新バーの上昇確率を返す。モデル未学習の場合は None。"""
        if not HAS_LGB:
            return None

        model = self.models.get(market)
        if model is None:
            return None

        if len(df) == 0:
            return None

        last = df.iloc[[-1]]
        available_cols = [c for c in FEATURE_COLS if c in last.columns]
        if not available_cols:
            return None

        try:
            X = last[available_cols].values
            prob = float(model.predict(X)[0])
            return prob
        except Exception as e:
            logger.debug(f"ML予測失敗: {e}")
            return None

    def maybe_retrain(self, market: str, data_dict: dict[str, pd.DataFrame]) -> None:
        """再学習が必要な場合のみ学習を実行（週次）。"""
        if self._needs_retrain(market):
            logger.info(f"[ML] {market} モデル再学習開始...")
            self.train(market, data_dict)
