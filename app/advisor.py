"""Claude API による売買判断（AIアドバイザー）。

価格履歴・テクニカル指標・現在の保有状況・資金を Claude に渡し、
BUY / SELL / HOLD と数量・確信度・根拠を構造化出力させる。
"""
from __future__ import annotations

import json

from . import config, engine, indicators, market
from .database import connect, now_iso

SYSTEM_PROMPT = """\
あなたは仮想資金で運用する日本株のポートフォリオ・マネージャーです。
リアルマネーは一切使いません。提供される価格履歴・テクニカル指標・保有状況・
利用可能な資金にもとづいて、各銘柄について BUY / SELL / HOLD を判断します。

ルール:
- 日本株は単元株(通常100株)単位で売買します。数量は100の倍数で答えてください。
- 1銘柄への過度な集中を避け、資金管理を意識してください。
- BUY の場合、利用可能な資金(available_cash)を超える注文は出さないこと。
- SELL の場合、保有数量(position.quantity)を超える売却は出さないこと。
- HOLD の場合、quantity は 0 にしてください。
- rationale は日本語で、根拠を2〜4文で簡潔に述べてください。
- confidence は 0.0〜1.0 の確信度です。
必ず submit_decision ツールを用いて構造化した結果を返してください。"""

DECISION_TOOL = {
    "name": "submit_decision",
    "description": "売買判断の結果を構造化して提出する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["BUY", "SELL", "HOLD"],
                "description": "売買アクション",
            },
            "quantity": {
                "type": "integer",
                "description": "売買する株数(100の倍数, HOLDの場合は0)",
            },
            "confidence": {
                "type": "number",
                "description": "確信度 0.0〜1.0",
            },
            "rationale": {
                "type": "string",
                "description": "判断の根拠(日本語, 2〜4文)",
            },
        },
        "required": ["action", "quantity", "confidence", "rationale"],
    },
}


class AdvisorError(Exception):
    pass


def _build_context(code: str) -> dict:
    history = market.get_history(code, days=120)
    if not history:
        raise AdvisorError(f"価格データを取得できませんでした: {code}")
    stats = indicators.summarize(history)
    quote = market.get_quote(code)

    conn = connect()
    try:
        pos = conn.execute(
            "SELECT quantity, avg_cost FROM holdings WHERE code = ?", (code,)
        ).fetchone()
    finally:
        conn.close()

    recent = [
        {"date": h["date"], "close": h["close"]} for h in history[-30:]
    ]
    return {
        "code": code,
        "name": market.resolve_name(code),
        "available_cash": round(engine.get_cash(), 2),
        "trade_unit": config.TRADE_UNIT,
        "current_price": quote["price"],
        "indicators": stats,
        "position": {
            "quantity": pos["quantity"] if pos else 0,
            "avg_cost": round(pos["avg_cost"], 2) if pos else None,
        },
        "recent_closes": recent,
    }


def decide(code: str) -> dict:
    """Claude に1銘柄の売買判断をさせ、結果を返す（執行はしない）。"""
    if not config.ANTHROPIC_API_KEY:
        raise AdvisorError(
            "ANTHROPIC_API_KEY が設定されていません。.env または環境変数に設定してください。"
        )
    try:
        import anthropic
    except ImportError as exc:
        raise AdvisorError(
            "anthropic パッケージがインストールされていません: pip install anthropic"
        ) from exc

    context = _build_context(code)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=config.ADVISOR_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[DECISION_TOOL],
        tool_choice={"type": "tool", "name": "submit_decision"},
        messages=[
            {
                "role": "user",
                "content": (
                    "次の銘柄について売買判断をしてください。\n\n"
                    + json.dumps(context, ensure_ascii=False, indent=2)
                ),
            }
        ],
    )

    decision = None
    for block in message.content:
        if block.type == "tool_use" and block.name == "submit_decision":
            decision = block.input
            break
    if decision is None:
        raise AdvisorError("Claude から構造化された判断を取得できませんでした。")

    result = {
        "code": code,
        "name": context["name"],
        "action": decision["action"],
        "quantity": int(decision.get("quantity", 0) or 0),
        "confidence": float(decision.get("confidence", 0) or 0),
        "rationale": decision.get("rationale", ""),
        "current_price": context["current_price"],
        "model": config.ADVISOR_MODEL,
        "context": context,
    }
    return result


def _record_decision(d: dict, executed: bool) -> int:
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO decisions (ts, code, name, action, quantity, "
            "confidence, rationale, executed, model) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                now_iso(),
                d["code"],
                d["name"],
                d["action"],
                d["quantity"],
                d["confidence"],
                d["rationale"],
                1 if executed else 0,
                d["model"],
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def decide_and_maybe_execute(code: str, auto_execute: bool = False) -> dict:
    """判断を行い、auto_execute なら売買も執行する。"""
    d = decide(code)
    executed = False
    execution = None
    error = None

    if auto_execute and d["action"] in ("BUY", "SELL") and d["quantity"] > 0:
        try:
            if d["action"] == "BUY":
                execution = engine.buy(
                    code,
                    d["quantity"],
                    price=d["current_price"],
                    decided_by="claude",
                    reason=d["rationale"],
                )
            else:
                execution = engine.sell(
                    code,
                    d["quantity"],
                    price=d["current_price"],
                    decided_by="claude",
                    reason=d["rationale"],
                )
            executed = True
        except engine.TradeError as exc:
            error = str(exc)

    decision_id = _record_decision(d, executed)
    d.pop("context", None)  # レスポンスを軽くする
    d.update(
        {
            "decision_id": decision_id,
            "executed": executed,
            "execution": execution,
            "error": error,
            "auto_execute": auto_execute,
        }
    )
    return d


def list_decisions(limit: int = 100) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
