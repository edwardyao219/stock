from __future__ import annotations

from typing import Any

PERSISTENT_MAINLINE_TRAILING_MULTIPLIER = 1.50


def _feature_float(features: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = features.get(key)
    return float(value) if value is not None else default


def is_persistent_mainline(features: dict[str, Any]) -> bool:
    volume_confirmation = _feature_float(features, "volume_confirmation_score", 50.0)
    price_volume_trend = _feature_float(features, "price_volume_trend_score", 50.0)
    return (
        _feature_float(features, "sector_trend_continuity_score", 50.0) >= 72.0
        and _feature_float(features, "sector_breadth_score", 50.0) >= 60.0
        and _feature_float(features, "sector_trend_resilience_score", 50.0) >= 64.0
        and (volume_confirmation >= 66.0 or price_volume_trend >= 70.0)
        and _feature_float(features, "overheat_score", 50.0) <= 60.0
        and _feature_float(features, "volume_trap_risk_score", 50.0) <= 55.0
    )


def guard_parameters_for_features(
    features: dict[str, Any],
    *,
    stop_loss_pct: float,
    trailing_drawdown_pct: float,
) -> tuple[float, float]:
    if not is_persistent_mainline(features):
        return stop_loss_pct, trailing_drawdown_pct
    return (
        stop_loss_pct,
        trailing_drawdown_pct * PERSISTENT_MAINLINE_TRAILING_MULTIPLIER,
    )
