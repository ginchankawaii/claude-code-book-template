"""ポートフォリオの正規化データモデル。

楽天証券のCSV・手入力YAML・MarketSpeed II RSSの出力は形がバラバラなので、
ローダーは必ずここで定義した型に落としてから分析側に渡す。
分析コードがデータ元を意識しなくて済むようにするのが目的。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# 制度信用の返済期限（建日から6ヶ月）
SEIDO_TERM_DAYS = 183


class AssetClass(str, Enum):
    JP_STOCK = "jp_stock"
    US_STOCK = "us_stock"
    FUND = "fund"
    BOND = "bond"
    CASH = "cash"
    OTHER = "other"


class MarginSide(str, Enum):
    LONG = "買建"
    SHORT = "売建"


class MarginKind(str, Enum):
    SEIDO = "制度"
    IPPAN = "一般"
    DAYTRADE = "いちにち"
    UNKNOWN = "不明"


# 口座区分は非課税判定に使うだけなので、細かい枠の違いは潰さず素の文字列で持つ。
NISA_MARKERS = ("NISA", "ＮＩＳＡ", "つみたて", "成長投資枠", "非課税")


def is_nisa(account: str) -> bool:
    return any(m in (account or "") for m in NISA_MARKERS)


@dataclass
class SpotPosition:
    """現物ポジション（国内株・米国株・投資信託を共通で扱う）。"""

    symbol: str
    name: str = ""
    asset_class: AssetClass = AssetClass.JP_STOCK
    account: str = "不明"
    quantity: float = 0.0
    avg_cost: float = 0.0
    last_price: Optional[float] = None
    currency: str = "JPY"
    # 投資信託は「10,000口あたりの基準価額」なので評価額の計算に倍率が要る
    price_multiplier: float = 1.0
    price_asof: Optional[str] = None
    source: str = ""

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost * self.price_multiplier

    @property
    def market_value(self) -> Optional[float]:
        if self.last_price is None:
            return None
        return self.quantity * self.last_price * self.price_multiplier

    @property
    def unrealized_pnl(self) -> Optional[float]:
        mv = self.market_value
        if mv is None:
            return None
        return mv - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> Optional[float]:
        pnl = self.unrealized_pnl
        if pnl is None or self.cost_basis == 0:
            return None
        return pnl / abs(self.cost_basis) * 100

    @property
    def is_nisa(self) -> bool:
        return is_nisa(self.account)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "asset_class": self.asset_class.value,
            "account": self.account,
            "is_nisa": self.is_nisa,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "last_price": self.last_price,
            "currency": self.currency,
            "cost_basis": _r(self.cost_basis),
            "market_value": _r(self.market_value),
            "unrealized_pnl": _r(self.unrealized_pnl),
            "unrealized_pnl_pct": _r(self.unrealized_pnl_pct, 2),
            "price_asof": self.price_asof,
            "source": self.source,
        }


@dataclass
class MarginPosition:
    """信用建玉。売建は損益の符号が反転するのでここで吸収する。"""

    symbol: str
    name: str = ""
    side: MarginSide = MarginSide.LONG
    kind: MarginKind = MarginKind.UNKNOWN
    quantity: float = 0.0
    open_price: float = 0.0
    last_price: Optional[float] = None
    open_date: Optional[dt.date] = None
    due_date: Optional[dt.date] = None
    # 金利・貸株料・逆日歩などの累計。CSVに載っていれば取り込む
    accrued_cost: float = 0.0
    currency: str = "JPY"
    source: str = ""

    def __post_init__(self) -> None:
        # 制度信用で返済期限が空欄なら建日から6ヶ月で補完する
        if self.due_date is None and self.open_date and self.kind is MarginKind.SEIDO:
            self.due_date = self.open_date + dt.timedelta(days=SEIDO_TERM_DAYS)

    @property
    def notional(self) -> float:
        """建代金（保証金維持率の分母）。"""
        return self.quantity * self.open_price

    @property
    def market_value(self) -> Optional[float]:
        if self.last_price is None:
            return None
        return self.quantity * self.last_price

    @property
    def unrealized_pnl(self) -> Optional[float]:
        if self.last_price is None:
            return None
        gross = (self.last_price - self.open_price) * self.quantity
        if self.side is MarginSide.SHORT:
            gross = -gross
        return gross - self.accrued_cost

    @property
    def unrealized_pnl_pct(self) -> Optional[float]:
        pnl = self.unrealized_pnl
        if pnl is None or self.notional == 0:
            return None
        return pnl / self.notional * 100

    @property
    def signed_exposure(self) -> Optional[float]:
        """買建は+、売建は-の時価エクスポージャー。"""
        mv = self.market_value
        if mv is None:
            return None
        return mv if self.side is MarginSide.LONG else -mv

    def days_to_due(self, today: Optional[dt.date] = None) -> Optional[int]:
        if self.due_date is None:
            return None
        return (self.due_date - (today or dt.date.today())).days

    def to_dict(self, today: Optional[dt.date] = None) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "side": self.side.value,
            "kind": self.kind.value,
            "quantity": self.quantity,
            "open_price": self.open_price,
            "last_price": self.last_price,
            "notional": _r(self.notional),
            "market_value": _r(self.market_value),
            "unrealized_pnl": _r(self.unrealized_pnl),
            "unrealized_pnl_pct": _r(self.unrealized_pnl_pct, 2),
            "accrued_cost": _r(self.accrued_cost),
            "open_date": self.open_date.isoformat() if self.open_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "days_to_due": self.days_to_due(today),
            "source": self.source,
        }


@dataclass
class MarginAccount:
    """信用口座の保証金。CSVに載らないことが多いので手入力YAMLで補完する前提。"""

    cash_deposit: float = 0.0
    substitute_value: float = 0.0  # 代用有価証券の時価（掛目適用前）
    substitute_haircut: float = 0.8  # 楽天証券の代用掛目は原則80%

    @property
    def collateral(self) -> float:
        return self.cash_deposit + self.substitute_value * self.substitute_haircut

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash_deposit": _r(self.cash_deposit),
            "substitute_value": _r(self.substitute_value),
            "substitute_haircut": self.substitute_haircut,
            "collateral": _r(self.collateral),
        }


@dataclass
class Portfolio:
    asof: Optional[str] = None
    spot: list[SpotPosition] = field(default_factory=list)
    margin: list[MarginPosition] = field(default_factory=list)
    cash: float = 0.0
    margin_account: Optional[MarginAccount] = None
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "Portfolio") -> "Portfolio":
        """複数ファイルの読み込み結果を1つに束ねる。後勝ちではなく積み上げ。"""
        self.spot.extend(other.spot)
        self.margin.extend(other.margin)
        self.cash += other.cash
        if other.margin_account is not None:
            self.margin_account = other.margin_account
        if other.asof and (self.asof is None or other.asof > self.asof):
            self.asof = other.asof
        self.sources.extend(other.sources)
        self.warnings.extend(other.warnings)
        return self

    @property
    def spot_market_value(self) -> float:
        return sum(p.market_value or p.cost_basis for p in self.spot)

    @property
    def margin_unrealized(self) -> float:
        return sum(p.unrealized_pnl or 0.0 for p in self.margin)

    @property
    def net_asset_value(self) -> float:
        """純資産＝現金＋現物評価額＋信用の評価損益。"""
        return self.cash + self.spot_market_value + self.margin_unrealized

    @property
    def missing_prices(self) -> list[str]:
        out = [p.symbol for p in self.spot if p.last_price is None]
        out += [p.symbol for p in self.margin if p.last_price is None]
        return sorted(set(out))

    def to_dict(self, today: Optional[dt.date] = None) -> dict[str, Any]:
        return {
            "asof": self.asof,
            "net_asset_value": _r(self.net_asset_value),
            "cash": _r(self.cash),
            "spot_market_value": _r(self.spot_market_value),
            "margin_unrealized": _r(self.margin_unrealized),
            "spot": [p.to_dict() for p in self.spot],
            "margin": [p.to_dict(today) for p in self.margin],
            "margin_account": self.margin_account.to_dict() if self.margin_account else None,
            "sources": self.sources,
            "warnings": self.warnings,
            "missing_prices": self.missing_prices,
        }


def _r(v: Optional[float], digits: int = 0) -> Optional[float]:
    """JSONに出す前の丸め。Noneはそのまま通す。"""
    if v is None:
        return None
    return round(v, digits) if digits else round(v)
