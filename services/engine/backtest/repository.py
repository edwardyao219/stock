from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.backtest.models import DailyBacktestInput, FeatureSnapshot
from services.engine.features.repository import load_daily_bars
from services.engine.plans.context import build_strategy_context, load_sector_feature_map
from services.shared.models import DailyBar, Security, StockFeatureDaily


def load_backtest_input(
    db: Session,
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> DailyBacktestInput:
    bars = load_daily_bars(db, symbol=symbol, start_date=start_date, end_date=end_date)
    stmt = (
        select(StockFeatureDaily, DailyBar, Security)
        .join(
            DailyBar,
            (DailyBar.symbol == StockFeatureDaily.symbol)
            & (DailyBar.trade_date == StockFeatureDaily.trade_date),
        )
        .join(Security, Security.symbol == StockFeatureDaily.symbol)
        .where(StockFeatureDaily.symbol == symbol)
        .order_by(StockFeatureDaily.trade_date)
    )
    if start_date:
        stmt = stmt.where(StockFeatureDaily.trade_date >= start_date)
    if end_date:
        stmt = stmt.where(StockFeatureDaily.trade_date <= end_date)

    sector_feature_maps: dict[date, dict[str, dict[str, object]]] = {}
    snapshots = []
    for feature_row, bar, security in db.execute(stmt):
        if feature_row.trade_date not in sector_feature_maps:
            sector_feature_maps[feature_row.trade_date] = load_sector_feature_map(
                db,
                feature_row.trade_date,
            )
        snapshots.append(
            FeatureSnapshot(
                symbol=feature_row.symbol,
                trade_date=feature_row.trade_date.isoformat(),
                context=build_strategy_context(
                    db,
                    feature_row=feature_row,
                    security=security,
                    bar=bar,
                    sector_feature_map=sector_feature_maps[feature_row.trade_date],
                ),
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
