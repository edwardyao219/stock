from __future__ import annotations

from datetime import date

from services.engine.plans.generator import generate_trade_plans
from services.engine.plans.learning_adjustments import load_plan_learning_adjustments
from services.engine.plans.repository import (
    latest_feature_date,
    load_feature_contexts,
    retire_unselected_trade_plans,
    upsert_trade_plans,
)
from services.engine.research_pool.repository import list_pool_symbols
from services.engine.risk.repository import (
    load_matching_risk_profile,
    load_risk_profile,
    seed_default_risk_profile,
)
from services.engine.rules.seed_rules import MVP_RULES
from services.shared.database import SessionLocal

MAIN_TRADE_STRATEGY_TYPES = {"long_term", "swing"}


def generate_and_store_trade_plans(
    plan_date: str,
    trade_date: str,
    feature_date: str | None = None,
    symbols: list[str] | None = None,
    pool_name: str | None = None,
    limit: int | None = None,
    risk_profile_name: str = "default",
    use_learning_adjustments: bool = True,
) -> dict[str, int]:
    with SessionLocal() as db:
        seed_default_risk_profile(db)
        risk_profile = load_risk_profile(db, risk_profile_name)
        effective_feature_date = feature_date
        if effective_feature_date is None:
            latest_date = latest_feature_date(db, before=date.fromisoformat(trade_date))
            effective_feature_date = latest_date.isoformat() if latest_date else plan_date
        target_symbols = symbols
        should_retire_unselected = pool_name is not None and symbols is None
        if target_symbols is None and pool_name:
            target_symbols = list_pool_symbols(
                db,
                pool_name=pool_name,
                latest_candidate_batch_only=True,
            )
            if not target_symbols:
                retire_unselected_trade_plans(
                    db,
                    plan_date=plan_date,
                    trade_date=trade_date,
                    active_keys=set(),
                    include_all_plan_dates=True,
                )
                db.commit()
                return {
                    "contexts": 0,
                    "plans": 0,
                    "written": 0,
                    "feature_date": effective_feature_date,
                    "symbols": 0,
                }
            limit = None
        contexts = load_feature_contexts(
            db,
            feature_date=effective_feature_date,
            symbols=target_symbols,
            limit=limit,
            prefer_strategy_candidates=target_symbols is None,
        )
        feature_date_obj = date.fromisoformat(effective_feature_date)

        def learning_loader(rule, context, signal_tags):
            return load_plan_learning_adjustments(
                db,
                rule_id=rule.id,
                symbol=context.get("symbol"),
                sector_code=context.get("sector_code") or context.get("industry"),
                signal_tags=signal_tags,
                feature_date=feature_date_obj,
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
            allowed_strategy_types=MAIN_TRADE_STRATEGY_TYPES,
        )
        written = upsert_trade_plans(db, plans)
        if should_retire_unselected:
            retire_unselected_trade_plans(
                db,
                plan_date=plan_date,
                trade_date=trade_date,
                active_keys={(plan.symbol, plan.rule_id) for plan in plans},
                include_all_plan_dates=True,
            )
        db.commit()
    return {
        "contexts": len(contexts),
        "plans": len(plans),
        "written": written,
        "feature_date": effective_feature_date,
        "symbols": len(target_symbols) if target_symbols is not None else 0,
    }
