"""M1: リーク安全(point-in-time)な特徴量パイプライン。

鉄則:
  1. 当該レースの確定後カラム(着順・タイム・上がり・確定オッズ・払戻)は
     特徴量に絶対入れない。
  2. 馬・騎手・種牡馬の履歴集計は「対象レース日より *厳密に前*」の走のみで
     算出する(race_date < 対象日)。同日の他レースも混入させない。
  3. Benter流の二段構成に従い、ファンダメンタル特徴量には市場オッズを入れない
     (市場確率は blend 段で別軸合成する)。

返す DataFrame は keys(race_id, race_date)・特徴量・ラベル(is_win,is_top3)・
決済用オッズ(final_odds, morning_odds)を持つが、特徴量列は FEATURE_COLUMNS
だけが学習に使われる(オッズ・ラベルは学習対象外)。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import schema

# 学習に用いる特徴量の確定リスト(post-race を一切含まない)
FEATURE_COLUMNS = [
    # 当該レースの発走前情報
    "post_position",
    "field_size",
    "rel_post",          # 馬番の頭数内相対位置(内=0)
    "draw_bias",
    "carried_weight",
    "horse_weight",
    "weight_diff",
    "age",
    "sex",
    "days_since_last",
    "class_level",
    "surface",
    "distance",
    "going",
    "moisture",
    "running_style",
    "is_first_start",
    # 馬の過去走集計(PiT)
    "h_starts",
    "h_win_rate",
    "h_avg_relfinish",   # 調子の主代理。市場が過小評価する信号
    "h_recent_relfinish",
    "h_best_relfinish",
    "h_avg_last3f",
    "h_form_momentum",   # 直近 - 通算 の差(上昇度)
    "h_mud_affinity",    # 道悪適性の代理: 過去の(重馬場-良馬場)相対着順差(PiT)
    # 騎手の過去走集計(PiT)
    "j_starts",
    "j_win_rate",
    "j_surface_win",     # 当該馬場(芝/ダ)での騎手勝率(PiT)
    # 種牡馬の過去走集計(PiT)
    "s_starts",
    "s_win_rate",
    "s_avg_relfinish",
]

LABEL_WIN = "is_win"
LABEL_TOP3 = "is_top3"
KEYS = ["race_id", "race_date"]
SETTLE_COLS = ["final_odds", "morning_odds", "intermediate_odds", "final_popularity"]


@dataclass
class FeatureConfig:
    recent_window: int = 3   # 直近何走を recent とみなすか


def build_features(runners: pd.DataFrame, config: FeatureConfig | None = None) -> pd.DataFrame:
    """runners から PiT 特徴量行列を構築して返す。"""

    cfg = config or FeatureConfig()
    df = runners.sort_values(["race_date", "race_id"]).reset_index(drop=True).copy()

    # 過去走の相対着順強度(1=勝ち, 0=最下位)。これが各種履歴集計の素。
    df["rel_finish"] = (df["field_size"] - df["finish_pos"]) / np.maximum(df["field_size"] - 1, 1)
    df["rel_post"] = (df["post_position"] - 1) / np.maximum(df["field_size"] - 1, 1)

    # --- 馬の PiT 集計 ---
    df["h_starts"] = _pit_count(df, "horse_id")
    df["h_win_rate"] = _pit_mean(df, "horse_id", "is_win")
    df["h_avg_relfinish"] = _pit_mean(df, "horse_id", "rel_finish")
    df["h_best_relfinish"] = _pit_max(df, "horse_id", "rel_finish")
    df["h_avg_last3f"] = _pit_mean(df, "horse_id", "last_3f")
    df["h_recent_relfinish"] = _pit_recent_mean(df, "horse_id", "rel_finish", cfg.recent_window)
    df["h_form_momentum"] = df["h_recent_relfinish"] - df["h_avg_relfinish"]

    # 道悪適性(PiT): 過去の「重馬場(going>=2)平均 - 良馬場平均」相対着順差。
    df["_is_wet"] = (df["going"] >= 2).astype(float)
    df["_rf_wet"] = df["rel_finish"] * df["_is_wet"]
    df["_rf_dry"] = df["rel_finish"] * (1.0 - df["_is_wet"])
    wet_sum, _ = _pit_daily_cumulative(df, "horse_id", "_rf_wet")
    wet_cnt, _ = _pit_daily_cumulative(df, "horse_id", "_is_wet")
    dry_sum, dry_rows = _pit_daily_cumulative(df, "horse_id", "_rf_dry")
    with np.errstate(invalid="ignore", divide="ignore"):
        wet_mean = np.where(wet_cnt > 0, wet_sum / wet_cnt, np.nan)
        dry_cnt = dry_rows - wet_cnt  # 全件数 - 重件数 = 良件数
        dry_mean = np.where(dry_cnt > 0, dry_sum / dry_cnt, np.nan)
    df["h_mud_affinity"] = wet_mean - dry_mean  # 不明(どちらか未経験)は NaN

    # --- 騎手の PiT 集計 ---
    df["j_starts"] = _pit_count(df, "jockey_id")
    df["j_win_rate"] = _pit_mean(df, "jockey_id", "is_win")
    # 当該馬場での騎手勝率(PiT): (jockey, surface) 複合キーで集計
    df["_jsurf"] = df["jockey_id"].astype(np.int64) * 2 + df["surface"].astype(np.int64)
    df["j_surface_win"] = _pit_mean(df, "_jsurf", "is_win")

    # --- 種牡馬の PiT 集計 ---
    df["s_starts"] = _pit_count(df, "sire_id")
    df["s_win_rate"] = _pit_mean(df, "sire_id", "is_win")
    df["s_avg_relfinish"] = _pit_mean(df, "sire_id", "rel_finish")

    # finish_pos は lambdarank の relevance ラベルとして保持(特徴量ではない)
    keep = KEYS + FEATURE_COLUMNS + [LABEL_WIN, LABEL_TOP3, "finish_pos"] + SETTLE_COLS
    out = df[keep].copy()

    # 欠損(初出走など)は GBDT のネイティブ NaN 処理に任せるため数値NaNのまま残す。
    # ただし件数系は 0 が自然なので 0 埋め。
    for col in ["h_starts", "j_starts", "s_starts"]:
        out[col] = out[col].fillna(0)
    return out


# ----------------------------------------------------------------------------
# PiT 集計ヘルパ:各行に対し「同一エンティティ・race_date が厳密に前」の集計を返す。
# 同日の他レースも除外することで、同日レース間のリークも防ぐ。
# ----------------------------------------------------------------------------

def _pit_daily_cumulative(df: pd.DataFrame, entity: str, value: str):
    """(entity,date) ごとに、その日より前の cum_sum / cum_count を行に展開して返す。"""
    daily = (
        df.groupby([entity, "race_date"])
        .agg(_v=(value, "sum"), _n=(value, "count"))
        .reset_index()
        .sort_values([entity, "race_date"])
    )
    g = daily.groupby(entity, sort=False)
    daily["cum_v"] = g["_v"].cumsum() - daily["_v"]   # 当日を除外
    daily["cum_n"] = g["_n"].cumsum() - daily["_n"]
    merged = df[[entity, "race_date"]].merge(
        daily[[entity, "race_date", "cum_v", "cum_n"]], on=[entity, "race_date"], how="left"
    )
    return merged["cum_v"].to_numpy(), merged["cum_n"].to_numpy()


def _pit_count(df: pd.DataFrame, entity: str) -> np.ndarray:
    _, n = _pit_daily_cumulative(df, entity, "is_win")
    return n


def _pit_mean(df: pd.DataFrame, entity: str, value: str) -> np.ndarray:
    v, n = _pit_daily_cumulative(df, entity, value)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(n > 0, v / n, np.nan)
    return out


def _pit_max(df: pd.DataFrame, entity: str, value: str) -> np.ndarray:
    """対象日より前の最大値。cummax を当日除外で計算。"""
    daily = (
        df.groupby([entity, "race_date"])
        .agg(_m=(value, "max"))
        .reset_index()
        .sort_values([entity, "race_date"])
    )
    g = daily.groupby(entity, sort=False)
    daily["prev_max"] = g["_m"].cummax().shift()  # shift で当日を除外
    # shift はグループ跨ぎの値を持ち込むため、グループ先頭を NaN に戻す
    first_mask = ~daily.duplicated(entity)
    daily.loc[first_mask, "prev_max"] = np.nan
    merged = df[[entity, "race_date"]].merge(
        daily[[entity, "race_date", "prev_max"]], on=[entity, "race_date"], how="left"
    )
    return merged["prev_max"].to_numpy()


def _pit_recent_mean(df: pd.DataFrame, entity: str, value: str, window: int) -> np.ndarray:
    """対象レースの直前 window 開催日(厳密に前の日)の平均。

    同一馬が同日に複数走するケースでも「同日の他レース」を取り込まないよう、
    まず (entity, race_date) で日次集計してから日次系列に shift().rolling() を
    当てて *当日を完全に除外* する(_pit_daily_cumulative と同じ当日除外設計)。
    通常(1日1走)なら直前 window 走の平均と一致する。
    """
    daily = (
        df.groupby([entity, "race_date"])[value].mean().reset_index()
        .sort_values([entity, "race_date"])
    )
    daily["recent"] = (
        daily.groupby(entity, sort=False)[value]
        .transform(lambda x: x.shift().rolling(window, min_periods=1).mean())
    )
    merged = df[[entity, "race_date"]].merge(
        daily[[entity, "race_date", "recent"]], on=[entity, "race_date"], how="left"
    )
    return merged["recent"].to_numpy()
