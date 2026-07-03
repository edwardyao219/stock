from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from services.engine.fundamental.repository import load_fundamental_context_map
from services.engine.plans.context import (
    _ts_code_for_symbol,
    build_strategy_context,
    load_sector_feature_map,
    load_tushare_daily_basic_map,
    load_tushare_industry_moneyflow_map,
    load_tushare_moneyflow_map,
)
from services.engine.plans.generator import TradePlanCandidate
from services.engine.sector.repository import load_sector_profile_map
from services.shared.models import DailyBar, Security, StockFeatureDaily, TradePlan
from services.shared.upsert import upsert_rows


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, 6)))


def latest_feature_date(db: Session, before: date | None = None) -> date | None:
    stmt = select(func.max(StockFeatureDaily.trade_date))
    if before is not None:
        stmt = stmt.where(StockFeatureDaily.trade_date < before)
    return db.execute(stmt).scalar_one_or_none()


def load_feature_contexts(
    db: Session,
    feature_date: str,
    symbols: list[str] | None = None,
    limit: int | None = None,
    include_fundamentals: bool = True,
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
    if symbols:
        stmt = stmt.where(StockFeatureDaily.symbol.in_(symbols))
    if limit:
        stmt = stmt.limit(limit)

    sector_feature_map = load_sector_feature_map(db, target_date)

    rows = list(db.execute(stmt))
    ts_codes = [_ts_code_for_symbol(security) for _feature_row, security, _bar in rows]
    symbols = [feature_row.symbol for feature_row, _security, _bar in rows]
    sector_codes = [security.industry for _feature_row, security, _bar in rows]

    tushare_daily_basic_map = load_tushare_daily_basic_map(db, ts_codes, target_date)
    tushare_moneyflow_map = load_tushare_moneyflow_map(db, ts_codes, target_date)
    industry_moneyflow_map = load_tushare_industry_moneyflow_map(
        db,
        sector_codes,
        target_date,
    )
    fundamental_context_map = (
        load_fundamental_context_map(db, symbols, target_date) if include_fundamentals else {}
    )
    sector_profile_map = load_sector_profile_map(db, sector_codes)

    contexts: list[dict[str, Any]] = []
    for feature_row, security, bar in rows:
        contexts.append(
            build_strategy_context(
                db,
                feature_row,
                security,
                bar,
                sector_feature_map=sector_feature_map,
                tushare_daily_basic_map=tushare_daily_basic_map,
                tushare_moneyflow_map=tushare_moneyflow_map,
                industry_moneyflow_map=industry_moneyflow_map,
                fundamental_context_map=fundamental_context_map,
                sector_profile_map=sector_profile_map,
            )
        )
    return contexts


def upsert_trade_plans(db: Session, plans: list[TradePlanCandidate]) -> int:
    plan_dates = [
        (
            _date(plan.plan_date),
            _date(plan.trade_date),
            plan.symbol,
            plan.rule_id,
        )
        for plan in plans
    ]
    existing_statuses = _existing_plan_statuses(db, plan_dates)
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
            "status": _next_status(
                existing_statuses.get(
                    (_date(plan.plan_date), _date(plan.trade_date), plan.symbol, plan.rule_id)
                )
            ),
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


def _existing_plan_statuses(
    db: Session,
    keys: list[tuple[date, date, str, str]],
) -> dict[tuple[date, date, str, str], str]:
    if not keys:
        return {}
    stmt = select(
        TradePlan.plan_date,
        TradePlan.trade_date,
        TradePlan.symbol,
        TradePlan.rule_id,
        TradePlan.status,
    ).where(
        tuple_(
            TradePlan.plan_date,
            TradePlan.trade_date,
            TradePlan.symbol,
            TradePlan.rule_id,
        ).in_(keys)
    )
    return {
        (plan_date, trade_date, symbol, rule_id): status
        for plan_date, trade_date, symbol, rule_id, status in db.execute(stmt)
    }


def _next_status(existing_status: str | None) -> str:
    if existing_status in {"executed", "skipped", "cancelled"}:
        return existing_status
    return "planned"
