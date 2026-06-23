from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.engine.rules.evaluator import evaluate_group
from services.engine.rules.models import StrategyRule


@dataclass(frozen=True)
class TradePlanCandidate:
    plan_date: str
    trade_date: str
    symbol: str
    rule_id: str
    entry_summary: str
    initial_stop: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    position_size: float
    confidence_score: float
    strategy_type: str = "short_term"
    sector_code: str | None = None
    entry_condition: dict[str, Any] | None = None
    max_holding_days: int | None = None
    risk_notes: str | None = None


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    return float(value)


def _build_plan_from_context(
    plan_date: str,
    trade_date: str,
    rule: StrategyRule,
    context: dict[str, Any],
) -> TradePlanCandidate:
    close = _safe_float(context.get("close"))
    atr_14 = _safe_float(context.get("atr_14"), 0.0) or 0.0
    distance_to_20d_high = abs(_safe_float(context.get("distance_to_20d_high"), 0.0) or 0.0)
    risk_score = _safe_float(context.get("risk_score"), 50.0) or 50.0

    initial_stop = None
    if close:
        if rule.stop.type in {"atr", "composite"}:
            multiple = float(rule.stop.params.get("atr_multiple", 1.5))
            initial_stop = close - atr_14 * multiple
        elif rule.stop.type == "fixed_pct":
            initial_stop = close * (1 - float(rule.stop.params.get("pct", 0.05)))

    take_profit_1 = None
    take_profit_2 = None
    if close:
        take_profit_1 = close * 1.06
        take_profit_2 = close * 1.12

    confidence_score = max(
        0.0,
        min(
            100.0,
            (
                (_safe_float(context.get("trend_score"), 50.0) or 50.0) * 0.30
                + (_safe_float(context.get("volume_score"), 50.0) or 50.0) * 0.25
                + (_safe_float(context.get("relative_strength_score"), 50.0) or 50.0) * 0.25
                + (100.0 - min(distance_to_20d_high * 500, 100.0)) * 0.10
                + (100.0 - risk_score) * 0.10
            ),
        ),
    )

    return TradePlanCandidate(
        plan_date=plan_date,
        trade_date=trade_date,
        symbol=str(context["symbol"]),
        rule_id=rule.id,
        strategy_type=rule.strategy_type.value,
        sector_code=context.get("sector_code"),
        entry_summary=f"{rule.name}: {rule.description}",
        entry_condition={
            "rule": rule.model_dump(mode="json"),
            "snapshot": context,
        },
        initial_stop=initial_stop,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        max_holding_days=rule.time_exit.max_holding_days,
        position_size=rule.position.base_position_pct,
        confidence_score=confidence_score,
        risk_notes=None,
    )


def generate_trade_plans(
    plan_date: str,
    trade_date: str,
    rules: list[StrategyRule],
    feature_contexts: list[dict[str, Any]] | None = None,
) -> list[TradePlanCandidate]:
    """Generate trade plans from enabled rules and feature snapshots."""
    active_rules = [rule for rule in rules if rule.strategy_type.value != "filter"]
    plans: list[TradePlanCandidate] = []
    for context in feature_contexts or []:
        for rule in active_rules:
            if evaluate_group(rule.entry, context):
                plans.append(_build_plan_from_context(plan_date, trade_date, rule, context))
    return sorted(plans, key=lambda item: item.confidence_score, reverse=True)
