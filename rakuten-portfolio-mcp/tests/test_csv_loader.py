from __future__ import annotations

import datetime as dt
from pathlib import Path

from rakuten_portfolio_mcp.loaders import csv_rakuten
from rakuten_portfolio_mcp.models import AssetClass, MarginKind, MarginSide


def test_sections_are_split_and_classified(sample_csv: Path):
    rows, _ = csv_rakuten.read_rows(sample_csv)
    blocks = csv_rakuten.split_blocks(rows)
    labels = [b.label for b in blocks]
    assert "国内株式(現物)" in labels
    assert "投資信託" in labels
    assert "信用建玉一覧" in labels


def test_load_spot_positions(sample_csv: Path):
    pf = csv_rakuten.load_csv(sample_csv)
    by_symbol = {p.symbol: p for p in pf.spot}

    toyota = by_symbol["7203"]
    assert toyota.name == "トヨタ自動車"
    assert toyota.quantity == 300
    assert toyota.avg_cost == 2850
    assert toyota.last_price == 3120
    assert toyota.cost_basis == 855_000
    assert toyota.market_value == 936_000
    assert toyota.unrealized_pnl == 81_000
    assert toyota.asset_class is AssetClass.JP_STOCK
    assert not toyota.is_nisa


def test_negative_pnl_and_nisa_flag(sample_csv: Path):
    pf = csv_rakuten.load_csv(sample_csv)
    ntt = next(p for p in pf.spot if p.symbol == "9432")
    assert ntt.is_nisa
    assert ntt.unrealized_pnl == -8_000


def test_fund_uses_10000_unit_price(sample_csv: Path):
    """投資信託の基準価額は1万口あたり。口数×基準価額/10000 が評価額になること。"""
    pf = csv_rakuten.load_csv(sample_csv)
    fund = next(p for p in pf.spot if p.name.startswith("eMAXIS"))
    assert fund.asset_class is AssetClass.FUND
    assert fund.quantity == 1_250_000
    assert fund.market_value == 2_367_500
    assert fund.cost_basis == 1_903_750
    assert fund.unrealized_pnl == 463_750
    assert fund.is_nisa


def test_load_margin_positions(sample_csv: Path):
    pf = csv_rakuten.load_csv(sample_csv)
    by_key = {(p.symbol, p.side) for p in pf.margin}
    assert ("6758", MarginSide.LONG) in by_key
    assert ("9984", MarginSide.SHORT) in by_key

    sony = next(p for p in pf.margin if p.symbol == "6758")
    assert sony.kind is MarginKind.SEIDO
    assert sony.notional == 640_000
    # 建値3200 → 現在値3050、諸経費1250
    assert sony.unrealized_pnl == -31_250
    assert sony.open_date == dt.date(2026, 4, 10)
    assert sony.due_date == dt.date(2026, 10, 9)


def test_short_position_pnl_sign_is_inverted(sample_csv: Path):
    """売建は株価が上がると損失になること。"""
    pf = csv_rakuten.load_csv(sample_csv)
    sbg = next(p for p in pf.margin if p.symbol == "9984")
    assert sbg.side is MarginSide.SHORT
    assert sbg.unrealized_pnl == -67_100
    assert sbg.signed_exposure == -1_185_000


def test_seido_due_date_is_inferred_when_blank(sample_csv: Path):
    """返済期限が空欄の一般信用(無期限)は補完しないこと。"""
    pf = csv_rakuten.load_csv(sample_csv)
    mhi = next(p for p in pf.margin if p.symbol == "7011")
    assert mhi.kind is MarginKind.IPPAN
    assert mhi.due_date is None


def test_account_scalars_are_picked_up(sample_csv: Path):
    pf = csv_rakuten.load_csv(sample_csv)
    assert pf.cash == 523_400
    assert pf.margin_account is not None
    assert pf.margin_account.cash_deposit == 800_000
    assert pf.margin_account.substitute_value == 1_200_000
    assert pf.margin_account.collateral == 1_760_000
    assert pf.asof == "2026-07-24"


def test_totals_row_is_ignored(tmp_path: Path):
    content = (
        "国内株式(現物),,,,\n"
        "銘柄コード,銘柄名,口座区分,保有数量,平均取得価額,現在値\n"
        "7203,トヨタ自動車,特定,100,2850,3120\n"
        ",合計,,100,,\n"
    )
    path = tmp_path / "totals.csv"
    path.write_text(content, encoding="utf-8")
    pf = csv_rakuten.load_csv(path)
    assert len(pf.spot) == 1


def test_cp932_is_decoded(tmp_path: Path, sample_csv: Path):
    """楽天証券のCSVはCP932で落ちてくるのが基本。"""
    path = tmp_path / "sjis.csv"
    path.write_bytes(sample_csv.read_text(encoding="utf-8").encode("cp932"))
    rows, encoding = csv_rakuten.read_rows(path)
    assert encoding == "cp932"
    pf = csv_rakuten.load_csv(path)
    assert len(pf.spot) == 6
    assert len(pf.margin) == 3


def test_market_value_backfills_missing_price(tmp_path: Path):
    """現在値の列が無くても評価額から単価を逆算すること。"""
    content = (
        "国内株式(現物),,,\n"
        "銘柄コード,銘柄名,保有数量,平均取得価額,時価評価額[円]\n"
        "7203,トヨタ自動車,100,2850,312000\n"
    )
    path = tmp_path / "novalue.csv"
    path.write_text(content, encoding="utf-8")
    pf = csv_rakuten.load_csv(path)
    assert pf.spot[0].last_price == 3120


def test_unreadable_file_produces_warning_not_crash(tmp_path: Path):
    path = tmp_path / "junk.csv"
    path.write_text("これはCSVではない\n適当な文章\n", encoding="utf-8")
    pf = csv_rakuten.load_csv(path)
    assert pf.spot == [] and pf.margin == []
    assert pf.warnings


def test_inspect_reports_blocks(sample_csv: Path):
    result = csv_rakuten.inspect(sample_csv)
    assert result["encoding"] == "utf-8-sig"
    kinds = {b["label"]: b["classified_as"] for b in result["blocks"]}
    assert kinds["国内株式(現物)"] == "spot"
    assert kinds["信用建玉一覧"] == "margin"
    assert kinds["投資信託"] == "spot"
