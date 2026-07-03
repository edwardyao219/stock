from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from services.engine.backtest.replay import run_historical_replay
from services.jobs.pipeline import (
    prepare_next_trade_session,
    resolve_next_trade_date,
    run_after_close_session,
    run_daily_research_pipeline,
    run_intraday_trade_session,
)
from services.shared.time import now_local

router = APIRouter()

PipelineStage = Literal["daily", "prepare", "intraday", "after-close"]


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


def _today() -> str:
    return now_local().date().isoformat()


def _next_date(value: str) -> str:
    return resolve_next_trade_date(value)


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
