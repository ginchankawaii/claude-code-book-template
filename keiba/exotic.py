"""連系券種(馬連・ワイド・三連複)の確率展開と期待値ベット。

単勝の勝率(モデルのブレンド確率/市場確率)から Harville(1973)逐次条件付き
確率で連系の組合せ確率を導出し、期待値で購入判定する。

設計上の注意(research第5.5章):
  * Harville は上位人気を過大評価するバイアスを持つ。実データでは discounted
    Harville や2着/3着の直接学習で補正する(本実装は素の Harville)。
  * 合成の連系オッズは「単勝市場の暗黙確率 → Harville → 控除率」で生成する。
    つまり連系市場も単勝市場の近視眼性を継承する(整合的な合成環境)。
  * 控除率は券種別: 馬連/ワイド 22.5%、三連複 25%(research第6.1章)。
  * 組合せ爆発を避けるため、各レースでモデル確率上位 K 頭に絞って点を作る
    (実務でも全頭ボックスはしない)。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, permutations

import numpy as np
import pandas as pd

TAKEOUT = {"umaren": 0.225, "wide": 0.225, "sanrenpuku": 0.25}


@dataclass
class ExoticConfig:
    shortlist_k: int = 6        # 各レースで点を作る上位頭数(モデル確率順)
    wide_third_k: int = 8       # ワイドの第3頭を探索する上位頭数
    ev_threshold: float = 1.20  # 連系は分散が大きいので単勝より高め
    edge_ratio: float = 1.30    # モデル確率 / 市場確率 の下限
    max_odds: float = 200.0     # 高オッズ点は自己インパクト/分散で除外
    kelly_fraction: float = 0.15
    max_stake_per_bet: float = 0.02
    types: tuple = ("umaren", "wide", "sanrenpuku")


def _order_prob(p: np.ndarray, order) -> float:
    """指定した着順(index列)になる Harville 確率。"""
    remaining = p.sum()
    prob = 1.0
    for idx in order:
        if remaining <= 0:
            return 0.0
        prob *= p[idx] / remaining
        remaining -= p[idx]
    return prob


def _set_top_prob(p: np.ndarray, members) -> float:
    """members(集合)がちょうど上位 len(members) 着を占める確率(順序不問)。"""
    return sum(_order_prob(p, perm) for perm in permutations(members))


def umaren_prob(p: np.ndarray, i: int, j: int) -> float:
    """馬連 {i,j} が1-2着(順不問)。"""
    return _order_prob(p, (i, j)) + _order_prob(p, (j, i))


def sanrenpuku_prob(p: np.ndarray, i: int, j: int, k: int) -> float:
    """三連複 {i,j,k} が上位3着(順不問)。"""
    return _set_top_prob(p, (i, j, k))


def wide_prob(p: np.ndarray, i: int, j: int, third_pool) -> float:
    """ワイド: i と j がともに3着内。第3頭を third_pool で近似列挙。"""
    total = 0.0
    for k in third_pool:
        if k == i or k == j:
            continue
        total += _set_top_prob(p, (i, j, k))
    return total


def select_exotic_bets(race: pd.DataFrame, model_p: np.ndarray, market_p: np.ndarray,
                       config: ExoticConfig | None = None) -> pd.DataFrame:
    """1レース分の連系 EV ベットを選定し、確定着順で決済情報を付けて返す。

    race は1レース(同一 race_id)の行集合。finish_pos を含むこと。
    model_p / market_p は race の行順に整列した単勝確率(合計1)。
    """
    cfg = config or ExoticConfig()
    n = len(race)
    if n < 3:
        return _empty_exotic()
    mp = np.clip(np.asarray(model_p, float), 1e-12, None)
    qp = np.clip(np.asarray(market_p, float), 1e-12, None)
    finish = race["finish_pos"].to_numpy()
    rid = int(race["race_id"].iloc[0])
    rdate = int(race["race_date"].iloc[0])
    top2 = set(np.where(finish <= 2)[0])
    top3 = set(np.where(finish <= 3)[0])

    order = np.argsort(-mp)
    short = list(order[: cfg.shortlist_k])
    third_pool = list(order[: cfg.wide_third_k])

    rows = []

    def consider(bet_type, members, model_prob, hit):
        t = TAKEOUT[bet_type]
        mkt_prob = _market_prob_for(bet_type, qp, members, third_pool)
        if mkt_prob <= 0:
            return
        odds = (1.0 - t) / mkt_prob
        if odds > cfg.max_odds:
            return
        ev = model_prob * odds
        if ev <= cfg.ev_threshold or model_prob / mkt_prob < cfg.edge_ratio:
            return
        b = max(odds - 1.0, 1e-9)
        kelly = max((model_prob * odds - 1.0) / b, 0.0)
        stake = min(kelly * cfg.kelly_fraction, cfg.max_stake_per_bet)
        if stake <= 0:
            return
        rows.append({
            "race_id": rid, "race_date": rdate, "bet_type": bet_type,
            "combo": "-".join(str(int(race.iloc[m]["post_position"])) for m in members)
                     if "post_position" in race.columns else str(members),
            "model_prob": model_prob, "market_prob": mkt_prob, "odds": odds,
            "ev": ev, "stake_frac": stake, "is_win": int(hit),
            "final_odds": odds,
        })

    if "umaren" in cfg.types:
        for i, j in combinations(short, 2):
            consider("umaren", (i, j), umaren_prob(mp, i, j),
                     {i, j} == top2)
    if "wide" in cfg.types:
        for i, j in combinations(short, 2):
            consider("wide", (i, j), wide_prob(mp, i, j, third_pool),
                     {i, j} <= top3)
    if "sanrenpuku" in cfg.types:
        for i, j, k in combinations(short, 3):
            consider("sanrenpuku", (i, j, k), sanrenpuku_prob(mp, i, j, k),
                     {i, j, k} == top3)

    if not rows:
        return _empty_exotic()
    return pd.DataFrame(rows)


def _market_prob_for(bet_type, qp, members, third_pool) -> float:
    if bet_type == "umaren":
        return umaren_prob(qp, *members)
    if bet_type == "sanrenpuku":
        return sanrenpuku_prob(qp, *members)
    if bet_type == "wide":
        return wide_prob(qp, members[0], members[1], third_pool)
    return 0.0


def summarize_exotic(bets: pd.DataFrame) -> dict:
    """券種別の回収率(フラット)・的中率・点数を集計する。"""
    out = {}
    if bets is None or len(bets) == 0:
        return out
    for bt, g in bets.groupby("bet_type"):
        ret = (g["is_win"].to_numpy() * g["final_odds"].to_numpy()).sum()
        out[bt] = {
            "n_bets": int(len(g)),
            "hit_rate": float(g["is_win"].mean()),
            "roi": float(ret / len(g)),
        }
    return out


def _empty_exotic() -> pd.DataFrame:
    return pd.DataFrame(columns=["race_id", "race_date", "bet_type", "combo",
                                 "model_prob", "market_prob", "odds", "ev",
                                 "stake_frac", "is_win", "final_odds"])
