from __future__ import annotations

from datetime import datetime

from services.collector.akshare_client import RealtimeQuoteRow, fetch_realtime_quotes
from services.collector.repository import upsert_realtime_quotes
from services.shared.database import SessionLocal
from services.shared.time import now_local


def sync_realtime_quotes(
    symbols: list[str] | set[str] | None = None,
    quote_time: datetime | None = None,
) -> list[RealtimeQuoteRow]:
    current_time = (quote_time or now_local()).replace(tzinfo=None)
    target_symbols = set(symbols) if symbols else None
    quotes = fetch_realtime_quotes(symbols=target_symbols, quote_time=current_time)
    with SessionLocal() as db:
        upsert_realtime_quotes(db, quotes)
        db.commit()
    return quotes
