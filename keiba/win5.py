"""WIN5(重勝式: 指定5レースの1着を全て的中)の買い目最適化。

各レースの勝率(モデルのブレンド確率)から、予算(点数=100円単位)内で
**通算的中確率**を最大化する選択を貪欲法で決める。

考え方:
  * 1点 = 各レース1頭ずつの組合せ。点数 = Π(各レースの選択頭数)。
  * 1頭堅いレース(勝率が抜けてる)は1頭固定、混戦レースは手広く——を
    「的中確率の増加 / コストの増加」が最大の馬から1頭ずつ足して自動配分。
  * WIN5は控除率30%・配当が読めない(繰越/人気で乱高下)のでEVは出さない。
    代わりに『的中確率・点数(コスト)・概算フェア配当』を提示する。

入力 legs は5レース分の勝率配列(各レース内で正規化される)。
返り値の selections は各レースで選んだ「leg配列内のindex」。馬番への変換は呼び出し側。
"""

from __future__ import annotations

import math

import numpy as np

WIN5_TAKEOUT = 0.30


def _norm(p) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    s = p.sum()
    return p / s if s > 0 else p


def optimize(legs, max_points: int = 100) -> dict:
    """予算(点数)内で通算的中確率を最大化する選択を貪欲法で返す。

    legs: 各レースの勝率配列のリスト。
    """
    legs = [_norm(p) for p in legs]
    order = [np.argsort(-p) for p in legs]          # 各レース: 勝率降順の馬index
    sp = [p[o] for p, o in zip(legs, order)]         # 降順に並べた勝率
    counts = [1] * len(legs)                          # 各レースの選択頭数(まず本命1頭)
    cov = [float(s[0]) if len(s) else 0.0 for s in sp]  # 選択がカバーする勝率和

    def points() -> int:
        pr = 1
        for c in counts:
            pr *= c
        return pr

    while True:
        best = None  # (key, leg_index, next_prob)
        for i in range(len(legs)):
            if counts[i] >= len(sp[i]):
                continue
            nxt = float(sp[i][counts[i]])
            new_pts = points() // counts[i] * (counts[i] + 1)
            if new_pts > max_points:
                continue
            if cov[i] <= 0 or nxt <= 0:
                continue
            # log空間で「的中確率の増分 / コストの増分」を評価(=ナップサック貪欲)
            d_prob = math.log((cov[i] + nxt) / cov[i])
            d_cost = math.log((counts[i] + 1) / counts[i])
            score = d_prob / d_cost if d_cost > 0 else 0.0
            # 同点(均等レース)は選択頭数の少ないレースへ→偏らせず手広く分散
            key = (score, -counts[i])
            if best is None or key > best[0]:
                best = (key, i, nxt)
        if best is None:
            break
        _, i, nxt = best
        counts[i] += 1
        cov[i] += nxt

    selections = [sorted(order[i][:counts[i]].tolist()) for i in range(len(legs))]
    hit = 1.0
    for c in cov:
        hit *= c
    return {
        "selections": selections,        # 各レースで選んだ leg配列内 index
        "counts": counts,                # 各レースの選択頭数
        "coverage": [float(c) for c in cov],  # 各レースの選択カバー勝率
        "points": points(),              # 買い目点数
        "cost_yen": points() * 100,      # 100円/点
        "hit_prob": float(hit),          # 通算的中確率
        "fair_odds": fair_odds(hit),     # 概算フェア配当倍率
    }


def plans(legs, budgets=(1, 18, 72, 200, 500)) -> list[dict]:
    """複数の予算(点数)での推奨買い目をまとめて返す。"""
    return [optimize(legs, b) for b in budgets]


def fair_odds(hit_prob: float, takeout: float = WIN5_TAKEOUT) -> float:
    """この的中確率なら『何倍以上の配当でプラスか』(控除率込みフェア配当)。"""
    if hit_prob <= 0:
        return float("inf")
    return (1.0 - takeout) / hit_prob
