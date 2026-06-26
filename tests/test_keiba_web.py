"""keiba: 当日予想 Web ビューアのレンダリングのスモークテスト。"""

import pandas as pd
import pytest

pytest.importorskip("flask")

import keiba.web as web


def test_race_label():
    assert web._race_label(202602010501).startswith("函館")
    assert "9R" in web._race_label(202610020109)


def test_index_renders():
    rows = []
    for rid in [202602010501, 202610020109]:
        for i, (p, o, ev, bet) in enumerate([(0.4, 1.5, 0.6, False),
                                             (0.06, 20.0, 1.2, True)], 1):
            rows.append(dict(race_id=rid, post_position=i, win_prob=p, market_prob=p,
                             odds=o, ev=ev, edge=1.3, bet=bet, rank=i))
    web.STATE.update(pred=pd.DataFrame(rows), updated="2026-06-27 09:00:00",
                     n_races=2, n_runners=4, building=False, error=None, issues=[])
    html = web.app.test_client().get("/").get_data(as_text=True)
    assert "函館 1R" in html
    assert "小倉 9R" in html
    assert "◎" in html             # 買い目マーク
    assert "ペーパートレード" in html  # caveat


def test_index_empty_ok():
    web.STATE.update(pred=None, updated=None, n_races=0, n_runners=0,
                     building=False, error=None, issues=[])
    r = web.app.test_client().get("/")
    assert r.status_code == 200
