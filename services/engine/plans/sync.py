from __future__ import annotations

from services.engine.plans.generator import generate_trade_plans
from services.engine.plans.repository import load_feature_contexts, upsert_trade_plans
from services.engine.rules.seed_rules import MVP_RULES
from services.shared.database import SessionLocal


def generate_and_store_trade_plans(
    plan_date: str,
    trade_date: str,
    feature_date: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    with SessionLocal() as db:
        contexts = load_feature_contexts(db, feature_date=feature_date or plan_date, limit=limit)
        plans = generate_trade_plans(
            plan_date=plan_date,
            trade_date=trade_date,
            rules=MVP_RULES,
            feature_contexts=contexts,
        )
        written = upsert_trade_plans(db, plans)
        db.commit()
    return {"contexts": len(contexts), "plans": len(plans), "written": written}
