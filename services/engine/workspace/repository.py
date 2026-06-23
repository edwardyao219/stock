from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from services.engine.rules.seed_rules import MVP_RULES
from services.shared.models import (
    BacktestTradeRecord,
    DailyBar,
    ResearchPoolItem,
    Security,
    TradePlan,
)

ACTIVE_RULE_IDS = tuple(rule.id for rule in MVP_RULES)


@dataclass(frozen=True)
class WorkspacePlan:
    id: int
    rule_id: str
    strategy_type: str
    plan_date: str
    trade_date: str
    position_size: float
    confidence_score: float | None
    initial_stop: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    status: str


@dataclass(frozen=True)
class StrategyBacktestSummary:
    rule_id: str
    trade_count: int
    win_rate: float
    avg_return: float
    total_return: float
    avg_mfe: float
    avg_mae: float
    best_return: float
    worst_return: float
    latest_entry_date: str | None
    latest_exit_date: str | None
    latest_pnl_pct: float | None
    latest_exit_reason: str | None


@dataclass(frozen=True)
class BacktestTradeItem:
    id: int
    rule_id: str
    signal_date: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    holding_days: int
    pnl_pct: float
    mfe_pct: float
    mae_pct: float
    exit_reason: str


@dataclass(frozen=True)
class WorkspaceItem:
    symbol: str
    name: str | None
    industry: str | None
    sector_style: str | None
    source: str
    manual_note: str | None
    manual_tags: list[str]
    latest_trade_date: str | None
    latest_close: float | None
    return_5d: float | None
    return_20d: float | None
    plans: list[WorkspacePlan]
    strategy_summaries: list[StrategyBacktestSummary]
    recent_backtest_trades: list[BacktestTradeItem]


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _return_from_bars(bars: list[DailyBar], lookback: int) -> float | None:
    if len(bars) <= lookback:
        return None
    latest = float(bars[-1].close)
    base = float(bars[-lookback - 1].close)
    if base == 0:
        return None
    return latest / base - 1


def _load_recent_bars(db: Session, symbol: str, limit: int = 61) -> list[DailyBar]:
    stmt = (
        select(DailyBar)
        .where(DailyBar.symbol == symbol)
        .order_by(desc(DailyBar.trade_date))
        .limit(limit)
    )
    return list(reversed(db.execute(stmt).scalars().all()))


def _load_recent_backtest_trades(
    db: Session,
    symbol: str,
    limit: int = 30,
) -> list[BacktestTradeRecord]:
    stmt = (
        select(BacktestTradeRecord)
        .where(BacktestTradeRecord.symbol == symbol)
        .order_by(desc(BacktestTradeRecord.exit_date), desc(BacktestTradeRecord.id))
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def _summarize_strategy_trades(
    trades: list[BacktestTradeRecord],
) -> list[StrategyBacktestSummary]:
    grouped: dict[str, list[BacktestTradeRecord]] = {}
    for trade in trades:
        grouped.setdefault(trade.rule_id, []).append(trade)

    summaries: list[StrategyBacktestSummary] = []
    for rule_id, items in grouped.items():
        pnl_values = [float(item.pnl_pct) for item in items]
        mfe_values = [float(item.mfe_pct) for item in items]
        mae_values = [float(item.mae_pct) for item in items]
        latest = max(items, key=lambda item: (item.exit_date, item.id))
        summaries.append(
            StrategyBacktestSummary(
                rule_id=rule_id,
                trade_count=len(items),
                win_rate=sum(1 for value in pnl_values if value > 0) / len(items),
                avg_return=sum(pnl_values) / len(items),
                total_return=sum(pnl_values),
                avg_mfe=sum(mfe_values) / len(items),
                avg_mae=sum(mae_values) / len(items),
                best_return=max(pnl_values),
                worst_return=min(pnl_values),
                latest_entry_date=latest.entry_date.isoformat(),
                latest_exit_date=latest.exit_date.isoformat(),
                latest_pnl_pct=float(latest.pnl_pct),
                latest_exit_reason=latest.exit_reason,
            )
        )
    return sorted(summaries, key=lambda item: item.total_return, reverse=True)


def _to_backtest_trade_item(trade: BacktestTradeRecord) -> BacktestTradeItem:
    return BacktestTradeItem(
        id=trade.id,
        rule_id=trade.rule_id,
        signal_date=trade.signal_date.isoformat(),
        entry_date=trade.entry_date.isoformat(),
        entry_price=float(trade.entry_price),
        exit_date=trade.exit_date.isoformat(),
        exit_price=float(trade.exit_price),
        holding_days=trade.holding_days,
        pnl_pct=float(trade.pnl_pct),
        mfe_pct=float(trade.mfe_pct),
        mae_pct=float(trade.mae_pct),
        exit_reason=trade.exit_reason,
    )


def _load_latest_trade_plans(db: Session) -> dict[str, list[TradePlan]]:
    latest_plan_date = db.execute(select(func.max(TradePlan.plan_date))).scalar_one_or_none()
    if latest_plan_date is None:
        return {}

    stmt = (
        select(TradePlan)
        .where(TradePlan.plan_date == latest_plan_date)
        .where(TradePlan.rule_id.in_(ACTIVE_RULE_IDS))
        .order_by(desc(TradePlan.confidence_score))
    )
    grouped: dict[str, list[TradePlan]] = {}
    for item in db.execute(stmt).scalars():
        grouped.setdefault(item.symbol, []).append(item)
    return grouped


def _load_manual_pool_items(db: Session, pool_name: str = "manual") -> dict[str, ResearchPoolItem]:
    stmt = (
        select(ResearchPoolItem)
        .where(ResearchPoolItem.pool_name == pool_name)
        .where(ResearchPoolItem.status == "active")
        .order_by(ResearchPoolItem.symbol)
    )
    return {item.symbol: item for item in db.execute(stmt).scalars()}


def _build_workspace_item(
    db: Session,
    *,
    symbol: str,
    security: Security | None,
    manual: ResearchPoolItem | None,
    plans: list[TradePlan],
) -> WorkspaceItem:
    recent_bars = _load_recent_bars(db, symbol)
    backtest_trades = _load_recent_backtest_trades(db, symbol)
    latest_bar = recent_bars[-1] if recent_bars else None
    source_parts = []
    if plans:
        source_parts.append("auto")
    if manual:
        source_parts.append("manual")

    return WorkspaceItem(
        symbol=symbol,
        name=security.name if security else None,
        industry=security.industry if security else None,
        sector_style=security.sector_style if security else None,
        source="+".join(source_parts) or "unknown",
        manual_note=manual.note if manual else None,
        manual_tags=(manual.tags_json or {}).get("tags", []) if manual else [],
        latest_trade_date=latest_bar.trade_date.isoformat() if latest_bar else None,
        latest_close=_float(latest_bar.close) if latest_bar else None,
        return_5d=_return_from_bars(recent_bars, 5),
        return_20d=_return_from_bars(recent_bars, 20),
        plans=[
            WorkspacePlan(
                id=plan.id,
                rule_id=plan.rule_id,
                strategy_type=plan.strategy_type,
                plan_date=plan.plan_date.isoformat(),
                trade_date=plan.trade_date.isoformat(),
                position_size=float(plan.position_size),
                confidence_score=_float(plan.confidence_score),
                initial_stop=_float(plan.initial_stop),
                take_profit_1=_float(plan.take_profit_1),
                take_profit_2=_float(plan.take_profit_2),
                status=plan.status,
            )
            for plan in plans
        ],
        strategy_summaries=_summarize_strategy_trades(backtest_trades),
        recent_backtest_trades=[_to_backtest_trade_item(item) for item in backtest_trades[:10]],
    )


def load_stock_workspace_items(
    db: Session,
    *,
    pool_name: str = "manual",
    limit: int = 200,
) -> list[WorkspaceItem]:
    plan_map = _load_latest_trade_plans(db)
    manual_map = _load_manual_pool_items(db, pool_name=pool_name)
    symbols = sorted(set(plan_map) | set(manual_map))[:limit]

    if not symbols:
        return []

    securities = {
        item.symbol: item
        for item in db.execute(select(Security).where(Security.symbol.in_(symbols))).scalars()
    }

    rows: list[WorkspaceItem] = []
    for symbol in symbols:
        rows.append(
            _build_workspace_item(
                db,
                symbol=symbol,
                security=securities.get(symbol),
                manual=manual_map.get(symbol),
                plans=plan_map.get(symbol, []),
            )
        )

    return sorted(
        rows,
        key=lambda item: (
            0 if "auto" in item.source else 1,
            -(max((plan.confidence_score or 0 for plan in item.plans), default=0)),
            item.symbol,
        ),
    )


def load_stock_workspace_item(
    db: Session,
    *,
    symbol: str,
    pool_name: str = "manual",
) -> WorkspaceItem | None:
    plan_map = _load_latest_trade_plans(db)
    manual_map = _load_manual_pool_items(db, pool_name=pool_name)
    if symbol not in plan_map and symbol not in manual_map:
        return None

    security = db.execute(select(Security).where(Security.symbol == symbol)).scalar_one_or_none()
    return _build_workspace_item(
        db,
        symbol=symbol,
        security=security,
        manual=manual_map.get(symbol),
        plans=plan_map.get(symbol, []),
    )
