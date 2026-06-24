from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from services.engine.paper.learning import learn_from_paper_trade_reviews
from services.shared.models import PaperTradeReview


def load_learning_insights(
    db: Session,
    *,
    report_date: str,
    scope_type: str | None = None,
) -> list[dict]:
    insights = learn_from_paper_trade_reviews(db, report_date)
    if scope_type:
        insights = [item for item in insights if item.scope_type == scope_type]
    return [item.to_dict() for item in insights]


def load_recent_trade_reviews(
    db: Session,
    *,
    symbol: str | None = None,
    rule_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[PaperTradeReview]:
    stmt = select(PaperTradeReview)
    if symbol:
        stmt = stmt.where(PaperTradeReview.symbol == symbol)
    if rule_id:
        stmt = stmt.where(PaperTradeReview.rule_id == rule_id)
    stmt = stmt.order_by(desc(PaperTradeReview.exit_date), desc(PaperTradeReview.id))
    stmt = stmt.offset(offset).limit(limit)
    return list(db.execute(stmt).scalars())


def latest_review_date(db: Session) -> str | None:
    latest = db.execute(
        select(PaperTradeReview.exit_date).order_by(desc(PaperTradeReview.exit_date))
    ).scalar()
    return latest.isoformat() if isinstance(latest, date) else None
