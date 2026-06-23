from __future__ import annotations

from datetime import date
from typing import Iterable

from services.engine.features.daily import compute_stock_daily_features
from services.engine.features.repository import list_active_symbols, load_daily_bars, upsert_stock_features
from services.shared.database import SessionLocal


def compute_and_store_stock_features(
    symbols: Iterable[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    processed_symbols = 0
    written_rows = 0

    with SessionLocal() as db:
        target_symbols = list(symbols) if symbols is not None else list_active_symbols(db, limit=limit)
        for symbol in target_symbols:
            bars = load_daily_bars(db, symbol=symbol, start_date=start_date, end_date=end_date)
            feature_rows = compute_stock_daily_features(bars)
            written_rows += upsert_stock_features(db, feature_rows)
            processed_symbols += 1
        db.commit()

    return {"symbols": processed_symbols, "rows": written_rows}
