"""競馬予想 (Horse Racing Prediction) パッケージ。

馬の各種属性（スピード指数・近走成績・斤量・人気オッズ・騎手評価など）から
レースの着順・勝率をヒューリスティックに予想する、外部依存ゼロのツール。
"""

from .model import Horse, Prediction, predict_race, score_horse

__all__ = ["Horse", "Prediction", "predict_race", "score_horse"]
__version__ = "0.1.0"
