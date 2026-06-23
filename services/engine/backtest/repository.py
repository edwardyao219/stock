from __future__ import annotations

from datetime import date
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.backtest.models import DailyBacktestInput, FeatureSnapshot
from services.engine.features.repository import load_daily_bars
from services.shared.models import DailyBar, StockFeatureDaily


def load_backtest_input(
    db: Session,
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> DailyBacktestInput:
    bars = load_daily_bars(db, symbol=symbol, start_date=start_date, end_date=end_date)
    stmt = (
        select(StockFeatureDaily, DailyBar)
        .join(
            DailyBar,
            (DailyBar.symbol == StockFeatureDaily.symbol)
            & (DailyBar.trade_date == StockFeatureDaily.trade_date),
        )
        .where(StockFeatureDaily.symbol == symbol)
        .order_by(StockFeatureDaily.trade_date)
    )
    if start_date:
        stmt = stmt.where(StockFeatureDaily.trade_date >= start_date)
    if end_date:
        stmt = stmt.where(StockFeatureDaily.trade_date <= end_date)

    snapshots = []
    for feature_row, bar in db.execute(stmt):
        snapshots.append(
            FeatureSnapshot(
                symbol=feature_row.symbol,
                trade_date=feature_row.trade_date.isoformat(),
                context={
                    "symbol": feature_row.symbol,
                    "trade_date": feature_row.trade_date.isoformat(),
                    **(feature_row.features or {}),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "amount": float(bar.amount) if bar.amount is not None else None,
                    "volume": float(bar.volume) if bar.volume is not None else None,
                    "turnover_rate": float(bar.turnover_rate) if bar.turnover_rate is not None else None,
                },
            )
        )
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
