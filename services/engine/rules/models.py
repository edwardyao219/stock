from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class StrategyType(str, Enum):
    SHORT_TERM = "short_term"
    SWING = "swing"
    LONG_TERM = "long_term"
    FILTER = "filter"


class RuleStatus(str, Enum):
    DRAFT = "draft"
    TESTING = "testing"
    PAPER_ENABLED = "paper_enabled"
    LIVE_CANDIDATE = "live_candidate"
    DISABLED = "disabled"


class Condition(BaseModel):
    feature: Optional[str] = None
    field: Optional[str] = None
    op: Literal[">", ">=", "<", "<=", "==", "!=", "in", "not_in"]
    value: Optional[Any] = None
    ref: Optional[str] = None


class ConditionGroup(BaseModel):
    all: list[Union[Condition, "ConditionGroup"]] = Field(default_factory=list)
    any: list[Union[Condition, "ConditionGroup"]] = Field(default_factory=list)


class StopRule(BaseModel):
    type: Literal["fixed_pct", "atr", "structure", "time", "composite"]
    params: dict[str, Any] = Field(default_factory=dict)


class TakeProfitRule(BaseModel):
    type: Literal["fixed_pct", "trailing", "target_then_trailing", "none"]
    params: dict[str, Any] = Field(default_factory=dict)


class TimeExitRule(BaseModel):
    max_holding_days: Optional[int] = None
    exit_if_no_new_high_days: Optional[int] = None


class PositionRule(BaseModel):
    base_position_pct: float
    max_position_pct: float
    reduce_when_market_weak_pct: float = 0.5


class StrategyRule(BaseModel):
    id: str
    name: str
    version: str = "0.1.0"
    strategy_type: StrategyType
    status: RuleStatus = RuleStatus.TESTING
    description: str
    market_filter: ConditionGroup = Field(default_factory=ConditionGroup)
    entry: ConditionGroup = Field(default_factory=ConditionGroup)
    trigger: ConditionGroup = Field(default_factory=ConditionGroup)
    stop: StopRule
    take_profit: TakeProfitRule
    time_exit: TimeExitRule = Field(default_factory=TimeExitRule)
    position: PositionRule
    tags: list[str] = Field(default_factory=list)


ConditionGroup.model_rebuild()
