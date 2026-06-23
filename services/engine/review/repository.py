from __future__ import annotations

from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from services.shared.models import ReviewReport, RulePerformanceDaily, TradePlan


def load_rule_performance_for_date(db: Session, report_date: str) -> list[RulePerformanceDaily]:
    stmt = (
        select(RulePerformanceDaily)
        .where(RulePerformanceDaily.trade_date == date.fromisoformat(report_date))
        .order_by(desc(RulePerformanceDaily.score))
    )
    return list(db.execute(stmt).scalars())


def load_trade_plans_for_date(db: Session, plan_date: str, limit: int = 20) -> list[TradePlan]:
    stmt = (
        select(TradePlan)
        .where(TradePlan.plan_date == date.fromisoformat(plan_date))
        .order_by(desc(TradePlan.confidence_score))
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def insert_review_report(
    db: Session,
    report_date: str,
    report_type: str,
    content_md: str,
    metrics_json: dict | None = None,
    scope: str = "market",
    generator: str = "mechanical",
) -> int:
    db.add(
        ReviewReport(
            report_date=date.fromisoformat(report_date),
            report_type=report_type,
            scope=scope,
            generator=generator,
            content_md=content_md,
            metrics_json=metrics_json or {},
        )
    )
    return 1
