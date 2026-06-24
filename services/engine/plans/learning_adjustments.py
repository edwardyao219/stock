from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from services.engine.risk.trade_parameters import TradeParameters
from services.shared.models import ParameterRecommendation

PAPER_LEARNING_SOURCES = {"paper_learning_review"}
DEFAULT_PAPER_LEARNING_STATUSES = ("pending", "approved", "applied")
PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


def _float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    return float(value)


def _bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _round_price(value: float) -> float:
    return round(value, 4)


def _recommendation_rank(item: ParameterRecommendation) -> tuple[int, Any, int]:
    return (
        PRIORITY_RANK.get(item.priority, 0),
        item.report_date,
        item.id,
    )


def load_plan_learning_adjustments(
    db: Session,
    *,
    rule_id: str,
    sector_code: str | None = None,
    signal_tags: list[str] | None = None,
    statuses: tuple[str, ...] = DEFAULT_PAPER_LEARNING_STATUSES,
    limit: int = 20,
) -> list[ParameterRecommendation]:
    scope_filters = [
        (ParameterRecommendation.scope_type == "rule")
        & (ParameterRecommendation.scope_value == rule_id),
    ]
    if sector_code:
        scope_filters.append(
            (ParameterRecommendation.scope_type == "sector")
            & (ParameterRecommendation.scope_value == sector_code)
        )
    for tag in signal_tags or []:
        scope_filters.append(
            (ParameterRecommendation.scope_type == "signal")
            & (ParameterRecommendation.scope_value == tag)
        )

    stmt = (
        select(ParameterRecommendation)
        .where(ParameterRecommendation.source_report_type.in_(PAPER_LEARNING_SOURCES))
        .where(ParameterRecommendation.status.in_(statuses))
        .where(or_(*scope_filters))
        .order_by(desc(ParameterRecommendation.report_date), desc(ParameterRecommendation.id))
        .limit(limit)
    )
    rows = list(db.execute(stmt).scalars())
    return sorted(rows, key=_recommendation_rank, reverse=True)


def _adjust_stop(params: TradeParameters, multiplier: float) -> dict[str, float]:
    risk = max(params.entry_trigger_price - params.initial_stop, 0.01)
    adjusted_risk = risk * _bounded(multiplier, 0.5, 1.5)
    stop = min(params.entry_trigger_price - 0.01, params.entry_trigger_price - adjusted_risk)
    take_profit_1 = params.entry_trigger_price + adjusted_risk * (
        (params.take_profit_1 - params.entry_trigger_price) / risk
    )
    take_profit_2 = params.entry_trigger_price + adjusted_risk * (
        (params.take_profit_2 - params.entry_trigger_price) / risk
    )
    return {
        "initial_stop": _round_price(stop),
        "risk_per_share": _round_price(adjusted_risk),
        "take_profit_1": _round_price(take_profit_1),
        "take_profit_2": _round_price(take_profit_2),
    }


def _adjust_take_profit(params: TradeParameters, proposed: dict[str, Any]) -> dict[str, float]:
    risk = max(params.risk_per_share, 0.01)
    take_profit_1 = params.take_profit_1
    take_profit_2 = params.take_profit_2
    if proposed.get("take_profit_1_r_multiplier") is not None:
        multiplier = _bounded(float(proposed["take_profit_1_r_multiplier"]), 0.5, 1.8)
        current_r = (params.take_profit_1 - params.entry_trigger_price) / risk
        take_profit_1 = params.entry_trigger_price + risk * current_r * multiplier
    if proposed.get("take_profit_2_r_multiplier") is not None:
        multiplier = _bounded(float(proposed["take_profit_2_r_multiplier"]), 0.5, 2.0)
        current_r = (params.take_profit_2 - params.entry_trigger_price) / risk
        take_profit_2 = params.entry_trigger_price + risk * current_r * multiplier
    return {
        "take_profit_1": _round_price(take_profit_1),
        "take_profit_2": _round_price(take_profit_2),
    }


def apply_plan_learning_adjustments(
    params: TradeParameters,
    recommendations: list[ParameterRecommendation],
) -> tuple[TradeParameters, float, list[dict[str, Any]]]:
    if not recommendations:
        return params, 0.0, []

    updates: dict[str, Any] = {}
    invalid_conditions = list(params.invalid_conditions)
    confidence_delta = 0.0
    applied: list[dict[str, Any]] = []

    for item in recommendations:
        proposed = item.proposed_json or {}
        applied_item: dict[str, Any] = {
            "id": item.id,
            "report_date": item.report_date.isoformat(),
            "status": item.status,
            "priority": item.priority,
            "scope_type": item.scope_type,
            "scope_value": item.scope_value,
            "target_type": item.target_type,
            "target_name": item.target_name,
            "action": item.action,
            "rationale": item.rationale,
            "proposed": proposed,
        }

        stop_multiplier = _float(proposed.get("max_stop_loss_pct_multiplier"))
        if stop_multiplier is not None:
            updates.update(_adjust_stop(replace(params, **updates), stop_multiplier))

        trailing_multiplier = _float(proposed.get("trailing_drawdown_pct_multiplier"))
        if trailing_multiplier is not None:
            current = updates.get("trailing_drawdown_pct", params.trailing_drawdown_pct)
            updates["trailing_drawdown_pct"] = round(
                _bounded(current * trailing_multiplier, 0.02, 0.15),
                4,
            )

        position_multiplier = _float(
            proposed.get("position_size_pct_multiplier"),
            _float(proposed.get("max_position_pct_multiplier")),
        )
        if position_multiplier is not None:
            current = updates.get("position_size_pct", params.position_size_pct)
            updates["position_size_pct"] = round(
                _bounded(current * position_multiplier, 0, 0.25),
                4,
            )

        if proposed.get("take_profit_1_r_multiplier") or proposed.get("take_profit_2_r_multiplier"):
            updates.update(_adjust_take_profit(replace(params, **updates), proposed))

        max_gap = _float(proposed.get("candidate_gap_up_pct_max"))
        if max_gap is None and proposed.get("max_gap_up_pct_multiplier") is not None:
            max_gap = params.max_gap_up_pct * float(proposed["max_gap_up_pct_multiplier"])
        if max_gap is not None:
            updates["max_gap_up_pct"] = round(_bounded(max_gap, 0.0, params.max_gap_up_pct), 4)

        holding_multiplier = _float(proposed.get("max_holding_days_multiplier"))
        if holding_multiplier is not None:
            current_days = updates.get("max_holding_days", params.max_holding_days)
            updates["max_holding_days"] = max(1, int(round(current_days * holding_multiplier)))

        holding_delta = proposed.get("max_holding_days_delta")
        if holding_delta is not None:
            current_days = updates.get("max_holding_days", params.max_holding_days)
            updates["max_holding_days"] = max(1, int(current_days + int(holding_delta)))

        score_delta = _float(proposed.get("priority_score_delta"), 0.0) or 0.0
        confidence_delta += score_delta

        if proposed.get("require_extra_confirmation"):
            condition = "learned extra confirmation required before entry"
            if condition not in invalid_conditions:
                invalid_conditions.append(condition)

        applied.append(applied_item)

    evidence = {
        **params.evidence,
        "learning_adjustments": applied,
        "learning_confidence_delta": confidence_delta,
    }
    adjusted = replace(
        params,
        **updates,
        invalid_conditions=invalid_conditions,
        evidence=evidence,
    )
    return adjusted, confidence_delta, applied
