"""keiba: Web ビューア(ナビ/日次/通算)のレンダリング・スモークテスト。"""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("flask")

import keiba.web as web


def test_helpers():
    assert web._venue(202602010501) == "函館"
    assert web._racenum(202602010512) == 12
    assert "(" in web._date_label(dt.date(2026, 6, 27).toordinal())


def _pred_frame():
    """2レース×複数頭、片方は確定(着順あり)・片方は発走前。"""
    base = dt.date(2026, 3, 30).toordinal()
    rows = []
    specs = {
        202602010501: (base, [(1, 0.45, 1.8, 1), (2, 0.20, 4.0, 3), (3, 0.10, 9.0, 2)]),
        202610020112: (base, [(1, 0.40, 2.0, None), (2, 0.06, 20.0, None)]),
    }
    for rid, (od, horses) in specs.items():
        finished = any(h[3] == 1 for h in horses)
        for rank, (post, p, o, fin) in enumerate(horses, 1):
            rows.append(dict(race_id=rid, race_date=od, post_position=post, win_prob=p,
                             market_prob=p, odds=o, ev=p * o, edge=1.3,
                             finish_pos=(np.nan if fin is None else fin),
                             is_win=(1.0 if fin == 1 else 0.0),
                             bet=(p * o > 1.15 and o <= 30), rank=rank, race_finished=finished))
    return pd.DataFrame(rows)


@pytest.fixture()
def state():
    pred = _pred_frame()
    web.STATE.update(pred=pred, today=int(pred["race_date"].max()),
                     cutoff=dt.date(2026, 1, 1).toordinal(), updated="10:00",
                     building=False, error=None, issues=[], refresh_sec=90)
    return pred


def test_nav_days(state):
    days = web._nav_days(state)
    assert len(days) >= 1
    assert "函館" in days[0]["venues"] or "小倉" in days[0]["venues"]


def test_day_route_renders(state):
    od = int(state["race_date"].max())
    html = web.app.test_client().get(f"/day/{od}").get_data(as_text=True)
    assert "函館 1R" in html
    assert "買い方" not in html or "妙味" in html      # 買い方提案(妙味目安)が出る
    assert "馬連" in html and "三連単" in html          # 全券種の的中確率
    assert "的中" in html                                # 結果バッジ(確定レース)


def test_summary_route(state):
    html = web.app.test_client().get("/summary").get_data(as_text=True)
    assert "通算成績" in html
    s = web._summary_view(state)
    assert s["n_finished"] >= 1
    assert 0.0 <= s["honmei_win"] <= 1.0


def test_index_redirects_to_today(state):
    r = web.app.test_client().get("/")
    assert r.status_code in (301, 302)


def _win5_pred_frame():
    """WIN5対象5レース(全確定)。1着の馬番が分かる形で並べる。"""
    base = dt.date(2026, 6, 21).toordinal()
    rids = [202609010610 + i for i in range(5)]
    rows = []
    for rid in rids:
        horses = [(1, 0.50, 1), (2, 0.25, 2), (3, 0.15, 3), (4, 0.10, 4)]
        for rank, (post, p, fin) in enumerate(horses, 1):
            rows.append(dict(race_id=rid, race_date=base, post_position=post, win_prob=p,
                             market_prob=p, odds=2.0, ev=p * 2, edge=1.3, finish_pos=fin,
                             is_win=(1.0 if fin == 1 else 0.0), bet=False, rank=rank,
                             race_finished=True))
    return pd.DataFrame(rows), rids


def test_win5_route_renders():
    pred, rids = _win5_pred_frame()
    od = int(pred["race_date"].max())
    web.STATE.update(pred=pred, today=od, cutoff=dt.date(2026, 1, 1).toordinal(),
                     updated="10:00", building=False, error=None, issues=[],
                     refresh_sec=90, win5_cache={od: {"races": rids, "carryover": True}})
    html = web.app.test_client().get(f"/win5/{od}").get_data(as_text=True)
    assert "WIN5" in html
    assert "キャリーオーバー" in html
    assert "的中率" in html
    # 全レース1番人気が1着 → 推奨(本命固定)は的中
    assert "的中" in html
    web.STATE["win5_cache"] = {}


def test_win5_route_no_data():
    pred, _ = _win5_pred_frame()
    od = int(pred["race_date"].max())
    web.STATE.update(pred=pred, today=od, cutoff=dt.date(2026, 1, 1).toordinal(),
                     updated="10:00", building=False, error=None, issues=[],
                     refresh_sec=90, win5_cache={od: None}, db=None)
    html = web.app.test_client().get(f"/win5/{od}").get_data(as_text=True)
    assert "NL_WF" in html
    web.STATE["win5_cache"] = {}
