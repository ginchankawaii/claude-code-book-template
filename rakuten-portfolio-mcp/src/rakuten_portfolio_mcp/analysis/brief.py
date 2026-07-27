"""助言用のコンテキストを1発でまとめるレイヤー。

方針: このMCPは「こう売買しろ」という結論を自前で出さない。
数字と機械的に判定できる注意フラグだけを揃えて、解釈と助言はClaude側に任せる。
判定ロジックをサーバー側に埋め込むと、根拠の見えない指示が出る割に
前提の調整が効かなくなるため。
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from ..config import Config
from ..models import MarginKind, MarginSide, Portfolio
from . import concentration, margin, pnl, risk

DISCLAIMER = (
    "これは自分の口座データを整理して眺めるための道具であって、投資助言ではない。"
    "数字は入力したCSV/手入力の正確さに依存する。発注判断は自己責任で。"
)


def flags(pf: Portfolio, cfg: Config, today: Optional[dt.date] = None) -> list[dict[str, str]]:
    """機械的に判定できる注意点だけを列挙する。"""
    today = today or dt.date.today()
    out: list[dict[str, str]] = []

    def add(level: str, topic: str, message: str) -> None:
        out.append({"level": level, "topic": topic, "message": message})

    rate = margin.maintenance_rate(pf, cfg)
    if rate is not None:
        if rate < cfg.maintenance_threshold:
            add("critical", "追証", f"委託保証金維持率が{rate:.1f}%で最低ライン{cfg.maintenance_threshold}%を下回っている。")
        elif rate < cfg.warning_threshold:
            add("warning", "維持率", f"維持率{rate:.1f}%。警戒ライン{cfg.warning_threshold}%割れ。")

        to_call = margin.shock_to_threshold(pf, cfg, cfg.maintenance_threshold)
        if to_call is not None and -15 <= to_call < 0:
            add("warning", "追証距離", f"一律{abs(to_call):.1f}%の下落で追証ラインに到達する。")

    for p in margin.expiring_positions(pf, 14, today):
        add(
            "warning" if p["days_to_due"] >= 0 else "critical",
            "期日",
            f"{p['symbol']} {p['name']} の返済期限まで{p['days_to_due']}日（{p['due_date']}）。",
        )

    conc = concentration.summarize(pf)
    top = conc["top_positions"][0] if conc["top_positions"] else None
    if top and top["weight_pct"] >= 30:
        add("warning", "集中", f"{top['symbol']} {top['name']} が総エクスポージャーの{top['weight_pct']:.1f}%。")
    if conc.get("gross_leverage") and conc["gross_leverage"] >= 2.0:
        add("warning", "レバレッジ", f"総建玉/純資産が{conc['gross_leverage']}倍。")

    for m in pf.margin:
        if m.side is MarginSide.SHORT and m.kind is MarginKind.SEIDO:
            add("info", "逆日歩", f"{m.symbol} {m.name} は制度信用の売建。逆日歩と規制の確認を。")

    if pf.missing_prices:
        add(
            "info",
            "データ",
            f"現在値が取得できていない銘柄が{len(pf.missing_prices)}件（{', '.join(pf.missing_prices[:5])}）。",
        )
    if pf.margin and pf.margin_account is None:
        add("warning", "データ", "信用建玉はあるが保証金情報が未入力。維持率が計算できていない。")

    return out


def build(pf: Portfolio, cfg: Config, today: Optional[dt.date] = None) -> dict[str, Any]:
    today = today or dt.date.today()
    return {
        "generated_at": today.isoformat(),
        "portfolio": pf.to_dict(today),
        "concentration": concentration.summarize(pf),
        "margin": margin.summarize(pf, cfg, today),
        "risk": risk.summarize(pf, cfg),
        "pnl": pnl.summarize(pf, cfg),
        "flags": flags(pf, cfg, today),
        "disclaimer": DISCLAIMER,
    }
