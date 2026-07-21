from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from services.engine.features.health import (
    assess_trade_data_evidence_risk,
    inspect_tushare_evidence_health,
)
from services.engine.features.late_market_turn_health import (
    late_market_turn_health,
    late_market_turn_snapshot,
)
from services.engine.intraday.candidates import discover_intraday_candidates
from services.engine.research_pool.repository import (
    candidate_tags,
    filter_latest_candidate_batch_items,
    manual_focus_tags,
)
from services.engine.rules.seed_rules import MVP_RULES
from services.engine.rules.evaluator import evaluate_condition, evaluate_group
from services.engine.rules.models import Condition, ConditionGroup
from services.shared.models import (
    DailyBar,
    IntradayMarketTurnSnapshot,
    PaperPosition,
    RealtimeQuote,
    ResearchPoolItem,
    Security,
    StockFeatureDaily,
    TradePlan,
    TradingCalendar,
)
from services.shared.symbols import is_growth_board_symbol, is_star_market_symbol
from services.shared.time import now_local

ACTIVE_RULE_IDS = tuple(rule.id for rule in MVP_RULES) + ("OBS001",)
WORKSPACE_POOL_ALIASES: dict[str, tuple[str, ...]] = {
    "experiment": ("experiment", "experiment_star"),
}


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
    entry_trigger_price: float | None
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
class PlanAvailability:
    status: str
    label: str
    reason: str


@dataclass(frozen=True)
class IntradayPlanGuard:
    selection_tier: str
    selection_tier_label: str
    selection_reason: str
    intraday_label: str
    sector_signal_label: str


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
    current_price: float | None
    current_pnl_pct: float | None
    current_stop: float | None
    take_profit_1: float | None
    quote_time: str | None


@dataclass(frozen=True)
class WorkspaceItem:
    symbol: str
    name: str | None
    industry: str | None
    sector_style: str | None
    source: str
    manual_note: str | None
    manual_tags: list[str]
    candidate_rank: int | None
    candidate_score: float | None
    candidate_tier: str | None
    candidate_tier_label: str | None
    candidate_tier_reason: str | None
    startup_signal_score: float | None
    startup_signal_label: str | None
    startup_signal_reasons: list[str]
    feature_date: str | None
    latest_trade_date: str | None
    latest_close: float | None
    current_price: float | None
    day_change_pct: float | None
    quote_time: str | None
    return_5d: float | None
    return_20d: float | None
    trend_score: float | None
    relative_strength_score: float | None
    sector_strength_score: float | None
    volume_confirmation_score: float | None
    risk_score: float | None
    overheat_score: float | None
    volume_trap_risk_score: float | None
    distance_to_ma20: float | None
    amount_percentile_60d: float | None
    amount_ratio_5d: float | None
    pullback_volume_ratio: float | None
    ma20_slope_20d: float | None
    ma60_slope_20d: float | None
    ma_alignment_score: float | None
    trend_quality_score: float | None
    route_score: float | None
    route_label: str | None
    route_reason: str | None
    plans: list[WorkspacePlan]
    paper_trade_summaries: list[PaperTradeSummary]
    recent_paper_trades: list[PaperTradeItem]
    plan_availability: PlanAvailability = field(
        default_factory=lambda: PlanAvailability(
            "unknown", "计划待确认", "计划状态暂未计算。"
        )
    )


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


def _latest_feature_snapshot(db: Session, symbol: str) -> tuple[str | None, dict[str, Any]]:
    stmt = (
        select(StockFeatureDaily)
        .where(StockFeatureDaily.symbol == symbol)
        .order_by(desc(StockFeatureDaily.trade_date))
        .limit(1)
    )
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        return None, {}
    return row.trade_date.isoformat(), row.features or {}


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


def _is_intraday_trading_time(value: time) -> bool:
    return time(9, 30) <= value <= time(11, 30) or time(13, 0) <= value <= time(15, 0)


def load_sustained_startup_sectors(
    db: Session,
    *,
    trade_date: date,
    as_of: datetime,
) -> set[str]:
    row = db.execute(
        select(IntradayMarketTurnSnapshot)
        .where(IntradayMarketTurnSnapshot.trade_date == trade_date)
        .where(IntradayMarketTurnSnapshot.snapshot_time <= as_of)
        .order_by(IntradayMarketTurnSnapshot.snapshot_time.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return set()
    state = row.state_json or {}
    if not state.get("data_ready"):
        return set()
    cross_day_mainline = state.get("cross_day_mainline")
    if not isinstance(cross_day_mainline, dict):
        return set()
    if cross_day_mainline.get("status") != "观察确认":
        return set()
    return {
        str(sector).strip()
        for sector in cross_day_mainline.get("confirmed_sectors") or []
        if str(sector).strip()
    }


def _load_intraday_plan_guards(
    db: Session,
    *,
    pool_name: str,
    include_growth_board: bool,
    market_stress: dict[str, Any] | None = None,
) -> dict[str, IntradayPlanGuard]:
    current = now_local()
    if not _is_intraday_trading_time(current.time()):
        return {}
    if not _is_open_trade_date(db, current.date()):
        return {}
    sustained_startup_sectors = load_sustained_startup_sectors(
        db,
        trade_date=current.date(),
        as_of=current,
    )

    result = discover_intraday_candidates(
        db,
        trade_date=current.date(),
        pool_name=pool_name,
        limit=50,
        include_growth_board=include_growth_board,
        as_of=current,
        market_stress=market_stress,
        sustained_startup_sectors=sustained_startup_sectors,
    )
    guards: dict[str, IntradayPlanGuard] = {}
    for item in result.get("candidates", []):
        if item.get("selection_tier") == "formal":
            continue
        symbol = str(item.get("symbol") or "")
        if not symbol:
            continue
        guards[symbol] = IntradayPlanGuard(
            selection_tier=str(item.get("selection_tier") or ""),
            selection_tier_label=str(item.get("selection_tier_label") or "暂缓"),
            selection_reason=str(item.get("selection_reason") or "最新盘中快照不支持买入"),
            intraday_label=str(item.get("intraday_label") or "盘中转弱"),
            sector_signal_label=str(item.get("sector_signal_label") or "板块待确认"),
        )
    return guards


def _apply_intraday_plan_guard(
    state: tuple[bool, str, str, str],
    guard: IntradayPlanGuard | None,
) -> tuple[bool, str, str, str]:
    can_buy_now, execution_status, execution_label, execution_note = state
    if not can_buy_now or guard is None:
        return state

    context = f"最新盘中快照：{guard.intraday_label}，{guard.sector_signal_label}"
    note = f"{context}；{guard.selection_reason}。"
    return False, "intraday_defer", "盘中暂缓", note


def _apply_market_stress_plan_guard(
    state: tuple[bool, str, str, str],
    market_stress: dict[str, Any] | None,
) -> tuple[bool, str, str, str]:
    can_buy_now, _, _, _ = state
    if not can_buy_now or not market_stress:
        return state

    status = str(market_stress.get("stress_status") or "")
    if status != "risk_off":
        return state

    action = str(market_stress.get("risk_action_label") or "停止扩散，只做观察和风控")
    reasons = [str(reason) for reason in market_stress.get("stress_reasons") or []]
    reason_text = f"；{reasons[0]}" if reasons else ""
    return (
        False,
        "market_risk_off",
        "市场压力暂缓",
        f"全市场压力大，{action}{reason_text}。",
    )


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
    route_score = snapshot.get("route_score")
    route_label = snapshot.get("route_label")
    route_reason = snapshot.get("route_reason")
    trend_score = snapshot.get("route_trend_score") or snapshot.get("trend_score")
    participation_score = snapshot.get("route_participation_score")
    risk_score = snapshot.get("route_risk_score") or snapshot.get("risk_score")
    momentum_score = snapshot.get("route_momentum_score")
    sector_strength = snapshot.get("sector_strength_score")
    fundamental_score = snapshot.get("fundamental_score")
    evidence = [
        PlanEvidence(
            category="技术面",
            label="趋势/动能",
            value=_score_text(trend_score),
            verdict=_score_verdict(float(trend_score) if trend_score is not None else None),
            note=f"动能 {_score_text(momentum_score)}，趋势不要和资金分开看。",
        ),
        PlanEvidence(
            category="资金/量能",
            label="资金参与",
            value=_score_text(participation_score),
            verdict=_score_verdict(
                float(participation_score) if participation_score is not None else None
            ),
            note="资金只做确认，不单独当买点。",
        ),
        PlanEvidence(
            category="板块",
            label="板块强度",
            value=_score_text(sector_strength),
            verdict=_score_verdict(float(sector_strength) if sector_strength is not None else None),
            note=f"行业 {snapshot.get('industry') or '-'}，板块环境只做背景。",
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
        PlanEvidence(
            category="路线",
            label=route_label or "路线判断",
            value=_score_text(route_score),
            verdict=_score_verdict(float(route_score) if route_score is not None else None),
            note=route_reason or "路线分来自趋势、资金和风险的综合判断",
        ),
    ]
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


def _load_latest_quotes(db: Session, symbols: list[str]) -> dict[str, RealtimeQuote]:
    if not symbols:
        return {}
    latest_times = (
        select(
            RealtimeQuote.symbol.label("symbol"),
            func.max(RealtimeQuote.quote_time).label("quote_time"),
        )
        .where(RealtimeQuote.symbol.in_(symbols))
        .group_by(RealtimeQuote.symbol)
        .subquery()
    )
    stmt = (
        select(RealtimeQuote)
        .join(
            latest_times,
            (RealtimeQuote.symbol == latest_times.c.symbol)
            & (RealtimeQuote.quote_time == latest_times.c.quote_time),
        )
    )
    return {item.symbol: item for item in db.execute(stmt).scalars()}


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


def _current_pnl_pct(position: PaperPosition, current_price: Decimal | None) -> float | None:
    if position.status != "open" or current_price is None or position.entry_price == 0:
        return _float(position.pnl_pct)
    return float(
        (current_price / position.entry_price - Decimal("1")).quantize(Decimal("0.000001"))
    )


def _quote_change_pct(quote: RealtimeQuote | None) -> float | None:
    if quote is None or quote.price is None or quote.pre_close is None or quote.pre_close == 0:
        return None
    return float((quote.price / quote.pre_close - Decimal("1")).quantize(Decimal("0.000001")))


def _daily_change_pct(bar: DailyBar | None) -> float | None:
    if bar is None or bar.pre_close is None or bar.pre_close == 0:
        return None
    return float((bar.close / bar.pre_close - Decimal("1")).quantize(Decimal("0.000001")))


def _tag_number(tags: list[str], prefix: str, cast):
    for tag in tags:
        if tag.startswith(prefix):
            try:
                return cast(tag.removeprefix(prefix))
            except ValueError:
                return None
    return None


def _tag_text(tags: list[str], prefix: str) -> str | None:
    for tag in tags:
        if tag.startswith(prefix):
            value = tag.removeprefix(prefix).strip()
            return value or None
    return None


def _tag_texts(tags: list[str], prefix: str) -> list[str]:
    return [
        value
        for tag in tags
        if tag.startswith(prefix)
        for value in [tag.removeprefix(prefix).strip()]
        if value
    ]


def _candidate_tier_label(value: str | None) -> str | None:
    labels = {
        "core_action": "核心行动",
        "sector_watch": "板块观察",
        "watch_wait": "观察等待",
        "risk_reject": "淘汰/风险",
    }
    return labels.get(str(value or ""), None)


def _candidate_tier_reason(tags: list[str], tier: str | None) -> str | None:
    tagged_reason = _tag_text(tags, "tier_reason:")
    if tagged_reason:
        return tagged_reason
    if tier == "core_action":
        return "板块和个股趋势同时在线，作为核心行动候选；盘中仍看承接。"
    if tier == "sector_watch":
        return "防守阶段板块观察：每个方向保留代表票，交给人盘中判断，非买点。"
    if tier == "watch_wait":
        return "趋势仍可跟踪，但还需要买点、板块延续或盘中承接确认。"
    if tier == "risk_reject":
        return "风险信号偏重，暂不纳入行动池。"
    return None


def _plan_availability(
    *,
    plans: list[TradePlan],
    manual_tags: list[str],
    candidate_tier: str | None,
    candidate_tier_reason: str | None,
    data_evidence_risk: dict[str, object] | None,
    feature_snapshot: dict[str, Any] | None = None,
) -> PlanAvailability:
    if plans:
        return PlanAvailability("planned", "计划已生成", "已生成交易计划，仍需按触发价和盘中承接执行。")
    risk = data_evidence_risk or {}
    reasons = [str(item) for item in risk.get("reasons") or []]
    if risk.get("status") == "blocked":
        return PlanAvailability(
            "data_blocked",
            "数据门禁拦截",
            "；".join(reasons) or "数据证据未完整到位，暂不生成交易计划。",
        )
    is_auto_candidate = any(tag in {"after_close_candidate", "next_session"} for tag in manual_tags)
    if not is_auto_candidate:
        return PlanAvailability("manual_watch", "仅手动关注", "尚未进入自动候选批次，不生成交易计划。")
    tier_reason = candidate_tier_reason or ""
    if "市场" in tier_reason and any(word in tier_reason for word in ("观察", "暂停", "风险")):
        return PlanAvailability("market_guard", "市场风控观察", tier_reason)
    if candidate_tier == "risk_reject":
        return PlanAvailability("risk_reject", "风险暂缓", tier_reason or "风险信号偏重，暂不生成交易计划。")
    if candidate_tier in {"watch_wait", "sector_watch"}:
        return PlanAvailability("watch_only", "买点待确认", tier_reason or "候选仍在观察，等待买点和盘中承接确认。")
    rule_id = _tag_text(manual_tags, "rule:")
    if rule_id:
        gaps = _rule_entry_gaps(rule_id, feature_snapshot) if feature_snapshot is not None else []
        gap_text = f"当前缺口：{'；'.join(gaps)}。" if gaps else ""
        return PlanAvailability(
            "rule_pending", "规则待确认", f"策略 {rule_id} 已入选候选，但入场条件尚未全部满足。{gap_text}"
        )
    return PlanAvailability("rule_pending", "规则待确认", "候选已入池，但尚未满足可执行交易计划的规则条件。")


def _condition_gap(condition: Condition, context: dict[str, Any]) -> str:
    key = condition.feature or condition.field or "条件"
    labels = {
        "sector_strength_score": "板块强度",
        "relative_strength_score": "相对强度",
        "amount_percentile_60d": "成交额分位",
    }
    label = labels.get(key, key)
    value = context.get(key)
    right = context.get(condition.ref) if condition.ref else condition.value
    value_text = f"{float(value):.1f}" if isinstance(value, (int, float)) else "缺失"
    if condition.op == ">=":
        return f"{label} {value_text}，需不低于 {right}"
    return f"{label} 未满足 {condition.op} {right}"


def _group_gaps(group: ConditionGroup, context: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    for item in group.all:
        if isinstance(item, ConditionGroup):
            if not evaluate_group(item, context):
                gaps.extend(_group_gaps(item, context))
        elif not evaluate_condition(item, context):
            gaps.append(_condition_gap(item, context))
    if group.any and not any(
        evaluate_group(item, context) if isinstance(item, ConditionGroup) else evaluate_condition(item, context)
        for item in group.any
    ):
        for item in group.any:
            if isinstance(item, ConditionGroup):
                gaps.extend(_group_gaps(item, context))
            else:
                gaps.append(_condition_gap(item, context))
    return gaps


def _rule_entry_gaps(rule_id: str, context: dict[str, Any]) -> list[str]:
    rule = next((item for item in MVP_RULES if item.id == rule_id), None)
    return _group_gaps(rule.entry, context)[:3] if rule else []


def _data_evidence_risks(db: Session, feature_dates: set[str]) -> dict[str, dict[str, object]]:
    risks: dict[str, dict[str, object]] = {}
    for feature_date in feature_dates:
        try:
            trade_date = date.fromisoformat(feature_date)
        except ValueError:
            continue
        risks[feature_date] = assess_trade_data_evidence_risk(
            inspect_tushare_evidence_health(db, trade_date),
            late_market_turn_health(late_market_turn_snapshot(db, trade_date)),
        )
    return risks


def _to_paper_trade_item(
    position: PaperPosition,
    latest_bar: DailyBar | None,
    latest_quote: RealtimeQuote | None,
) -> PaperTradeItem:
    current_price = latest_quote.price if latest_quote is not None else None
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
        current_price=_float(current_price),
        current_pnl_pct=_current_pnl_pct(position, current_price),
        current_stop=_float(position.current_stop),
        take_profit_1=_float(position.take_profit_1),
        quote_time=latest_quote.quote_time.isoformat(timespec="seconds") if latest_quote else None,
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
    return _load_manual_pool_items_for_pools(db, _pool_names(pool_name))


def _pool_names(pool_name: str) -> tuple[str, ...]:
    names = WORKSPACE_POOL_ALIASES.get(pool_name)
    if names:
        return names
    return (pool_name,)


def _append_manual_tag(tags: list[str], tag: str) -> list[str]:
    if tag in tags:
        return tags
    return [*tags, tag]


def _load_manual_pool_items_for_pools(
    db: Session,
    pool_names: tuple[str, ...],
) -> dict[str, ResearchPoolItem]:
    stmt = (
        select(ResearchPoolItem)
        .where(ResearchPoolItem.pool_name.in_(pool_names))
        .where(ResearchPoolItem.status == "active")
        .order_by(ResearchPoolItem.symbol, ResearchPoolItem.updated_at.desc())
    )
    items = filter_latest_candidate_batch_items(list(db.execute(stmt).scalars()))
    merged: dict[str, ResearchPoolItem] = {}
    for item in items:
        if item.pool_name == "experiment_star" or is_star_market_symbol(item.symbol):
            current_tags = list((item.tags_json or {}).get("tags", []))
            item.tags_json = {"tags": _append_manual_tag(current_tags, "star_pool")}
        current = merged.get(item.symbol)
        if current is None:
            merged[item.symbol] = item
            continue

        current_tags = list((current.tags_json or {}).get("tags", []))
        incoming_tags = list((item.tags_json or {}).get("tags", []))
        if item.pool_name == "experiment_star" or is_star_market_symbol(item.symbol):
            incoming_tags = _append_manual_tag(incoming_tags, "star_pool")
        merged_tags = list(dict.fromkeys([*current_tags, *incoming_tags]))

        if item.note and not current.note:
            current.note = item.note
        current.tags_json = {"tags": merged_tags}
        if item.updated_at and (current.updated_at is None or item.updated_at > current.updated_at):
            current.updated_at = item.updated_at
        if current.pool_name != item.pool_name and item.pool_name == "experiment_star":
            current.pool_name = pool_names[0]
    return merged


def _has_current_auto_candidate_batch(manual_map: dict[str, ResearchPoolItem]) -> bool:
    for item in manual_map.values():
        tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
        if candidate_tags(tags) and not manual_focus_tags(tags):
            return True
    return False


def _workspace_symbol_candidates(
    plan_map: dict[str, list[TradePlan]],
    manual_map: dict[str, ResearchPoolItem],
) -> set[str]:
    if _has_current_auto_candidate_batch(manual_map):
        return set(manual_map)
    return set(plan_map) | set(manual_map)


def load_workspace_symbols(
    db: Session,
    pool_name: str = "manual",
    include_growth_board: bool = False,
) -> list[str]:
    plan_map = _load_latest_trade_plans(db)
    manual_map = _load_manual_pool_items(db, pool_name=pool_name)
    return _filter_workspace_symbols(
        sorted(_workspace_symbol_candidates(plan_map, manual_map)),
        manual_map=manual_map,
        include_growth_board=include_growth_board,
    )


def _filter_growth_board_symbols(symbols: list[str], include_growth_board: bool) -> list[str]:
    if include_growth_board:
        return symbols
    return [symbol for symbol in symbols if not is_growth_board_symbol(symbol)]


def _filter_workspace_symbols(
    symbols: list[str],
    *,
    manual_map: dict[str, ResearchPoolItem],
    include_growth_board: bool,
) -> list[str]:
    if include_growth_board:
        return symbols
    return [symbol for symbol in symbols if not is_growth_board_symbol(symbol)]


def _to_workspace_plan(
    db: Session,
    plan: TradePlan,
    intraday_guard: IntradayPlanGuard | None = None,
    market_stress: dict[str, Any] | None = None,
) -> WorkspacePlan:
    state = _apply_market_stress_plan_guard(_plan_execution_state(db, plan), market_stress)
    can_buy_now, execution_status, execution_label, execution_note = _apply_intraday_plan_guard(
        state,
        intraday_guard,
    )
    return WorkspacePlan(
        id=plan.id,
        rule_id=plan.rule_id,
        strategy_type=plan.strategy_type,
        plan_date=plan.plan_date.isoformat(),
        trade_date=plan.trade_date.isoformat(),
        position_size=float(plan.position_size),
        confidence_score=_float(plan.confidence_score),
        entry_trigger_price=_float(plan.entry_trigger_price),
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
    latest_quote: RealtimeQuote | None = None,
    intraday_guards: dict[str, IntradayPlanGuard] | None = None,
    market_stress: dict[str, Any] | None = None,
    data_evidence_risks: dict[str, dict[str, object]] | None = None,
) -> WorkspaceItem:
    recent_bars = _load_recent_bars(db, symbol)
    latest_bar = recent_bars[-1] if recent_bars else None
    feature_date, feature_snapshot = _latest_feature_snapshot(db, symbol)
    route_score = feature_snapshot.get("route_score")
    route_label = feature_snapshot.get("route_label")
    route_reason = feature_snapshot.get("route_reason")
    paper_positions = _load_recent_paper_positions(db, symbol)
    quote_change_pct = _quote_change_pct(latest_quote)
    source_parts = []
    if plans:
        source_parts.append("auto")
    if manual:
        source_parts.append("manual")
    manual_tags = (manual.tags_json or {}).get("tags", []) if manual else []
    candidate_tier = _tag_text(manual_tags, "tier:")
    candidate_tier_reason = _candidate_tier_reason(manual_tags, candidate_tier)

    return WorkspaceItem(
        symbol=symbol,
        name=security.name if security else None,
        industry=security.industry if security else None,
        sector_style=security.sector_style if security else None,
        source="+".join(source_parts) or "unknown",
        manual_note=manual.note if manual else None,
        manual_tags=manual_tags,
        candidate_rank=_tag_number(manual_tags, "rank:", int),
        candidate_score=_tag_number(manual_tags, "score:", float),
        candidate_tier=candidate_tier,
        candidate_tier_label=_candidate_tier_label(candidate_tier),
        candidate_tier_reason=candidate_tier_reason,
        startup_signal_score=_tag_number(manual_tags, "startup_signal_score:", float),
        startup_signal_label=_tag_text(manual_tags, "startup_signal_label:"),
        startup_signal_reasons=_tag_texts(manual_tags, "startup_signal_reason:"),
        feature_date=feature_date,
        latest_trade_date=latest_bar.trade_date.isoformat() if latest_bar else None,
        latest_close=_float(latest_bar.close) if latest_bar else None,
        current_price=_float(latest_quote.price) if latest_quote else None,
        day_change_pct=(
            quote_change_pct if quote_change_pct is not None else _daily_change_pct(latest_bar)
        ),
        quote_time=latest_quote.quote_time.isoformat(timespec="seconds") if latest_quote else None,
        return_5d=_return_from_bars(recent_bars, 5),
        return_20d=_return_from_bars(recent_bars, 20),
        trend_score=_float(feature_snapshot.get("trend_score")) if feature_snapshot else None,
        relative_strength_score=_float(feature_snapshot.get("relative_strength_score"))
        if feature_snapshot
        else None,
        sector_strength_score=_float(feature_snapshot.get("sector_strength_score"))
        if feature_snapshot
        else None,
        volume_confirmation_score=_float(feature_snapshot.get("volume_confirmation_score"))
        if feature_snapshot
        else None,
        risk_score=_float(feature_snapshot.get("risk_score")) if feature_snapshot else None,
        overheat_score=_float(feature_snapshot.get("overheat_score")) if feature_snapshot else None,
        volume_trap_risk_score=_float(feature_snapshot.get("volume_trap_risk_score"))
        if feature_snapshot
        else None,
        distance_to_ma20=_float(feature_snapshot.get("distance_to_ma20"))
        if feature_snapshot
        else None,
        amount_percentile_60d=_float(feature_snapshot.get("amount_percentile_60d"))
        if feature_snapshot
        else None,
        amount_ratio_5d=_float(feature_snapshot.get("amount_ratio_5d"))
        if feature_snapshot
        else None,
        pullback_volume_ratio=_float(feature_snapshot.get("pullback_volume_ratio"))
        if feature_snapshot
        else None,
        ma20_slope_20d=_float(feature_snapshot.get("ma20_slope_20d"))
        if feature_snapshot
        else None,
        ma60_slope_20d=_float(feature_snapshot.get("ma60_slope_20d"))
        if feature_snapshot
        else None,
        ma_alignment_score=_float(feature_snapshot.get("ma_alignment_score"))
        if feature_snapshot
        else None,
        trend_quality_score=_float(feature_snapshot.get("trend_quality_score"))
        if feature_snapshot
        else None,
        route_score=_float(route_score) if route_score is not None else None,
        route_label=str(route_label) if route_label is not None else None,
        route_reason=str(route_reason) if route_reason is not None else None,
        plan_availability=_plan_availability(
            plans=plans,
            manual_tags=manual_tags,
            candidate_tier=candidate_tier,
            candidate_tier_reason=candidate_tier_reason,
            data_evidence_risk=(data_evidence_risks or {}).get(feature_date or ""),
            feature_snapshot=feature_snapshot,
        ),
        plans=[
            _to_workspace_plan(
                db,
                plan,
                (intraday_guards or {}).get(plan.symbol),
                market_stress,
            )
            for plan in plans
        ],
        paper_trade_summaries=_summarize_paper_trades(paper_positions),
        recent_paper_trades=[
            _to_paper_trade_item(item, latest_bar, latest_quote) for item in paper_positions[:10]
        ],
    )


def load_stock_workspace_items(
    db: Session,
    *,
    pool_name: str = "manual",
    limit: int = 200,
    include_growth_board: bool = False,
    market_stress: dict[str, Any] | None = None,
) -> list[WorkspaceItem]:
    plan_map = _load_latest_trade_plans(db)
    manual_map = _load_manual_pool_items(db, pool_name=pool_name)
    symbols = _filter_workspace_symbols(
        sorted(_workspace_symbol_candidates(plan_map, manual_map)),
        manual_map=manual_map,
        include_growth_board=include_growth_board,
    )[:limit]

    if not symbols:
        return []

    intraday_guards = _load_intraday_plan_guards(
        db,
        pool_name=pool_name,
        include_growth_board=include_growth_board,
        market_stress=market_stress,
    )
    securities = {
        item.symbol: item
        for item in db.execute(select(Security).where(Security.symbol.in_(symbols))).scalars()
    }
    latest_quotes = _load_latest_quotes(db, symbols)
    feature_dates = {
        row.trade_date.isoformat()
        for row in db.execute(
            select(
                StockFeatureDaily.symbol,
                func.max(StockFeatureDaily.trade_date).label("trade_date"),
            )
            .where(StockFeatureDaily.symbol.in_(symbols))
            .group_by(StockFeatureDaily.symbol)
        )
        if row.trade_date is not None
    }
    data_evidence_risks = _data_evidence_risks(db, feature_dates)

    rows: list[WorkspaceItem] = []
    for symbol in symbols:
        rows.append(
            _build_workspace_item(
                db,
                symbol=symbol,
                security=securities.get(symbol),
                manual=manual_map.get(symbol),
                plans=plan_map.get(symbol, []),
                latest_quote=latest_quotes.get(symbol),
                intraday_guards=intraday_guards,
                market_stress=market_stress,
                data_evidence_risks=data_evidence_risks,
            )
        )

    return sorted(
        rows,
        key=lambda item: (
            0 if any(trade.status == "open" for trade in item.recent_paper_trades) else 1,
            item.candidate_rank if item.candidate_rank is not None else 999,
            0 if "auto" in item.source else 1,
            -(
                item.candidate_score
                or max((plan.confidence_score or 0 for plan in item.plans), default=0)
            ),
            item.symbol,
        ),
    )


def load_stock_workspace_item(
    db: Session,
    *,
    symbol: str,
    pool_name: str = "manual",
    include_growth_board: bool = False,
    market_stress: dict[str, Any] | None = None,
) -> WorkspaceItem | None:
    manual_map = _load_manual_pool_items(db, pool_name=pool_name)
    if not include_growth_board and symbol not in _filter_workspace_symbols(
        [symbol],
        manual_map=manual_map,
        include_growth_board=include_growth_board,
    ):
        return None
    plan_map = _load_latest_trade_plans(db)
    if symbol not in plan_map and symbol not in manual_map:
        return None

    security = db.execute(select(Security).where(Security.symbol == symbol)).scalar_one_or_none()
    latest_quote = _load_latest_quotes(db, [symbol]).get(symbol)
    intraday_guards = _load_intraday_plan_guards(
        db,
        pool_name=pool_name,
        include_growth_board=include_growth_board,
        market_stress=market_stress,
    )
    return _build_workspace_item(
        db,
        symbol=symbol,
        security=security,
        manual=manual_map.get(symbol),
        plans=plan_map.get(symbol, []),
        latest_quote=latest_quote,
        intraday_guards=intraday_guards,
        market_stress=market_stress,
    )
