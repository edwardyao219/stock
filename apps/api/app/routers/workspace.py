from datetime import datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.collector.realtime import sync_realtime_quotes
from services.engine.intraday.candidates import discover_intraday_candidates
from services.engine.research_pool.manual_research import (
    ManualResearchResult,
    refresh_manual_stock_research,
)
from services.engine.research_pool.repository import (
    add_symbols_to_pool,
    filter_latest_candidate_batch_items,
)
from services.engine.workspace.repository import (
    load_stock_workspace_item,
    load_stock_workspace_items,
    load_workspace_symbols,
)
from services.shared.database import get_db
from services.shared.models import RealtimeQuote, ResearchPoolItem
from services.shared.symbols import is_growth_board_symbol
from services.shared.time import now_local

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


class PlanEvidenceResponse(BaseModel):
    category: str
    label: str
    value: str
    verdict: str
    note: str


class WorkspacePlanResponse(BaseModel):
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
    evidence: list[PlanEvidenceResponse]


class PaperTradeSummaryResponse(BaseModel):
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


class PaperTradeResponse(BaseModel):
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


class ManualRefreshResponse(BaseModel):
    symbol: str
    security_rows: int
    daily_rows: int
    feature_rows: int
    sector_rows: int
    fundamental_ok: int
    formal_plan_rows: int
    watch_plan_rows: int
    feature_date: str | None
    warnings: list[str]


class IntradayCandidateResponse(BaseModel):
    symbol: str
    name: str | None
    sector: str | None
    quote_time: str
    price: float | None
    day_change_pct: float | None
    candidate_rank: int | None
    candidate_score: float | None
    intraday_state: str
    intraday_label: str
    intraday_score: float
    review_window: str
    review_window_label: str
    sector_signal: str
    sector_signal_label: str
    sector_quality_score: float
    sector_quality_label: str
    selection_tier: str
    selection_tier_label: str
    selection_reason: str
    summary: str
    theme_signal_label: str | None = None
    theme_signal_reason: str | None = None
    caution_reasons: list[str]
    support_flags: list[str]
    risk_flags: list[str]


class CandidateBatchResponse(BaseModel):
    auto_feature_date: str | None = None
    auto_hold_until: str | None = None
    auto_batch_id: str | None = None
    source_item_count: int
    usable_item_count: int
    current_auto_candidate_count: int
    manual_focus_count: int
    stale_auto_candidate_count: int


class IntradayCandidateListResponse(BaseModel):
    trade_date: str
    as_of: str | None = None
    pool_name: str
    candidate_count: int
    candidate_batch: CandidateBatchResponse
    candidates: list[IntradayCandidateResponse]


class IntradayCandidateSnapshotResponse(IntradayCandidateListResponse):
    stage: str
    stage_label: str


def _active_intraday_candidate_symbols(
    db: Session,
    *,
    pool_name: str,
    include_growth_board: bool,
) -> list[str]:
    stmt = (
        select(ResearchPoolItem)
        .where(ResearchPoolItem.pool_name == pool_name)
        .where(ResearchPoolItem.status == "active")
    )
    symbols: list[str] = []
    for item in filter_latest_candidate_batch_items(list(db.execute(stmt).scalars())):
        tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
        if not (
            "after_close_candidate" in tags
            or "next_session" in tags
            or "manual_focus" in tags
        ):
            continue
        if not include_growth_board and is_growth_board_symbol(item.symbol):
            continue
        symbols.append(item.symbol)
    return sorted(set(symbols))


class IntradaySnapshotLearningResponse(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None
    from_stage: str
    from_stage_label: str
    to_stage: str
    to_stage_label: str
    from_state: str
    from_label: str
    to_state: str
    to_label: str
    from_score: float
    to_score: float
    score_delta: float
    verdict: str
    verdict_label: str
    reason: str


class IntradaySectorVerdictResponse(BaseModel):
    sector: str
    transition_count: int
    weakened_count: int
    repaired_count: int
    held_strength_count: int
    stayed_weak_count: int


class IntradaySnapshotLearningSummaryResponse(BaseModel):
    sample_days: int
    transition_count: int
    verdict_counts: dict[str, int]
    sector_verdicts: list[IntradaySectorVerdictResponse]
    pattern_notes: list[str]


class IntradayCandidateSnapshotListResponse(BaseModel):
    trade_date: str
    pool_name: str
    snapshots: list[IntradayCandidateSnapshotResponse]
    learning: list[IntradaySnapshotLearningResponse] = []
    learning_summary: IntradaySnapshotLearningSummaryResponse | None = None


class WorkspaceStockResponse(BaseModel):
    symbol: str
    name: str | None
    industry: str | None
    sector_style: str | None
    source: str
    manual_note: str | None
    manual_tags: list[str]
    candidate_rank: int | None
    candidate_score: float | None
    candidate_tier: str | None = None
    candidate_tier_label: str | None = None
    candidate_tier_reason: str | None = None
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
    plans: list[WorkspacePlanResponse]
    paper_trade_summaries: list[PaperTradeSummaryResponse]
    recent_paper_trades: list[PaperTradeResponse]
    manual_refresh: ManualRefreshResponse | None = None


class ManualStockRequest(BaseModel):
    symbol: str
    note: str | None = None
    tags: list[str] = []
    pool_name: str = "manual"
    refresh_research: bool = True
    include_growth_board: bool = False


def _manual_refresh_response(result: ManualResearchResult) -> ManualRefreshResponse:
    return ManualRefreshResponse(
        symbol=result.symbol,
        security_rows=result.security_rows,
        daily_rows=result.daily_rows,
        feature_rows=result.feature_rows,
        sector_rows=result.sector_rows,
        fundamental_ok=result.fundamental_ok,
        formal_plan_rows=result.formal_plan_rows,
        watch_plan_rows=result.watch_plan_rows,
        feature_date=result.feature_date,
        warnings=result.warnings,
    )


def _to_response(
    item,
    manual_refresh: ManualRefreshResponse | None = None,
) -> WorkspaceStockResponse:
    return WorkspaceStockResponse(
        symbol=item.symbol,
        name=item.name,
        industry=item.industry,
        sector_style=item.sector_style,
        source=item.source,
        manual_note=item.manual_note,
        manual_tags=item.manual_tags,
        candidate_rank=item.candidate_rank,
        candidate_score=item.candidate_score,
        candidate_tier=item.candidate_tier,
        candidate_tier_label=item.candidate_tier_label,
        candidate_tier_reason=item.candidate_tier_reason,
        feature_date=item.feature_date,
        latest_trade_date=item.latest_trade_date,
        latest_close=item.latest_close,
        current_price=item.current_price,
        day_change_pct=item.day_change_pct,
        quote_time=item.quote_time,
        return_5d=item.return_5d,
        return_20d=item.return_20d,
        trend_score=item.trend_score,
        relative_strength_score=item.relative_strength_score,
        sector_strength_score=item.sector_strength_score,
        volume_confirmation_score=item.volume_confirmation_score,
        risk_score=item.risk_score,
        overheat_score=item.overheat_score,
        volume_trap_risk_score=item.volume_trap_risk_score,
        distance_to_ma20=item.distance_to_ma20,
        amount_percentile_60d=item.amount_percentile_60d,
        amount_ratio_5d=item.amount_ratio_5d,
        pullback_volume_ratio=item.pullback_volume_ratio,
        ma20_slope_20d=item.ma20_slope_20d,
        ma60_slope_20d=item.ma60_slope_20d,
        ma_alignment_score=item.ma_alignment_score,
        trend_quality_score=item.trend_quality_score,
        route_score=item.route_score,
        route_label=item.route_label,
        route_reason=item.route_reason,
        plans=[
            WorkspacePlanResponse(
                id=plan.id,
                rule_id=plan.rule_id,
                strategy_type=plan.strategy_type,
                plan_date=plan.plan_date,
                trade_date=plan.trade_date,
                position_size=plan.position_size,
                confidence_score=plan.confidence_score,
                entry_trigger_price=plan.entry_trigger_price,
                initial_stop=plan.initial_stop,
                take_profit_1=plan.take_profit_1,
                take_profit_2=plan.take_profit_2,
                status=plan.status,
                can_buy_now=plan.can_buy_now,
                execution_status=plan.execution_status,
                execution_label=plan.execution_label,
                execution_note=plan.execution_note,
                evidence=[
                    PlanEvidenceResponse(
                        category=item.category,
                        label=item.label,
                        value=item.value,
                        verdict=item.verdict,
                        note=item.note,
                    )
                    for item in plan.evidence
                ],
            )
            for plan in item.plans
        ],
        paper_trade_summaries=[
            PaperTradeSummaryResponse(
                rule_id=summary.rule_id,
                closed_count=summary.closed_count,
                open_count=summary.open_count,
                win_rate=summary.win_rate,
                avg_return=summary.avg_return,
                total_return=summary.total_return,
                avg_mfe=summary.avg_mfe,
                avg_mae=summary.avg_mae,
                best_return=summary.best_return,
                worst_return=summary.worst_return,
                latest_entry_date=summary.latest_entry_date,
                latest_exit_date=summary.latest_exit_date,
                latest_pnl_pct=summary.latest_pnl_pct,
                latest_exit_reason=summary.latest_exit_reason,
            )
            for summary in item.paper_trade_summaries
        ],
        recent_paper_trades=[
            PaperTradeResponse(
                id=trade.id,
                trade_plan_id=trade.trade_plan_id,
                rule_id=trade.rule_id,
                entry_date=trade.entry_date,
                entry_price=trade.entry_price,
                exit_date=trade.exit_date,
                exit_price=trade.exit_price,
                holding_days=trade.holding_days,
                pnl_pct=trade.pnl_pct,
                mfe_pct=trade.mfe_pct,
                mae_pct=trade.mae_pct,
                highest_price=trade.highest_price,
                lowest_price=trade.lowest_price,
                quantity=trade.quantity,
                status=trade.status,
                exit_reason=trade.exit_reason,
                current_price=trade.current_price,
                current_pnl_pct=trade.current_pnl_pct,
                current_stop=trade.current_stop,
                take_profit_1=trade.take_profit_1,
                quote_time=trade.quote_time,
            )
            for trade in item.recent_paper_trades
        ],
        manual_refresh=manual_refresh,
    )


@router.get("/intraday-candidates", response_model=IntradayCandidateListResponse)
def list_intraday_candidates(
    db: DbSession,
    pool_name: str = "experiment",
    limit: Annotated[int, Query(ge=1, le=50)] = 15,
    formal_limit: Annotated[int, Query(ge=1, le=10)] = 3,
    formal_per_sector_limit: Annotated[int, Query(ge=1, le=5)] = 2,
    include_growth_board: bool = False,
    as_of: str | None = None,
    refresh_quotes: bool = False,
) -> dict:
    current_time = now_local()
    parsed_as_of = datetime.fromisoformat(as_of) if as_of else current_time
    if refresh_quotes and not as_of:
        symbols = _active_intraday_candidate_symbols(
            db,
            pool_name=pool_name,
            include_growth_board=include_growth_board,
        )
        if symbols:
            sync_realtime_quotes(symbols=symbols, quote_time=parsed_as_of)
            db.expire_all()
    return discover_intraday_candidates(
        db,
        trade_date=current_time.date(),
        pool_name=pool_name,
        limit=limit,
        formal_limit=formal_limit,
        formal_per_sector_limit=formal_per_sector_limit,
        include_growth_board=include_growth_board,
        as_of=parsed_as_of,
    )


def _intraday_snapshot_points(current_time: datetime) -> list[tuple[str, str, datetime]]:
    def at_clock(clock: time) -> datetime:
        return datetime.combine(current_time.date(), clock, tzinfo=current_time.tzinfo)

    candidates = [
        (
            "midday",
            "午间复盘",
            at_clock(time(11, 35)),
        ),
        (
            "late_session",
            "尾盘前",
            at_clock(time(14, 50)),
        ),
        ("latest", "最新快照", current_time),
    ]
    points: list[tuple[str, str, datetime]] = []
    seen: set[datetime] = set()
    for stage, label, as_of in candidates:
        if as_of > current_time or as_of in seen:
            continue
        points.append((stage, label, as_of))
        seen.add(as_of)
    return points


def _fixed_intraday_snapshot_points_for_day(value: datetime) -> list[tuple[str, str, datetime]]:
    return [
        ("midday", "午间复盘", datetime.combine(value.date(), time(11, 35), tzinfo=value.tzinfo)),
        (
            "late_session",
            "尾盘前",
            datetime.combine(value.date(), time(14, 50), tzinfo=value.tzinfo),
        ),
        ("latest", "最新快照", datetime.combine(value.date(), time(15, 5), tzinfo=value.tzinfo)),
    ]


def _recent_intraday_trade_dates(db: Session, current_time: datetime, limit: int) -> list:
    stmt = (
        select(RealtimeQuote.trade_date)
        .where(RealtimeQuote.trade_date <= current_time.date())
        .group_by(RealtimeQuote.trade_date)
        .order_by(RealtimeQuote.trade_date.desc())
        .limit(max(1, limit))
    )
    return [item[0] for item in db.execute(stmt).all()]


_SUPPORTIVE_INTRADAY_STATES = {"gap_down_repair", "strong_continuation", "pullback_repair"}
_WEAK_INTRADAY_STATES = {"distribution", "fading", "downside"}


def _snapshot_learning_verdict(
    from_candidate: dict,
    to_candidate: dict,
) -> tuple[str, str, str]:
    from_state = str(from_candidate.get("intraday_state") or "")
    to_state = str(to_candidate.get("intraday_state") or "")
    score_delta = float(to_candidate.get("intraday_score") or 0) - float(
        from_candidate.get("intraday_score") or 0
    )
    if from_state in _SUPPORTIVE_INTRADAY_STATES and to_state in _WEAK_INTRADAY_STATES:
        return "weakened", "转弱", "午间到尾盘前转弱，盘中承接被破坏，后续先降权观察"
    if from_state in _WEAK_INTRADAY_STATES and to_state in _SUPPORTIVE_INTRADAY_STATES:
        return "repaired", "修复", "盘中由弱转强，说明承接恢复，但仍要看板块是否同步"
    if from_state in _SUPPORTIVE_INTRADAY_STATES and to_state in _SUPPORTIVE_INTRADAY_STATES:
        return "held_strength", "保持强势", "盘中强势保持，顺势候选可以继续观察"
    if from_state in _WEAK_INTRADAY_STATES and to_state in _WEAK_INTRADAY_STATES:
        return "stayed_weak", "持续偏弱", "盘中持续偏弱，除非板块重新走强，否则不急着接"
    if score_delta >= 5:
        return "improved", "改善", "盘中评分改善，观察是否有放量和板块配合"
    if score_delta <= -5:
        return "softened", "走弱", "盘中评分回落，先看尾盘资金是否继续撤退"
    return "stable", "平稳", "盘中变化不大，维持原观察级别"


def _build_intraday_snapshot_learning(snapshots: list[dict]) -> list[dict]:
    learning: list[dict] = []
    for earlier, later in zip(snapshots, snapshots[1:], strict=False):
        earlier_by_symbol = {item["symbol"]: item for item in earlier.get("candidates", [])}
        later_by_symbol = {item["symbol"]: item for item in later.get("candidates", [])}
        for symbol in sorted(set(earlier_by_symbol) & set(later_by_symbol)):
            from_candidate = earlier_by_symbol[symbol]
            to_candidate = later_by_symbol[symbol]
            verdict, verdict_label, reason = _snapshot_learning_verdict(
                from_candidate,
                to_candidate,
            )
            from_score = float(from_candidate.get("intraday_score") or 0)
            to_score = float(to_candidate.get("intraday_score") or 0)
            learning.append(
                {
                    "symbol": symbol,
                    "name": to_candidate.get("name") or from_candidate.get("name"),
                    "sector": to_candidate.get("sector") or from_candidate.get("sector"),
                    "from_stage": earlier["stage"],
                    "from_stage_label": earlier["stage_label"],
                    "to_stage": later["stage"],
                    "to_stage_label": later["stage_label"],
                    "from_state": from_candidate["intraday_state"],
                    "from_label": from_candidate["intraday_label"],
                    "to_state": to_candidate["intraday_state"],
                    "to_label": to_candidate["intraday_label"],
                    "from_score": from_score,
                    "to_score": to_score,
                    "score_delta": round(to_score - from_score, 4),
                    "verdict": verdict,
                    "verdict_label": verdict_label,
                    "reason": reason,
                }
            )
    return learning[:20]


def _build_intraday_learning_summary(learning: list[dict], *, sample_days: int) -> dict:
    verdict_counts: dict[str, int] = {}
    sector_counts: dict[str, dict[str, int | str]] = {}
    for item in learning:
        verdict = str(item["verdict"])
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        sector = str(item.get("sector") or "未分类")
        row = sector_counts.setdefault(
            sector,
            {
                "sector": sector,
                "transition_count": 0,
                "weakened_count": 0,
                "repaired_count": 0,
                "held_strength_count": 0,
                "stayed_weak_count": 0,
            },
        )
        row["transition_count"] = int(row["transition_count"]) + 1
        if verdict == "weakened":
            row["weakened_count"] = int(row["weakened_count"]) + 1
        elif verdict == "repaired":
            row["repaired_count"] = int(row["repaired_count"]) + 1
        elif verdict == "held_strength":
            row["held_strength_count"] = int(row["held_strength_count"]) + 1
        elif verdict == "stayed_weak":
            row["stayed_weak_count"] = int(row["stayed_weak_count"]) + 1

    sector_verdicts = sorted(
        sector_counts.values(),
        key=lambda item: (
            int(item["weakened_count"]),
            int(item["transition_count"]),
            str(item["sector"]),
        ),
        reverse=True,
    )[:8]
    pattern_notes: list[str] = []
    if verdict_counts.get("weakened", 0):
        pattern_notes.append(
            f"转弱 {verdict_counts['weakened']} 次：午间强不等于能拿到尾盘，尾盘承接要二次确认"
        )
    if verdict_counts.get("repaired", 0):
        pattern_notes.append(
            f"修复 {verdict_counts['repaired']} 次：盘中回踩能修复的票，次日可继续观察板块配合"
        )
    if verdict_counts.get("held_strength", 0):
        pattern_notes.append(
            f"保持强势 {verdict_counts['held_strength']} 次：顺势票优先看板块同步和量能延续"
        )
    if not pattern_notes:
        pattern_notes.append("样本还少，先观察阶段变化，不调整策略参数")

    return {
        "sample_days": sample_days,
        "transition_count": len(learning),
        "verdict_counts": verdict_counts,
        "sector_verdicts": sector_verdicts,
        "pattern_notes": pattern_notes,
    }


def _intraday_snapshots_for_points(
    db: Session,
    *,
    trade_date,
    points: list[tuple[str, str, datetime]],
    pool_name: str,
    limit: int,
    include_growth_board: bool,
    formal_limit: int = 3,
    formal_per_sector_limit: int = 2,
    sector_feedback: dict[str, dict[str, int]] | None = None,
) -> list[dict]:
    snapshots = []
    for stage, label, as_of in points:
        result = discover_intraday_candidates(
            db,
            trade_date=trade_date,
            pool_name=pool_name,
            limit=limit,
            formal_limit=formal_limit,
            formal_per_sector_limit=formal_per_sector_limit,
            include_growth_board=include_growth_board,
            as_of=as_of,
            sector_feedback=sector_feedback,
        )
        snapshots.append(
            {
                **result,
                "stage": stage,
                "stage_label": label,
            }
        )
    return snapshots


@router.get(
    "/intraday-candidate-snapshots",
    response_model=IntradayCandidateSnapshotListResponse,
)
def list_intraday_candidate_snapshots(
    db: DbSession,
    pool_name: str = "experiment",
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
    formal_limit: Annotated[int, Query(ge=1, le=10)] = 3,
    formal_per_sector_limit: Annotated[int, Query(ge=1, le=5)] = 2,
    include_growth_board: bool = False,
    lookback_days: Annotated[int, Query(ge=1, le=20)] = 5,
) -> dict:
    current_time = now_local()
    historical_learning: list[dict] = []
    trade_dates = _recent_intraday_trade_dates(db, current_time, lookback_days)
    for trade_date in trade_dates:
        if trade_date == current_time.date():
            continue
        day_time = datetime.combine(trade_date, current_time.time(), tzinfo=current_time.tzinfo)
        day_snapshots = _intraday_snapshots_for_points(
            db,
            trade_date=trade_date,
            points=_fixed_intraday_snapshot_points_for_day(day_time),
            pool_name=pool_name,
            limit=limit,
            include_growth_board=include_growth_board,
            formal_limit=formal_limit,
            formal_per_sector_limit=formal_per_sector_limit,
        )
        historical_learning.extend(_build_intraday_snapshot_learning(day_snapshots))

    historical_summary = _build_intraday_learning_summary(
        historical_learning,
        sample_days=len([item for item in trade_dates if item != current_time.date()]),
    )
    sector_feedback = {
        str(item["sector"]): {
            "weakened_count": int(item["weakened_count"]),
            "repaired_count": int(item["repaired_count"]),
            "held_strength_count": int(item["held_strength_count"]),
            "stayed_weak_count": int(item["stayed_weak_count"]),
        }
        for item in historical_summary["sector_verdicts"]
    }
    snapshots = _intraday_snapshots_for_points(
        db,
        trade_date=current_time.date(),
        points=_intraday_snapshot_points(current_time),
        pool_name=pool_name,
        limit=limit,
        include_growth_board=include_growth_board,
        formal_limit=formal_limit,
        formal_per_sector_limit=formal_per_sector_limit,
        sector_feedback=sector_feedback,
    )
    current_learning = _build_intraday_snapshot_learning(snapshots)
    all_learning = [*historical_learning, *current_learning]

    return {
        "trade_date": current_time.date().isoformat(),
        "pool_name": pool_name,
        "snapshots": snapshots,
        "learning": current_learning,
        "learning_summary": _build_intraday_learning_summary(
            all_learning,
            sample_days=len(trade_dates),
        ),
    }


@router.get("/stocks", response_model=list[WorkspaceStockResponse])
def list_workspace_stocks(
    db: DbSession,
    pool_name: str = "experiment",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    include_growth_board: bool = False,
) -> list[WorkspaceStockResponse]:
    return [
        _to_response(item)
        for item in load_stock_workspace_items(
            db,
            pool_name=pool_name,
            limit=limit,
            include_growth_board=include_growth_board,
        )
    ]


@router.post("/refresh", response_model=list[WorkspaceStockResponse])
def refresh_workspace_stocks(
    db: DbSession,
    pool_name: str = "experiment",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    include_growth_board: bool = False,
) -> list[WorkspaceStockResponse]:
    symbols = load_workspace_symbols(
        db,
        pool_name=pool_name,
        include_growth_board=include_growth_board,
    )[:limit]
    if symbols:
        try:
            sync_realtime_quotes(symbols=symbols)
        except Exception:
            db.rollback()
        db.expire_all()
    return [
        _to_response(item)
        for item in load_stock_workspace_items(
            db,
            pool_name=pool_name,
            limit=limit,
            include_growth_board=include_growth_board,
        )
    ]


@router.get("/stocks/{symbol}", response_model=WorkspaceStockResponse)
def get_workspace_stock(
    symbol: str,
    db: DbSession,
    pool_name: str = "experiment",
    include_growth_board: bool = False,
) -> WorkspaceStockResponse:
    item = load_stock_workspace_item(
        db,
        symbol=symbol,
        pool_name=pool_name,
        include_growth_board=include_growth_board,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="股票不在工作台列表中")
    return _to_response(item)


@router.post("/manual-stocks", response_model=WorkspaceStockResponse)
def add_manual_stock(
    payload: ManualStockRequest,
    db: DbSession,
) -> WorkspaceStockResponse:
    symbol = payload.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="股票代码不能为空")
    add_symbols_to_pool(
        db,
        [symbol],
        pool_name=payload.pool_name,
        note=payload.note,
        tags=list(dict.fromkeys([*payload.tags, "manual_focus"])),
    )
    db.commit()

    if payload.refresh_research:
        try:
            refresh_result = refresh_manual_stock_research(symbol, pool_name=payload.pool_name)
        except Exception as exc:
            refresh_result = ManualResearchResult(
                symbol=symbol,
                warnings=[f"手动关注刷新失败：{type(exc).__name__}: {exc}"],
            )
    else:
        refresh_result = ManualResearchResult(symbol=symbol)

    db.expire_all()
    item = load_stock_workspace_item(
        db,
        symbol=symbol,
        pool_name=payload.pool_name,
        include_growth_board=True,
    )
    if item is None:
        raise HTTPException(status_code=500, detail="手动股票已保存，但工作台加载失败")
    return _to_response(item, manual_refresh=_manual_refresh_response(refresh_result))
