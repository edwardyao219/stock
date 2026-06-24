from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from services.jobs.pipeline import (
    prepare_next_trade_session,
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
    disable_learning_adjustments: bool = False
    dry_run_exits: bool = False


class PipelineStepResponse(BaseModel):
    name: str
    status: str
    detail: str


class PipelineRunResponse(BaseModel):
    trade_date: str
    next_trade_date: str
    stage: str
    steps: list[PipelineStepResponse]


def _today() -> str:
    return now_local().date().isoformat()


def _next_date(value: str) -> str:
    return (date.fromisoformat(value) + timedelta(days=1)).isoformat()


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
            force=payload.force,
        )
    elif payload.stage == "intraday":
        result = run_intraday_trade_session(
            trade_date,
            account=payload.account,
            execute_exits=not payload.dry_run_exits,
            force=payload.force,
        )
    elif payload.stage == "after-close":
        result = run_after_close_session(
            trade_date,
            next_trade_date,
            limit=payload.limit,
            account=payload.account,
        )
    else:
        result = run_daily_research_pipeline(trade_date, next_trade_date)

    return PipelineRunResponse(**result.to_dict())
