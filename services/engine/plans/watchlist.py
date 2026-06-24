from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.plans.context import build_strategy_context, load_sector_feature_map
from services.engine.plans.repository import latest_feature_date
from services.engine.research_pool.repository import list_pool_symbols
from services.shared.models import DailyBar, Security, StockFeatureDaily, TradePlan
from services.shared.upsert import upsert_rows


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, 4)))


def _float(context: dict, key: str, default: float | None = None) -> float | None:
    value = context.get(key)
    if value is None:
        return default
    return float(value)


def _build_watch_plan_row(
    *,
    plan_date: date,
    trade_date: date,
    context: dict,
) -> dict:
    close = _float(context, "close")
    breakout = _float(context, "breakout_level") or _float(context, "recent_high_20d") or close
    atr = _float(context, "atr_14", 0.0) or 0.0
    support = _float(context, "support_level")
    if close is None or close <= 0 or breakout is None or breakout <= 0:
        raise ValueError("close and breakout level are required")

    trigger = max(close * 1.003, breakout)
    atr_stop = trigger - atr * 1.4 if atr else trigger * 0.94
    structure_stop = support * 0.997 if support else None
    raw_stop = max(value for value in [atr_stop, structure_stop] if value is not None)
    initial_stop = min(trigger * 0.982, max(trigger * 0.93, raw_stop))
    risk = max(trigger - initial_stop, trigger * 0.018)
    take_profit_1 = trigger + risk
    take_profit_2 = trigger + risk * 2

    confidence = max(
        0.0,
        min(
            100.0,
            (_float(context, "trend_score", 50.0) or 50.0) * 0.30
            + (_float(context, "volume_score", 50.0) or 50.0) * 0.20
            + (_float(context, "relative_strength_score", 50.0) or 50.0) * 0.20
            + (_float(context, "sector_strength_score", 50.0) or 50.0) * 0.15
            + (100.0 - (_float(context, "risk_score", 50.0) or 50.0)) * 0.15,
        ),
    )

    return {
        "plan_date": plan_date,
        "trade_date": trade_date,
        "symbol": context["symbol"],
        "rule_id": "OBS001",
        "strategy_type": "watch_breakout",
        "sector_code": context.get("sector_code"),
        "entry_condition_json": {
            "source": "watchlist_observation",
            "snapshot": context,
            "note": "观察触发单：用于真实盘中采样，不代表正式买入策略通过。",
        },
        "entry_trigger_price": _decimal(trigger),
        "max_gap_up_pct": Decimal("0.0600"),
        "trailing_drawdown_pct": Decimal("0.0600"),
        "initial_stop": _decimal(initial_stop),
        "take_profit_1": _decimal(take_profit_1),
        "take_profit_2": _decimal(take_profit_2),
        "max_holding_days": 5,
        "position_size": Decimal("0.0300"),
        "confidence_score": _decimal(confidence),
        "risk_notes": "观察单小仓位；当前价触发才纸面买入；用于收集真实盘中样本。",
        "status": "planned",
    }


def generate_watchlist_observation_plans(
    *,
    db: Session,
    plan_date: str,
    trade_date: str,
    pool_name: str = "experiment",
    feature_date: str | None = None,
) -> dict[str, int | str]:
    parsed_plan_date = date.fromisoformat(plan_date)
    parsed_trade_date = date.fromisoformat(trade_date)
    symbols = list_pool_symbols(db, pool_name=pool_name)
    if not symbols:
        return {"symbols": 0, "contexts": 0, "plans": 0, "written": 0, "feature_date": ""}

    effective_feature_date = feature_date
    if effective_feature_date is None:
        latest_date = latest_feature_date(db, before=parsed_trade_date)
        effective_feature_date = latest_date.isoformat() if latest_date else plan_date
    parsed_feature_date = date.fromisoformat(effective_feature_date)
    sector_feature_map = load_sector_feature_map(db, parsed_feature_date)

    stmt = (
        select(StockFeatureDaily, Security, DailyBar)
        .join(Security, Security.symbol == StockFeatureDaily.symbol)
        .join(
            DailyBar,
            (DailyBar.symbol == StockFeatureDaily.symbol)
            & (DailyBar.trade_date == StockFeatureDaily.trade_date),
        )
        .where(StockFeatureDaily.trade_date == parsed_feature_date)
        .where(StockFeatureDaily.symbol.in_(symbols))
        .where(Security.is_active.is_(True))
        .order_by(StockFeatureDaily.symbol)
    )
    contexts = [
        build_strategy_context(db, feature_row, security, bar, sector_feature_map)
        for feature_row, security, bar in db.execute(stmt)
    ]
    rows = [
        _build_watch_plan_row(
            plan_date=parsed_plan_date,
            trade_date=parsed_trade_date,
            context=context,
        )
        for context in contexts
    ]
    written = upsert_rows(
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
    return {
        "symbols": len(symbols),
        "contexts": len(contexts),
        "plans": len(rows),
        "written": written,
        "feature_date": effective_feature_date,
    }
