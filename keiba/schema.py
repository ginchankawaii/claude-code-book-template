"""正規化スキーマと「発走前/レース後」の可用性(availability)定義。

JV-Data は1レコードに発走前情報(枠・斤量・オッズ)と確定後情報(着順・
走破タイム・上がり3F・払戻)が混在する。リーク防止の要は、各カラムが
「予測時点(発走前)で取得可能だったか」をメタデータとして持ち、対象レースの
特徴量から確定後カラムを機械的に除外することにある。

ここでは実 JV-Data の最小サブセットを、分析層が扱いやすい1つの "runner"
テーブル(1行=1出走馬)に正規化したスキーマを定義する。実データ取り込み時も
この列名・可用性に合わせてマッピングすれば、下流(特徴量/学習/検証)は無改修。
"""

from __future__ import annotations

# --- レースを一意に識別 ---
RACE_KEYS = ["race_id", "race_date"]

# --- 発走前に取得可能(=特徴量に使ってよい)な出走馬カラム ---
# 当該レースのこれらは予測入力に使える。過去レースのものは履歴集計に使う。
PRE_RACE_COLUMNS = [
    "horse_id",
    "jockey_id",
    "trainer_id",
    "sire_id",
    "post_position",   # 馬番
    "field_size",      # 出走頭数
    "draw_bias",       # コース×枠の事前バイアス(過去から推定する想定。合成では真値の代理)
    "carried_weight",  # 斤量 kg
    "horse_weight",    # 馬体重 kg(発走前に速報WHで公表)
    "weight_diff",     # 前走比増減 kg
    "age",
    "sex",             # 0=牡,1=牝,2=セ
    "days_since_last", # 前走間隔(日)
    "class_level",     # クラス(数値が大きいほど上級)
    "surface",         # 0=芝,1=ダート
    "distance",        # m
    "going",           # 馬場状態 0=良,1=稍重,2=重,3=不良(当日発走前に確定)
    "moisture",        # 含水率%(当日発走前に確定)
    "running_style",   # 脚質 0=逃げ,1=先行,2=差し,3=追込(持続的な馬の特性)
    "is_first_start",  # 初出走フラグ
    "bms_id",          # 母父(母の父)の繁殖登録番号。母系の適性代理(血統 UM 由来)
    "dm_score",        # タイム型データマイニング予想タイム(JRA-VANが発走前に算出)
    "tm_score",        # 対戦型データマイニング予想スコア(同上)
]

# --- レース確定後にしか存在しない(=当該レースの特徴量に入れたら即リーク) ---
# ただし過去レースのこれらは「履歴」として特徴量化に使ってよい(PiT集計)。
POST_RACE_COLUMNS = [
    "finish_pos",      # 着順
    "finish_time",     # 走破タイム(秒)
    "last_3f",         # 上がり3F(秒)
    "passing_rank",    # 道中の通過順(平均)
    "is_win",          # 1着フラグ
    "is_top3",         # 3着内フラグ
]

# --- 市場(オッズ)関連。締切前後で可用性が異なるので別管理 ---
# morning_odds/intermediate_odds は発走前に取得可。final_odds は確定後。
# odds_drift は速報オッズ時系列(寄りつき→直近)の動きで、発走前情報のみで算出。
MARKET_PRE_RACE = ["morning_odds", "intermediate_odds", "odds_drift"]
MARKET_POST_RACE = ["final_odds", "final_popularity", "payout_win"]

# 集計・JOIN の各段に必ず適用すべき時間フィルタのキー
POINT_IN_TIME_KEY = "race_date"


def post_race_columns() -> set[str]:
    """当該レースの特徴量から必ず除外すべき確定後カラム集合。"""
    return set(POST_RACE_COLUMNS) | set(MARKET_POST_RACE)


def pre_race_columns() -> set[str]:
    """当該レースで特徴量に使ってよい発走前カラム集合。"""
    return set(PRE_RACE_COLUMNS) | set(MARKET_PRE_RACE) | set(RACE_KEYS)


def all_columns() -> list[str]:
    return (
        RACE_KEYS
        + PRE_RACE_COLUMNS
        + POST_RACE_COLUMNS
        + MARKET_PRE_RACE
        + MARKET_POST_RACE
    )
