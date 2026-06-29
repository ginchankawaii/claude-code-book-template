"""買い方提案エンジン(決定論的ルール)。

1レースの勝率分布(モデルのブレンド確率)から、
  * 勝率の形(本命型/上位2頭/混戦/標準)を判定して「買い方の根拠コメント」を生成
  * 各券種について、上位数頭の組合せを総当りし Harville で的中確率を算出
  * 連系の **実オッズ(O2〜O6)** があれば実EV(=的中確率×払戻)を計算し、
    券種ごとに **最大EVの組(=妙味)** を提示。無ければフェア倍率((1-控除率)/確率)を提示
  * 単勝は実オッズから EV を計算して妙味馬を提案
を返す。LLM不使用・再現可能。
"""

from __future__ import annotations

from itertools import combinations, permutations

import numpy as np
import pandas as pd

from .blend import harville_exacta, harville_trifecta
from .exotic import sanrenpuku_prob, umaren_prob, wide_prob

# 券種別の控除率(フェア倍率の計算に使用)
TAKEOUT = {"単勝": 0.20, "複勝": 0.20, "枠連": 0.225, "馬連": 0.225, "ワイド": 0.225,
           "馬単": 0.25, "三連複": 0.25, "三連単": 0.275}

# (券種, 頭数, 順序あり)
_EXOTIC_KINDS = [("馬連", 2, False), ("ワイド", 2, False), ("馬単", 2, True),
                 ("三連複", 3, False), ("三連単", 3, True)]
_TOPK = 5            # 各券種で組合せを作る上位頭数(モデル確率順)
_EV_BUY = 1.0        # 実EVがこの値以上なら「妙味あり(買い)」とみなす


def _fair(prob: float, kind: str) -> float:
    """この確率なら『何倍以上で買えば +EV か』(フェア倍率)。"""
    if prob <= 0:
        return float("inf")
    return (1.0 - TAKEOUT.get(kind, 0.2)) / prob


def _combo_prob(kind: str, p: np.ndarray, combo, third_pool) -> float:
    if kind == "馬連":
        return umaren_prob(p, combo[0], combo[1])
    if kind == "ワイド":
        return wide_prob(p, combo[0], combo[1], third_pool)
    if kind == "馬単":
        return harville_exacta(p, combo[0], combo[1])
    if kind == "三連複":
        return sanrenpuku_prob(p, combo[0], combo[1], combo[2])
    if kind == "三連単":
        return harville_trifecta(p, combo[0], combo[1], combo[2])
    return 0.0


def _fmt_sel(posts, ordered: bool) -> str:
    sep = "→" if ordered else "-"
    return sep.join(str(x) for x in posts)


def _best_exotic(kind: str, nh: int, ordered: bool, p: np.ndarray, posts,
                 third_pool, odds_for_kind: dict | None) -> dict:
    """上位 _TOPK 頭の組合せを総当りし、実オッズがあれば最大EV組、

    無ければ最大確率組(=本線)を選んで返す。"""
    n = len(p)
    if n < nh:
        return None
    idxs = list(np.argsort(-p)[:min(_TOPK, n)])
    cand = permutations(idxs, nh) if ordered else combinations(idxs, nh)
    best = None
    for combo in cand:
        prob = _combo_prob(kind, p, combo, third_pool)
        sel_posts = tuple(posts[m] for m in combo)
        key = sel_posts if ordered else tuple(sorted(sel_posts))
        odds = None
        if odds_for_kind:
            odds = odds_for_kind.get(key)
        if odds is not None:
            ev = prob * odds
            score = (1, ev)         # 実オッズあり → EVで選ぶ(オッズ無し組より優先)
        else:
            ev = None
            score = (0, prob)       # 実オッズ無し → 確率で選ぶ(本線)
        if best is None or score > best["_score"]:
            best = {"_score": score, "kind": kind, "sel": _fmt_sel(sel_posts, ordered),
                    "prob": float(prob), "odds": (None if odds is None else float(odds)),
                    "ev": (None if ev is None else float(ev)),
                    "fair": _fair(prob, kind), "buy": bool(ev is not None and ev >= _EV_BUY)}
    if best is not None:
        best.pop("_score", None)
    return best


def advise_race(g: pd.DataFrame, odds_map: dict | None = None) -> dict:
    """1レース分(rank昇順=本命が先頭)の予測から買い方提案を作る。

    odds_map = {"馬連": {(1,2): 倍率, ...}, "ワイド": {...}, ...}(任意)。
    与えられた券種は実オッズで EV を計算し最大EV組を提示、無い券種はフェア倍率。
    """
    g = g.sort_values("rank")
    probs = g["win_prob"].to_numpy(dtype=float)
    posts = [_int(x) for x in g["post_position"].to_numpy()]
    n = len(g)
    if n < 2:
        return {"type": "—", "comment": "出走頭数不足", "tan_bets": [], "exotic": [], "honmei": None}

    p = probs / probs.sum() if probs.sum() > 0 else probs
    p1 = p[0]; p2 = p[1] if n > 1 else 0.0
    top4 = float(p[:4].sum())

    # --- 形の判定 + 根拠コメント ---
    if p1 >= 0.40 and p1 >= 2.2 * p2:
        kind = "本命型"
        comment = (f"◎{posts[0]}番が抜けている(勝率{p1*100:.0f}%)。単勝・複勝が本線。"
                   f"3連系は◎1着固定のフォーメーション/マルチで手広く。")
    elif p1 >= 0.24 and (p1 + p2) >= 0.52 and p2 >= 0.15:
        kind = "上位2頭型"
        comment = (f"◎{posts[0]}・○{posts[1]}の上位2頭が抜けている。"
                   f"馬連・ワイドで2頭軸、3連複は2頭軸→相手数点が効率的。")
    elif p1 < 0.22 and top4 >= 0.55:
        kind = "混戦型"
        comment = (f"上位拮抗の混戦(1位でも{p1*100:.0f}%)。手広くワイドBOX、"
                   f"または上位3-4頭の三連複ボックス。単勝は妙味馬のみ。")
    else:
        kind = "標準型"
        comment = (f"標準的な力関係。◎{posts[0]}から相手2-3頭へ馬連/ワイド流し、"
                   f"3連複は◎軸の流しが基本。")

    # --- 単勝の妙味(実オッズがある時) ---
    tan_bets = []
    if "ev" in g and "odds" in g:
        for _, r in g.iterrows():
            if bool(r.get("bet", False)):
                tan_bets.append({"post": _int(r["post_position"]),
                                 "odds": None if r["odds"] != r["odds"] else float(r["odds"]),
                                 "ev": None if r["ev"] != r["ev"] else float(r["ev"])})
    if tan_bets:
        comment += " 妙味: " + "・".join(
            f"{b['post']}番(単勝EV{b['ev']:.2f})" for b in tan_bets if b["ev"]) + "。"

    # --- 連系: 各券種の最大EV組(実オッズ)or 本線+フェア倍率 ---
    third_pool = list(np.argsort(-p)[:min(n, 8)])
    exotic = []
    for kname, nh, ordered in _EXOTIC_KINDS:
        if n < nh:
            continue
        ofk = (odds_map or {}).get(kname)
        e = _best_exotic(kname, nh, ordered, p, posts, third_pool, ofk)
        if e is not None:
            exotic.append(e)

    # 実EVで妙味の出た券種をコメントに追記
    buys = [e for e in exotic if e["buy"]]
    if buys:
        comment += " 実オッズ妙味: " + "・".join(
            f"{e['kind']}{e['sel']}(EV{e['ev']:.2f})" for e in buys) + "。"

    honmei = {"post": posts[0], "win": float(p1),
              "odds": None if g.iloc[0]["odds"] != g.iloc[0]["odds"] else float(g.iloc[0]["odds"])}
    return {"type": kind, "comment": comment, "tan_bets": tan_bets,
            "exotic": exotic, "honmei": honmei}


def _int(x):
    try:
        if x != x:
            return "-"
        return int(x)
    except (ValueError, TypeError):
        return "-"
