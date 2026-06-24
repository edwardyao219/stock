from __future__ import annotations

from services.engine.plans.generator import generate_trade_plans
from services.engine.plans.learning_adjustments import load_plan_learning_adjustments
from services.engine.plans.repository import load_feature_contexts, upsert_trade_plans
from services.engine.risk.repository import (
    load_matching_risk_profile,
    load_risk_profile,
    seed_default_risk_profile,
)
from services.engine.rules.seed_rules import MVP_RULES
from services.shared.database import SessionLocal


def generate_and_store_trade_plans(
    plan_date: str,
    trade_date: str,
    feature_date: str | None = None,
    limit: int | None = None,
    risk_profile_name: str = "default",
    use_learning_adjustments: bool = True,
) -> dict[str, int]:
    with SessionLocal() as db:
        seed_default_risk_profile(db)
        risk_profile = load_risk_profile(db, risk_profile_name)
        contexts = load_feature_contexts(db, feature_date=feature_date or plan_date, limit=limit)

        def learning_loader(rule, context, signal_tags):
            return load_plan_learning_adjustments(
                db,
                rule_id=rule.id,
                sector_code=context.get("sector_code") or context.get("industry"),
                signal_tags=signal_tags,
            )

        plans = generate_trade_plans(
            plan_date=plan_date,
            trade_date=trade_date,
            rules=MVP_RULES,
            feature_contexts=contexts,
            risk_profile=risk_profile,
            risk_profile_selector=lambda rule, context: load_matching_risk_profile(
                db,
                strategy_type=rule.strategy_type.value,
                sector_code=context.get("sector_code") or context.get("industry"),
                style=context.get("style"),
            ),
            learning_adjustment_loader=learning_loader if use_learning_adjustments else None,
        )
        written = upsert_trade_plans(db, plans)
        db.commit()
    return {"contexts": len(contexts), "plans": len(plans), "written": written}
