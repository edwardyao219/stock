from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.plans.generator import generate_trade_plans
from services.engine.plans.learning_adjustments import load_plan_learning_adjustments
from services.engine.rules.seed_rules import MVP_RULES
from services.shared.database import Base
from services.shared.models import ParameterRecommendation


def _context() -> dict:
    return {
        "symbol": "000001",
        "trade_date": "2026-06-23",
        "close": 10.0,
        "atr_14": 0.3,
        "breakout_level": 10.2,
        "support_level": 9.4,
        "sector_code": "银行",
        "sector_strength_score": 80,
        "relative_strength_score": 75,
        "amount_percentile_60d": 90,
        "distance_to_20d_high": -0.01,
        "trend_score": 80,
        "volume_score": 90,
        "risk_score": 20,
        "is_st": False,
        "is_suspended": False,
    }


def _add_recommendation(db, **overrides) -> ParameterRecommendation:
    payload = {
        "report_date": date(2026, 1, 10),
        "rule_id": "R001",
        "scope_type": "rule",
        "scope_value": "R001",
        "target_type": "exit_policy",
        "target_name": "learned_profit_protection",
        "action": "test_tighter_trailing_from_reviews",
        "priority": "high",
        "rationale": "sample",
        "current_json": {},
        "proposed_json": {"trailing_drawdown_pct_multiplier": 0.5},
        "guardrails_json": {"items": []},
        "source_report_type": "paper_learning_review",
        "status": "pending",
        **overrides,
    }
    row = ParameterRecommendation(**payload)
    db.add(row)
    db.commit()
    return row


def test_learning_adjustments_change_plan_parameters_and_evidence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_recommendation(db)

        plans = generate_trade_plans(
            plan_date="2026-06-23",
            trade_date="2026-06-24",
            rules=MVP_RULES,
            feature_contexts=[_context()],
            learning_adjustment_loader=lambda rule, context, tags: load_plan_learning_adjustments(
                db,
                rule_id=rule.id,
                sector_code=context.get("sector_code"),
                signal_tags=tags,
            ),
        )

    plan = plans[0]
    assert plan.trailing_drawdown_pct == pytest.approx(0.03)
    assert plan.entry_condition["learning_adjustments"][0]["target_name"] == (
        "learned_profit_protection"
    )
    assert plan.entry_condition["trade_parameters"]["evidence"]["learning_adjustments"]


def test_learning_adjustments_can_reduce_position_and_require_confirmation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_recommendation(
            db,
            target_type="entry_filter",
            target_name="learned_entry_quality",
            action="tighten_entry_or_reduce_priority",
            proposed_json={
                "position_size_pct_multiplier": 0.5,
                "priority_score_delta": -3,
                "require_extra_confirmation": True,
            },
        )

        plans = generate_trade_plans(
            plan_date="2026-06-23",
            trade_date="2026-06-24",
            rules=MVP_RULES,
            feature_contexts=[_context()],
            learning_adjustment_loader=lambda rule, context, tags: load_plan_learning_adjustments(
                db,
                rule_id=rule.id,
                sector_code=context.get("sector_code"),
                signal_tags=tags,
            ),
        )

    plan = plans[0]
    assert plan.position_size == pytest.approx(0.05)
    assert plan.confidence_score < 80
    assert "learned extra confirmation required before entry" in plan.risk_notes
