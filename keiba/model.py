"""M2: LightGBM による強さ推定モデル。

2系統を実装:
  * binary   : 各馬が3着内(または1着)に入るかの2値分類。出力はレース内で
               正規化して勝率(合計1)にする。較正必須。
  * lambdarank: レース(group)内の相対順位を直接最適化する Learning-to-Rank。
               出力スコアをレース内ソフトマックスで確率化する。

いずれも「同一レース内で出走馬を相対化する」ことが本質(research第5章)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except Exception as exc:  # pragma: no cover
    lgb = None
    _LGB_ERR = exc

from .features import FEATURE_COLUMNS, LABEL_TOP3, LABEL_WIN

# カテゴリとして扱う特徴量
CATEGORICAL = ["sex", "surface", "class_level", "going", "running_style"]


def _coerce_categoricals(X: pd.DataFrame, cats: list[str]) -> pd.DataFrame:
    """カテゴリ列の負値を NaN(=欠損)に統一する。

    LightGBM のカテゴリ特徴は非負整数のみ。負値(例: 馬場コード0由来の going=-1)が
    あると警告を出して NaN 化されるので、ここで明示的に NaN にして警告を消し、
    扱いを揃える。
    """
    if not cats:
        return X
    X = X.copy()
    for c in cats:
        if c in X.columns:
            col = pd.to_numeric(X[c], errors="coerce")
            X[c] = col.where(col >= 0)   # 負値 → NaN
    return X


@dataclass
class ModelConfig:
    objective: str = "binary"          # "binary" | "lambdarank"(ensemble=False の時に使用)
    label: str = LABEL_TOP3            # binary の学習ラベル(3着内が安定)
    softmax_temperature: float = 1.0   # 確率化時の温度
    num_boost_round: int = 400
    learning_rate: float = 0.03
    num_leaves: int = 31
    min_data_in_leaf: int = 80
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    bagging_freq: int = 1
    lambda_l2: float = 1.0
    max_depth: int = -1
    seed: int = 42
    verbose: int = -1
    # --- 任意の追加機構(既定OFF) -------------------------------------------
    # 合成データのA/B(500日・1600日の両スケール)では、以下はいずれも
    # 中立〜わずかに悪化だったため既定にしない(実測で勝った構成を既定とする)。
    # 実データでは挙動が変わる可能性があるので --ensemble-model で検証できる。
    # 検証区間の指標が改善しなくなったら打ち切る(0で無効)。
    early_stopping_rounds: int = 0
    # 3系統アンサンブル: top3ラベル + 勝ちラベル + lambdarank を対数平均で合成。
    ensemble: bool = False
    n_seeds: int = 1                   # 各系統をシード違いで複数本(バギング)


class KeibaModel:
    """LightGBM をラップし、レース内正規化済みの勝率を返すモデル。

    ensemble=True(既定)の場合、性質の異なる3系統
      * binary(top3ラベル): 安定だが「勝ち」への偏りが弱い
      * binary(勝ちラベル): 不偏だがノイジー
      * lambdarank        : レース内の相対順位を直接最適化
    を学習し、レース内確率の対数平均(幾何平均)で合成する。
    """

    def __init__(self, config: ModelConfig | None = None, features=FEATURE_COLUMNS):
        if lgb is None:  # pragma: no cover
            raise ImportError(f"lightgbm が利用できません: {_LGB_ERR}")
        self.cfg = config or ModelConfig()
        self.features = list(features)
        self.cats = [c for c in CATEGORICAL if c in self.features]
        self.booster: "lgb.Booster | None" = None
        self.members: list[tuple] = []   # [(booster, objective), ...]

    # ------------------------------------------------------------------
    def _member_specs(self) -> list[tuple]:
        """学習する (objective, label) の一覧。ensemble なら3系統×シード数。"""
        cfg = self.cfg
        if cfg.ensemble:
            specs = [("binary", LABEL_TOP3), ("binary", LABEL_WIN), ("lambdarank", None)]
        else:
            specs = [(cfg.objective, cfg.label if cfg.objective == "binary" else None)]
        out = []
        for s in range(max(1, cfg.n_seeds)):
            out += [(obj, lab, cfg.seed + 101 * s) for obj, lab in specs]
        return out

    def _train_one(self, objective: str, label, seed: int,
                   train: pd.DataFrame, valid: pd.DataFrame | None):
        cfg = self.cfg
        cats = self.cats
        Xtr = _coerce_categoricals(train[self.features], cats)
        if objective == "binary":
            params = self._binary_params()
            dtrain = lgb.Dataset(Xtr, label=train[label].to_numpy(),
                                 categorical_feature=cats, free_raw_data=False)
            dvalid = None
            if valid is not None:
                dvalid = lgb.Dataset(_coerce_categoricals(valid[self.features], cats),
                                     label=valid[label].to_numpy(), reference=dtrain,
                                     categorical_feature=cats, free_raw_data=False)
        elif objective == "lambdarank":
            params = self._rank_params()
            dtrain = lgb.Dataset(Xtr, label=_relevance(train), group=_group_sizes(train),
                                 categorical_feature=cats, free_raw_data=False)
            dvalid = None
            if valid is not None:
                dvalid = lgb.Dataset(_coerce_categoricals(valid[self.features], cats),
                                     label=_relevance(valid), group=_group_sizes(valid),
                                     reference=dtrain, categorical_feature=cats,
                                     free_raw_data=False)
        else:
            raise ValueError(f"未知の objective: {objective}")
        params["seed"] = seed
        use_es = dvalid is not None and cfg.early_stopping_rounds > 0
        # 早期停止できない時に2500本も回すと過学習・低速なので 400 に抑える
        rounds = cfg.num_boost_round if use_es else min(cfg.num_boost_round, 400)
        callbacks = [lgb.log_evaluation(0)]
        if use_es:
            callbacks.append(lgb.early_stopping(cfg.early_stopping_rounds, verbose=False))
        return lgb.train(params, dtrain, num_boost_round=rounds,
                         valid_sets=[dvalid] if dvalid is not None else [dtrain],
                         callbacks=callbacks)

    def fit(self, train: pd.DataFrame, valid: pd.DataFrame | None = None) -> "KeibaModel":
        self.members = [(self._train_one(obj, lab, seed, train, valid), obj)
                        for obj, lab, seed in self._member_specs()]
        self.booster = self.members[0][0]   # 後方互換(重要度表示・保存など)
        return self

    # ------------------------------------------------------------------
    def raw_score(self, df: pd.DataFrame) -> np.ndarray:
        if self.booster is None:
            raise RuntimeError("fit されていません")
        return self.booster.predict(_coerce_categoricals(df[self.features], self.cats))

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """レース内で正規化した勝率(合計1)を返す。ensemble は対数平均で合成。"""
        if not self.members:
            raise RuntimeError("fit されていません")
        X = _coerce_categoricals(df[self.features], self.cats)
        log_sum = None
        for booster, obj in self.members:
            scores = booster.predict(X)
            p = _race_normalize(df, scores, self.cfg.softmax_temperature,
                                is_prob=(obj == "binary"))
            lp = np.log(np.clip(p, 1e-12, 1.0))
            log_sum = lp if log_sum is None else log_sum + lp
        mix = np.exp(log_sum / len(self.members))
        return _race_normalize(df, mix, 1.0, is_prob=True)

    # ------------------------------------------------------------------
    def _binary_params(self) -> dict:
        c = self.cfg
        return {
            "objective": "binary", "metric": "binary_logloss",
            "learning_rate": c.learning_rate, "num_leaves": c.num_leaves,
            "min_data_in_leaf": c.min_data_in_leaf, "feature_fraction": c.feature_fraction,
            "bagging_fraction": c.bagging_fraction, "bagging_freq": c.bagging_freq,
            "lambda_l2": c.lambda_l2, "max_depth": c.max_depth, "seed": c.seed,
            "verbose": c.verbose,
        }

    def _rank_params(self) -> dict:
        c = self.cfg
        return {
            "objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [1, 3],
            "learning_rate": c.learning_rate, "num_leaves": c.num_leaves,
            "min_data_in_leaf": c.min_data_in_leaf, "feature_fraction": c.feature_fraction,
            "bagging_fraction": c.bagging_fraction, "bagging_freq": c.bagging_freq,
            "lambda_l2": c.lambda_l2, "max_depth": c.max_depth, "seed": c.seed,
            "verbose": c.verbose, "label_gain": list(range(0, 64)),
        }


# ----------------------------------------------------------------------------
def _group_sizes(df: pd.DataFrame) -> list[int]:
    # race_id ごとの行数(出走頭数)。df は race_id 連続でなくてよいが順序維持。
    return df.groupby("race_id", sort=False).size().tolist()


def _relevance(df: pd.DataFrame) -> np.ndarray:
    # 着順 → graded relevance。1着が最大。field_size でクリップ。
    rel = (df["field_size"] - df["finish_pos"]).clip(lower=0)
    return rel.to_numpy()


def _race_normalize(df: pd.DataFrame, scores: np.ndarray, temperature: float,
                    is_prob: bool) -> np.ndarray:
    """レース内でスコアを勝率(合計1)に正規化する。"""
    out = np.empty(len(df), dtype=float)
    rid = df["race_id"].to_numpy()
    # レース単位に処理
    order = np.argsort(rid, kind="stable")
    s_sorted = scores[order]
    r_sorted = rid[order]
    # 区切り位置
    _, starts = np.unique(r_sorted, return_index=True)
    starts = list(starts) + [len(r_sorted)]
    res_sorted = np.empty(len(df), dtype=float)
    for i in range(len(starts) - 1):
        a, b = starts[i], starts[i + 1]
        seg = s_sorted[a:b]
        if is_prob:
            # 確率を温度付きでべき乗し正規化(温度1ならそのまま比率)
            p = np.clip(seg, 1e-9, 1.0) ** (1.0 / temperature)
            res_sorted[a:b] = p / p.sum()
        else:
            z = (seg - seg.max()) / temperature
            e = np.exp(z)
            res_sorted[a:b] = e / e.sum()
    out[order] = res_sorted
    return out
