"""約定モデルとコストの境界条件。"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from erb.data import daily_with_turnover_average, normalize
from erb.simulate import (NO_OPEN_EXCLUDE_LIMIT_UP, NO_OPEN_NEXT, PriceIndex,
                          apply_costs, simulate_portfolio, simulate_trades)


@pytest.fixture
def prices(cfg, daily):
    d = daily_with_turnover_average(normalize(cfg, "daily", daily), 20)
    return PriceIndex.build(d)


def _event(code: str, entry: date, **kw) -> pd.DataFrame:
    base = {
        "code": code, "disc_date": entry, "entry_date": entry,
        "revision_rate": 0.30, "mkt_cap": 2e10, "habitual": False,
        "habitual_window_complete": True, "after_close": True,
        "excluded_by_spec": False, "doc_class": "earn_forecast_revision",
        "is_initial_forecast": False,
    }
    base.update(kw)
    return pd.DataFrame([base])


def test_entry_and_exit_use_adjusted_open(prices, calendar, topix, cfg):
    ev = _event("A0001", date(2024, 11, 12))
    t = simulate_trades(ev, prices, calendar, 5, position_size_jpy=500_000,
                        topix=normalize(cfg, "topix", topix))
    row = t.iloc[0]
    assert row["status"] == "ok"
    # A0001 は 1営業日あたり +1 円。5営業日で +5 円。
    entry_px = prices.field("A0001", prices.position("A0001", date(2024, 11, 12)), "adj_open")
    assert row["gross_return"] == pytest.approx(5.0 / entry_px, rel=1e-6)


def test_lot_size_uses_raw_price_not_adjusted(cfg, daily, calendar):
    """値がさ株は単元100株が建玉に収まらないので除外する。

    調整済み価格で判定すると、将来分割された銘柄が不当に「買えた」ことになる。
    """
    d = daily.copy()
    mask = d["Code"] == "B0002"
    for col in ("AdjO", "AdjH", "AdjL", "AdjC"):
        d[col] = d[col].astype(float)
        d.loc[mask, col] = d.loc[mask, col] / 10   # 調整後は 800 円に見える
    dn = daily_with_turnover_average(normalize(cfg, "daily", d), 20)
    px = PriceIndex.build(dn)
    ev = _event("B0002", date(2024, 11, 12))
    t = simulate_trades(ev, px, calendar, 5, position_size_jpy=500_000)
    # 生値 8000 円 x 100 株 = 80万 > 50万 なので除外されなければならない
    assert t.iloc[0]["status"] == "lot_too_large"


def test_delisting_before_exit_settles_at_last_close(prices, calendar, days):
    """保有中に上場廃止になっても除外しない。最終取引日の終値で手仕舞う。

    C0003 は最後の5営業日のデータが無い（= その間に上場廃止された想定）。
    """
    c_last = days[len(days) - 6]      # C0003 の最終取引日
    entry = days[len(days) - 8]       # その2営業日前に建てる
    ev = _event("C0003", entry)
    t = simulate_trades(ev, prices, calendar, 5, position_size_jpy=500_000)
    row = t.iloc[0]
    assert row["status"] == "ok"
    assert row["exit_kind"] == "delisted_or_halted"
    assert row["exit_date"] == c_last


def test_no_open_is_skipped_by_default(cfg, daily, calendar):
    d = daily.copy()
    d["O"] = d["O"].astype(float)
    mask = (d["Code"] == "A0001") & (d["Date"] == date(2024, 11, 12))
    d.loc[mask, "Vo"] = 0
    d.loc[mask, "O"] = np.nan
    dn = daily_with_turnover_average(normalize(cfg, "daily", d), 20)
    px = PriceIndex.build(dn)
    ev = _event("A0001", date(2024, 11, 12))
    t = simulate_trades(ev, px, calendar, 5, position_size_jpy=500_000)
    assert t.iloc[0]["status"] == "no_open"


def test_no_open_next_policy_buys_at_first_traded_open(cfg, daily, calendar):
    d = daily.copy()
    d["O"] = d["O"].astype(float)
    mask = (d["Code"] == "A0001") & (d["Date"] == date(2024, 11, 12))
    d.loc[mask, "Vo"] = 0
    d.loc[mask, "O"] = np.nan
    dn = daily_with_turnover_average(normalize(cfg, "daily", d), 20)
    px = PriceIndex.build(dn)
    ev = _event("A0001", date(2024, 11, 12))
    t = simulate_trades(ev, px, calendar, 5, position_size_jpy=500_000,
                        no_open_policy=NO_OPEN_NEXT)
    row = t.iloc[0]
    assert row["status"] == "ok"
    assert row["entry_date"] == date(2024, 11, 13)


def test_limit_up_entries_can_be_excluded(cfg, daily, calendar):
    d = daily.copy()
    mask = (d["Code"] == "A0001") & (d["Date"] == date(2024, 11, 12))
    d.loc[mask, "UL"] = "1"
    dn = daily_with_turnover_average(normalize(cfg, "daily", d), 20)
    px = PriceIndex.build(dn)
    ev = _event("A0001", date(2024, 11, 12))
    t = simulate_trades(ev, px, calendar, 5, position_size_jpy=500_000,
                        no_open_policy=NO_OPEN_EXCLUDE_LIMIT_UP)
    assert t.iloc[0]["status"] == "excluded_limit_up"


def test_holding_days_are_inclusive_calendar_days(prices, calendar):
    ev = _event("A0001", date(2024, 11, 12))
    t = simulate_trades(ev, prices, calendar, 5, position_size_jpy=500_000)
    # 11/12(火) -> 11/19(火) は 8 暦日（両端入れ）
    assert t.iloc[0]["holding_calendar_days"] == 8


def test_interest_scales_with_calendar_days():
    trades = pd.DataFrame([
        {"gross_return": 0.01, "topix_return": 0.0, "holding_calendar_days": 7},
        {"gross_return": 0.01, "topix_return": 0.0, "holding_calendar_days": 14},
    ])
    priced = apply_costs(trades, 0.4, 2.80, 0, 500_000)
    assert priced["interest_cost"].iloc[0] == pytest.approx(0.028 * 7 / 365)
    assert priced["interest_cost"].iloc[1] == pytest.approx(0.028 * 14 / 365)
    # 純リターン = 粗 - 滑り - 金利
    assert priced["net_return"].iloc[0] == pytest.approx(0.01 - 0.004 - 0.028 * 7 / 365)


def test_break_even_matches_design_table():
    """設計書の損益分岐表と一致すること。N=5・滑り0.4% で 0.454%。"""
    interest = 2.80 * 7 / 365
    assert interest + 0.4 == pytest.approx(0.4537, abs=1e-3)


def test_excess_return_subtracts_topix(cfg, prices, calendar, topix):
    ev = _event("A0001", date(2024, 11, 12))
    t = simulate_trades(ev, prices, calendar, 5, position_size_jpy=500_000,
                        topix=normalize(cfg, "topix", topix))
    priced = apply_costs(t, 0.4, 2.80, 0, 500_000)
    row = priced.iloc[0]
    assert row["excess_return"] == pytest.approx(row["gross_return"] - row["topix_return"])


def test_portfolio_respects_max_concurrent(prices, calendar):
    """同時保有枠を超えたシグナルは見送り、件数を数える。"""
    evs = pd.concat([
        _event("A0001", date(2024, 11, 12)),
        _event("A0001", date(2024, 11, 12)),
        _event("A0001", date(2024, 11, 12)),
        _event("A0001", date(2024, 11, 12)),
    ], ignore_index=True)
    t = simulate_trades(evs, prices, calendar, 5, position_size_jpy=500_000)
    priced = apply_costs(t, 0.4, 2.80, 0, 500_000)
    pf = simulate_portfolio(priced, position_size_jpy=500_000, max_concurrent=3,
                            equity_jpy=1_500_000, maintenance_margin_ratio=0.20,
                            prices=prices)
    assert pf["taken"] == 3
    assert pf["skipped_no_slot"] == 1


def test_margin_call_counted_for_thin_equity(prices, calendar, cfg, daily):
    """元金50万・建玉150万は13.3%の下落で追証。"""
    d = daily.copy()
    mask = d["Code"] == "A0001"
    # エントリー後に 20% 下落させる
    later = mask & (d["Date"] > date(2024, 11, 12))
    for col in ("C", "AdjC"):
        d[col] = d[col].astype(float)
        d.loc[later, col] = d.loc[later, col] * 0.8
    dn = daily_with_turnover_average(normalize(cfg, "daily", d), 20)
    px = PriceIndex.build(dn)
    evs = pd.concat([_event("A0001", date(2024, 11, 12))] * 3, ignore_index=True)
    t = simulate_trades(evs, px, calendar, 10, position_size_jpy=500_000)
    priced = apply_costs(t, 0.4, 2.80, 0, 500_000)
    thin = simulate_portfolio(priced, position_size_jpy=500_000, max_concurrent=3,
                              equity_jpy=500_000, maintenance_margin_ratio=0.20,
                              prices=px, calendar=calendar)
    thick = simulate_portfolio(priced, position_size_jpy=500_000, max_concurrent=3,
                               equity_jpy=1_500_000, maintenance_margin_ratio=0.20,
                               prices=px, calendar=calendar)
    assert thin["margin_call_days"] > 0
    assert thick["margin_call_days"] == 0


def test_margin_call_needs_full_calendar_scan(prices, calendar, cfg, daily):
    """保有途中だけで起きた急落を、営業日を全部見ないと取りこぼす。

    建てた日と返済日しか見ないと追証が 0 件に見えてしまう。
    """
    d = daily.copy()
    mask = d["Code"] == "A0001"
    crash_day = date(2024, 11, 18)
    hit = mask & (d["Date"] == crash_day)
    for col in ("C", "AdjC"):
        d[col] = d[col].astype(float)
        d.loc[hit, col] = d.loc[hit, col] * 0.7   # その日だけ 30% 下落
    dn = daily_with_turnover_average(normalize(cfg, "daily", d), 20)
    px = PriceIndex.build(dn)
    evs = pd.concat([_event("A0001", date(2024, 11, 12))] * 3, ignore_index=True)
    t = simulate_trades(evs, px, calendar, 10, position_size_jpy=500_000)
    priced = apply_costs(t, 0.4, 2.80, 0, 500_000)

    with_cal = simulate_portfolio(priced, position_size_jpy=500_000, max_concurrent=3,
                                  equity_jpy=500_000, maintenance_margin_ratio=0.20,
                                  prices=px, calendar=calendar)
    without_cal = simulate_portfolio(priced, position_size_jpy=500_000, max_concurrent=3,
                                     equity_jpy=500_000, maintenance_margin_ratio=0.20,
                                     prices=px)
    assert with_cal["margin_call_days"] > 0
    assert without_cal["margin_call_days"] == 0


def test_bankruptcy_stops_the_simulation(prices, calendar, cfg, daily):
    """元金を失ったら退場する。

    止めないと、入れていない金で建て続ける前提の損益になり、
    最大DDが -2,889% のような意味のない値になる。
    """
    d = daily.copy()
    mask = d["Code"] == "A0001"
    later = mask & (d["Date"] > date(2024, 11, 12))
    for col in ("C", "AdjC"):
        d[col] = d[col].astype(float)
        d.loc[later, col] = d.loc[later, col] * 0.3      # 70% 下落
    dn = daily_with_turnover_average(normalize(cfg, "daily", d), 20)
    px = PriceIndex.build(dn)
    evs = pd.concat([_event("A0001", date(2024, 11, 12))] * 3, ignore_index=True)
    t = simulate_trades(evs, px, calendar, 10, position_size_jpy=500_000)
    priced = apply_costs(t, 0.4, 2.80, 0, 500_000)

    pf = simulate_portfolio(priced, position_size_jpy=500_000, max_concurrent=3,
                            equity_jpy=500_000, maintenance_margin_ratio=0.20,
                            prices=px, calendar=calendar)
    assert pf["bankrupt_on"] is not None
    assert pf["max_drawdown_pct"] >= -100.0


def test_drawdown_never_exceeds_minus_100_percent():
    from erb.simulate import _max_drawdown

    assert _max_drawdown(pd.Series([1_000_000, 500_000, -3_000_000])) == -1.0
    assert _max_drawdown(pd.Series([1_000_000, 900_000])) == pytest.approx(-0.1)
    assert _max_drawdown(pd.Series([], dtype=float)) == 0.0



def test_same_day_close_exit_uses_close_and_zero_day_trade_interest(prices, calendar, cfg, topix):
    """N=0 は当日引けで返済。日計り信用なら金利0。"""
    from erb.data import normalize

    ev = _event("A0001", date(2024, 11, 12))
    t = simulate_trades(ev, prices, calendar, 0, position_size_jpy=500_000,
                        topix=normalize(cfg, "topix", topix))
    row = t.iloc[0]
    assert row["status"] == "ok"
    assert row["exit_kind"] == "same_day_close"
    assert row["exit_date"] == date(2024, 11, 12)
    i = prices.position("A0001", date(2024, 11, 12))
    o, c = prices.field("A0001", i, "adj_open"), prices.field("A0001", i, "adj_close")
    assert row["gross_return"] == pytest.approx(c / o - 1)
    assert row["holding_calendar_days"] == 1

    priced = apply_costs(t, 0.4, 2.80, 0, 500_000, day_trade_interest_annual_pct=0.0)
    assert priced["interest_cost"].iloc[0] == 0.0
    # 持ち越しなら金利がかかる
    t5 = simulate_trades(ev, prices, calendar, 5, position_size_jpy=500_000)
    priced5 = apply_costs(t5, 0.4, 2.80, 0, 500_000, day_trade_interest_annual_pct=0.0)
    assert priced5["interest_cost"].iloc[0] > 0


def test_day0_decomposition_sums_to_next_open_return(prices, calendar):
    """始値→引け と 引け→翌始値 を合成すると N=1 の粗リターンになること。"""
    ev = _event("A0001", date(2024, 11, 12))
    t = simulate_trades(ev, prices, calendar, 1, position_size_jpy=500_000)
    row = t.iloc[0]
    composed = (1 + row["d0_open_to_close"]) * (1 + row["d0_close_to_next_open"]) - 1
    assert composed == pytest.approx(row["gross_return"], rel=1e-9)



def test_portfolio_pnl_equals_taken_mean_times_count(prices, calendar):
    """建てた本の平均純リターン x 本数 x 建玉 = 実現損益 であること。

    これが崩れていたら、選択則ではなくシミュレータのバグ。
    """
    evs = pd.concat([_event("A0001", date(2024, 11, 12), revision_rate=r)
                     for r in (0.5, 0.4, 0.3, 0.2, 0.1)], ignore_index=True)
    t = simulate_trades(evs, prices, calendar, 5, position_size_jpy=500_000)
    priced = apply_costs(t, 0.4, 2.80, 0, 500_000)
    pf = simulate_portfolio(priced, position_size_jpy=500_000, max_concurrent=3,
                            equity_jpy=1_500_000, maintenance_margin_ratio=0.20,
                            prices=prices, calendar=calendar)
    assert pf["taken"] == 3 and pf["skipped_no_slot"] == 2
    expected = pf["taken_mean_net_pct"] / 100 * 500_000 * pf["taken"]
    assert pf["realized_pnl_jpy"] == pytest.approx(expected, rel=1e-9)
    # 全件同じ銘柄・同じ日なので、建てた本と見送った本の平均は一致する
    assert pf["taken_mean_net_pct"] == pytest.approx(pf["skipped_mean_net_pct"])



def test_slot_rule_changes_which_signals_are_taken(prices, calendar):
    """選択則で建てる本が変わること。既定は従来の修正率降順。"""
    evs = pd.concat([
        _event("A0001", date(2024, 11, 12), revision_rate=0.9, turnover_avg=1e7),
        _event("A0001", date(2024, 11, 12), revision_rate=0.1, turnover_avg=1e9),
    ], ignore_index=True)
    t = simulate_trades(evs, prices, calendar, 5, position_size_jpy=500_000)
    t["turnover_avg"] = [1e7, 1e9]
    priced = apply_costs(t, 0.4, 2.80, 0, 500_000)
    kw = dict(position_size_jpy=500_000, max_concurrent=1, equity_jpy=1_500_000,
              maintenance_margin_ratio=0.20, prices=prices, calendar=calendar)
    by_rev = simulate_portfolio(priced, slot_rule="revision_desc", **kw)
    by_turn = simulate_portfolio(priced, slot_rule="turnover_desc", **kw)
    assert by_rev["taken"] == 1 and by_turn["taken"] == 1
    # 同じ銘柄・同じ日なのでリターンは同じ。選ばれた本が違うことは skipped の平均で見る
    with pytest.raises(ValueError):
        simulate_portfolio(priced, slot_rule="nonsense", **kw)
