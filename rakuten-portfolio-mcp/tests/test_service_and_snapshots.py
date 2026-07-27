from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest

from rakuten_portfolio_mcp import service, snapshots
from rakuten_portfolio_mcp.config import Config
from rakuten_portfolio_mcp.loaders import manual
from rakuten_portfolio_mcp.models import AssetClass, MarginSide

MANUAL_YAML = """
asof: 2026-07-24
cash: 100000
margin_account:
  cash_deposit: 500000
  substitute_value: 250000
spot:
  - symbol: "7203"
    name: トヨタ自動車
    account: 特定
    quantity: 100
    avg_cost: 2800
    last_price: 3000
  - symbol: AAPL
    name: Apple Inc.
    asset_class: us_stock
    account: 特定
    quantity: 10
    avg_cost: 200
    last_price: 220
    currency: USD
margin:
  - symbol: "6758"
    name: ソニーグループ
    side: 売建
    kind: 制度
    open_date: 2026-06-01
    quantity: 100
    open_price: 3000
    last_price: 2800
"""


@pytest.fixture
def manual_dir(tmp_path: Path) -> Path:
    (tmp_path / "portfolio.yaml").write_text(MANUAL_YAML, encoding="utf-8")
    return tmp_path


def test_manual_yaml_is_loaded(manual_dir: Path):
    pf = manual.load_manual(manual_dir / "portfolio.yaml")
    assert pf.cash == 100_000
    assert pf.asof == "2026-07-24"
    assert pf.margin_account.collateral == 500_000 + 250_000 * 0.8

    toyota = next(p for p in pf.spot if p.symbol == "7203")
    assert toyota.unrealized_pnl == 20_000

    apple = next(p for p in pf.spot if p.symbol == "AAPL")
    assert apple.asset_class is AssetClass.US_STOCK
    assert apple.currency == "USD"

    sony = pf.margin[0]
    assert sony.side is MarginSide.SHORT
    # 売建は値下がりが利益
    assert sony.unrealized_pnl == 20_000
    # 制度信用は建日から6ヶ月で返済期限を補完する
    assert sony.due_date == dt.date(2026, 6, 1) + dt.timedelta(days=183)


def test_foreign_currency_is_converted_with_fixed_rate(manual_dir: Path):
    cfg = Config(data_dir=manual_dir, price_source="none", usdjpy=150.0)
    pf = service.load_portfolio(cfg)
    apple = next(p for p in pf.spot if p.symbol == "AAPL")
    assert apple.currency == "JPY"
    assert apple.last_price == pytest.approx(220 * 150.0)
    assert apple.market_value == pytest.approx(330_000)


def test_missing_fx_rate_leaves_position_untouched(manual_dir: Path):
    """レートが取れないときに勝手な換算をしないこと。"""
    cfg = Config(data_dir=manual_dir, price_source="none", usdjpy=0.0)
    pf = service.load_portfolio(cfg)
    apple = next(p for p in pf.spot if p.symbol == "AAPL")
    assert apple.currency == "USD"
    assert any("USD/JPY" in w for w in pf.warnings)


def test_csv_and_yaml_are_merged(tmp_path: Path, sample_csv: Path):
    shutil.copy(sample_csv, tmp_path / sample_csv.name)
    (tmp_path / "extra.yaml").write_text(
        'spot:\n  - symbol: "4755"\n    name: 楽天グループ\n    account: 特定\n'
        "    quantity: 100\n    avg_cost: 700\n    last_price: 820\n",
        encoding="utf-8",
    )
    cfg = Config(data_dir=tmp_path, price_source="none")
    pf = service.load_portfolio(cfg)
    assert len(pf.spot) == 7
    assert any(p.symbol == "4755" for p in pf.spot)


def test_duplicate_symbol_across_files_warns(tmp_path: Path, sample_csv: Path):
    shutil.copy(sample_csv, tmp_path / sample_csv.name)
    shutil.copy(sample_csv, tmp_path / "copy.csv")
    cfg = Config(data_dir=tmp_path, price_source="none")
    pf = service.load_portfolio(cfg)
    assert any("二重計上" in w for w in pf.warnings)


def test_example_files_are_skipped(tmp_path: Path):
    (tmp_path / "portfolio.example.yaml").write_text("cash: 999\n", encoding="utf-8")
    cfg = Config(data_dir=tmp_path, price_source="none")
    pf = service.load_portfolio(cfg)
    assert pf.cash == 0
    assert any("読み込めるファイルが無い" in w for w in pf.warnings)


def test_broken_file_does_not_abort_the_rest(tmp_path: Path, sample_csv: Path):
    shutil.copy(sample_csv, tmp_path / sample_csv.name)
    (tmp_path / "broken.json") .write_text("{ これはJSONではない", encoding="utf-8")
    cfg = Config(data_dir=tmp_path, price_source="none")
    pf = service.load_portfolio(cfg)
    assert len(pf.spot) == 6
    assert any("読み込み失敗" in w for w in pf.warnings)


def test_missing_price_degrades_gracefully(tmp_path: Path):
    """株価を取れない環境でも落ちず、取得単価ベースで計算を続けること。"""
    (tmp_path / "portfolio.yaml").write_text(
        'spot:\n  - symbol: "7203"\n    name: トヨタ自動車\n    account: 特定\n'
        "    quantity: 100\n    avg_cost: 2800\n",  # last_price を書かない
        encoding="utf-8",
    )
    cfg = Config(data_dir=tmp_path, price_source="none")
    pf = service.load_portfolio(cfg)

    assert pf.spot[0].last_price is None
    assert pf.spot[0].market_value is None
    assert pf.missing_prices == ["7203"]
    # 評価額不明でも取得原価で純資産を出す
    assert pf.net_asset_value == 280_000
    assert any("株価を取得できなかった" in w for w in pf.warnings)


def test_list_sources(cfg: Config):
    result = service.list_sources(cfg)
    assert result["file_count"] == 1
    assert result["files"][0]["kind"] == "csv"


def test_inspect_file_reports_parse_result(cfg: Config, sample_csv: Path):
    result = service.inspect_file(cfg, sample_csv.name)
    assert result["parsed_spot_count"] == 6
    assert result["parsed_margin_count"] == 3


def test_inspect_missing_file(cfg: Config):
    assert "error" in service.inspect_file(cfg, "nope.csv")


# --- スナップショット --------------------------------------------------


def test_snapshot_roundtrip(cfg: Config):
    pf = service.load_portfolio(cfg)
    path = snapshots.save(pf, cfg, "before", now=dt.datetime(2026, 7, 24, 9, 0))
    assert path.exists()

    pf.spot[0].last_price = 3500  # トヨタが上昇
    snapshots.save(pf, cfg, "after", now=dt.datetime(2026, 7, 25, 9, 0))

    listed = snapshots.listing(cfg)
    assert [s["label"] for s in listed] == ["before", "after"]

    diff = snapshots.compare(cfg, "20260724-0900", "20260725-0900")
    assert diff["net_asset_value"]["change"] == 114_000  # 300株 × 380円
    changed = {c["symbol"] for c in diff["position_changes"]}
    assert changed == {"7203"}


def test_compare_missing_snapshot(cfg: Config):
    assert "error" in snapshots.compare(cfg, "nope", "alsonope")
