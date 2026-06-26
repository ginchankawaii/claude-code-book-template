"""keiba: 買い方提案エンジンのテスト。"""

import numpy as np
import pandas as pd

from keiba.betadvice import advise_race


def _race(probs, odds=None):
    n = len(probs)
    odds = odds or [round(1.0 / p, 1) for p in probs]
    return pd.DataFrame({
        "rank": list(range(1, n + 1)),
        "post_position": list(range(1, n + 1)),
        "win_prob": probs,
        "odds": odds,
        "ev": [p * o for p, o in zip(probs, odds)],
        "bet": [False] * n,
    })


def test_honmei_type():
    adv = advise_race(_race([0.55, 0.15, 0.10, 0.08, 0.07, 0.05]))
    assert adv["type"] == "本命型"
    assert "単勝" in adv["comment"]
    assert adv["honmei"]["post"] == 1


def test_kontsen_type():
    adv = advise_race(_race([0.16, 0.15, 0.14, 0.13, 0.12, 0.11, 0.10, 0.09]))
    assert adv["type"] == "混戦型"
    assert "ワイド" in adv["comment"] or "三連複" in adv["comment"]


def test_exotic_probs_present_and_valid():
    adv = advise_race(_race([0.4, 0.25, 0.15, 0.1, 0.06, 0.04]))
    kinds = {e["kind"] for e in adv["exotic"]}
    assert {"馬連", "ワイド", "馬単", "三連複", "三連単"} <= kinds
    for e in adv["exotic"]:
        assert 0.0 <= e["prob"] <= 1.0
        assert e["fair"] > 1.0          # フェア倍率は1倍超
    # ワイド的中率 >= 馬連的中率(同じ2頭)
    um = next(e["prob"] for e in adv["exotic"] if e["kind"] == "馬連")
    wd = next(e["prob"] for e in adv["exotic"] if e["kind"] == "ワイド")
    assert wd >= um - 1e-9


def test_tan_value_bet_in_comment():
    df = _race([0.3, 0.2, 0.5], odds=[5.0, 3.0, 2.0])
    df["bet"] = [True, False, False]   # 1番に単勝妙味
    adv = advise_race(df)
    assert any(b["post"] == 1 for b in adv["tan_bets"])
    assert "妙味" in adv["comment"]
