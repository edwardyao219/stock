from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from services.engine.rules.seed_rules import MVP_RULES
from services.shared.models import (
    ParameterRecommendation,
    ReviewReport,
    RulePerformanceDaily,
    TradePlan,
)

ACTIVE_RULE_IDS = tuple(rule.id for rule in MVP_RULES)


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
        .where(TradePlan.rule_id.in_(ACTIVE_RULE_IDS))
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


def upsert_parameter_recommendations(
    db: Session,
    report_date: str,
    suggestions: list[dict],
    source_report_type: str = "daily_mechanical",
) -> int:
    parsed_report_date = date.fromisoformat(report_date)
    changed = 0

    for item in suggestions:
        rule_id = item.get("scope_value") if item.get("scope_type", "rule") == "rule" else None
        stmt = select(ParameterRecommendation).where(
            ParameterRecommendation.report_date == parsed_report_date,
            ParameterRecommendation.scope_type == item.get("scope_type", "rule"),
            ParameterRecommendation.scope_value == item.get("scope_value"),
            ParameterRecommendation.target_type == item["target_type"],
            ParameterRecommendation.target_name == item["target_name"],
            ParameterRecommendation.action == item["action"],
        )
        existing = db.execute(stmt).scalar_one_or_none()
        payload = {
            "scope_type": item.get("scope_type", "rule"),
            "scope_value": item.get("scope_value"),
            "priority": item.get("priority", "medium"),
            "rationale": item.get("rationale", ""),
            "current_json": item.get("current", {}),
            "proposed_json": item.get("proposed", {}),
            "guardrails_json": {"items": item.get("guardrails", [])},
            "source_report_type": source_report_type,
        }

        if existing is None:
            db.add(
                ParameterRecommendation(
                    report_date=parsed_report_date,
                    rule_id=rule_id,
                    target_type=item["target_type"],
                    target_name=item["target_name"],
                    action=item["action"],
                    status="pending",
                    **payload,
                )
            )
            changed += 1
            continue

        if existing.status != "pending":
            continue

        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = datetime.utcnow()
        changed += 1

    return changed
