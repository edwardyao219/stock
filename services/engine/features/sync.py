from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from math import ceil

from services.engine.features.daily import compute_stock_daily_features
from services.engine.features.repository import (
    list_active_symbols,
    load_daily_bars,
    load_stock_feature_contexts,
    upsert_sector_features,
    upsert_stock_features,
)
from services.engine.features.sector import compute_sector_features
from services.shared.database import SessionLocal

FEATURE_WARMUP_DAYS = 120
SECTOR_FEATURE_MIN_COVERAGE_RATIO = 0.80


def _feature_history_start(start_date: date | None) -> date | None:
    if start_date is None:
        return None
    return start_date - timedelta(days=FEATURE_WARMUP_DAYS)


def compute_and_store_stock_features(
    symbols: Iterable[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    processed_symbols = 0
    written_rows = 0

    with SessionLocal() as db:
        target_symbols = (
            list(symbols) if symbols is not None else list_active_symbols(db, limit=limit)
        )
        history_start = _feature_history_start(start_date)
        for symbol in target_symbols:
            bars = load_daily_bars(
                db,
                symbol=symbol,
                start_date=history_start,
                end_date=end_date,
            )
            feature_rows = _filter_feature_rows(
                compute_stock_daily_features(bars),
                start_date=start_date,
                end_date=end_date,
            )
            written_rows += upsert_stock_features(db, feature_rows)
            processed_symbols += 1
        db.commit()

    return {"symbols": processed_symbols, "rows": written_rows}


def _filter_feature_rows(
    feature_rows,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
):
    if start_date is None and end_date is None:
        return feature_rows
    return [
        row
        for row in feature_rows
        if (start_date is None or date.fromisoformat(row.trade_date) >= start_date)
        and (end_date is None or date.fromisoformat(row.trade_date) <= end_date)
    ]


def compute_and_store_sector_features(
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, int]:
    with SessionLocal() as db:
        stock_contexts = load_stock_feature_contexts(db, start_date=start_date, end_date=end_date)
        covered_contexts = _filter_low_coverage_context_days(stock_contexts)
        sector_rows = compute_sector_features(covered_contexts)
        written_rows = upsert_sector_features(db, sector_rows)
        db.commit()

    sectors = {row.sector_code for row in sector_rows}
    return {"sectors": len(sectors), "rows": written_rows}


def _filter_low_coverage_context_days(
    stock_contexts: list[dict[str, object]],
) -> list[dict[str, object]]:
    counts_by_date: dict[str, int] = {}
    for context in stock_contexts:
        trade_date = context.get("trade_date")
        if trade_date:
            counts_by_date[str(trade_date)] = counts_by_date.get(str(trade_date), 0) + 1
    if not counts_by_date:
        return stock_contexts

    max_count = max(counts_by_date.values())
    min_count = max(1, ceil(max_count * SECTOR_FEATURE_MIN_COVERAGE_RATIO))
    valid_dates = {
        trade_date for trade_date, count in counts_by_date.items() if count >= min_count
    }
    return [
        context
        for context in stock_contexts
        if str(context.get("trade_date")) in valid_dates
    ]
