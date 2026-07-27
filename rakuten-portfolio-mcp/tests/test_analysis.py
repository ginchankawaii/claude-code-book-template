from __future__ import annotations

import datetime as dt

import pytest

from rakuten_portfolio_mcp import service
from rakuten_portfolio_mcp.analysis import brief, concentration, margin, pnl, risk
from rakuten_portfolio_mcp.config import Config
from rakuten_portfolio_mcp.models import (
    MarginAccount,
    MarginKind,
    MarginPosition,
    MarginSide,
    Portfolio,
)


@pytest.fixture
def pf(cfg: Config):
    return service.load_portfolio(cfg)


def _leveraged(cash: float = 1_000_000.0, substitute: float = 0.0) -> Portfolio:
    """買い一辺倒の建玉だけを持つ検証用ポートフォリオ。

    サンプルCSVは売建が買建をほぼ相殺していて維持率が株価に鈍感なので、
    追証まわりの挙動はこちらの素直な買い建て玉で確認する。
    """
    return Portfolio(
        margin=[
            MarginPosition(
                symbol="7203",
                name="トヨタ自動車",
                side=MarginSide.LONG,
                kind=MarginKind.SEIDO,
                quantity=1000,
                open_price=3000,
                last_price=3000,
                open_date=dt.date(2026, 5, 1),
            )
        ],
        margin_account=MarginAccount(cash_deposit=cash, substitute_value=substitute),
    )


def test_portfolio_totals(pf):
    assert pf.cash == 523_400
    assert pf.spot_market_value == 6_024_040
    assert pf.margin_unrealized == -60_230
    assert pf.net_asset_value == 6_487_210


# --- 信用取引 ----------------------------------------------------------


def test_maintenance_rate(pf, cfg: Config):
    # (受入保証金1,760,000 + 評価損益-60,230) ÷ 建玉代金2,504,000
    assert margin.maintenance_rate(pf, cfg) == pytest.approx(67.8822, abs=1e-3)


def test_conservative_rate_excludes_unrealized_gains(pf, cfg: Config):
    """含み益を保証金に算入しない保守版は、通常版より低くなること。"""
    assert margin.maintenance_rate(pf, cfg, conservative=True) < margin.maintenance_rate(pf, cfg)


def test_shock_to_threshold_is_consistent_with_rate_at_shock(pf, cfg: Config):
    """解析的に解いた到達点で、実際に維持率がその値になること。"""
    for threshold in (20.0, 30.0, 50.0):
        shock = margin.shock_to_threshold(pf, cfg, threshold)
        assert shock is not None
        assert margin.rate_at_shock(pf, cfg, shock) == pytest.approx(threshold, abs=1e-6)


def test_margin_call_distance_on_leveraged_book(cfg: Config):
    """保証金1,000,000で建玉3,000,000なら維持率33.3%、13.3%下落で追証。"""
    book = _leveraged()
    assert margin.maintenance_rate(book, cfg) == pytest.approx(33.333, abs=1e-3)
    assert margin.shock_to_threshold(book, cfg, 20.0) == pytest.approx(-13.333, abs=1e-3)


def test_substitute_securities_decline_is_included(cfg: Config):
    """代用有価証券も株価と一緒に目減りする分、維持率の下がり方が急になること。

    ここを式から落とすと追証までの距離を実際より甘く見積もる。
    """
    all_cash = _leveraged(cash=1_000_000, substitute=0)
    # 掛目80%なので代用1,250,000 = 現金1,000,000と同じ担保価値
    with_substitute = _leveraged(cash=0, substitute=1_250_000)

    assert margin.maintenance_rate(all_cash, cfg) == pytest.approx(
        margin.maintenance_rate(with_substitute, cfg)
    )

    drop_cash = 33.333 - margin.rate_at_shock(all_cash, cfg, -10.0)
    drop_substitute = 33.333 - margin.rate_at_shock(with_substitute, cfg, -10.0)
    assert drop_substitute > drop_cash
    # 代用のほうが早く追証に届く
    assert margin.shock_to_threshold(with_substitute, cfg, 20.0) > margin.shock_to_threshold(
        all_cash, cfg, 20.0
    )


def test_additional_deposit_is_zero_when_healthy(pf, cfg: Config):
    assert margin.additional_deposit_needed(pf, cfg) == 0.0


def test_additional_deposit_when_undercollateralised(pf, cfg: Config):
    pf.margin_account.cash_deposit = 0.0
    pf.margin_account.substitute_value = 0.0
    # 必要額 = 2,504,000 × 20% − 評価損益(−60,230)
    assert margin.additional_deposit_needed(pf, cfg) == pytest.approx(561_030, abs=1)


def test_new_position_capacity(cfg: Config):
    # 保証金1,000,000 ÷ 30% = 建玉3,333,333 まで。既存3,000,000を引いた分が余力
    book = _leveraged()
    assert margin.new_position_capacity(book, cfg) == pytest.approx(333_333, abs=1)


def test_expiring_positions(pf):
    rows = margin.expiring_positions(pf, within_days=30, today=dt.date(2026, 10, 1))
    symbols = [r["symbol"] for r in rows]
    assert "6758" in symbols  # 返済期限 2026-10-09
    assert "9984" not in symbols  # 2026-12-28 はまだ先


def test_margin_summary_shape(pf, cfg: Config):
    summary = margin.summarize(pf, cfg, today=dt.date(2026, 7, 24))
    assert summary["has_margin_positions"] is True
    assert summary["total_notional"] == 2_504_000
    assert summary["status"] == "余裕"
    assert summary["net_direction"] == "買い偏重"
    assert summary["short_seido_count"] == 1


def test_no_margin_account_is_reported(pf, cfg: Config):
    pf.margin_account = None
    summary = margin.summarize(pf, cfg)
    assert summary["maintenance_rate_pct"] == pytest.approx(-2.4, abs=0.1)
    assert "保証金情報が未入力" in summary["note"]


def test_no_margin_positions(cfg: Config):
    summary = margin.summarize(Portfolio(), cfg)
    assert summary["has_margin_positions"] is False


# --- 集中度 ------------------------------------------------------------


def test_spot_and_margin_are_netted_per_symbol(pf):
    """同じ銘柄を現物で持ちつつ信用買いもしている場合、通算で見えること。"""
    sony = concentration.exposures(pf)["6758"]
    assert sony["spot_value"] == 305_000
    assert sony["margin_value"] == 610_000
    assert sony["net_exposure"] == 915_000


def test_short_reduces_net_exposure(pf):
    book = concentration.exposures(pf)
    assert book["9984"]["net_exposure"] == -1_185_000
    assert book["9984"]["gross_exposure"] == 1_185_000


def test_concentration_summary(pf):
    summary = concentration.summarize(pf)
    assert summary["gross_exposure"] == 8_602_040
    assert summary["top_positions"][0]["name"].startswith("eMAXIS")
    assert summary["top_positions"][0]["weight_pct"] == pytest.approx(27.52, abs=0.01)
    assert 0 < summary["hhi"] < 10000


def test_hhi_extremes():
    assert concentration.hhi([100.0]) == 10000
    assert concentration.hhi([10.0] * 10) == pytest.approx(1000)


# --- リスク ------------------------------------------------------------


def test_shock_pnl(pf):
    result = risk.portfolio_pnl_at_shock(pf, -10.0)
    assert result["spot_delta"] == pytest.approx(-602_404)
    # 買建1,393,000 − 売建1,185,000 = ネット208,000 の10%
    assert result["margin_delta"] == pytest.approx(-20_800)


def test_scenario_table_flags_margin_call(cfg: Config):
    table = risk.scenario_table(_leveraged(), cfg, [-10.0, -20.0])
    assert table[0]["margin_call"] is False
    assert table[1]["margin_call"] is True


def test_single_name_shock(pf, cfg: Config):
    result = risk.single_name_shock(pf, "6758", -20.0, cfg)
    assert result["positions_affected"] == 2
    assert result["spot_delta"] == -61_000
    assert result["margin_delta"] == -122_000
    assert result["total_delta"] == -183_000
    assert result["maintenance_rate_after_pct"] < result["maintenance_rate_before_pct"]


# --- 損益 --------------------------------------------------------------


def test_pnl_splits_nisa_and_taxable(pf, cfg: Config):
    summary = pnl.summarize(pf, cfg)
    assert summary["nisa_unrealized_pnl"] == 455_750
    assert summary["taxable_unrealized_pnl"] == 427_510
    assert summary["total_unrealized_pnl"] == 883_260
    # 課税対象の含み益にだけ税がかかる
    assert summary["estimated_tax_if_realized"] == round(427_510 * cfg.tax_rate)


def test_loss_harvest_ignores_nisa_losses(pf, cfg: Config):
    """NISAの含み損は他口座と損益通算できないので候補に出さないこと。"""
    assert pnl.summarize(pf, cfg)["loss_harvest_candidates"] == []


def test_loss_harvest_picks_taxable_losses(pf, cfg: Config):
    taxable_loser = next(p for p in pf.spot if p.symbol == "7203")
    taxable_loser.last_price = 2000  # 含み損に転落させる
    candidates = pnl.summarize(pf, cfg)["loss_harvest_candidates"]
    assert [c["symbol"] for c in candidates] == ["7203"]


# --- ブリーフ ----------------------------------------------------------


def test_brief_contains_all_sections(pf, cfg: Config):
    result = brief.build(pf, cfg, today=dt.date(2026, 7, 24))
    for key in ("portfolio", "concentration", "margin", "risk", "pnl", "flags", "disclaimer"):
        assert key in result


def test_flags_warn_on_expiring_position(pf, cfg: Config):
    flags = brief.flags(pf, cfg, today=dt.date(2026, 10, 5))
    assert "期日" in {f["topic"] for f in flags}


def test_flags_escalate_on_margin_call(cfg: Config):
    book = _leveraged(cash=500_000)  # 維持率16.7%
    flags = brief.flags(book, cfg, today=dt.date(2026, 7, 24))
    assert any(f["level"] == "critical" and f["topic"] == "追証" for f in flags)


def test_flags_note_missing_margin_account(pf, cfg: Config):
    pf.margin_account = None
    assert any(f["topic"] == "データ" for f in brief.flags(pf, cfg))
