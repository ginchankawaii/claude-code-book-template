"""Multi-signal generator for swing trading entry/exit decisions."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from loguru import logger


@dataclass
class TradeSignal:
    symbol: str
    action: str           # "BUY", "SELL", "HOLD"
    score: float          # 0.0 - 1.0
    reasons: list[str] = field(default_factory=list)
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    ml_prob: float | None = None


class SignalGenerator:
    """
    5つのテクニカルシグナルを組み合わせてエントリー判断。
    設定したスコア閾値以上で BUY シグナルを発生。
    """

    def __init__(self, config: dict):
        self.threshold = config.get("signal_threshold", 4)
        risk_cfg = config.get("risk", {})
        self.sl_atr_mult = risk_cfg.get("stop_loss_atr_multiplier", 2.5)
        self.tp1_pct = risk_cfg.get("take_profit_1_pct", 0.06)
        self.tp2_pct = risk_cfg.get("take_profit_2_pct", 0.10)

    def generate(
        self,
        symbol: str,
        df: pd.DataFrame,
        ml_prob: float | None = None,
    ) -> TradeSignal:
        """最新バーに対してシグナルを生成。"""
        if len(df) < 50:
            return TradeSignal(symbol=symbol, action="HOLD", score=0.0)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        score = 0
        reasons: list[str] = []

        # --- シグナル1: RSI オーバーソルドからの反発 ---
        rsi_now = last.get("rsi", 50)
        rsi_prev = prev.get("rsi", 50)
        if 30 <= rsi_now <= 55 and rsi_prev < 40 and rsi_now > rsi_prev:
            score += 1
            reasons.append(f"RSI反発({rsi_prev:.1f}→{rsi_now:.1f})")

        # --- シグナル2: MACD ゴールデンクロス（直近3日以内）---
        recent = df.tail(3)
        if recent["macd_cross_up"].any():
            score += 1
            reasons.append("MACDクロス(↑)")
        elif last.get("macd", 0) > last.get("macd_signal", 0) and last.get("macd_hist", 0) > 0:
            score += 0.5
            reasons.append("MACD陽転維持")

        # --- シグナル3: 価格が EMA20 を上回っている ---
        close = last["close"]
        ema20 = last.get("ema20", 0)
        if close > ema20 and ema20 > 0:
            score += 1
            reasons.append(f"EMA20超({close:.2f}>{ema20:.2f})")

        # --- シグナル4: 出来高急増（平均の1.3倍以上）---
        vol_ratio = last.get("vol_ratio", 1.0)
        if vol_ratio >= 1.3:
            score += 1
            reasons.append(f"出来高増({vol_ratio:.1f}x)")

        # --- シグナル5: ADX でトレンド強度確認 (ADX > 20) ---
        adx = last.get("adx", 0)
        plus_di = last.get("plus_di", 0)
        minus_di = last.get("minus_di", 0)
        if adx >= 20 and plus_di > minus_di:
            score += 1
            reasons.append(f"ADX={adx:.1f}(強トレンド)")

        # --- ML フィルター ---
        if ml_prob is not None:
            if ml_prob >= 0.60:
                score += 0.5
                reasons.append(f"ML確率={ml_prob:.2f}(高)")
            elif ml_prob < 0.45:
                score -= 1.0
                reasons.append(f"ML確率={ml_prob:.2f}(低→抑制)")

        # --- アクション決定 ---
        atr = last.get("atr", close * 0.02)
        stop_loss = close - self.sl_atr_mult * atr
        tp1 = close * (1 + self.tp1_pct)
        tp2 = close * (1 + self.tp2_pct)

        if score >= self.threshold:
            action = "BUY"
        else:
            action = "HOLD"

        return TradeSignal(
            symbol=symbol,
            action=action,
            score=score,
            reasons=reasons,
            stop_loss=stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            ml_prob=ml_prob,
        )

    def check_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        entry_price: float,
        stop_loss: float,
        trailing_high: float,
        trailing_active: bool,
        trailing_stop_atr_mult: float = 2.0,
        tp1_pct: float = 0.06,
        tp2_pct: float = 0.10,
    ) -> tuple[str, str]:
        """
        保有ポジションの決済判断。
        Returns: (action, reason) action = "HOLD" | "SELL_HALF" | "SELL_ALL"
        """
        last = df.iloc[-1]
        close = last["close"]
        atr = last.get("atr", entry_price * 0.02)

        # ストップロス
        if close <= stop_loss:
            return "SELL_ALL", f"ストップロス({close:.2f}<={stop_loss:.2f})"

        # トレーリングストップ
        if trailing_active:
            trail_stop = trailing_high - trailing_stop_atr_mult * atr
            if close <= trail_stop:
                return "SELL_ALL", f"トレーリングストップ({close:.2f}<={trail_stop:.2f})"

        # テイクプロフィット
        ret = (close - entry_price) / entry_price
        if ret >= tp2_pct:
            return "SELL_ALL", f"TP2到達(+{ret:.1%})"
        if ret >= tp1_pct:
            return "SELL_HALF", f"TP1到達(+{ret:.1%})"

        # MACD デッドクロス（利益保護のため早期撤退）
        if last.get("macd_cross_down", False) and ret > 0.02:
            return "SELL_ALL", "MACDデッドクロス(利益確定)"

        # RSI 過買い
        rsi = last.get("rsi", 50)
        if rsi >= 75:
            return "SELL_HALF", f"RSI過買い({rsi:.1f})"

        return "HOLD", ""
