from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.engine.research_pool.repository import add_symbols_to_pool
from services.engine.workspace.repository import (
    load_stock_workspace_item,
    load_stock_workspace_items,
)
from services.shared.database import get_db

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


class WorkspacePlanResponse(BaseModel):
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


class WorkspaceStockResponse(BaseModel):
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
    plans: list[WorkspacePlanResponse]
    paper_trade_summaries: list[PaperTradeSummaryResponse]
    recent_paper_trades: list[PaperTradeResponse]


class ManualStockRequest(BaseModel):
    symbol: str
    note: str | None = None
    tags: list[str] = []
    pool_name: str = "manual"


def _to_response(item) -> WorkspaceStockResponse:
    return WorkspaceStockResponse(
        symbol=item.symbol,
        name=item.name,
        industry=item.industry,
        sector_style=item.sector_style,
        source=item.source,
        manual_note=item.manual_note,
        manual_tags=item.manual_tags,
        latest_trade_date=item.latest_trade_date,
        latest_close=item.latest_close,
        return_5d=item.return_5d,
        return_20d=item.return_20d,
        plans=[
            WorkspacePlanResponse(
                id=plan.id,
                rule_id=plan.rule_id,
                strategy_type=plan.strategy_type,
                plan_date=plan.plan_date,
                trade_date=plan.trade_date,
                position_size=plan.position_size,
                confidence_score=plan.confidence_score,
                initial_stop=plan.initial_stop,
                take_profit_1=plan.take_profit_1,
                take_profit_2=plan.take_profit_2,
                status=plan.status,
                can_buy_now=plan.can_buy_now,
                execution_status=plan.execution_status,
                execution_label=plan.execution_label,
                execution_note=plan.execution_note,
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
            )
            for trade in item.recent_paper_trades
        ],
    )


@router.get("/stocks", response_model=list[WorkspaceStockResponse])
def list_workspace_stocks(
    db: DbSession,
    pool_name: str = "manual",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[WorkspaceStockResponse]:
    return [
        _to_response(item)
        for item in load_stock_workspace_items(db, pool_name=pool_name, limit=limit)
    ]


@router.get("/stocks/{symbol}", response_model=WorkspaceStockResponse)
def get_workspace_stock(
    symbol: str,
    db: DbSession,
    pool_name: str = "manual",
) -> WorkspaceStockResponse:
    item = load_stock_workspace_item(db, symbol=symbol, pool_name=pool_name)
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
        tags=payload.tags,
    )
    db.commit()

    item = load_stock_workspace_item(db, symbol=symbol, pool_name=payload.pool_name)
    if item is None:
        raise HTTPException(status_code=500, detail="手动股票已保存，但工作台加载失败")
    return _to_response(item)
