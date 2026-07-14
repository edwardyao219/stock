from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketTurnState:
    key: str
    label: str
    summary: str
    confirmed_signals: tuple[str, ...]
    pending_signals: tuple[str, ...]
    startup_candidates_allowed: bool
    core_action_allowed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "summary": self.summary,
            "confirmed_signals": list(self.confirmed_signals),
            "pending_signals": list(self.pending_signals),
            "startup_candidates_allowed": self.startup_candidates_allowed,
            "core_action_allowed": self.core_action_allowed,
        }


def classify_market_turn_state(
    *,
    trend_score: float,
    breadth_score: float,
    emotion_score: float,
    liquidity_score: float,
    strong_trend_rate: float,
    up_signal_rate: float,
) -> MarketTurnState:
    signals = {
        "趋势结构止跌": trend_score >= 60.0,
        "特征宽度转暖": breadth_score >= 60.0,
        "特征成交承接": liquidity_score >= 60.0,
        "强势结构扩散": strong_trend_rate >= 20.0 and up_signal_rate >= 12.0,
        "情绪持续改善": emotion_score >= 60.0,
    }
    confirmed = tuple(label for label, value in signals.items() if value)
    pending = tuple(label for label, value in signals.items() if not value)

    if not confirmed and (trend_score <= 50.0 or breadth_score <= 45.0 or emotion_score <= 45.0):
        return MarketTurnState(
            key="defense",
            label="防守",
            summary="宽度、趋势和情绪仍弱，只保留观察与风险控制。",
            confirmed_signals=confirmed,
            pending_signals=pending,
            startup_candidates_allowed=False,
            core_action_allowed=False,
        )
    if len(confirmed) == len(signals):
        return MarketTurnState(
            key="actionable",
            label="可行动",
            summary="五项收盘结构确认同时成立，允许从候选中筛选核心行动。",
            confirmed_signals=confirmed,
            pending_signals=pending,
            startup_candidates_allowed=True,
            core_action_allowed=True,
        )
    if (
        trend_score >= 48.0
        and breadth_score >= 55.0
        and emotion_score >= 50.0
        and liquidity_score >= 50.0
        and strong_trend_rate >= 12.0
        and up_signal_rate >= 6.0
    ):
        return MarketTurnState(
            key="startup_allowed",
            label="允许启动候选",
            summary="修复已有承接，允许启动候选进入观察池，但未满足核心行动的五项结构确认。",
            confirmed_signals=confirmed,
            pending_signals=pending,
            startup_candidates_allowed=True,
            core_action_allowed=False,
        )
    return MarketTurnState(
        key="watch_repair",
        label="观察修复",
        summary="市场有修复迹象，但确认不足，先看承接和板块是否同步。",
        confirmed_signals=confirmed,
        pending_signals=pending,
        startup_candidates_allowed=False,
        core_action_allowed=False,
    )
