"""keiba: 当日予想 Web ビューアのレンダリングのスモークテスト。"""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("flask")

import keiba.web as web


def test_race_label():
    assert web._race_label(202602010501).startswith("函館")
    assert "9R" in web._race_label(202610020109)


def _day_frame():
    rows = []
    # race A: finished (本命=馬番1 が1着 → 的中), race B: 発走前
    specs = {
        202602010501: [(1, 0.40, 1.5, 1.0, 1), (2, 0.20, 4.0, 0.8, 3), (3, 0.10, 9.0, 0.9, 2)],
        202610020109: [(1, 0.45, 1.6, 0.7, None), (2, 0.06, 20.0, 1.2, None)],
    }
    for rid, horses in specs.items():
        finished = any(h[4] is not None for h in horses) and any(h[4] == 1 for h in horses)
        for rank, (post, p, o, ev, fin) in enumerate(horses, 1):
            rows.append(dict(race_id=rid, post_position=post, win_prob=p, market_prob=p,
                             odds=o, ev=ev, edge=1.3, finish_pos=(np.nan if fin is None else fin),
                             is_win=(1.0 if fin == 1 else 0.0),
                             bet=(ev > 1.15 and o <= 30), rank=rank, race_finished=finished))
    return pd.DataFrame(rows)


def test_index_renders_with_results():
    web.STATE.update(pred=_day_frame(), updated="10:00:00", building=False,
                     error=None, issues=[], refresh_sec=90)
    html = web.app.test_client().get("/").get_data(as_text=True)
    assert "函館 1R" in html and "小倉 9R" in html
    assert "買い目提案" in html
    assert "本命的中" in html        # 成績サマリ(確定レースあり)
    assert "的中" in html            # ステータスバッジ
    assert "発走前" in html          # 未確定レース
    assert "◎" in html              # 妙味(買い目)マーク


def test_build_view_summary():
    view = web._build_view(_day_frame())
    s = view["summary"]
    assert s["finished"] == 1
    assert s["win"] == 1             # 本命(馬番1)が1着
    assert 0.0 <= s["win_rate"] <= 1.0


def test_index_empty_ok():
    web.STATE.update(pred=None, updated=None, building=False, error=None, issues=[], refresh_sec=90)
    assert web.app.test_client().get("/").status_code == 200
