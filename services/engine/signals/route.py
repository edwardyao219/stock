from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _float(context: dict[str, Any], key: str, default: float = 50.0) -> float:
    value = context.get(key)
    return float(value) if value is not None else default


def _score_between(value: float | None, low: float, high: float) -> float:
    if value is None or high == low:
        return 50.0
    score = (value - low) / (high - low) * 100
    return max(0.0, min(100.0, score))


def _score_peak(value: float | None, ideal: float, tolerance: float) -> float:
    if value is None or tolerance <= 0:
        return 50.0
    distance = abs(value - ideal) / tolerance
    return max(0.0, min(100.0, (1 - distance) * 100))


@dataclass(frozen=True)
class SignalRoute:
    route_score: float
    trend_score: float
    participation_score: float
    risk_score: float
    momentum_score: float
    route_label: str
    route_reason: str
    route_components: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_signal_route(context: dict[str, Any]) -> SignalRoute:
    stored_route_score = context.get("route_score")
    stored_route_label = context.get("route_label")
    stored_route_reason = context.get("route_reason")
    stored_route_components = context.get("route_components")
    if (
        stored_route_score is not None
        and stored_route_label is not None
        and stored_route_reason is not None
    ):
        route_components = stored_route_components if isinstance(stored_route_components, dict) else {}
        trend_score = _float(context, "route_trend_score", _float(context, "trend_score", 50.0))
        participation_score = _float(
            context,
            "route_participation_score",
            _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0)),
        )
        risk_score = _float(context, "route_risk_score", _float(context, "risk_score", 50.0))
        momentum_score = _float(context, "route_momentum_score", 50.0)
        if not route_components:
            route_components = {
                "trend_stack": trend_score,
                "participation_stack": participation_score,
                "context_stack": momentum_score,
                "risk_stack": risk_score,
            }
        return SignalRoute(
            route_score=float(stored_route_score),
            trend_score=trend_score,
            participation_score=participation_score,
            risk_score=risk_score,
            momentum_score=momentum_score,
            route_label=str(stored_route_label),
            route_reason=str(stored_route_reason),
            route_components={k: float(v) for k, v in route_components.items() if v is not None},
        )

    trend_score = _float(context, "trend_score", 50.0)
    relative_strength = _float(context, "relative_strength_score", 50.0)
    sector_strength = _float(context, "sector_strength_score", 50.0)
    amount_percentile = _float(context, "amount_percentile_60d", 50.0)
    amount_ratio_5d = context.get("amount_ratio_5d")
    recent_amount_ratio_20d = context.get("recent_amount_ratio_20d")
    close_position_in_range = context.get("close_position_in_range")
    distance_to_ma20 = context.get("distance_to_ma20")
    return_20d = context.get("return_20d")
    return_5d = context.get("return_5d")
    risk_score = _float(context, "risk_score", 50.0)
    overheat_score = _float(context, "overheat_score", 50.0)
    volume_trap_risk_score = _float(context, "volume_trap_risk_score", 50.0)
    volume_confirmation_score = _float(
        context,
        "volume_confirmation_score",
        _float(context, "volume_score", 50.0),
    )
    trend_quality_score = _float(context, "trend_quality_score", 50.0)
    ma_alignment_score = _float(context, "ma_alignment_score", 50.0)
    atr_pct = context.get("atr_pct")

    trend_stack = (
        trend_score * 0.34
        + _score_between(relative_strength, 42.0, 82.0) * 0.22
        + _score_between(sector_strength, 42.0, 82.0) * 0.16
        + trend_quality_score * 0.16
        + ma_alignment_score * 0.12
    )
    participation_stack = (
        amount_percentile * 0.26
        + _score_peak(amount_ratio_5d, 1.10, 0.60) * 0.16
        + _score_peak(recent_amount_ratio_20d, 1.00, 0.60) * 0.14
        + volume_confirmation_score * 0.30
        + _score_between(close_position_in_range, 0.30, 0.85) * 0.14
    )
    context_stack = (
        _score_between(distance_to_ma20, -0.08, 0.18) * 0.30
        + _score_between(return_20d, -0.06, 0.32) * 0.30
        + _score_between(return_5d, -0.08, 0.20) * 0.20
        + _score_between(atr_pct, 0.01, 0.10) * 0.20
    )
    risk_stack = max(
        0.0,
        min(
            100.0,
            risk_score * 0.32
            + overheat_score * 0.24
            + volume_trap_risk_score * 0.24
            + (100.0 - _score_between(distance_to_ma20, -0.02, 0.22)) * 0.10
            + (100.0 - _score_between(return_20d, -0.05, 0.38)) * 0.10,
        ),
    )

    route_score = max(
        0.0,
        min(
            100.0,
            trend_stack * 0.36
            + participation_stack * 0.26
            + context_stack * 0.18
            + (100.0 - risk_stack) * 0.20,
        ),
    )

    if route_score >= 76:
        route_label = "强路线"
    elif route_score >= 65:
        route_label = "可跟踪"
    elif route_score >= 45:
        route_label = "观察路线"
    else:
        route_label = "弱路线"

    if trend_stack >= 74 and participation_stack >= 55:
        route_reason = "趋势和资金都在同一方向"
    elif trend_stack >= 68 and risk_stack <= 55:
        route_reason = "趋势结构还在，风险没有明显失控"
    elif participation_stack >= 62:
        route_reason = "资金参与顺，但还要看趋势是否跟上"
    else:
        route_reason = "只保留基础观察，不把噪音当信号"

    return SignalRoute(
        route_score=round(route_score, 4),
        trend_score=round(trend_stack, 4),
        participation_score=round(participation_stack, 4),
        risk_score=round(risk_stack, 4),
        momentum_score=round(context_stack, 4),
        route_label=route_label,
        route_reason=route_reason,
        route_components={
            "trend_stack": round(trend_stack, 4),
            "participation_stack": round(participation_stack, 4),
            "context_stack": round(context_stack, 4),
            "risk_stack": round(risk_stack, 4),
        },
    )
