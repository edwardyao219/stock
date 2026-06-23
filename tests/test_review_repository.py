from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.review.repository import (
    load_trade_plans_for_date,
    upsert_parameter_recommendations,
)
from services.shared.database import Base
from services.shared.models import ParameterRecommendation, TradePlan


def test_load_trade_plans_for_date_filters_unknown_rule_ids() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add_all(
            [
                TradePlan(
                    plan_date=date(2026, 6, 23),
                    trade_date=date(2026, 6, 24),
                    symbol="000001",
                    rule_id="R001",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("80"),
                    status="planned",
                ),
                TradePlan(
                    plan_date=date(2026, 6, 23),
                    trade_date=date(2026, 6, 24),
                    symbol="000001",
                    rule_id="TEST",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("99"),
                    status="planned",
                ),
            ]
        )
        db.commit()

        plans = load_trade_plans_for_date(db, "2026-06-23")

    assert [item.rule_id for item in plans] == ["R001"]


def test_upsert_parameter_recommendations_updates_pending_without_duplicates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    suggestion = {
        "target_type": "rule_condition",
        "target_name": "banking_compound_valuation",
        "action": "test_tighten",
        "rationale": "old",
        "priority": "medium",
        "scope_type": "rule",
        "scope_value": "R004",
        "current": {"pb_max": 1.0},
        "proposed": {"candidate_pb_max": 0.8},
        "guardrails": ["只作为候选参数，不自动应用"],
    }

    with session() as db:
        assert upsert_parameter_recommendations(db, "2026-06-23", [suggestion]) == 1
        db.commit()

        suggestion["rationale"] = "new"
        suggestion["priority"] = "high"
        assert upsert_parameter_recommendations(db, "2026-06-23", [suggestion]) == 1
        db.commit()

        rows = db.query(ParameterRecommendation).all()

    assert len(rows) == 1
    assert rows[0].rationale == "new"
    assert rows[0].priority == "high"
    assert rows[0].status == "pending"
    assert rows[0].guardrails_json["items"] == ["只作为候选参数，不自动应用"]


def test_upsert_parameter_recommendations_does_not_overwrite_decided_items() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    suggestion = {
        "target_type": "risk_profile",
        "target_name": "position_sizing",
        "action": "test_reduce",
        "rationale": "system suggestion",
        "priority": "high",
        "scope_type": "rule",
        "scope_value": "R001",
        "current": {},
        "proposed": {"max_position_pct_multiplier": 0.8},
        "guardrails": [],
    }

    with session() as db:
        assert upsert_parameter_recommendations(db, "2026-06-23", [suggestion]) == 1
        db.commit()

        row = db.query(ParameterRecommendation).one()
        row.status = "approved"
        row.decision_reason = "manual decision"
        db.commit()

        suggestion["rationale"] = "new system suggestion"
        suggestion["priority"] = "medium"
        assert upsert_parameter_recommendations(db, "2026-06-23", [suggestion]) == 0
        db.commit()

        row = db.query(ParameterRecommendation).one()

    assert row.status == "approved"
    assert row.rationale == "system suggestion"
    assert row.priority == "high"
    assert row.decision_reason == "manual decision"
