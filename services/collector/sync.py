from __future__ import annotations

from collections.abc import Iterable

from services.collector.akshare_client import (
    fetch_a_share_securities,
    fetch_industry_boards,
    fetch_industry_constituents,
    fetch_index_daily_bars,
    fetch_stock_daily_bars,
    fetch_trade_dates,
)
from services.collector.contracts import CollectionResult
from services.collector.repository import (
    upsert_daily_bars,
    upsert_industry_constituents,
    upsert_securities,
    upsert_trade_calendar,
)
from services.shared.config import get_settings
from services.shared.database import SessionLocal

DEFAULT_INDEX_SYMBOLS = ["000001", "399001", "399006"]


def sync_calendar_and_securities() -> list[CollectionResult]:
    with SessionLocal() as db:
        trade_dates = fetch_trade_dates()
        calendar_rows = upsert_trade_calendar(db, trade_dates)

        securities = fetch_a_share_securities()
        security_rows = upsert_securities(db, securities)

        db.commit()

    latest_trade_date = trade_dates[-1] if trade_dates else ""
    return [
        CollectionResult(
            source="akshare",
            dataset="trading_calendar",
            trade_date=latest_trade_date,
            rows=calendar_rows,
            status="ok",
        ),
        CollectionResult(
            source="akshare",
            dataset="securities",
            trade_date=latest_trade_date,
            rows=security_rows,
            status="ok",
        ),
    ]


def sync_index_daily_bars(
    start_date: str | None = None,
    end_date: str | None = None,
    symbols: Iterable[str] = DEFAULT_INDEX_SYMBOLS,
) -> list[CollectionResult]:
    settings = get_settings()
    start = start_date or settings.data_start_date
    end = end_date or "20991231"
    results: list[CollectionResult] = []
    with SessionLocal() as db:
        for symbol in symbols:
            bars = fetch_index_daily_bars(symbol=symbol, start_date=start, end_date=end)
            rows = upsert_daily_bars(db, bars)
            results.append(
                CollectionResult(
                    source="akshare",
                    dataset=f"index_daily:{symbol}",
                    trade_date=end,
                    rows=rows,
                    status="ok",
                )
            )
        db.commit()
    return results


def sync_stock_daily_bars(
    symbols: Iterable[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[CollectionResult]:
    settings = get_settings()
    start = start_date or settings.data_start_date
    end = end_date or "20991231"
    results: list[CollectionResult] = []
    with SessionLocal() as db:
        for symbol in symbols:
            bars = fetch_stock_daily_bars(symbol=symbol, start_date=start, end_date=end)
            rows = upsert_daily_bars(db, bars)
            results.append(
                CollectionResult(
                    source="akshare",
                    dataset=f"stock_daily:{symbol}",
                    trade_date=end,
                    rows=rows,
                    status="ok",
                )
            )
        db.commit()
    return results


def sync_industry_constituents(limit: int | None = None) -> list[CollectionResult]:
    try:
        boards = fetch_industry_boards()
    except Exception as exc:
        return [
            CollectionResult(
                source="akshare",
                dataset="industry_constituents",
                trade_date="",
                rows=0,
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
        ]
    if limit:
        boards = boards[:limit]

    results: list[CollectionResult] = []
    with SessionLocal() as db:
        for board in boards:
            try:
                constituents = fetch_industry_constituents(board)
                rows = upsert_industry_constituents(db, constituents)
                results.append(
                    CollectionResult(
                        source="akshare",
                        dataset=f"industry_constituents:{board.name}",
                        trade_date="",
                        rows=rows,
                        status="ok",
                        message=board.code,
                    )
                )
            except Exception as exc:
                results.append(
                    CollectionResult(
                        source="akshare",
                        dataset=f"industry_constituents:{board.name}",
                        trade_date="",
                        rows=0,
                        status="failed",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )
        db.commit()
    return results
