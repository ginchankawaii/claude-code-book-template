"""競馬予想 (Horse Racing Prediction) パッケージ。

馬の各種属性（スピード指数・近走成績・斤量・人気オッズ・騎手評価など）から
レースの着順・勝率をヒューリスティックに予想する、外部依存ゼロのツール。
"""

from .jra import load_jra_csv
from .model import Horse, Prediction, jra_bonus, predict_race, score_horse

__all__ = [
    "Horse",
    "Prediction",
    "predict_race",
    "score_horse",
    "jra_bonus",
    "load_jra_csv",
]
__version__ = "0.1.0"
