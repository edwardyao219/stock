from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.main import create_app
from apps.api.app.routers.parameter_recommendations import (
    ParameterRecommendationDecisionRequest as DecisionRequest,
)
from apps.api.app.routers.parameter_recommendations import (
    get_recommendation,
    get_recommendation_summary,
    list_recommendations,
    update_recommendation_decision,
)
from services.shared.database import Base
from services.shared.models import ParameterRecommendation


def _session_with_recommendations() -> tuple[sessionmaker, Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session()
    db.add_all(
        [
            ParameterRecommendation(
                report_date=date(2026, 6, 23),
                rule_id="R001",
                scope_type="rule",
                scope_value="R001",
                target_type="research_process",
                target_name="out_of_sample_collection",
                action="expand_sample",
                priority="high",
                rationale="expand sample",
                current_json={"trade_count": 9},
                proposed_json={"minimum_trade_count_before_position_change": 20},
                guardrails_json={"items": ["低样本规则禁止放大仓位"]},
                source_report_type="daily_mechanical",
                status="pending",
            ),
            ParameterRecommendation(
                report_date=date(2026, 6, 23),
                rule_id="R004",
                scope_type="rule",
                scope_value="R004",
                target_type="rule_condition",
                target_name="banking_compound_valuation",
                action="test_tighten",
                priority="medium",
                rationale="tighten valuation",
                current_json={"pb_max": 1.0},
                proposed_json={"candidate_pb_max": 0.8},
                guardrails_json={"items": ["不要因为短期涨幅好而放宽估值约束"]},
                source_report_type="daily_mechanical",
                status="approved",
                decision_reason="manual approval",
            ),
        ]
    )
    db.commit()
    return session, db


def test_parameter_recommendation_routes_are_registered() -> None:
    schema = create_app().openapi()

    assert "/parameter-recommendations" in schema["paths"]
    assert "/parameter-recommendations/summary" in schema["paths"]
    assert "/parameter-recommendations/{recommendation_id}/decision" in schema["paths"]
    decision_schema = schema["components"]["schemas"]["ParameterRecommendationDecisionRequest"]
    assert decision_schema["properties"]["status"]["enum"] == ["pending", "approved", "rejected"]


def test_list_parameter_recommendations_filters_by_status() -> None:
    _, db = _session_with_recommendations()

    payload = list_recommendations(db=db, status="pending")

    assert len(payload) == 1
    assert payload[0].rule_id == "R001"
    assert payload[0].guardrails == ["低样本规则禁止放大仓位"]
    db.close()


def test_get_parameter_recommendation_summary() -> None:
    _, db = _session_with_recommendations()

    payload = get_recommendation_summary(db=db)

    assert payload.by_status == {"approved": 1, "pending": 1}
    assert payload.pending == 1
    db.close()


def test_update_parameter_recommendation_decision() -> None:
    session, db = _session_with_recommendations()

    payload = update_recommendation_decision(
        recommendation_id=1,
        payload=DecisionRequest(status="rejected", decision_reason="too few samples"),
        db=db,
    )

    assert payload.status == "rejected"
    assert payload.decision_reason == "too few samples"
    db.close()

    with session() as verify_db:
        row = verify_db.get(ParameterRecommendation, 1)

    assert row is not None
    assert row.status == "rejected"


def test_get_parameter_recommendation_returns_404_for_missing_item() -> None:
    _, db = _session_with_recommendations()

    with pytest.raises(HTTPException) as exc:
        get_recommendation(recommendation_id=999, db=db)

    assert exc.value.status_code == 404
    db.close()
