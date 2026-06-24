from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.engine.plans.evidence import build_trade_evidence
from services.engine.plans.learning_adjustments import apply_plan_learning_adjustments
from services.engine.risk.profiles import DEFAULT_RISK_PROFILE, RiskProfile
from services.engine.risk.trade_parameters import build_trade_parameters
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
    entry_trigger_price: float | None = None
    max_gap_up_pct: float | None = None
    trailing_drawdown_pct: float | None = None
    max_holding_days: int | None = None
    risk_notes: str | None = None


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    return float(value)


def _fundamental_adjustment(context: dict[str, Any]) -> float:
    verdict = context.get("fundamental_verdict")
    score = _safe_float(context.get("fundamental_score"), 50.0) or 50.0
    if verdict == "supportive":
        return min(8.0, max(2.0, (score - 50.0) * 0.18))
    if verdict == "weak":
        return -min(12.0, max(4.0, (50.0 - score) * 0.25))
    return 0.0


def _build_plan_from_context(
    plan_date: str,
    trade_date: str,
    rule: StrategyRule,
    context: dict[str, Any],
    risk_profile: RiskProfile,
    learning_adjustment_loader: Any | None = None,
) -> TradePlanCandidate:
    params = build_trade_parameters(rule=rule, context=context, profile=risk_profile)
    evidence = build_trade_evidence(context, risk_profile.evidence_thresholds)
    learning_recommendations = []
    if learning_adjustment_loader:
        learning_recommendations = learning_adjustment_loader(
            rule,
            context,
            [*evidence["support_flags"], *evidence["risk_flags"]],
        )
        params, learning_confidence_delta, applied_learning_adjustments = (
            apply_plan_learning_adjustments(params, learning_recommendations)
        )
    else:
        learning_confidence_delta = 0.0
        applied_learning_adjustments = []

    distance_to_20d_high = abs(_safe_float(context.get("distance_to_20d_high"), 0.0) or 0.0)
    risk_score = _safe_float(context.get("risk_score"), 50.0) or 50.0
    sector_strength_score = _safe_float(context.get("sector_strength_score"), 50.0) or 50.0

    confidence_score = max(
        0.0,
        min(
            100.0,
            (
                (_safe_float(context.get("trend_score"), 50.0) or 50.0) * 0.30
                + (_safe_float(context.get("volume_score"), 50.0) or 50.0) * 0.20
                + (_safe_float(context.get("relative_strength_score"), 50.0) or 50.0) * 0.20
                + sector_strength_score * 0.15
                + (100.0 - min(distance_to_20d_high * 500, 100.0)) * 0.10
                + (100.0 - risk_score) * 0.05
                + _fundamental_adjustment(context)
                + learning_confidence_delta
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
            "evidence": evidence,
            "trade_parameters": params.to_dict(),
            "invalid_conditions": params.invalid_conditions,
            "learning_adjustments": applied_learning_adjustments,
        },
        entry_trigger_price=params.entry_trigger_price,
        max_gap_up_pct=params.max_gap_up_pct,
        trailing_drawdown_pct=params.trailing_drawdown_pct,
        initial_stop=params.initial_stop,
        take_profit_1=params.take_profit_1,
        take_profit_2=params.take_profit_2,
        max_holding_days=params.max_holding_days,
        position_size=params.position_size_pct,
        confidence_score=confidence_score,
        risk_notes="; ".join(params.invalid_conditions),
    )


def generate_trade_plans(
    plan_date: str,
    trade_date: str,
    rules: list[StrategyRule],
    feature_contexts: list[dict[str, Any]] | None = None,
    risk_profile: RiskProfile = DEFAULT_RISK_PROFILE,
    risk_profile_selector: Any | None = None,
    learning_adjustment_loader: Any | None = None,
) -> list[TradePlanCandidate]:
    """Generate trade plans from enabled rules and feature snapshots."""
    active_rules = [rule for rule in rules if rule.strategy_type.value != "filter"]
    plans: list[TradePlanCandidate] = []
    for context in feature_contexts or []:
        for rule in active_rules:
            if evaluate_group(rule.entry, context):
                selected_profile = (
                    risk_profile_selector(rule, context) if risk_profile_selector else risk_profile
                )
                plans.append(
                    _build_plan_from_context(
                        plan_date,
                        trade_date,
                        rule,
                        context,
                        selected_profile,
                        learning_adjustment_loader,
                    )
                )
    return sorted(plans, key=lambda item: item.confidence_score, reverse=True)
