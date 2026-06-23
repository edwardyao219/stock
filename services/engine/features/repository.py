from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.features.daily import BarInput, StockFeatureRow
from services.engine.features.sector import SectorFeatureRow
from services.shared.models import DailyBar, SectorFeatureDaily, Security, StockFeatureDaily
from services.shared.upsert import upsert_rows


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def list_active_symbols(db: Session, limit: int | None = None) -> list[str]:
    stmt = select(Security.symbol).where(Security.is_active.is_(True)).order_by(Security.symbol)
    if limit:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())


def load_daily_bars(
    db: Session,
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[BarInput]:
    stmt = select(DailyBar).where(DailyBar.symbol == symbol).order_by(DailyBar.trade_date)
    if start_date:
        stmt = stmt.where(DailyBar.trade_date >= start_date)
    if end_date:
        stmt = stmt.where(DailyBar.trade_date <= end_date)

    bars: list[BarInput] = []
    for row in db.execute(stmt).scalars():
        bars.append(
            BarInput(
                symbol=row.symbol,
                trade_date=row.trade_date.isoformat(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                pre_close=_float(row.pre_close),
                amount=_float(row.amount),
                volume=_float(row.volume),
                turnover_rate=_float(row.turnover_rate),
            )
        )
    return bars


def upsert_stock_features(db: Session, feature_rows: Iterable[StockFeatureRow]) -> int:
    rows = [
        {
            "symbol": item.symbol,
            "trade_date": date.fromisoformat(item.trade_date),
            "features": item.features,
        }
        for item in feature_rows
    ]
    if not rows:
        return 0
    return upsert_rows(
        db,
        StockFeatureDaily,
        rows,
        update_columns=["features"],
        constraint="uq_stock_features_symbol_date",
    )


def load_stock_feature_contexts(
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, object]]:
    stmt = (
        select(StockFeatureDaily, Security)
        .join(Security, Security.symbol == StockFeatureDaily.symbol)
        .where(Security.is_active.is_(True))
        .order_by(StockFeatureDaily.trade_date, StockFeatureDaily.symbol)
    )
    if start_date:
        stmt = stmt.where(StockFeatureDaily.trade_date >= start_date)
    if end_date:
        stmt = stmt.where(StockFeatureDaily.trade_date <= end_date)

    contexts: list[dict[str, object]] = []
    for feature_row, security in db.execute(stmt):
        contexts.append(
            {
                **(feature_row.features or {}),
                "symbol": feature_row.symbol,
                "trade_date": feature_row.trade_date.isoformat(),
                "sector_code": security.industry,
                "industry": security.industry,
            }
        )
    return contexts


def upsert_sector_features(db: Session, feature_rows: Iterable[SectorFeatureRow]) -> int:
    rows = [
        {
            "sector_code": item.sector_code,
            "trade_date": date.fromisoformat(item.trade_date),
            "features": item.features,
        }
        for item in feature_rows
    ]
    if not rows:
        return 0
    return upsert_rows(
        db,
        SectorFeatureDaily,
        rows,
        update_columns=["features"],
        constraint="uq_sector_features_code_date",
    )
