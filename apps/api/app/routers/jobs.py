from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.engine.backtest.replay import run_historical_replay
from services.jobs.pipeline import (
    prepare_next_trade_session,
    resolve_next_trade_date,
    run_after_close_session,
    run_daily_research_pipeline,
    run_intraday_trade_session,
)
from services.jobs.status import read_after_close_status
from services.shared.database import get_db
from services.shared.models import BacktestTradeRecord, RulePerformanceDaily
from services.shared.time import now_local

router = APIRouter()

PipelineStage = Literal["daily", "prepare", "intraday", "after-close"]
DbSession = Annotated[Session, Depends(get_db)]
RULE_REGRESSION_TASK = "services.jobs.tasks.run_rule_regression_task"


class PipelineRunRequest(BaseModel):
    stage: PipelineStage
    trade_date: str | None = None
    next_trade_date: str | None = None
    limit: int = 200
    account: str = "default"
    force: bool = False
    full_market_sync: bool = False
    disable_learning_adjustments: bool = False
    dry_run_entries: bool = False
    dry_run_exits: bool = False


class PipelineStepResponse(BaseModel):
    name: str
    status: str
    detail: str
    summary: str | None = None
    details: list[str] = []


class PipelineRunResponse(BaseModel):
    trade_date: str
    next_trade_date: str
    stage: str
    steps: list[PipelineStepResponse]


class HistoricalReplayRunRequest(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    symbols: list[str] | None = None
    preset: str | None = None
    account: str = "历史回放"
    initial_cash: float = 1_000_000
    limit: int = 30
    use_learning_adjustments: bool = True
    generate_learning: bool = True
    dry_run: bool = False


class HistoricalReplayDayResponse(BaseModel):
    trade_date: str
    next_trade_date: str | None
    feature_rows: int
    sector_rows: int
    contexts: int
    candidates: int = 0
    plans: int
    written_plans: int
    opened: int
    closed: int
    skipped: int
    paper_reviews: int
    backtest_trades: int = 0
    paper_learning: int
    backtest_learning: int
    messages: list[str]


class HistoricalReplayAccountSummaryResponse(BaseModel):
    initial_cash: float
    cash: float
    market_value: float
    equity: float
    total_return_pct: float
    realized_pnl: float
    open_positions: int
    closed_positions: int
    win_rate: float | None
    avg_closed_return_pct: float | None


class HistoricalReplayRunResponse(BaseModel):
    start_date: str
    end_date: str
    account: str
    preset: str | None = None
    symbols: list[str]
    processed_days: int
    generated_plans: int
    opened: int
    closed: int
    skipped: int
    account_summary: HistoricalReplayAccountSummaryResponse
    days: list[HistoricalReplayDayResponse]


class RuleRegressionStatusResponse(BaseModel):
    status: Literal["running", "queued", "idle", "never_run"]
    is_running: bool
    active_tasks: int
    reserved_tasks: int
    scheduled_tasks: int
    latest_run_date: str | None
    latest_trade_count: int
    latest_performance_rows: int
    message: str


class AfterCloseStatusResponse(BaseModel):
    trade_date: str
    next_trade_date: str | None = None
    status: str
    message: str
    updated_at: str | None = None
    candidate_count: int = 0
    plan_count: int = 0
    dingtalk_statuses: list[str] = []
    market_summary: str | None = None
    tushare_evidence_health: dict[str, Any] = Field(default_factory=dict)
    scheduler_health: dict[str, Any] = Field(default_factory=dict)
    source: str = "cache"


def _today() -> str:
    return now_local().date().isoformat()


def _next_date(value: str) -> str:
    return resolve_next_trade_date(value)


def _task_name(task: Any) -> str | None:
    if not isinstance(task, dict):
        return None
    if task.get("name"):
        return str(task["name"])
    request = task.get("request")
    if isinstance(request, dict) and request.get("name"):
        return str(request["name"])
    return None


def _count_rule_regression_tasks(worker_tasks: dict[str, list[Any]] | None) -> int:
    if not worker_tasks:
        return 0
    return sum(
        1
        for tasks in worker_tasks.values()
        for task in tasks
        if _task_name(task) == RULE_REGRESSION_TASK
    )


def _rule_regression_celery_counts() -> dict[str, int]:
    try:
        from services.jobs.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1)
        return {
            "active": _count_rule_regression_tasks(inspector.active()),
            "reserved": _count_rule_regression_tasks(inspector.reserved()),
            "scheduled": _count_rule_regression_tasks(inspector.scheduled()),
        }
    except Exception:
        return {"active": 0, "reserved": 0, "scheduled": 0}


@router.post("/pipeline/run", response_model=PipelineRunResponse)
def run_pipeline_stage(payload: PipelineRunRequest) -> PipelineRunResponse:
    trade_date = payload.trade_date or _today()
    next_trade_date = payload.next_trade_date or _next_date(trade_date)

    if payload.stage == "prepare":
        result = prepare_next_trade_session(
            trade_date,
            next_trade_date,
            limit=payload.limit,
            use_learning_adjustments=not payload.disable_learning_adjustments,
            full_market_sync=payload.full_market_sync,
            force=payload.force,
        )
    elif payload.stage == "intraday":
        result = run_intraday_trade_session(
            trade_date,
            account=payload.account,
            execute_entries=not payload.dry_run_entries,
            execute_exits=not payload.dry_run_exits,
            force=payload.force,
        )
    elif payload.stage == "after-close":
        result = run_after_close_session(
            trade_date,
            next_trade_date,
            limit=payload.limit,
            account=payload.account,
            use_learning_adjustments=not payload.disable_learning_adjustments,
            full_market_sync=payload.full_market_sync,
        )
    else:
        result = run_daily_research_pipeline(trade_date, next_trade_date)

    return PipelineRunResponse(**result.to_dict())


@router.post("/historical-replay/run", response_model=HistoricalReplayRunResponse)
def run_historical_replay_job(payload: HistoricalReplayRunRequest) -> HistoricalReplayRunResponse:
    result = run_historical_replay(
        start_date=payload.start_date,
        end_date=payload.end_date,
        symbols=payload.symbols,
        preset=payload.preset,
        account_name=payload.account,
        initial_cash=Decimal(str(payload.initial_cash)),
        limit=payload.limit,
        use_learning_adjustments=payload.use_learning_adjustments,
        generate_learning=payload.generate_learning,
        dry_run=payload.dry_run,
    )
    return HistoricalReplayRunResponse(**result.to_dict())


@router.get("/after-close/status", response_model=AfterCloseStatusResponse)
def get_after_close_status(trade_date: str | None = None) -> AfterCloseStatusResponse:
    target_date = trade_date or _today()
    cached = read_after_close_status(target_date)
    if cached:
        return AfterCloseStatusResponse(**cached)
    return AfterCloseStatusResponse(
        trade_date=target_date,
        status="unknown",
        message=f"{target_date} 还没有收盘推送记录；如果刚重启过服务，请以钉钉和候选池为准。",
        source="empty",
    )


@router.get("/rule-regression/status", response_model=RuleRegressionStatusResponse)
def get_rule_regression_status(db: DbSession) -> RuleRegressionStatusResponse:
    counts = _rule_regression_celery_counts()
    active = counts.get("active", 0)
    reserved = counts.get("reserved", 0)
    scheduled = counts.get("scheduled", 0)

    latest_run_date = db.execute(
        select(func.max(BacktestTradeRecord.run_date))
    ).scalar_one_or_none()
    latest_trade_count = 0
    latest_performance_rows = 0
    latest_run_date_text = None
    if latest_run_date is not None:
        latest_run_date_text = latest_run_date.isoformat()
        latest_trade_count = db.execute(
            select(func.count()).select_from(BacktestTradeRecord).where(
                BacktestTradeRecord.run_date == latest_run_date
            )
        ).scalar_one()
        latest_performance_rows = db.execute(
            select(func.count()).select_from(RulePerformanceDaily).where(
                RulePerformanceDaily.trade_date == latest_run_date
            )
        ).scalar_one()

    if active > 0:
        status: Literal["running", "queued", "idle", "never_run"] = "running"
        message = f"规则回归运行中；active {active}，排队 {reserved + scheduled}。"
    elif reserved + scheduled > 0:
        status = "queued"
        message = f"规则回归排队中；reserved {reserved}，scheduled {scheduled}。"
    elif latest_run_date is None:
        status = "never_run"
        message = "还没有回归落库记录。"
    else:
        status = "idle"
        message = (
            f"规则回归空闲；最近一次 {latest_run_date_text}，"
            f"交易样本 {latest_trade_count}，表现行 {latest_performance_rows}。"
        )

    return RuleRegressionStatusResponse(
        status=status,
        is_running=status == "running",
        active_tasks=active,
        reserved_tasks=reserved,
        scheduled_tasks=scheduled,
        latest_run_date=latest_run_date_text,
        latest_trade_count=latest_trade_count,
        latest_performance_rows=latest_performance_rows,
        message=message,
    )
