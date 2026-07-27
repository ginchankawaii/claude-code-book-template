"""損益サマリと課税区分の整理。

NISA枠の含み益には税金がかからず、特定・一般口座の含み益には約20.315%かかる。
「見かけの含み益」と「税引後に手元に残る額」は別物なので分けて出す。
含み損の銘柄は損益通算（いわゆる損出し）の候補として拾っておく。
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..models import MarginSide, Portfolio


def summarize(pf: Portfolio, cfg: Config) -> dict[str, Any]:
    nisa_pnl = 0.0
    taxable_pnl = 0.0
    unknown_pnl = 0.0
    nisa_value = 0.0
    taxable_value = 0.0

    for p in pf.spot:
        pnl = p.unrealized_pnl
        mv = p.market_value or p.cost_basis
        if pnl is None:
            unknown_pnl += 0.0
            continue
        if p.is_nisa:
            nisa_pnl += pnl
            nisa_value += mv
        else:
            taxable_pnl += pnl
            taxable_value += mv

    # 信用取引はNISA対象外なので必ず課税区分
    margin_pnl = sum(m.unrealized_pnl or 0.0 for m in pf.margin)
    taxable_pnl += margin_pnl

    tax_on_gain = max(0.0, taxable_pnl) * cfg.tax_rate
    total_pnl = nisa_pnl + taxable_pnl

    winners = _ranked(pf, best=True)
    losers = _ranked(pf, best=False)

    return {
        "total_unrealized_pnl": round(total_pnl),
        "nisa_unrealized_pnl": round(nisa_pnl),
        "taxable_unrealized_pnl": round(taxable_pnl),
        "margin_unrealized_pnl": round(margin_pnl),
        "nisa_market_value": round(nisa_value),
        "taxable_market_value": round(taxable_value),
        "estimated_tax_if_realized": round(tax_on_gain),
        "after_tax_unrealized_pnl": round(total_pnl - tax_on_gain),
        "tax_rate": cfg.tax_rate,
        "top_winners": winners[:5],
        "top_losers": losers[:5],
        "loss_harvest_candidates": _loss_harvest(pf),
        "note": (
            "NISA口座の損失は他口座と損益通算できない点に注意。"
            "税額は概算で、繰越控除や配当との通算は考慮していない。"
        ),
    }


def _ranked(pf: Portfolio, best: bool) -> list[dict[str, Any]]:
    rows = []
    for p in pf.spot:
        if p.unrealized_pnl is None:
            continue
        rows.append(
            {
                "symbol": p.symbol,
                "name": p.name,
                "kind": "現物",
                "account": p.account,
                "unrealized_pnl": round(p.unrealized_pnl),
                "unrealized_pnl_pct": round(p.unrealized_pnl_pct or 0.0, 2),
            }
        )
    for m in pf.margin:
        if m.unrealized_pnl is None:
            continue
        rows.append(
            {
                "symbol": m.symbol,
                "name": m.name,
                "kind": f"信用{m.side.value}",
                "account": "信用",
                "unrealized_pnl": round(m.unrealized_pnl),
                "unrealized_pnl_pct": round(m.unrealized_pnl_pct or 0.0, 2),
            }
        )
    rows.sort(key=lambda r: r["unrealized_pnl"], reverse=best)
    return rows


def _loss_harvest(pf: Portfolio) -> list[dict[str, Any]]:
    """課税口座で含み損を抱えている現物。損益通算に使える候補。"""
    out = []
    for p in pf.spot:
        pnl = p.unrealized_pnl
        if pnl is None or pnl >= 0 or p.is_nisa:
            continue
        out.append(
            {
                "symbol": p.symbol,
                "name": p.name,
                "account": p.account,
                "unrealized_loss": round(pnl),
                "unrealized_pnl_pct": round(p.unrealized_pnl_pct or 0.0, 2),
            }
        )
    return sorted(out, key=lambda r: r["unrealized_loss"])[:10]
