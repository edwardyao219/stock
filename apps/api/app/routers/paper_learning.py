from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.engine.paper.learning_repository import (
    latest_review_date,
    load_learning_insights,
    load_recent_trade_reviews,
)
from services.shared.database import get_db
from services.shared.models import PaperTradeReview

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


class LearningInsightResponse(BaseModel):
    scope_type: str
    scope_value: str
    sample_count: int
    avg_return: float
    avg_giveback: float
    verdict_counts: dict[str, int]
    summary: str
    suggestions: list[dict[str, Any]]


class TradeReviewResponse(BaseModel):
    id: int
    position_id: int
    symbol: str
    rule_id: str
    sector_code: str | None
    strategy_type: str
    entry_date: date
    exit_date: date
    holding_days: int
    pnl_pct: float
    mfe_pct: float
    mae_pct: float
    giveback_pct: float
    exit_reason: str
    signal_tags: list[str]
    alert_summary: dict[str, Any]
    verdict: str
    summary: str


class PaperLearningOverviewResponse(BaseModel):
    latest_review_date: str | None
    insights: list[LearningInsightResponse]
    recent_reviews: list[TradeReviewResponse]


def _review_to_response(item: PaperTradeReview) -> TradeReviewResponse:
    return TradeReviewResponse(
        id=item.id,
        position_id=item.position_id,
        symbol=item.symbol,
        rule_id=item.rule_id,
        sector_code=item.sector_code,
        strategy_type=item.strategy_type,
        entry_date=item.entry_date,
        exit_date=item.exit_date,
        holding_days=item.holding_days,
        pnl_pct=float(item.pnl_pct),
        mfe_pct=float(item.mfe_pct),
        mae_pct=float(item.mae_pct),
        giveback_pct=float(item.giveback_pct),
        exit_reason=item.exit_reason,
        signal_tags=(item.signal_tags_json or {}).get("items", []),
        alert_summary=item.alert_summary_json or {},
        verdict=item.verdict,
        summary=item.summary,
    )


@router.get("/overview", response_model=PaperLearningOverviewResponse)
def get_learning_overview(
    db: DbSession,
    report_date: str | None = None,
    scope_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> PaperLearningOverviewResponse:
    effective_date = report_date or latest_review_date(db)
    insights = (
        load_learning_insights(db, report_date=effective_date, scope_type=scope_type)
        if effective_date
        else []
    )
    reviews = load_recent_trade_reviews(db, limit=limit)
    return PaperLearningOverviewResponse(
        latest_review_date=effective_date,
        insights=[LearningInsightResponse(**item) for item in insights],
        recent_reviews=[_review_to_response(item) for item in reviews],
    )


@router.get("/reviews", response_model=list[TradeReviewResponse])
def list_trade_reviews(
    db: DbSession,
    symbol: str | None = None,
    rule_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TradeReviewResponse]:
    return [
        _review_to_response(item)
        for item in load_recent_trade_reviews(
            db,
            symbol=symbol,
            rule_id=rule_id,
            limit=limit,
            offset=offset,
        )
    ]
