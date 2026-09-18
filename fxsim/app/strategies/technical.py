"""Technical strategy: an ensemble of classic indicators producing a score in
[-1, 1]. Each sub-signal votes; the weighted average is the conviction.
"""
from __future__ import annotations

import math

import pandas as pd

from ..models import Signal
from .base import Strategy


class TechnicalStrategy(Strategy):
    name = "technical"

    def generate(self, instrument: str, df: pd.DataFrame) -> Signal:
        if len(df) < 35:
            return Signal.flat("insufficient history")

        last = df.iloc[-1]
        prev = df.iloc[-2]
        components: dict[str, float] = {}

        # 1) Trend: fast vs slow MA, normalised by ATR so it is scale-free.
        atr = last["atr"] if last["atr"] and not math.isnan(last["atr"]) else None
        if atr and atr > 0 and not math.isnan(last["sma_slow"]):
            spread = (last["sma_fast"] - last["sma_slow"]) / atr
            components["ma_trend"] = float(max(-1.0, min(1.0, spread)))

        # 2) MACD histogram sign & momentum.
        if not math.isnan(last["macd_hist"]):
            hist = last["macd_hist"]
            scale = abs(df["macd_hist"].tail(50)).mean() or 1e-9
            components["macd"] = float(max(-1.0, min(1.0, hist / (2 * scale))))

        # 3) RSI mean-reversion: oversold -> long, overbought -> short.
        if not math.isnan(last["rsi"]):
            rsi = last["rsi"]
            components["rsi"] = float(max(-1.0, min(1.0, (50.0 - rsi) / 30.0)))

        # 4) Bollinger position: below lower band -> long, above upper -> short.
        if not math.isnan(last["bb_lower"]) and last["bb_upper"] > last["bb_lower"]:
            width = last["bb_upper"] - last["bb_lower"]
            pos = (last["close"] - last["bb_mid"]) / (width / 2)
            components["bollinger"] = float(max(-1.0, min(1.0, -pos)))

        # 5) Breakout confirmation: close crossing the fast MA with momentum.
        if not math.isnan(last["sma_fast"]):
            crossed_up = prev["close"] <= prev["sma_fast"] and last["close"] > last["sma_fast"]
            crossed_dn = prev["close"] >= prev["sma_fast"] and last["close"] < last["sma_fast"]
            components["breakout"] = 0.6 if crossed_up else (-0.6 if crossed_dn else 0.0)

        if not components:
            return Signal.flat("no indicators ready")

        # Weighted ensemble (trend-following weighted higher than reversion).
        weights = {
            "ma_trend": 1.4,
            "macd": 1.2,
            "rsi": 0.8,
            "bollinger": 0.7,
            "breakout": 1.0,
        }
        total_w = sum(weights[k] for k in components)
        score = sum(components[k] * weights[k] for k in components) / total_w
        score = float(max(-1.0, min(1.0, score)))
        direction = 0
        if score > 0.05:
            direction = 1
        elif score < -0.05:
            direction = -1
        reason = ", ".join(f"{k}={v:+.2f}" for k, v in components.items())
        return Signal(direction=direction, score=score, reason=reason, components=components)
