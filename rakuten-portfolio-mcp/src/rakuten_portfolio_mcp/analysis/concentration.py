"""集中度・エクスポージャー分析。

「1銘柄にいくら賭けているか」を現物と信用を通算して見る。
信用の買建は現物と同じ方向のリスクなので合算し、売建は差し引く。
iSPEEDの画面は現物と信用がタブで分かれていて通算のリスクが見えにくいので、
ここを埋めるのがこのモジュールの狙い。
"""

from __future__ import annotations

from typing import Any

from ..models import AssetClass, MarginSide, Portfolio


def exposures(pf: Portfolio) -> dict[str, dict[str, Any]]:
    """銘柄別の通算エクスポージャー。"""
    book: dict[str, dict[str, Any]] = {}

    for p in pf.spot:
        mv = p.market_value or p.cost_basis
        e = book.setdefault(p.symbol, _empty(p.symbol, p.name, p.asset_class.value))
        e["spot_value"] += mv
        e["net_exposure"] += mv
        e["gross_exposure"] += abs(mv)
        e["unrealized_pnl"] += p.unrealized_pnl or 0.0
        e["accounts"].add(p.account)

    for m in pf.margin:
        mv = m.market_value or m.notional
        signed = mv if m.side is MarginSide.LONG else -mv
        e = book.setdefault(m.symbol, _empty(m.symbol, m.name, AssetClass.JP_STOCK.value))
        e["margin_value"] += signed
        e["net_exposure"] += signed
        e["gross_exposure"] += abs(mv)
        e["unrealized_pnl"] += m.unrealized_pnl or 0.0
        e["accounts"].add(f"信用{m.side.value}")

    for e in book.values():
        e["accounts"] = sorted(e["accounts"])
    return book


def _empty(symbol: str, name: str, asset_class: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": name,
        "asset_class": asset_class,
        "spot_value": 0.0,
        "margin_value": 0.0,
        "net_exposure": 0.0,
        "gross_exposure": 0.0,
        "unrealized_pnl": 0.0,
        "accounts": set(),
    }


def hhi(weights_pct: list[float]) -> float:
    """ハーフィンダール指数。1銘柄集中なら10000、10銘柄均等なら1000。

    分散度合いを1つの数字で言い切れるので、時系列比較に使いやすい。
    """
    return sum(w * w for w in weights_pct)


def summarize(pf: Portfolio, top_n: int = 10) -> dict[str, Any]:
    book = exposures(pf)
    gross_total = sum(e["gross_exposure"] for e in book.values())
    nav = pf.net_asset_value

    rows = []
    for e in book.values():
        weight = e["gross_exposure"] / gross_total * 100 if gross_total else 0.0
        rows.append(
            {
                "symbol": e["symbol"],
                "name": e["name"],
                "asset_class": e["asset_class"],
                "spot_value": round(e["spot_value"]),
                "margin_value": round(e["margin_value"]),
                "net_exposure": round(e["net_exposure"]),
                "gross_exposure": round(e["gross_exposure"]),
                "weight_pct": round(weight, 2),
                "pct_of_nav": round(e["net_exposure"] / nav * 100, 2) if nav > 0 else None,
                "unrealized_pnl": round(e["unrealized_pnl"]),
                "accounts": e["accounts"],
            }
        )
    rows.sort(key=lambda r: r["gross_exposure"], reverse=True)

    weights = [r["weight_pct"] for r in rows]
    index = hhi(weights)
    top3 = sum(weights[:3])

    by_class: dict[str, float] = {}
    for r in rows:
        by_class[r["asset_class"]] = by_class.get(r["asset_class"], 0.0) + r["gross_exposure"]

    return {
        "position_count": len(rows),
        "gross_exposure": round(gross_total),
        "net_asset_value": round(nav),
        "cash": round(pf.cash),
        "cash_ratio_pct": round(pf.cash / nav * 100, 2) if nav > 0 else None,
        "gross_leverage": round(gross_total / nav, 2) if nav > 0 else None,
        "hhi": round(index),
        "hhi_interpretation": _interpret_hhi(index),
        "effective_positions": round(10000 / index, 1) if index > 0 else None,
        "top3_weight_pct": round(top3, 2),
        "top_positions": rows[:top_n],
        "by_asset_class": {
            k: {
                "value": round(v),
                "weight_pct": round(v / gross_total * 100, 2) if gross_total else 0.0,
            }
            for k, v in sorted(by_class.items(), key=lambda kv: -kv[1])
        },
    }


def _interpret_hhi(index: float) -> str:
    """HHIの目安。1500未満は分散、2500超で集中というのが一般的な線引き。"""
    if index == 0:
        return "ポジションなし"
    if index < 1500:
        return "分散（実質10銘柄以上に相当）"
    if index < 2500:
        return "やや集中"
    if index < 5000:
        return "集中（実質2〜4銘柄に相当）"
    return "極端に集中（ほぼ1〜2銘柄勝負）"
