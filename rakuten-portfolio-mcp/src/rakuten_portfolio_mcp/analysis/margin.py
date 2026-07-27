"""信用取引の維持率・追証距離・期日管理。

委託保証金維持率 = (受入保証金 + 建玉評価損益) ÷ 建玉代金合計 × 100

「あと何%下げたら追証か」を数値で出すのがこのモジュールの主目的。
維持率は株価に対して線形なので、シミュレーションを回さずに解析的に解ける。
代用有価証券も株価と一緒に目減りする点を式に入れてある（ここを忘れると
追証までの距離を実際より甘く見積もる）。
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from ..config import Config
from ..models import MarginKind, MarginSide, Portfolio


def _components(pf: Portfolio, cfg: Config) -> dict[str, float]:
    """維持率の式に出てくる各項をまとめて計算する。"""
    account = pf.margin_account
    cash = account.cash_deposit if account else 0.0
    substitute = account.substitute_value if account else 0.0
    haircut = account.substitute_haircut if account else cfg.substitute_haircut

    notional = 0.0  # 建玉代金合計（分母）
    signed_mv = 0.0  # Σ 符号付き時価。株価ショックに対する感応度そのもの
    signed_open = 0.0  # Σ 符号付き建代金
    accrued = 0.0
    unrealized = 0.0
    unrealized_loss_only = 0.0

    for p in pf.margin:
        sign = 1.0 if p.side is MarginSide.LONG else -1.0
        notional += p.notional
        signed_open += sign * p.open_price * p.quantity
        accrued += p.accrued_cost
        if p.last_price is not None:
            signed_mv += sign * p.last_price * p.quantity
        else:
            # 現在値不明なら建値のまま＝損益ゼロ扱い。無視するより保守的。
            signed_mv += sign * p.open_price * p.quantity
        pnl = p.unrealized_pnl or 0.0
        unrealized += pnl
        unrealized_loss_only += min(pnl, 0.0)

    return {
        "cash": cash,
        "substitute": substitute,
        "haircut": haircut,
        "collateral": cash + substitute * haircut,
        "notional": notional,
        "signed_mv": signed_mv,
        "signed_open": signed_open,
        "accrued": accrued,
        "unrealized": unrealized,
        "unrealized_loss_only": unrealized_loss_only,
    }


def maintenance_rate(pf: Portfolio, cfg: Config, conservative: bool = False) -> Optional[float]:
    """委託保証金維持率(%)。建玉が無ければ None。"""
    c = _components(pf, cfg)
    if c["notional"] <= 0:
        return None
    pnl = c["unrealized_loss_only"] if conservative else c["unrealized"]
    return (c["collateral"] + pnl) / c["notional"] * 100


def rate_at_shock(pf: Portfolio, cfg: Config, shock_pct: float) -> Optional[float]:
    """建玉と代用有価証券が一律 shock_pct% 動いたときの維持率。"""
    c = _components(pf, cfg)
    if c["notional"] <= 0:
        return None
    x = shock_pct / 100.0
    collateral = c["cash"] + c["substitute"] * c["haircut"] * (1 + x)
    unrealized = (1 + x) * c["signed_mv"] - c["signed_open"] - c["accrued"]
    return (collateral + unrealized) / c["notional"] * 100


def shock_to_threshold(pf: Portfolio, cfg: Config, threshold: float) -> Optional[float]:
    """維持率が threshold% に達する一律株価変動率(%)を解析的に解く。

    維持率は株価変動率 x に対して1次式なので、傾きから逆算できる。
    戻り値が負なら「その%下げると到達」、正なら「その%上げると到達」。
    傾きが0（デルタが完全中立）の場合は到達しないので None。
    """
    c = _components(pf, cfg)
    if c["notional"] <= 0:
        return None

    rate0 = (c["collateral"] + c["unrealized"]) / c["notional"] * 100
    slope = (c["substitute"] * c["haircut"] + c["signed_mv"]) / c["notional"] * 100
    if abs(slope) < 1e-9:
        return None
    return (threshold - rate0) / slope * 100


def additional_deposit_needed(pf: Portfolio, cfg: Config) -> float:
    """いま追証を解消するのに必要な追加入金額。余裕があれば0。"""
    c = _components(pf, cfg)
    if c["notional"] <= 0:
        return 0.0
    required = cfg.maintenance_threshold / 100 * c["notional"]
    return max(0.0, required - (c["collateral"] + c["unrealized"]))


def new_position_capacity(pf: Portfolio, cfg: Config) -> float:
    """新規建余力の概算。委託保証金率 initial_margin_rate% で計算。"""
    c = _components(pf, cfg)
    equity = c["collateral"] + c["unrealized"]
    if equity < cfg.min_deposit:
        return 0.0
    rate = cfg.initial_margin_rate / 100
    capacity = equity / rate - c["notional"]
    return max(0.0, capacity)


def expiring_positions(
    pf: Portfolio, within_days: int = 30, today: Optional[dt.date] = None
) -> list[dict[str, Any]]:
    """返済期限が近い建玉。制度信用は建日から6ヶ月で自動補完済み。"""
    today = today or dt.date.today()
    out = []
    for p in pf.margin:
        days = p.days_to_due(today)
        if days is None or days > within_days:
            continue
        out.append(
            {
                **p.to_dict(today),
                "urgency": "期限切れ" if days < 0 else ("要対応" if days <= 7 else "注意"),
            }
        )
    return sorted(out, key=lambda d: d["days_to_due"])


def summarize(pf: Portfolio, cfg: Config, today: Optional[dt.date] = None) -> dict[str, Any]:
    c = _components(pf, cfg)
    if c["notional"] <= 0:
        return {
            "has_margin_positions": False,
            "message": "信用建玉なし。",
        }

    rate = maintenance_rate(pf, cfg)
    rate_conservative = maintenance_rate(pf, cfg, conservative=True)
    to_call = shock_to_threshold(pf, cfg, cfg.maintenance_threshold)
    to_warn = shock_to_threshold(pf, cfg, cfg.warning_threshold)

    if pf.margin_account is None:
        note = (
            "保証金情報が未入力なので維持率は計算できていない。"
            "data/portfolio.yaml の margin_account に保証金現金と代用有価証券評価額を入れてほしい。"
        )
    else:
        note = None

    long_notional = sum(p.notional for p in pf.margin if p.side is MarginSide.LONG)
    short_notional = sum(p.notional for p in pf.margin if p.side is MarginSide.SHORT)

    return {
        "has_margin_positions": True,
        "maintenance_rate_pct": _r(rate, 2),
        "maintenance_rate_conservative_pct": _r(rate_conservative, 2),
        "threshold_pct": cfg.maintenance_threshold,
        "warning_threshold_pct": cfg.warning_threshold,
        "status": _status(rate, cfg),
        "collateral": _r(c["collateral"]),
        "cash_deposit": _r(c["cash"]),
        "substitute_value": _r(c["substitute"]),
        "substitute_haircut": c["haircut"],
        "total_notional": _r(c["notional"]),
        "long_notional": _r(long_notional),
        "short_notional": _r(short_notional),
        "net_direction": "買い偏重" if long_notional > short_notional * 1.2 else (
            "売り偏重" if short_notional > long_notional * 1.2 else "中立寄り"
        ),
        "unrealized_pnl": _r(c["unrealized"]),
        "accrued_cost": _r(c["accrued"]),
        "leverage_vs_nav": _r(c["notional"] / pf.net_asset_value, 2)
        if pf.net_asset_value > 0
        else None,
        "shock_to_margin_call_pct": _r(to_call, 2),
        "shock_to_warning_pct": _r(to_warn, 2),
        # 買建と売建が相殺していると、株価がいくら動いても維持率が閾値に届かないことがある。
        # その場合に -102% のような非現実的な数字を額面通り読まれないよう明示する。
        "margin_call_reachable": bool(to_call is not None and abs(to_call) < 100),
        "additional_deposit_needed": _r(additional_deposit_needed(pf, cfg)),
        "new_position_capacity": _r(new_position_capacity(pf, cfg)),
        "expiring_within_30d": expiring_positions(pf, 30, today),
        "short_seido_count": sum(
            1 for p in pf.margin if p.side is MarginSide.SHORT and p.kind is MarginKind.SEIDO
        ),
        "note": note,
    }


def _status(rate: Optional[float], cfg: Config) -> str:
    if rate is None:
        return "不明"
    if rate < cfg.maintenance_threshold:
        return "追証発生水準"
    if rate < cfg.warning_threshold:
        return "警戒"
    if rate < cfg.warning_threshold * 2:
        return "やや余裕"
    return "余裕"


def _r(v: Optional[float], digits: int = 0) -> Optional[float]:
    if v is None:
        return None
    return round(v, digits) if digits else round(v)
