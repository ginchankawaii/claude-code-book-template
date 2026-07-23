"""AI stock picker — Opus scans candidates, weighs 決算/news, picks margin longs.

Japanese stocks, 信用買い (margin long) ONLY, per the chosen design. Opus is given
a candidate pool (liquid names from kabu ranking + any watchlist) plus the
currently-held positions and the account, web-searches each name's earnings
(決算 actual vs 予想), guidance, news and the macro backdrop, and returns a
target portfolio: which to BUY / HOLD / CLOSE, with conviction (-> size), reason,
factors and a hold-plan — all in Japanese.

Falls back to "no decisions" (hold everything) on any API/parse error.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional

from .config import settings as default_settings


@dataclass
class StockCall:
    symbol: str
    action: str          # "buy" | "hold" | "close" | "skip"
    conviction: float    # 0..1
    reason: str
    factors: list = field(default_factory=list)
    plan: str = ""


@dataclass
class StockDecision:
    calls: list           # list[StockCall]
    note: str = ""        # overall macro note
    raw: str = ""
    ok: bool = True

    @classmethod
    def empty(cls, why: str) -> "StockDecision":
        return cls([], why, "", ok=False)


PROMPT = """\
あなたは規律重視・リスク第一の日本株ポートフォリオ・マネージャーです。信用買い
（margin long）のみ。ショートはしません。最大{max_positions}銘柄まで保有します。

web検索を使い、候補銘柄と保有銘柄について次を調べてください：
  - 直近の決算（実績 vs 予想、ガイダンス上方/下方修正）、適時開示、材料ニュース、
  - 業績トレンド・セクターの地合い・需給（信用残・出来高）、
  - 日本市場/マクロ（日銀・為替・米株）の追い風/逆風、
  - 直近で控える決算・イベント。

その上で各銘柄に判断を出してください：
  - action: "buy"(新規買い) / "hold"(継続保有) / "close"(手仕舞い) / "skip"(触らない),
  - conviction: 0.0-1.0（強さ。サイズに反映）,
  - reason: 1-2文・日本語・具体的な数字を引用（例「○○の今期営業益は予想比+15%上振れ」）,
  - factors: 2-4個の短い日本語の根拠（実数つき）,
  - plan: 保有方針1文（いつ/どの条件で手仕舞うか）。

原則：
  - 良いトレードを取るより悪いトレードを避ける。確信が無ければ "skip"。
  - 決算"直前"の新規買いは避ける（結果を見てから）。
  - 既存保有は理由なく動かさない（無駄な売買＝コスト負けを避ける）。
  - 買える銘柄が無ければ全て "skip"/"hold" で構いません。

コンテキスト(JSON):
{context}

JSONオブジェクトのみで返答：
{{"note": "...(日本語の全体観)", "decisions": [
  {{"symbol": "7203", "action": "buy", "conviction": 0.5, "reason": "...(日本語)",
    "factors": ["...", "..."], "plan": "...(日本語)"}}
]}}
"""


class AIStockTrader:
    def __init__(self, model: Optional[str] = None, max_positions: int = 3,
                 max_web_uses: int = 8) -> None:
        self.model = model or default_settings.decision_model  # claude-opus-4-8
        self.max_positions = max_positions
        self.max_web_uses = max_web_uses

    def decide(self, context: dict) -> StockDecision:
        try:
            import anthropic
        except ImportError:
            return StockDecision.empty("anthropic SDK not installed")
        if not default_settings.anthropic_api_key:
            return StockDecision.empty("ANTHROPIC_API_KEY not set")
        try:
            client = anthropic.Anthropic(api_key=default_settings.anthropic_api_key)
            resp = client.messages.create(
                model=self.model, max_tokens=3000,
                tools=[{"type": "web_search_20250305", "name": "web_search",
                        "max_uses": self.max_web_uses}],
                messages=[{"role": "user", "content": PROMPT.format(
                    max_positions=self.max_positions,
                    context=json.dumps(context, ensure_ascii=False, default=str))}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return _parse(text)
        except Exception as exc:  # pragma: no cover - network/SDK
            return StockDecision.empty(f"AI error: {exc}")


def _parse(text: str) -> StockDecision:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return StockDecision.empty("unparseable model output")
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return StockDecision.empty("invalid json from model")
    calls = []
    for d in obj.get("decisions", []) or []:
        action = str(d.get("action", "skip")).lower()
        if action not in ("buy", "hold", "close", "skip"):
            action = "skip"
        try:
            conv = max(0.0, min(1.0, float(d.get("conviction", 0.0))))
        except (TypeError, ValueError):
            conv = 0.0
        facs = d.get("factors") or []
        if not isinstance(facs, list):
            facs = [str(facs)]
        calls.append(StockCall(symbol=str(d.get("symbol", "")).strip(), action=action,
                               conviction=conv, reason=str(d.get("reason", "")),
                               factors=[str(f) for f in facs], plan=str(d.get("plan", ""))))
    return StockDecision(calls=calls, note=str(obj.get("note", "")), raw=text)


class RuleStockTrader:
    """Deterministic, offline stand-in for Opus — used by the --sim demo when no
    ANTHROPIC_API_KEY is set. Buys the top-ranked candidates (momentum proxy) up
    to max_positions, holds those still on top, closes the rest. Same .decide()
    interface as AIStockTrader, so cycle() is unchanged.
    """

    model = "sim-rule"

    def __init__(self, max_positions: int = 3) -> None:
        self.max_positions = max_positions

    def decide(self, context: dict) -> StockDecision:
        held = {h["symbol"] for h in context.get("account", {}).get("held", [])}
        cands = [c["symbol"] for c in context.get("candidates", [])]
        top = cands[: self.max_positions]
        calls: list = []
        convs = [0.7, 0.6, 0.5, 0.4]
        slots = self.max_positions - len(held)
        picked = 0
        for s in cands:
            if slots <= 0:
                break
            if s in held:
                continue
            calls.append(StockCall(
                symbol=s, action="buy", conviction=convs[min(picked, len(convs) - 1)],
                reason=f"シミュ: モメンタム上位（ランキング{picked + 1}位）",
                factors=["オフライン・シミュレーション選定（実データ・実決算ではない）"],
                plan="ランキング圏外に後退したら手仕舞い"))
            picked += 1
            slots -= 1
        for s in held:
            if s in top:
                calls.append(StockCall(s, "hold", 0.5, "シミュ: 上位維持→継続保有", [], ""))
            else:
                calls.append(StockCall(s, "close", 0.0, "シミュ: ランキング圏外→手仕舞い", [], ""))
        return StockDecision(calls=calls, note=(
            "オフライン・シミュレーション（ルールベース選定）。実運用ではOpusが"
            "各銘柄の決算・ニュース・マクロをweb検索して選定します。"))


def size_shares(conviction: float, balance: float, price: float, unit: int,
                max_risk: float, brake: float = 1.0, stop_pct: float = 0.08,
                max_name_notional: Optional[float] = None,
                margin_remaining: Optional[float] = None) -> int:
    """Convert conviction -> share quantity (multiple of the trading unit).

    risk_yen = balance * max_risk * conviction * brake
    shares   = risk_yen / (price * stop_pct)               # risk-based on an 8% stop
    then floor to the trading unit and cap notional by per-name and margin limits.
    """
    if conviction <= 0 or price <= 0 or balance <= 0:
        return 0
    risk_yen = balance * max_risk * max(0.0, min(1.0, conviction)) * max(0.0, min(1.0, brake))
    raw_shares = risk_yen / (price * stop_pct)
    notional_cap = float("inf")
    if max_name_notional is not None:
        notional_cap = min(notional_cap, max_name_notional)
    if margin_remaining is not None:
        notional_cap = min(notional_cap, max(0.0, margin_remaining))
    raw_shares = min(raw_shares, notional_cap / price)
    units = int(math.floor(raw_shares / unit))
    return units * unit
