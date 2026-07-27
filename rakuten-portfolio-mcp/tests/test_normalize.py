from __future__ import annotations

import datetime as dt

import pytest

from rakuten_portfolio_mcp import normalize as nz


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234", 1234.0),
        ("1,234円", 1234.0),
        ("▲5,000", -5000.0),
        ("△1.5", -1.5),
        ("+3,000", 3000.0),
        ("-250", -250.0),
        ("9.47％", 9.47),
        ("１２３４", 1234.0),  # 全角
        ("100株", 100.0),
        ("", None),
        ("--", None),
        ("N/A", None),
        (None, None),
        (1500, 1500.0),
    ],
)
def test_to_number(raw, expected):
    assert nz.to_number(raw) == expected


def test_to_number_extracts_from_noise():
    # 単位や注記が混ざっても数字を拾う
    assert nz.to_number("1234.5(円)") == 1234.5


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026/07/27", dt.date(2026, 7, 27)),
        ("2026-07-27", dt.date(2026, 7, 27)),
        ("20260727", dt.date(2026, 7, 27)),
        ("2026年7月27日", dt.date(2026, 7, 27)),
        ("", None),
        ("あああ", None),
    ],
)
def test_parse_date(raw, expected):
    assert nz.parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7203", "7203"),
        ("7203.0", "7203"),  # Excelで数値化された場合
        ("130", "0130"),  # 先頭0落ちの復元
        ("aapl", "AAPL"),
        ("'7203", "7203"),
    ],
)
def test_parse_symbol(raw, expected):
    assert nz.parse_symbol(raw) == expected


def test_normalize_header_strips_units_and_symbols():
    assert nz.normalize_header("時価評価額[円]") == "時価評価額"
    assert nz.normalize_header(" 銘柄 コード ") == "銘柄コード"
    assert nz.normalize_header("保有数量（株）") == "保有数量"


def test_header_map_prefers_exact_match():
    header = ["銘柄コード", "銘柄名", "現在値", "前日比", "時価評価額[円]", "評価損益[円]"]
    hmap = nz.HeaderMap(header)
    assert hmap.find(nz.LAST_PRICE, exclude=("前日比", "評価額")) == 2
    assert hmap.find(nz.MARKET_VALUE) == 4


def test_header_map_exclude_blocks_wrong_column():
    # 「時価評価額」しか無いとき、現在値として拾ってしまわないこと
    hmap = nz.HeaderMap(["銘柄名", "時価評価額[円]"])
    assert hmap.find(nz.LAST_PRICE, exclude=("前日比", "騰落", "評価額")) is None


def test_header_map_falls_back_to_partial_match():
    # 完全一致も前方一致もしない表記ゆれを部分一致で拾えること
    hmap = nz.HeaderMap(["銘柄コード", "参考現在値"])
    assert hmap.find(nz.LAST_PRICE) == 1
