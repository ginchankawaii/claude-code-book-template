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

    # --- 以下は JRA 由来の追加特徴。未指定(0/空/False)なら予想に影響しない ---
    # タイム指数 / スピード指数 (JRA-VAN 等。50 を平均とする。0=未指定)
    time_index: float = 0.0
    # 馬体重 前走比増減 kg (大きな増減はマイナス。0=増減なし/未指定)
    weight_diff: float = 0.0
    # 馬番 (1始まり。枠順バイアス用。0=未指定)
    post_position: int = 0
    # 出走頭数 (枠順バイアスの正規化に使用。0=未指定)
    field_size: int = 0
    # 今回距離 m (距離適性用。0=未指定)
    distance: int = 0
    # 得意距離 m (距離適性用。0=未指定)
    best_distance: int = 0
    # 前走からの間隔(日)。短すぎ/長すぎはマイナス。0=未指定
    days_since_last: int = 0
    # 昇級初戦か (True ならわずかにマイナス)
    class_up: bool = False
    # 調教評価 (0-100。50 を平均。0=未指定)
    training: float = 0.0

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

    base = (
        WEIGHTS["speed"] * speed_n
        + WEIGHTS["recent_form"] * form_n
        + WEIGHTS["weight"] * weight_n
        + WEIGHTS["odds"] * odds_n
        + WEIGHTS["jockey"] * jockey_n
        + WEIGHTS["going_fit"] * going_n
    )
    return base + jra_bonus(horse)


def jra_bonus(horse: Horse) -> float:
    """JRA 由来の追加特徴によるスコア補正(加算)。

    各項目はデータ未指定時に 0 を返すよう設計しており、その場合は
    全馬一律 0 となるため softmax の結果（勝率）を変えない。
    つまり JRA 情報を与えたときだけ予想に効く。
    """

    bonus = 0.0

    # タイム指数 / スピード指数: 50 平均、±50 を ±1.0 域に。最重要級。
    if horse.time_index > 0:
        bonus += 1.0 * _clamp((horse.time_index - 50.0) / 50.0, -1.0, 1.0)

    # 馬体重増減: ±8kg は許容、それを超える増減を線形に減点。
    over = max(0.0, abs(horse.weight_diff) - 8.0)
    bonus -= 0.03 * over

    # 枠順バイアス: 多くの JRA コースは内枠やや有利。中央を 0 に。
    if horse.post_position > 0 and horse.field_size > 1:
        rel = (horse.post_position - 1) / (horse.field_size - 1)  # 0=最内, 1=大外
        bonus += 0.3 * (0.5 - rel)

    # 距離適性: 今回距離が得意距離に近いほどプラス。±400m を目安に減衰。
    if horse.distance > 0 and horse.best_distance > 0:
        gap = (horse.distance - horse.best_distance) / 400.0
        closeness = math.exp(-(gap * gap))  # 1.0(一致)〜0
        bonus += 0.5 * (closeness - 0.5)

    # ローテ(前走間隔): 28〜70日を最適とし、短すぎ/長すぎを減点。
    d = horse.days_since_last
    if d > 0:
        if d < 28:
            bonus -= 0.01 * (28 - d)
        elif d > 70:
            bonus -= 0.004 * (d - 70)

    # 昇級初戦はわずかに割引。
    if horse.class_up:
        bonus -= 0.1

    # 調教評価: 50 平均、±50 を ±0.4 域に。
    if horse.training > 0:
        bonus += 0.4 * _clamp((horse.training - 50.0) / 50.0, -1.0, 1.0)

    return bonus


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
