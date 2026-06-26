"""買い方提案エンジン(決定論的ルール)。

1レースの勝率分布(モデルのブレンド確率)から、
  * 勝率の形(本命型/上位2頭/混戦/標準)を判定して「買い方の根拠コメント」を生成
  * 各券種の的中確率を Harville で算出し、+EVになる「妙味目安オッズ(倍以上で買い)」を提示
  * 単勝は実オッズがあれば EV を計算して妙味馬を提案
を返す。LLM不使用・再現可能。

⚠ 連系(馬連〜三連単)の *実オッズ* は別テーブル(O2〜O6)にあり、ここでは
  「的中確率」と「フェア倍率=(1-控除率)/確率」を提示する。実オッズ接続後は
  fair の代わりに実EVを出す(設計はそのまま差し替え可能)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .blend import harville_exacta, harville_trifecta
from .exotic import sanrenpuku_prob, umaren_prob, wide_prob

# 券種別の控除率(フェア倍率の計算に使用)
TAKEOUT = {"単勝": 0.20, "複勝": 0.20, "枠連": 0.225, "馬連": 0.225, "ワイド": 0.225,
           "馬単": 0.25, "三連複": 0.25, "三連単": 0.275}


def _fair(prob: float, kind: str) -> float:
    """この確率なら『何倍以上で買えば +EV か』(フェア倍率)。"""
    if prob <= 0:
        return float("inf")
    return (1.0 - TAKEOUT.get(kind, 0.2)) / prob


def advise_race(g: pd.DataFrame) -> dict:
    """1レース分(rank昇順=本命が先頭)の予測から買い方提案を作る。"""
    g = g.sort_values("rank")
    probs = g["win_prob"].to_numpy(dtype=float)
    posts = [(_int(x)) for x in g["post_position"].to_numpy()]
    n = len(g)
    if n < 2:
        return {"type": "—", "comment": "出走頭数不足", "tan_bets": [], "exotic": [], "honmei": None}

    p = probs / probs.sum() if probs.sum() > 0 else probs
    p1 = p[0]; p2 = p[1] if n > 1 else 0.0; p3 = p[2] if n > 2 else 0.0
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

    # --- 連系の的中確率 + フェア倍率(妙味目安) ---
    exotic = []
    i, j, k = 0, 1, (2 if n > 2 else 1)
    # 馬連(上位2頭)
    pr = umaren_prob(p, i, j)
    exotic.append({"kind": "馬連", "sel": f"{posts[i]}-{posts[j]}", "prob": pr, "fair": _fair(pr, "馬連")})
    # ワイド(上位2頭)
    pw = wide_prob(p, i, j, list(range(min(n, 8))))
    exotic.append({"kind": "ワイド", "sel": f"{posts[i]}-{posts[j]}", "prob": pw, "fair": _fair(pw, "ワイド")})
    # 馬単(本命1着→相手)
    pe = harville_exacta(p, i, j)
    exotic.append({"kind": "馬単", "sel": f"{posts[i]}→{posts[j]}", "prob": pe, "fair": _fair(pe, "馬単")})
    if n >= 3:
        # 三連複(上位3頭)
        ps = sanrenpuku_prob(p, i, j, k)
        exotic.append({"kind": "三連複", "sel": f"{posts[i]}-{posts[j]}-{posts[k]}",
                       "prob": ps, "fair": _fair(ps, "三連複")})
        # 三連単(本命1着固定→上位)
        pt = harville_trifecta(p, i, j, k)
        exotic.append({"kind": "三連単", "sel": f"{posts[i]}→{posts[j]}→{posts[k]}",
                       "prob": pt, "fair": _fair(pt, "三連単")})

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
