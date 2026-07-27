"""手入力のYAML/JSONを読む。

CSVが取れない商品（米国株の一部、iSPEEDの画面を見ながら入れたいとき）や、
CSVに載らない保証金情報の補完に使う。CSVと同じフォルダに置けば自動でマージされる。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .. import normalize as nz
from ..models import (
    AssetClass,
    MarginAccount,
    MarginKind,
    MarginPosition,
    MarginSide,
    Portfolio,
    SpotPosition,
)


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - 環境依存
            raise RuntimeError(
                "YAMLを読むには pyyaml が必要。JSONで書くか pyyaml を入れてほしい。"
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: トップレベルはマッピングで書いてほしい")
    return data


def _asset_class(value: Optional[str], symbol: str) -> AssetClass:
    v = (value or "").lower()
    table = {
        "jp_stock": AssetClass.JP_STOCK,
        "国内株": AssetClass.JP_STOCK,
        "us_stock": AssetClass.US_STOCK,
        "米国株": AssetClass.US_STOCK,
        "fund": AssetClass.FUND,
        "投資信託": AssetClass.FUND,
        "bond": AssetClass.BOND,
        "債券": AssetClass.BOND,
    }
    for key, ac in table.items():
        if key in v:
            return ac
    # 未指定なら数字4桁を国内株、それ以外を米国株とみなす
    return AssetClass.JP_STOCK if symbol.isdigit() else AssetClass.US_STOCK


def _side(value: Optional[str]) -> MarginSide:
    v = (value or "").lower()
    return MarginSide.SHORT if any(k in v for k in ("売", "short")) else MarginSide.LONG


def _kind(value: Optional[str]) -> MarginKind:
    v = value or ""
    if "いちにち" in v or "デイ" in v:
        return MarginKind.DAYTRADE
    if "制度" in v:
        return MarginKind.SEIDO
    if "一般" in v or "無期限" in v:
        return MarginKind.IPPAN
    return MarginKind.UNKNOWN


def load_manual(path: Path) -> Portfolio:
    data = _load_mapping(path)
    source = path.name
    pf = Portfolio(sources=[source])

    asof = data.get("asof")
    if asof is not None:
        d = nz.parse_date(asof)
        pf.asof = d.isoformat() if d else str(asof)

    pf.cash = float(nz.to_number(data.get("cash")) or 0.0)

    for item in data.get("spot") or []:
        symbol = nz.parse_symbol(item.get("symbol") or item.get("code") or "")
        ac = _asset_class(item.get("asset_class"), symbol)
        pf.spot.append(
            SpotPosition(
                symbol=symbol or str(item.get("name", "")),
                name=item.get("name") or "",
                asset_class=ac,
                account=item.get("account") or "不明",
                quantity=float(nz.to_number(item.get("quantity")) or 0.0),
                avg_cost=float(nz.to_number(item.get("avg_cost")) or 0.0),
                last_price=nz.to_number(item.get("last_price")),
                currency=(item.get("currency") or ("USD" if ac is AssetClass.US_STOCK else "JPY")).upper(),
                price_multiplier=1.0 / 10000.0 if ac is AssetClass.FUND else 1.0,
                source=source,
            )
        )

    for item in data.get("margin") or []:
        symbol = nz.parse_symbol(item.get("symbol") or item.get("code") or "")
        pf.margin.append(
            MarginPosition(
                symbol=symbol or str(item.get("name", "")),
                name=item.get("name") or "",
                side=_side(item.get("side")),
                kind=_kind(item.get("kind")),
                quantity=float(nz.to_number(item.get("quantity")) or 0.0),
                open_price=float(nz.to_number(item.get("open_price")) or 0.0),
                last_price=nz.to_number(item.get("last_price")),
                open_date=nz.parse_date(item.get("open_date")),
                due_date=nz.parse_date(item.get("due_date")),
                accrued_cost=abs(float(nz.to_number(item.get("accrued_cost")) or 0.0)),
                source=source,
            )
        )

    ma = data.get("margin_account")
    if isinstance(ma, dict):
        pf.margin_account = MarginAccount(
            cash_deposit=float(nz.to_number(ma.get("cash_deposit")) or 0.0),
            substitute_value=float(nz.to_number(ma.get("substitute_value")) or 0.0),
            substitute_haircut=float(nz.to_number(ma.get("substitute_haircut")) or 0.8),
        )

    return pf
