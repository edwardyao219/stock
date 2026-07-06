from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from services.engine.risk.trade_parameters import TradeParameters
from services.shared.models import ParameterRecommendation

LEARNING_SOURCES = {"paper_learning_review", "backtest_learning_review"}
DEFAULT_PAPER_LEARNING_STATUSES = ("pending", "approved", "applied")
PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}
LEARNING_LOOKBACK_DAYS = 60
LEARNING_RECENCY_HALF_LIFE_DAYS = 21.0
LEARNING_RECENCY_MIN_WEIGHT = 0.25


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


def _learning_recency_weight(report_date: date, feature_date: date | None) -> float:
    if feature_date is None:
        return 1.0
    days_old = max(0, (feature_date - report_date).days)
    if days_old <= 0:
        return 1.0
    weight = 0.5 ** (days_old / LEARNING_RECENCY_HALF_LIFE_DAYS)
    return max(LEARNING_RECENCY_MIN_WEIGHT, weight)


def _weighted_multiplier(multiplier: float, weight: float) -> float:
    return 1.0 + (multiplier - 1.0) * weight


def _weighted_delta(delta: float, weight: float) -> float:
    return delta * weight


def _extra_confirmation_condition(item: ParameterRecommendation) -> str:
    if item.target_name == "backtest_validation_quality":
        return "样本外验证转弱，入场前必须二次确认"
    if item.source_report_type == "backtest_learning_review":
        return "历史回归提示需二次确认后再入场"
    return "学习样本提示需二次确认后再入场"


def _matches_rule(item: ParameterRecommendation, rule_id: str) -> bool:
    proposed = item.proposed_json or {}
    source_rule_id = proposed.get("source_rule_id")
    if source_rule_id is None:
        return True
    return source_rule_id == rule_id


def load_plan_learning_adjustments(
    db: Session,
    *,
    rule_id: str,
    symbol: str | None = None,
    sector_code: str | None = None,
    signal_tags: list[str] | None = None,
    feature_date: date | None = None,
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
    if symbol:
        scope_filters.append(
            (ParameterRecommendation.scope_type == "symbol")
            & (ParameterRecommendation.scope_value == symbol)
        )
    for tag in signal_tags or []:
        scope_filters.append(
            (ParameterRecommendation.scope_type == "signal")
            & (ParameterRecommendation.scope_value == tag)
        )

    stmt = (
        select(ParameterRecommendation)
        .where(ParameterRecommendation.source_report_type.in_(LEARNING_SOURCES))
        .where(ParameterRecommendation.status.in_(statuses))
        .where(
            or_(
                ParameterRecommendation.rule_id.is_(None),
                ParameterRecommendation.rule_id == rule_id,
            )
        )
        .where(or_(*scope_filters))
    )
    if feature_date is not None:
        window_start = feature_date - timedelta(days=LEARNING_LOOKBACK_DAYS)
        stmt = stmt.where(ParameterRecommendation.report_date <= feature_date)
        stmt = stmt.where(ParameterRecommendation.report_date >= window_start)
    rows = list(
        db.execute(
            stmt.order_by(
                desc(ParameterRecommendation.report_date),
                desc(ParameterRecommendation.id),
            ).limit(limit)
        ).scalars()
    )
    matched_rows = [item for item in rows if _matches_rule(item, rule_id)]
    return sorted(matched_rows, key=_recommendation_rank, reverse=True)


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
    *,
    feature_date: date | None = None,
) -> tuple[TradeParameters, float, list[dict[str, Any]]]:
    if not recommendations:
        return params, 0.0, []

    updates: dict[str, Any] = {}
    invalid_conditions = list(params.invalid_conditions)
    confidence_delta = 0.0
    applied: list[dict[str, Any]] = []

    for item in recommendations:
        proposed = item.proposed_json or {}
        recency_weight = _learning_recency_weight(item.report_date, feature_date)
        recency_days = max(0, (feature_date - item.report_date).days) if feature_date else None
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
            "recency_weight": round(recency_weight, 4),
        }
        if recency_days is not None:
            applied_item["recency_days"] = recency_days

        stop_multiplier = _float(proposed.get("max_stop_loss_pct_multiplier"))
        if stop_multiplier is not None:
            updates.update(
                _adjust_stop(
                    replace(params, **updates),
                    _weighted_multiplier(stop_multiplier, recency_weight),
                )
            )

        trailing_multiplier = _float(proposed.get("trailing_drawdown_pct_multiplier"))
        if trailing_multiplier is not None:
            current = updates.get("trailing_drawdown_pct", params.trailing_drawdown_pct)
            updates["trailing_drawdown_pct"] = round(
                _bounded(
                    current * _weighted_multiplier(trailing_multiplier, recency_weight),
                    0.02,
                    0.15,
                ),
                4,
            )

        position_multiplier = _float(
            proposed.get("position_size_pct_multiplier"),
            _float(proposed.get("max_position_pct_multiplier")),
        )
        if position_multiplier is not None:
            current = updates.get("position_size_pct", params.position_size_pct)
            updates["position_size_pct"] = round(
                _bounded(
                    current * _weighted_multiplier(position_multiplier, recency_weight),
                    0,
                    0.25,
                ),
                4,
            )

        if proposed.get("take_profit_1_r_multiplier") or proposed.get("take_profit_2_r_multiplier"):
            weighted_proposed = dict(proposed)
            if weighted_proposed.get("take_profit_1_r_multiplier") is not None:
                weighted_proposed["take_profit_1_r_multiplier"] = _weighted_multiplier(
                    float(weighted_proposed["take_profit_1_r_multiplier"]),
                    recency_weight,
                )
            if weighted_proposed.get("take_profit_2_r_multiplier") is not None:
                weighted_proposed["take_profit_2_r_multiplier"] = _weighted_multiplier(
                    float(weighted_proposed["take_profit_2_r_multiplier"]),
                    recency_weight,
                )
            updates.update(_adjust_take_profit(replace(params, **updates), weighted_proposed))

        max_gap = _float(proposed.get("candidate_gap_up_pct_max"))
        if max_gap is None and proposed.get("max_gap_up_pct_multiplier") is not None:
            max_gap = params.max_gap_up_pct * _weighted_multiplier(
                float(proposed["max_gap_up_pct_multiplier"]),
                recency_weight,
            )
        if max_gap is not None:
            current = updates.get("max_gap_up_pct", params.max_gap_up_pct)
            weighted_gap = (
                current + (min(max_gap, params.max_gap_up_pct) - current) * recency_weight
            )
            updates["max_gap_up_pct"] = round(_bounded(weighted_gap, 0.0, params.max_gap_up_pct), 4)

        holding_multiplier = _float(proposed.get("max_holding_days_multiplier"))
        if holding_multiplier is not None:
            current_days = updates.get("max_holding_days", params.max_holding_days)
            updates["max_holding_days"] = max(
                1,
                int(round(current_days * _weighted_multiplier(holding_multiplier, recency_weight))),
            )

        holding_delta = proposed.get("max_holding_days_delta")
        if holding_delta is not None:
            current_days = updates.get("max_holding_days", params.max_holding_days)
            updates["max_holding_days"] = max(
                1,
                int(round(current_days + _weighted_delta(float(holding_delta), recency_weight))),
            )

        score_delta = _float(proposed.get("priority_score_delta"), 0.0) or 0.0
        weighted_score_delta = _weighted_delta(score_delta, recency_weight)
        confidence_delta += weighted_score_delta

        if proposed.get("require_extra_confirmation") and (
            recency_weight >= 0.5 or weighted_score_delta <= -1.0
        ):
            condition = _extra_confirmation_condition(item)
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
