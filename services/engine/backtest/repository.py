from __future__ import annotations

from datetime import date
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.backtest.models import DailyBacktestInput, FeatureSnapshot
from services.engine.features.repository import load_daily_bars
from services.shared.models import StockFeatureDaily


def load_backtest_input(
    db: Session,
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> DailyBacktestInput:
    bars = load_daily_bars(db, symbol=symbol, start_date=start_date, end_date=end_date)
    stmt = (
        select(StockFeatureDaily)
        .where(StockFeatureDaily.symbol == symbol)
        .order_by(StockFeatureDaily.trade_date)
    )
    if start_date:
        stmt = stmt.where(StockFeatureDaily.trade_date >= start_date)
    if end_date:
        stmt = stmt.where(StockFeatureDaily.trade_date <= end_date)

    snapshots = [
        FeatureSnapshot(
            symbol=row.symbol,
            trade_date=row.trade_date.isoformat(),
            context={"symbol": row.symbol, "trade_date": row.trade_date.isoformat(), **(row.features or {})},
        )
        for row in db.execute(stmt).scalars()
    ]
    return DailyBacktestInput(symbol=symbol, bars=bars, features=snapshots)


def load_many_backtest_inputs(
    db: Session,
    symbols: Iterable[str],
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[DailyBacktestInput]:
    return [
        load_backtest_input(db, symbol=symbol, start_date=start_date, end_date=end_date)
        for symbol in symbols
    ]
