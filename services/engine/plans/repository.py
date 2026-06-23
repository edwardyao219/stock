from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.plans.context import build_strategy_context, load_sector_feature_map
from services.engine.plans.generator import TradePlanCandidate
from services.shared.models import DailyBar, Security, StockFeatureDaily, TradePlan
from services.shared.upsert import upsert_rows


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, 6)))


def load_feature_contexts(
    db: Session,
    feature_date: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    target_date = _date(feature_date)
    stmt = (
        select(StockFeatureDaily, Security, DailyBar)
        .join(Security, Security.symbol == StockFeatureDaily.symbol)
        .join(
            DailyBar,
            (DailyBar.symbol == StockFeatureDaily.symbol)
            & (DailyBar.trade_date == StockFeatureDaily.trade_date),
        )
        .where(StockFeatureDaily.trade_date == target_date)
        .where(Security.is_active.is_(True))
        .order_by(StockFeatureDaily.symbol)
    )
    if limit:
        stmt = stmt.limit(limit)

    sector_feature_map = load_sector_feature_map(db, target_date)

    contexts: list[dict[str, Any]] = []
    for feature_row, security, bar in db.execute(stmt):
        contexts.append(
            build_strategy_context(
                db,
                feature_row,
                security,
                bar,
                sector_feature_map,
            )
        )
    return contexts


def upsert_trade_plans(db: Session, plans: list[TradePlanCandidate]) -> int:
    rows = [
        {
            "plan_date": _date(plan.plan_date),
            "trade_date": _date(plan.trade_date),
            "symbol": plan.symbol,
            "rule_id": plan.rule_id,
            "strategy_type": plan.strategy_type,
            "sector_code": plan.sector_code,
            "entry_condition_json": plan.entry_condition or {},
            "entry_trigger_price": _decimal(plan.entry_trigger_price),
            "max_gap_up_pct": _decimal(plan.max_gap_up_pct),
            "trailing_drawdown_pct": _decimal(plan.trailing_drawdown_pct),
            "initial_stop": _decimal(plan.initial_stop),
            "take_profit_1": _decimal(plan.take_profit_1),
            "take_profit_2": _decimal(plan.take_profit_2),
            "max_holding_days": plan.max_holding_days,
            "position_size": _decimal(plan.position_size) or Decimal("0"),
            "confidence_score": _decimal(plan.confidence_score),
            "risk_notes": plan.risk_notes,
            "status": "planned",
        }
        for plan in plans
    ]
    if not rows:
        return 0

    return upsert_rows(
        db,
        TradePlan,
        rows,
        update_columns=[
            "strategy_type",
            "sector_code",
            "entry_condition_json",
            "entry_trigger_price",
            "max_gap_up_pct",
            "trailing_drawdown_pct",
            "initial_stop",
            "take_profit_1",
            "take_profit_2",
            "max_holding_days",
            "position_size",
            "confidence_score",
            "risk_notes",
            "status",
        ],
        constraint="uq_trade_plans_daily_rule",
    )
