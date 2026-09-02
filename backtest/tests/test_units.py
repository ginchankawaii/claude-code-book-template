"""J-Quants が返す値の単位と型。

probe が実際に返した1件をそのまま使い、読み込み後に想定どおりの
数値・単位になっていることを固定する。
"""

import pandas as pd
import pytest

from erb.data import normalize

# probe が /equities/bars/daily から返した実物（極洋 1301）
REAL_DAILY_ROW = {
    "Date": "2025-06-02", "Code": "13010",
    "O": 4490.0, "H": 4515.0, "L": 4455.0, "C": 4475.0,
    "UL": "0", "LL": "0", "Vo": 51900.0, "Va": 232718000.0,
    "AdjFactor": 1.0, "AdjO": 4490.0, "AdjH": 4515.0, "AdjL": 4455.0,
    "AdjC": 4475.0, "AdjVo": 51900.0,
    "MktCap": 54050.0,          # 百万円単位
    "ExRT": None,
}

# 上場廃止銘柄（ネットワンシステムズ 7518・最終売買日）
REAL_DELISTED_ROW = {
    "Date": "2025-03-17", "Code": "75180",
    "O": 4480.0, "H": 4490.0, "L": 4480.0, "C": 4480.0,
    "UL": "0", "LL": "0", "Vo": 1318900.0, "Va": 5911806500.0,
    "AdjFactor": 1.0, "AdjO": 4480.0, "AdjH": 4490.0, "AdjL": 4480.0,
    "AdjC": 4480.0, "AdjVo": 1318900.0,
    "MktCap": 359783.0,
    "ExRT": None,
}


def test_mkt_cap_is_converted_from_millions_to_yen(cfg):
    """MktCap は百万円で返る。円に直さないと時価総額フィルタが一切効かない。

    54050（百万円）を円と誤読すると 5.4万円になり、
    「500億円以下」の条件を全銘柄が通過してしまう。
    """
    df = normalize(cfg, "daily", pd.DataFrame([REAL_DAILY_ROW]))
    assert df["mkt_cap"].iloc[0] == pytest.approx(54_050_000_000)   # 540.5億円


def test_mkt_cap_matches_shares_times_price(cfg):
    """円に直した時価総額が、株価 x 発行済株式数のオーダーと合うこと。"""
    df = normalize(cfg, "daily", pd.DataFrame([REAL_DELISTED_ROW]))
    mkt_cap = df["mkt_cap"].iloc[0]
    shares = mkt_cap / REAL_DELISTED_ROW["C"]
    # ネットワンシステムズの発行済株式数は8000万株規模
    assert 5e7 < shares < 1.2e8
    assert 3.0e11 < mkt_cap < 4.0e11      # 3000〜4000億円


def test_mkt_cap_filter_actually_excludes_large_caps(cfg):
    """単位を直した状態で「500億以下」が本当に効くこと。"""
    from erb.filters import apply_mktcap

    df = normalize(cfg, "daily", pd.DataFrame([REAL_DAILY_ROW, REAL_DELISTED_ROW]))
    t = pd.DataFrame({"mkt_cap": df["mkt_cap"]})
    # 極洋 540億 / ネットワン 3598億
    assert len(apply_mktcap(t, 50_000_000_000)) == 0    # どちらも500億超
    assert len(apply_mktcap(t, 100_000_000_000)) == 1   # 極洋だけ通る
    assert len(apply_mktcap(t, None)) == 2


def test_limit_flags_parse_from_string_zero(cfg):
    """UL / LL は "0" という文字列で返る。真偽値に直せていること。"""
    df = normalize(cfg, "daily", pd.DataFrame([REAL_DAILY_ROW]))
    assert bool(df["upper_limit"].iloc[0]) is False
    assert bool(df["lower_limit"].iloc[0]) is False

    hit = dict(REAL_DAILY_ROW, UL="1")
    df2 = normalize(cfg, "daily", pd.DataFrame([hit]))
    assert bool(df2["upper_limit"].iloc[0]) is True


def test_financial_figures_arrive_as_strings(cfg):
    """/fins/summary の数値は文字列で返り、欠損は空文字。数値に直せていること。"""
    row = {
        "DiscDate": "2025-05-15", "DiscTime": "15:40:00", "Code": "77090",
        "DiscNo": "20250206565562", "DocType": "FYFinancialStatements_Consolidated_JP",
        "CurPerType": "FY", "CurFYSt": "2024-04-01", "CurFYEn": "2025-03-31",
        "OP": "-125000000",      # 文字列。マイナスもある
        "FOP": "",               # 欠損は空文字
        "NxFOP": "1662000000",
        "FOP2Q": "", "ShOutFY": "13700000", "TrShFY": "0",
    }
    df = normalize(cfg, "summary", pd.DataFrame([row]))
    assert df["op_actual"].iloc[0] == pytest.approx(-125_000_000)
    assert pd.isna(df["fop"].iloc[0])
    assert df["nxfop"].iloc[0] == pytest.approx(1_662_000_000)
    assert df["shares_out"].iloc[0] == pytest.approx(13_700_000)


def test_long_disclosure_number_does_not_overflow(cfg):
    """DiscNo は14桁（例 20250206565562）。並び替えのキーで桁溢れしないこと。"""
    from erb.events import _sort_components

    df = normalize(cfg, "summary", pd.DataFrame([{
        "DiscDate": "2025-05-15", "DiscTime": "15:40:00", "Code": "77090",
        "DiscNo": "20250206565562",
    }]))
    comps = _sort_components(df)
    assert int(comps["_n"].iloc[0]) == 20250206565562
    assert int(comps["_t"].iloc[0]) == 154000
