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


def test_best_bet_picks_max_ev():
    adv = {"tan_bets": [{"post": 1, "odds": 5.0, "ev": 2.0}],
           "exotic": [{"kind": "馬連", "sel": "1-2", "odds": 30.0,
                       "prob": 0.05, "ev": 1.5, "buy": True}]}
    b = web._best_bet(adv)
    assert b["kind"] == "単勝" and abs(b["ev"] - 2.0) < 1e-9   # EV最大を選ぶ


def test_best_bet_none_when_no_overlay():
    assert web._best_bet({"tan_bets": [], "exotic": [{"kind": "馬連", "buy": False}]}) is None


def test_allocate_kelly_proportional():
    races = [
        {"cbval": "A", "label": "X 1R", "best_bet": {"kind": "単勝", "sel": "1", "odds": 5.0, "ev": 2.0}},
        {"cbval": "B", "label": "X 2R", "best_bet": {"kind": "単勝", "sel": "3", "odds": 3.0, "ev": 1.5}},
        {"cbval": "C", "label": "X 3R", "best_bet": None},  # 妙味なし→配分されない
    ]
    a = web._allocate(races, {"A", "B", "C"}, 10000)
    assert a["total"] <= 10000 and a["leftover"] == 10000 - a["total"]
    # f_A=(2-1)/(5-1)=0.25, f_B=(1.5-1)/(3-1)=0.25 → 均等
    amt = {r["label"]: r["amount"] for r in a["rows"]}
    assert amt["X 1R"] == amt["X 2R"] and a["total"] == 10000
    assert "X 3R" not in amt          # best_bet 無しは含まれない


def test_day_route_shows_allocation(state):
    od = int(state["race_date"].max())
    # 阪神(発走前)レースに +EV の単勝が出るよう pred を差し替え
    pred = state.copy()
    rid = 202610020112
    m = pred["race_id"] == rid
    pred.loc[m & (pred["post_position"] == 1), ["win_prob", "odds", "ev", "bet"]] = [0.40, 5.0, 2.0, True]
    web.STATE.update(pred=pred)
    cli = web.app.test_client()
    html = cli.get(f"/day/{od}?submitted=1&budget=10000&pick={rid}").get_data(as_text=True)
    assert "投資配分" in html
    assert "¥" in html and "EV" in html


def test_startup_cache_loads_without_ingest(tmp_path):
    import pickle
    db = tmp_path / "k.db"
    db.write_bytes(b"dummy")                       # cache-hit は stat しか見ない
    cdir = tmp_path / "cache"; cdir.mkdir()
    web.STATE.update(db=str(db), cache_dir=str(cdir), objective="binary", ev=1.15,
                     immutable=False, predictor=None, pred=None, building=False)
    full_key = f"{web._data_sig()}|{web._cfg_sig()}"
    dummy = pd.DataFrame({"race_id": [1], "race_date": [1]})
    with open(web._cache_file(), "wb") as fh:
        pickle.dump({"full_key": full_key, "pred": dummy, "predictor": "M",
                     "issues": [], "cutoff": 1, "today": 1, "updated": "00:00"}, fh)
    web.rebuild(use_cache=True)                    # 取込せず即ロードされる
    assert web.STATE["pred"] is not None and len(web.STATE["pred"]) == 1
    assert "cache" in (web.STATE["updated"] or "")
    web.STATE.update(cache_dir=None, db=None)


def test_settle_best_bet_win_and_exotic():
    # 1着=5番, 2着=3番, 3着=7番
    g = pd.DataFrame({"post_position": [5, 3, 7, 1], "finish_pos": [1, 2, 3, 4]})
    # 単勝 5番 的中(オッズ4.0払戻)
    _, ret, hit = web._settle_best_bet(g, {"kind": "単勝", "sel": "5", "odds": 4.0})
    assert hit and abs(ret - 4.0) < 1e-9
    # 単勝 3番 は外れ(払戻0)
    _, ret, hit = web._settle_best_bet(g, {"kind": "単勝", "sel": "3", "odds": 4.0})
    assert not hit and ret == 0.0
    # 馬連 5-3 的中、5-7 外れ
    assert web._settle_best_bet(g, {"kind": "馬連", "sel": "5-3", "odds": 9.0})[2]
    assert not web._settle_best_bet(g, {"kind": "馬連", "sel": "5-7", "odds": 9.0})[2]
    # 三連複 5-3-7 的中、三連単 5→3→7 的中・3→5→7 外れ
    assert web._settle_best_bet(g, {"kind": "三連複", "sel": "5-3-7", "odds": 30.0})[2]
    assert web._settle_best_bet(g, {"kind": "三連単", "sel": "5→3→7", "odds": 99.0})[2]
    assert not web._settle_best_bet(g, {"kind": "三連単", "sel": "3→5→7", "odds": 99.0})[2]


def test_allocate_risk_controls():
    races = [
        {"cbval": "A", "label": "X 1R", "best_bet": {"kind": "単勝", "sel": "1", "odds": 5.0, "ev": 2.0}},
        {"cbval": "B", "label": "X 2R", "best_bet": {"kind": "単勝", "sel": "3", "odds": 3.0, "ev": 1.5}},
        {"cbval": "C", "label": "X 3R", "best_bet": {"kind": "単勝", "sel": "2", "odds": 4.0, "ev": 1.05}},
    ]
    picks = {"A", "B", "C"}
    # 最低EV=1.4 → C(EV1.05)除外
    a = web._allocate(races, picks, 10000, min_ev=1.4)
    assert all("X 3R" != r["label"] for r in a["rows"]) and a["n_bet"] == 2
    # 最大点数=1 → EV最大のA(EV2.0)だけ
    a = web._allocate(races, picks, 10000, max_bets=1)
    assert a["n_bet"] == 1 and a["rows"][0]["label"] == "X 1R"
    # 1点上限30% → どの点も ¥3000 以下
    a = web._allocate(races, picks, 10000, cap_pct=30)
    assert all(r["amount"] <= 3000 for r in a["rows"])
    # コピー文字列が金額入りで生成される
    a = web._allocate(races, picks, 10000)
    assert "¥" in a["copy"] and "X 1R" in a["copy"]


def test_day_sort_ev_orders_overlays_first(state):
    od = int(state["race_date"].max())
    pred = state.copy()
    # 阪神2レース化: 1つに強い+EV、もう1つは無し
    rid = 202610020112
    pred.loc[(pred["race_id"] == rid) & (pred["post_position"] == 1),
             ["win_prob", "odds", "ev", "bet"]] = [0.5, 6.0, 3.0, True]
    web.STATE.update(pred=pred)
    v = web._day_view(pred, od, sort="ev")
    # 各会場で best_bet ありが先頭に来る
    for ven in v["venues"]:
        bets = [bool(r["best_bet"]) for r in ven["races"]]
        assert bets == sorted(bets, reverse=True)


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
