from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.database import get_db
from services.shared.models import DailyBar

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


class CandleResponse(BaseModel):
    time: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    amount: float | None
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _moving_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    running_sum = 0.0
    for index, value in enumerate(values):
        running_sum += value
        if index >= window:
            running_sum -= values[index - window]
        if index + 1 < window:
            result.append(None)
        else:
            result.append(running_sum / window)
    return result


@router.get("/overview")
def get_market_overview() -> dict[str, object]:
    return {
        "market_regime": "unknown",
        "emotion_score": None,
        "strong_sectors": [],
        "message": "Market overview will be generated after data ingestion is implemented.",
    }


@router.get("/candles/{symbol}", response_model=list[CandleResponse])
def get_symbol_candles(
    symbol: str,
    db: DbSession,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: Annotated[int, Query(ge=30, le=1000)] = 240,
) -> list[CandleResponse]:
    stmt = select(DailyBar).where(DailyBar.symbol == symbol)
    if start_date:
        stmt = stmt.where(DailyBar.trade_date >= date.fromisoformat(start_date))
    if end_date:
        stmt = stmt.where(DailyBar.trade_date <= date.fromisoformat(end_date))
    if not start_date:
        stmt = stmt.order_by(DailyBar.trade_date.desc()).limit(limit)
        bars = list(reversed(db.execute(stmt).scalars().all()))
    else:
        stmt = stmt.order_by(DailyBar.trade_date).limit(limit)
        bars = list(db.execute(stmt).scalars().all())

    closes = [float(item.close) for item in bars]
    ma5 = _moving_average(closes, 5)
    ma10 = _moving_average(closes, 10)
    ma20 = _moving_average(closes, 20)
    ma60 = _moving_average(closes, 60)

    return [
        CandleResponse(
            time=item.trade_date,
            open=float(item.open),
            high=float(item.high),
            low=float(item.low),
            close=float(item.close),
            volume=_float(item.volume),
            amount=_float(item.amount),
            ma5=ma5[index],
            ma10=ma10[index],
            ma20=ma20[index],
            ma60=ma60[index],
        )
        for index, item in enumerate(bars)
    ]
