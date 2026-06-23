from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from services.engine.review.repository import (
    count_parameter_recommendations_by_status,
    list_parameter_recommendations,
    load_parameter_recommendation,
    update_parameter_recommendation_decision,
)
from services.shared.database import get_db
from services.shared.models import ParameterRecommendation

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]

RecommendationStatus = Literal["pending", "approved", "rejected", "applied"]
RecommendationDecisionStatus = Literal["pending", "approved", "rejected"]


class ParameterRecommendationResponse(BaseModel):
    id: int
    report_date: date
    rule_id: str | None
    scope_type: str
    scope_value: str | None
    target_type: str
    target_name: str
    action: str
    priority: str
    rationale: str
    current: dict[str, Any]
    proposed: dict[str, Any]
    guardrails: list[str]
    source_report_type: str
    status: str
    decision_reason: str | None
    created_at: datetime
    updated_at: datetime


class ParameterRecommendationDecisionRequest(BaseModel):
    status: RecommendationDecisionStatus
    decision_reason: str | None = Field(default=None, max_length=1000)


class ParameterRecommendationSummaryResponse(BaseModel):
    by_status: dict[str, int]
    pending: int


def _to_response(item: ParameterRecommendation) -> ParameterRecommendationResponse:
    return ParameterRecommendationResponse(
        id=item.id,
        report_date=item.report_date,
        rule_id=item.rule_id,
        scope_type=item.scope_type,
        scope_value=item.scope_value,
        target_type=item.target_type,
        target_name=item.target_name,
        action=item.action,
        priority=item.priority,
        rationale=item.rationale,
        current=item.current_json or {},
        proposed=item.proposed_json or {},
        guardrails=(item.guardrails_json or {}).get("items", []),
        source_report_type=item.source_report_type,
        status=item.status,
        decision_reason=item.decision_reason,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=list[ParameterRecommendationResponse])
def list_recommendations(
    db: DbSession,
    status: RecommendationStatus | None = None,
    report_date: str | None = None,
    rule_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ParameterRecommendationResponse]:
    try:
        items = list_parameter_recommendations(
            db,
            status=status,
            report_date=report_date,
            rule_id=rule_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_to_response(item) for item in items]


@router.get("/summary", response_model=ParameterRecommendationSummaryResponse)
def get_recommendation_summary(
    db: DbSession,
) -> ParameterRecommendationSummaryResponse:
    by_status = count_parameter_recommendations_by_status(db)
    return ParameterRecommendationSummaryResponse(
        by_status=by_status,
        pending=by_status.get("pending", 0),
    )


@router.get("/{recommendation_id}", response_model=ParameterRecommendationResponse)
def get_recommendation(
    recommendation_id: int,
    db: DbSession,
) -> ParameterRecommendationResponse:
    item = load_parameter_recommendation(db, recommendation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Parameter recommendation not found")
    return _to_response(item)


@router.patch("/{recommendation_id}/decision", response_model=ParameterRecommendationResponse)
def update_recommendation_decision(
    recommendation_id: int,
    payload: ParameterRecommendationDecisionRequest,
    db: DbSession,
) -> ParameterRecommendationResponse:
    item = update_parameter_recommendation_decision(
        db,
        recommendation_id,
        status=payload.status,
        decision_reason=payload.decision_reason,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Parameter recommendation not found")
    db.commit()
    db.refresh(item)
    return _to_response(item)
