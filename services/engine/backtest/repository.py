from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.backtest.models import DailyBacktestInput, FeatureSnapshot
from services.engine.features.repository import load_daily_bars
from services.engine.plans.context import (
    build_strategy_context,
    load_sector_feature_map,
    load_tushare_industry_moneyflow_map,
)
from services.shared.models import DailyBar, Security, StockFeatureDaily


def load_backtest_input(
    db: Session,
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
    industry_moneyflow_maps: Mapping[date, Mapping[str, dict[str, Any]]] | None = None,
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

    feature_rows = list(db.execute(stmt))
    if industry_moneyflow_maps is None:
        sectors_by_date: dict[date, set[str]] = {}
        for feature_row, _bar, security in feature_rows:
            if security.industry:
                sectors_by_date.setdefault(feature_row.trade_date, set()).add(security.industry)
        industry_moneyflow_maps = {
            trade_date: load_tushare_industry_moneyflow_map(
                db,
                sorted(sector_codes),
                trade_date,
            )
            for trade_date, sector_codes in sectors_by_date.items()
        }

    sector_feature_maps: dict[date, dict[str, dict[str, object]]] = {}
    snapshots = []
    for feature_row, bar, security in feature_rows:
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
                    industry_moneyflow_map=industry_moneyflow_maps.get(
                        feature_row.trade_date,
                        {},
                    ),
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
    target_symbols = list(symbols)
    if not target_symbols:
        return []
    scope_stmt = (
        select(StockFeatureDaily.trade_date, Security.industry)
        .join(Security, Security.symbol == StockFeatureDaily.symbol)
        .where(StockFeatureDaily.symbol.in_(target_symbols))
        .distinct()
    )
    if start_date:
        scope_stmt = scope_stmt.where(StockFeatureDaily.trade_date >= start_date)
    if end_date:
        scope_stmt = scope_stmt.where(StockFeatureDaily.trade_date <= end_date)
    sectors_by_date: dict[date, set[str]] = {}
    for trade_date, sector_code in db.execute(scope_stmt):
        if sector_code:
            sectors_by_date.setdefault(trade_date, set()).add(sector_code)
    industry_moneyflow_maps = {
        trade_date: load_tushare_industry_moneyflow_map(
            db,
            sorted(sector_codes),
            trade_date,
        )
        for trade_date, sector_codes in sectors_by_date.items()
    }
    return [
        load_backtest_input(
            db,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            industry_moneyflow_maps=industry_moneyflow_maps,
        )
        for symbol in target_symbols
    ]
