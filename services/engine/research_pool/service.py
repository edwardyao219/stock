from __future__ import annotations

from datetime import date

from services.collector.sync import sync_stock_daily_bars
from services.engine.backtest.sync import run_rules_backtest
from services.engine.features.sync import compute_and_store_sector_features, compute_and_store_stock_features
from services.engine.research_pool.repository import (
    add_symbols_to_pool,
    list_pool_items,
    list_pool_symbols,
)
from services.shared.database import SessionLocal


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    if "-" in value:
        return date.fromisoformat(value)
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")


def add_manual_symbols(
    symbols: list[str],
    pool_name: str = "manual",
    note: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, object]:
    normalized = [symbol.strip() for symbol in symbols if symbol.strip()]
    with SessionLocal() as db:
        count = add_symbols_to_pool(db, normalized, pool_name=pool_name, note=note, tags=tags)
        db.commit()
    return {"pool": pool_name, "symbols": normalized, "written": count}


def list_manual_pool(pool_name: str = "manual") -> dict[str, object]:
    with SessionLocal() as db:
        items = list_pool_items(db, pool_name=pool_name)
    return {"pool": pool_name, "items": items}


def run_pool_research(
    pool_name: str = "manual",
    start_date: str | None = None,
    end_date: str | None = None,
    persist_backtest: bool = False,
    skip_sync: bool = False,
) -> dict[str, object]:
    with SessionLocal() as db:
        symbols = list_pool_symbols(db, pool_name=pool_name)

    if not symbols:
        return {
            "pool": pool_name,
            "symbols": 0,
            "message": "No active symbols in research pool.",
        }

    sync_results = []
    sync_error = None
    if not skip_sync:
        try:
            sync_results = sync_stock_daily_bars(symbols=symbols, start_date=start_date, end_date=end_date)
        except Exception as exc:
            sync_error = f"{type(exc).__name__}: {exc}"
    backtest_start_date = _parse_date(start_date)
    backtest_end_date = _parse_date(end_date)
    feature_result = compute_and_store_stock_features(symbols=symbols)
    sector_result = compute_and_store_sector_features(
        start_date=backtest_start_date,
        end_date=backtest_end_date,
    )
    backtest_result = run_rules_backtest(
        symbols=symbols,
        start_date=backtest_start_date,
        end_date=backtest_end_date,
        run_date=date.today(),
        persist=persist_backtest,
    )

    return {
        "pool": pool_name,
        "symbols": len(symbols),
        "sync_rows": sum(item.rows for item in sync_results),
        "sync_error": sync_error,
        "feature_rows": feature_result["rows"],
        "sector_rows": sector_result["rows"],
        "backtest": {
            "trade_count": backtest_result["trade_count"],
            "written_trades": backtest_result["written_trades"],
            "written_performance": backtest_result["written_performance"],
            "summaries": backtest_result["summaries"],
        },
    }
