"""M1: リーク監査ユーティリティ。

2種類の検査を提供する:
  1. 静的検査: 特徴量列に確定後(post-race)カラムが混ざっていないか。
  2. 経験的検査(時間不変性): ある対象レースの特徴量は、「そのレース以降の
     全データを削除しても変化しない」はず。変化したら未来情報が漏れている。
     これはPiTリークを最も強力に炙り出すテスト。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import schema
from .features import FEATURE_COLUMNS, build_features


def assert_no_post_race_features(feature_cols=FEATURE_COLUMNS) -> None:
    """特徴量に確定後カラムが含まれていないことを保証する。"""
    bad = set(feature_cols) & schema.post_race_columns()
    if bad:
        raise AssertionError(f"確定後カラムが特徴量に混入しています(リーク): {sorted(bad)}")


def audit_temporal_invariance(
    runners: pd.DataFrame,
    n_sample_races: int = 25,
    seed: int = 0,
    atol: float = 1e-9,
) -> dict:
    """サンプルした対象レースについて、未来データを削除しても特徴量が
    一致することを検証する。

    Returns: {"checked": int, "mismatches": [race_id...], "ok": bool}
    """
    full = build_features(runners)
    rng = np.random.default_rng(seed)

    # 履歴が十分あるよう、後半のレースから抽選する
    dates = runners["race_date"]
    cutoff = dates.quantile(0.5)
    candidate_races = (
        runners.loc[dates >= cutoff, "race_id"].drop_duplicates().to_numpy()
    )
    if len(candidate_races) == 0:
        candidate_races = runners["race_id"].drop_duplicates().to_numpy()
    sample = rng.choice(
        candidate_races, size=min(n_sample_races, len(candidate_races)), replace=False
    )

    feat_cols = FEATURE_COLUMNS
    mismatches = []
    for rid in sample:
        rdate = runners.loc[runners.race_id == rid, "race_date"].iloc[0]
        # 「厳密に前の日」+「当該レース自身の行」だけを残す。
        # これにより未来の日 *および同日の兄弟レース* を削除した状態で特徴量を
        # 再計算するため、同日リーク(同日の他レース依存)も検出できる。
        truncated = runners[(runners.race_date < rdate) | (runners.race_id == rid)]
        tfeat = build_features(truncated)

        a = full[full.race_id == rid].sort_values("post_position")[feat_cols].reset_index(drop=True)
        b = tfeat[tfeat.race_id == rid].sort_values("post_position")[feat_cols].reset_index(drop=True)
        if not _frames_close(a, b, atol):
            mismatches.append(int(rid))

    return {
        "checked": int(len(sample)),
        "mismatches": mismatches,
        "ok": len(mismatches) == 0,
    }


def audit_outcome_independence(
    runners: pd.DataFrame,
    n_sample_races: int = 25,
    seed: int = 0,
    atol: float = 1e-9,
) -> dict:
    """当該レース自身の確定後情報に対する不変性を検証する。

    時間不変性監査(audit_temporal_invariance)は「他レース(未来・同日兄弟)の
    未来情報」リークは捉えるが、対象レース *自身* の確定後カラム(着順等)を
    特徴量に使ってしまう種類のリークは捉えられない(対象行は full/truncated の
    両方に存在し値も同じため)。

    本監査は対象レースの POST_RACE カラムを書き換えてから特徴量を再構築し、
    そのレース自身の特徴量が変化しないことを確認する。変化したら、その特徴は
    自レースの結果に依存している = リーク。

    Returns: {"checked": int, "mismatches": [race_id...], "ok": bool}
    """
    full = build_features(runners)
    rng = np.random.default_rng(seed)
    post_cols = [c for c in schema.POST_RACE_COLUMNS if c in runners.columns]

    races = runners["race_id"].drop_duplicates().to_numpy()
    sample = rng.choice(races, size=min(n_sample_races, len(races)), replace=False)

    mismatches = []
    for rid in sample:
        modified = runners.copy()
        mask = modified["race_id"] == rid
        # 当該レースの確定後カラムを攪乱(順位を逆順化し、数値列をゼロ化)
        if "finish_pos" in modified.columns:
            n = int(mask.sum())
            modified.loc[mask, "finish_pos"] = list(range(n, 0, -1))
        for c in post_cols:
            if c == "finish_pos":
                continue
            modified.loc[mask, c] = 0

        mfeat = build_features(modified)
        a = full[full.race_id == rid].sort_values("post_position")[FEATURE_COLUMNS].reset_index(drop=True)
        b = mfeat[mfeat.race_id == rid].sort_values("post_position")[FEATURE_COLUMNS].reset_index(drop=True)
        if not _frames_close(a, b, atol):
            mismatches.append(int(rid))

    return {
        "checked": int(len(sample)),
        "mismatches": mismatches,
        "ok": len(mismatches) == 0,
    }


def _frames_close(a: pd.DataFrame, b: pd.DataFrame, atol: float) -> bool:
    if a.shape != b.shape:
        return False
    for col in a.columns:
        av = a[col].to_numpy(dtype=float)
        bv = b[col].to_numpy(dtype=float)
        both_nan = np.isnan(av) & np.isnan(bv)
        if not np.all(both_nan | (np.abs(av - bv) <= atol)):
            return False
    return True
