from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from services.engine.rules.seed_rules import MVP_RULES
from services.shared.models import (
    DailyBar,
    PaperPosition,
    ResearchPoolItem,
    Security,
    TradePlan,
    TradingCalendar,
)
from services.shared.time import now_local

ACTIVE_RULE_IDS = tuple(rule.id for rule in MVP_RULES)


@dataclass(frozen=True)
class PlanEvidence:
    category: str
    label: str
    value: str
    verdict: str
    note: str


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
    can_buy_now: bool
    execution_status: str
    execution_label: str
    execution_note: str
    evidence: list[PlanEvidence]


@dataclass(frozen=True)
class PaperTradeSummary:
    rule_id: str
    closed_count: int
    open_count: int
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
class PaperTradeItem:
    id: int
    trade_plan_id: int | None
    rule_id: str
    entry_date: str
    entry_price: float
    exit_date: str | None
    exit_price: float | None
    holding_days: int
    pnl_pct: float | None
    mfe_pct: float
    mae_pct: float
    highest_price: float
    lowest_price: float
    quantity: int
    status: str
    exit_reason: str | None


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
    paper_trade_summaries: list[PaperTradeSummary]
    recent_paper_trades: list[PaperTradeItem]


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


def _is_open_trade_date(db: Session, trade_date: date) -> bool:
    calendar_item = db.execute(
        select(TradingCalendar).where(TradingCalendar.trade_date == trade_date)
    ).scalar_one_or_none()
    if calendar_item is not None:
        return calendar_item.is_open
    return trade_date.weekday() < 5


def _plan_execution_state(db: Session, plan: TradePlan) -> tuple[bool, str, str, str]:
    current = now_local()
    today = current.date()
    current_time = current.time()
    trade_date = plan.trade_date
    session_text = "A股交易时段 09:30-11:30 / 13:00-15:00"

    if not _is_open_trade_date(db, trade_date):
        return False, "non_trading_day", "非交易日", f"{trade_date.isoformat()} 不是交易日。"
    if trade_date > today:
        label = "明日开盘观察" if (trade_date - today).days == 1 else "等待交易日"
        return (
            False,
            "future_trade_date",
            label,
            f"计划交易日 {trade_date.isoformat()}，当前还不能买；到交易日开盘后再观察触发价。",
        )
    if trade_date < today:
        return False, "expired", "计划已过期", f"计划交易日 {trade_date.isoformat()} 已经过了。"
    if not _is_open_trade_date(db, today):
        return False, "market_closed", "今日休市", f"今天不是交易日，不能买入；{session_text}。"
    if current_time < time(9, 30):
        return False, "pre_market", "开盘前等待", f"当前未开盘，9:30 后再观察；{session_text}。"
    if time(9, 30) <= current_time <= time(11, 30):
        return True, "tradable", "交易时段可观察", "当前在早盘交易时段，可按触发价观察。"
    if time(11, 30) < current_time < time(13, 0):
        return (
            False,
            "lunch_break",
            "午间休市",
            f"午间休市不能买入，13:00 后再观察；{session_text}。",
        )
    if time(13, 0) <= current_time <= time(15, 0):
        return True, "tradable", "交易时段可观察", "当前在午后交易时段，可按触发价观察。"
    return False, "market_closed", "已收盘", f"当前已收盘，今天不能买入；{session_text}。"


def _score_verdict(score: float | None, *, reverse: bool = False) -> str:
    if score is None:
        return "neutral"
    value = 100 - score if reverse else score
    if value >= 70:
        return "support"
    if value <= 40:
        return "risk"
    return "neutral"


def _pct_text(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.2f}%"


def _score_text(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}"


def _snapshot(plan: TradePlan) -> dict:
    data = plan.entry_condition_json or {}
    snapshot = data.get("snapshot") or {}
    return snapshot if isinstance(snapshot, dict) else {}


def _plan_evidence(plan: TradePlan) -> list[PlanEvidence]:
    snapshot = _snapshot(plan)
    trend_score = snapshot.get("trend_score")
    volume_score = snapshot.get("volume_score")
    sector_strength = snapshot.get("sector_strength_score")
    fundamental_score = snapshot.get("fundamental_score")
    risk_score = snapshot.get("risk_score")
    return_5d = snapshot.get("return_5d")
    return_20d = snapshot.get("return_20d")
    amount_percentile = snapshot.get("amount_percentile_60d")
    distance_to_high = snapshot.get("distance_to_20d_high")

    evidence = [
        PlanEvidence(
            category="技术面",
            label="趋势强度",
            value=_score_text(trend_score),
            verdict=_score_verdict(float(trend_score) if trend_score is not None else None),
            note=f"20日涨跌 {_pct_text(return_20d)}，距离20日高点 {_pct_text(distance_to_high)}",
        ),
        PlanEvidence(
            category="资金/量能",
            label="成交额分位",
            value=_score_text(amount_percentile or volume_score),
            verdict=_score_verdict(float(volume_score) if volume_score is not None else None),
            note=f"量能分数 {_score_text(volume_score)}，放量只作为确认，不单独构成买点。",
        ),
        PlanEvidence(
            category="板块",
            label="板块强度",
            value=_score_text(sector_strength),
            verdict=_score_verdict(float(sector_strength) if sector_strength is not None else None),
            note=f"行业 {snapshot.get('industry') or '-'}，板块表现决定参数不能一刀切。",
        ),
        PlanEvidence(
            category="基本面",
            label="基本面评分",
            value=_score_text(fundamental_score),
            verdict=snapshot.get("fundamental_verdict") or "neutral",
            note="；".join(snapshot.get("fundamental_reasons") or ["暂无足够基本面数据"]),
        ),
        PlanEvidence(
            category="情绪/风险",
            label="风险分数",
            value=_score_text(risk_score),
            verdict=_score_verdict(
                float(risk_score) if risk_score is not None else None,
                reverse=True,
            ),
            note="风险越高越要降低仓位或等待确认，避免利好兑现后的追高。",
        ),
    ]

    if (
        (return_5d is not None and float(return_5d) > 0.08)
        or (return_20d is not None and float(return_20d) > 0.20)
    ) and amount_percentile is not None and float(amount_percentile) >= 80:
        evidence.append(
            PlanEvidence(
                category="情绪/风险",
                label="利好兑现风险",
                value="偏高",
                verdict="risk",
                note="短期涨幅和成交分位同时偏高，A股里要防止利好兑现或消息落地即回落。",
            )
        )
    else:
        evidence.append(
            PlanEvidence(
                category="情绪/风险",
                label="利好兑现风险",
                value="观察",
                verdict="neutral",
                note="暂未识别到明显短期过热，但新闻/政策数据源接入前不能下确定结论。",
            )
        )
    return evidence


def _load_recent_paper_positions(
    db: Session,
    symbol: str,
    limit: int = 30,
) -> list[PaperPosition]:
    stmt = (
        select(PaperPosition)
        .where(PaperPosition.symbol == symbol)
        .order_by(desc(PaperPosition.entry_date), desc(PaperPosition.id))
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def _holding_days(position: PaperPosition, latest_bar: DailyBar | None) -> int:
    end_date = position.exit_date or (latest_bar.trade_date if latest_bar else position.entry_date)
    return (end_date - position.entry_date).days + 1


def _mfe_pct(position: PaperPosition) -> float:
    return float(position.highest_price / position.entry_price - Decimal("1"))


def _mae_pct(position: PaperPosition) -> float:
    return float(position.lowest_price / position.entry_price - Decimal("1"))


def _summarize_paper_trades(
    positions: list[PaperPosition],
) -> list[PaperTradeSummary]:
    grouped: dict[str, list[PaperPosition]] = {}
    for position in positions:
        grouped.setdefault(position.rule_id, []).append(position)

    summaries: list[PaperTradeSummary] = []
    for rule_id, items in grouped.items():
        closed = [item for item in items if item.status == "closed" and item.pnl_pct is not None]
        open_count = sum(1 for item in items if item.status == "open")
        if not closed:
            latest_entry = max(items, key=lambda item: item.entry_date)
            summaries.append(
                PaperTradeSummary(
                    rule_id=rule_id,
                    closed_count=0,
                    open_count=open_count,
                    win_rate=0,
                    avg_return=0,
                    total_return=0,
                    avg_mfe=0,
                    avg_mae=0,
                    best_return=0,
                    worst_return=0,
                    latest_entry_date=latest_entry.entry_date.isoformat(),
                    latest_exit_date=None,
                    latest_pnl_pct=None,
                    latest_exit_reason=None,
                )
            )
            continue

        pnl_values = [float(item.pnl_pct) for item in closed if item.pnl_pct is not None]
        mfe_values = [_mfe_pct(item) for item in closed]
        mae_values = [_mae_pct(item) for item in closed]
        latest = max(closed, key=lambda item: (item.exit_date or item.entry_date, item.id))
        summaries.append(
            PaperTradeSummary(
                rule_id=rule_id,
                closed_count=len(closed),
                open_count=open_count,
                win_rate=sum(1 for value in pnl_values if value > 0) / len(closed),
                avg_return=sum(pnl_values) / len(closed),
                total_return=sum(pnl_values),
                avg_mfe=sum(mfe_values) / len(closed),
                avg_mae=sum(mae_values) / len(closed),
                best_return=max(pnl_values),
                worst_return=min(pnl_values),
                latest_entry_date=latest.entry_date.isoformat(),
                latest_exit_date=latest.exit_date.isoformat() if latest.exit_date else None,
                latest_pnl_pct=float(latest.pnl_pct) if latest.pnl_pct is not None else None,
                latest_exit_reason=latest.exit_reason,
            )
        )
    return sorted(summaries, key=lambda item: item.total_return, reverse=True)


def _to_paper_trade_item(position: PaperPosition, latest_bar: DailyBar | None) -> PaperTradeItem:
    return PaperTradeItem(
        id=position.id,
        trade_plan_id=position.trade_plan_id,
        rule_id=position.rule_id,
        entry_date=position.entry_date.isoformat(),
        entry_price=float(position.entry_price),
        exit_date=position.exit_date.isoformat() if position.exit_date else None,
        exit_price=_float(position.exit_price),
        holding_days=_holding_days(position, latest_bar),
        pnl_pct=_float(position.pnl_pct),
        mfe_pct=_mfe_pct(position),
        mae_pct=_mae_pct(position),
        highest_price=float(position.highest_price),
        lowest_price=float(position.lowest_price),
        quantity=position.quantity,
        status=position.status,
        exit_reason=position.exit_reason,
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


def _to_workspace_plan(db: Session, plan: TradePlan) -> WorkspacePlan:
    can_buy_now, execution_status, execution_label, execution_note = _plan_execution_state(
        db,
        plan,
    )
    return WorkspacePlan(
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
        can_buy_now=can_buy_now,
        execution_status=execution_status,
        execution_label=execution_label,
        execution_note=execution_note,
        evidence=_plan_evidence(plan),
    )


def _build_workspace_item(
    db: Session,
    *,
    symbol: str,
    security: Security | None,
    manual: ResearchPoolItem | None,
    plans: list[TradePlan],
) -> WorkspaceItem:
    recent_bars = _load_recent_bars(db, symbol)
    latest_bar = recent_bars[-1] if recent_bars else None
    paper_positions = _load_recent_paper_positions(db, symbol)
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
        plans=[_to_workspace_plan(db, plan) for plan in plans],
        paper_trade_summaries=_summarize_paper_trades(paper_positions),
        recent_paper_trades=[
            _to_paper_trade_item(item, latest_bar) for item in paper_positions[:10]
        ],
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
