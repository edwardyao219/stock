from __future__ import annotations

from dataclasses import dataclass

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


def generate_trade_plans(
    plan_date: str,
    trade_date: str,
    rules: list[StrategyRule],
) -> list[TradePlanCandidate]:
    """Generate trade plans from enabled rules.

    This is intentionally empty until the feature store and rule executor are implemented.
    """
    active_rules = [rule for rule in rules if rule.strategy_type.value != "filter"]
    _ = (plan_date, trade_date, active_rules)
    return []
