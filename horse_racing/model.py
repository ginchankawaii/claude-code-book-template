"""予想モデル本体。

外部ライブラリに依存せず、馬の属性を重み付き合成スコアに変換し、
ソフトマックスで勝率を推定する。決定論的なので結果は再現可能。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class Horse:
    """1頭の出走馬を表す。

    属性はいずれも「大きいほど有利」になるよう正規化して扱う。
    """

    name: str
    # スピード指数 (0-120 程度を想定。大きいほど速い)
    speed: float = 0.0
    # 近5走の平均着順 (1.0 が最良。小さいほど好成績 → スコアでは反転)
    recent_form: float = 5.0
    # 斤量 kg (軽いほど有利 → スコアでは反転)
    weight: float = 55.0
    # 単勝オッズ (低いほど人気=強い → スコアでは反転)
    odds: float = 10.0
    # 騎手評価 (0-100。大きいほど好騎手)
    jockey: float = 50.0
    # 馬場適性 (0-100。今回の馬場・距離への適性)
    going_fit: float = 50.0

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Horse.name は空にできません")
        if self.odds <= 0:
            raise ValueError(f"odds は正の値である必要があります: {self.odds}")
        if self.weight <= 0:
            raise ValueError(f"weight は正の値である必要があります: {self.weight}")


@dataclass
class Prediction:
    """1頭分の予想結果。"""

    horse: Horse
    score: float
    win_probability: float
    rank: int = 0


# 各特徴量の重み。合計の絶対値で正規化されるため相対比が重要。
WEIGHTS = {
    "speed": 1.0,
    "recent_form": 0.9,
    "weight": 0.4,
    "odds": 0.8,
    "jockey": 0.5,
    "going_fit": 0.6,
}


def score_horse(horse: Horse) -> float:
    """馬の合成スコアを計算する。大きいほど勝ち負けに近い。

    各特徴量を概ね 0-1 のスケールに揃えてから重み付き和を取る。
    「小さいほど有利」な項目 (近走着順・斤量・オッズ) は反転させる。
    """

    # スピード: 0-120 を 0-1 に
    speed_n = _clamp(horse.speed / 120.0)
    # 近走着順: 1着=最良。1-18 を反転して 0-1 に
    form_n = _clamp((18.0 - horse.recent_form) / 17.0)
    # 斤量: 48-62kg を反転して 0-1 に (軽いほど有利)
    weight_n = _clamp((62.0 - horse.weight) / 14.0)
    # オッズ: 対数を取り、1.0-100倍を反転して 0-1 に (低人気ほど不利)
    odds_n = _clamp(1.0 - (math.log10(horse.odds) / 2.0))
    # 騎手・馬場適性: 0-100 を 0-1 に
    jockey_n = _clamp(horse.jockey / 100.0)
    going_n = _clamp(horse.going_fit / 100.0)

    return (
        WEIGHTS["speed"] * speed_n
        + WEIGHTS["recent_form"] * form_n
        + WEIGHTS["weight"] * weight_n
        + WEIGHTS["odds"] * odds_n
        + WEIGHTS["jockey"] * jockey_n
        + WEIGHTS["going_fit"] * going_n
    )


def predict_race(horses: Iterable[Horse], temperature: float = 0.35) -> list[Prediction]:
    """出走馬リストから着順予想と勝率を返す。

    勝率はスコアのソフトマックス。``temperature`` が小さいほど
    上位馬に確率が集中する (本命党)。大きいほど混戦想定 (穴党)。
    返り値はスコア降順 (=予想着順) に並ぶ。
    """

    horses = list(horses)
    if not horses:
        raise ValueError("出走馬が空です")
    if temperature <= 0:
        raise ValueError(f"temperature は正の値である必要があります: {temperature}")

    names = [h.name for h in horses]
    if len(set(names)) != len(names):
        raise ValueError("馬名が重複しています")

    scores = [score_horse(h) for h in horses]
    probs = _softmax(scores, temperature)

    preds = [
        Prediction(horse=h, score=s, win_probability=p)
        for h, s, p in zip(horses, scores, probs)
    ]
    preds.sort(key=lambda p: p.score, reverse=True)
    for i, pred in enumerate(preds, start=1):
        pred.rank = i
    return preds


def _softmax(values: list[float], temperature: float) -> list[float]:
    scaled = [v / temperature for v in values]
    m = max(scaled)
    exps = [math.exp(v - m) for v in scaled]
    total = sum(exps)
    return [e / total for e in exps]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
