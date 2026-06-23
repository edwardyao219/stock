from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MarketRegime = Literal["strong_trend", "weak_trend", "range", "panic", "rebound", "unknown"]


@dataclass(frozen=True)
class MarketRegimeSnapshot:
    trade_date: str
    regime: MarketRegime
    trend_score: float
    breadth_score: float
    emotion_score: float
    volatility_score: float
    risk_level: str


def classify_market_regime(
    trend_score: float,
    breadth_score: float,
    emotion_score: float,
    volatility_score: float,
) -> MarketRegime:
    if emotion_score <= 25 and breadth_score <= 30:
        return "panic"
    if trend_score >= 70 and breadth_score >= 60:
        return "strong_trend"
    if trend_score <= 35 and breadth_score <= 45:
        return "weak_trend"
    if trend_score >= 55 and emotion_score >= 50:
        return "rebound"
    return "range"
