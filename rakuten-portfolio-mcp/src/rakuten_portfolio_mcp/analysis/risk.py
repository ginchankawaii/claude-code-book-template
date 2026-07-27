"""下落シナリオのストレステスト。

「あと何%下げたら追証か」だけだと痛みの実額が分からないので、
一律ショックと個別銘柄ショックの両方で損益額と維持率を出す。
ベータや相関は使わない単純な一律変動モデル。前提を単純に保って
数字の出どころを説明できる状態にしておくほうが、判断材料として扱いやすい。
"""

from __future__ import annotations

from typing import Any, Optional

from ..config import Config
from ..models import MarginSide, Portfolio
from . import margin as margin_mod

DEFAULT_SCENARIOS = [-3.0, -5.0, -10.0, -15.0, -20.0, -30.0]


def portfolio_pnl_at_shock(pf: Portfolio, shock_pct: float) -> dict[str, float]:
    """一律 shock_pct% 変動したときの損益（現物・信用の内訳つき）。"""
    x = shock_pct / 100.0

    spot_delta = 0.0
    for p in pf.spot:
        mv = p.market_value
        if mv is None:
            continue
        spot_delta += mv * x

    margin_delta = 0.0
    for m in pf.margin:
        mv = m.market_value
        if mv is None:
            continue
        sign = 1.0 if m.side is MarginSide.LONG else -1.0
        margin_delta += sign * mv * x

    return {
        "spot_delta": spot_delta,
        "margin_delta": margin_delta,
        "total_delta": spot_delta + margin_delta,
    }


def scenario_table(
    pf: Portfolio, cfg: Config, scenarios: Optional[list[float]] = None
) -> list[dict[str, Any]]:
    scenarios = scenarios or DEFAULT_SCENARIOS
    nav = pf.net_asset_value
    out = []

    for s in scenarios:
        delta = portfolio_pnl_at_shock(pf, s)
        rate = margin_mod.rate_at_shock(pf, cfg, s)
        out.append(
            {
                "shock_pct": s,
                "spot_delta": round(delta["spot_delta"]),
                "margin_delta": round(delta["margin_delta"]),
                "total_delta": round(delta["total_delta"]),
                "nav_after": round(nav + delta["total_delta"]),
                "nav_change_pct": round(delta["total_delta"] / nav * 100, 2) if nav > 0 else None,
                "maintenance_rate_pct": round(rate, 2) if rate is not None else None,
                "margin_call": bool(rate is not None and rate < cfg.maintenance_threshold),
            }
        )
    return out


def single_name_shock(
    pf: Portfolio, symbol: str, shock_pct: float, cfg: Config
) -> dict[str, Any]:
    """特定銘柄だけが動いたときの影響。決算前の銘柄を見るとき用。"""
    x = shock_pct / 100.0
    delta = 0.0
    touched = 0

    for p in pf.spot:
        if p.symbol != symbol:
            continue
        mv = p.market_value
        if mv is not None:
            delta += mv * x
            touched += 1

    margin_delta = 0.0
    for m in pf.margin:
        if m.symbol != symbol:
            continue
        mv = m.market_value
        if mv is None:
            continue
        sign = 1.0 if m.side is MarginSide.LONG else -1.0
        margin_delta += sign * mv * x
        touched += 1

    nav = pf.net_asset_value
    total = delta + margin_delta

    # 維持率は建玉と代用有価証券の変化分だけ効く
    comp_before = margin_mod.maintenance_rate(pf, cfg)
    rate_after = None
    if comp_before is not None:
        c = margin_mod._components(pf, cfg)
        if c["notional"] > 0:
            rate_after = (
                (c["collateral"] + c["unrealized"] + margin_delta) / c["notional"] * 100
            )

    return {
        "symbol": symbol,
        "shock_pct": shock_pct,
        "positions_affected": touched,
        "spot_delta": round(delta),
        "margin_delta": round(margin_delta),
        "total_delta": round(total),
        "nav_change_pct": round(total / nav * 100, 2) if nav > 0 else None,
        "maintenance_rate_before_pct": round(comp_before, 2) if comp_before is not None else None,
        "maintenance_rate_after_pct": round(rate_after, 2) if rate_after is not None else None,
        "margin_call": bool(
            rate_after is not None and rate_after < cfg.maintenance_threshold
        ),
    }


def worst_single_name(pf: Portfolio, cfg: Config, shock_pct: float = -20.0) -> list[dict[str, Any]]:
    """全銘柄をそれぞれ単独で叩いて、影響の大きい順に並べる。"""
    symbols = {p.symbol for p in pf.spot} | {m.symbol for m in pf.margin}
    results = [single_name_shock(pf, s, shock_pct, cfg) for s in symbols]
    return sorted(results, key=lambda r: r["total_delta"])[:10]


def summarize(pf: Portfolio, cfg: Config, scenarios: Optional[list[float]] = None) -> dict[str, Any]:
    table = scenario_table(pf, cfg, scenarios)
    first_call = next((r for r in table if r["margin_call"]), None)
    return {
        "net_asset_value": round(pf.net_asset_value),
        "scenarios": table,
        "first_margin_call_scenario": first_call["shock_pct"] if first_call else None,
        "shock_to_margin_call_pct": margin_mod.shock_to_threshold(
            pf, cfg, cfg.maintenance_threshold
        ),
        "worst_single_names_at_minus20": worst_single_name(pf, cfg, -20.0),
        "model_note": (
            "全銘柄が同率で動く単純モデル。ベータ・相関・流動性は考慮していない。"
            "代用有価証券の目減りは維持率計算に含めている。"
        ),
    }
