from __future__ import annotations

from collections.abc import Iterable

from services.engine.fundamental.akshare_client import (
    fetch_financial_indicator_snapshots,
)
from services.engine.fundamental.repository import (
    FUNDAMENTAL_FIELDS,
    upsert_fundamental_snapshots,
)
from services.engine.fundamental.tushare_client import fetch_tushare_financial_snapshots
from services.engine.research_pool.repository import list_pool_symbols
from services.shared.database import SessionLocal


def merge_financial_sources(
    primary: list[dict[str, object]],
    fallback: list[dict[str, object]],
) -> list[dict[str, object]]:
    fallback_by_date = {str(row["report_date"]): row for row in fallback}
    merged: list[dict[str, object]] = []
    for primary_row in primary:
        row = dict(primary_row)
        fallback_row = fallback_by_date.pop(str(row["report_date"]), {})
        filled = []
        for field in FUNDAMENTAL_FIELDS:
            if row.get(field) is None and fallback_row.get(field) is not None:
                row[field] = fallback_row[field]
                filled.append(field)
        if filled:
            extra = dict(row.get("extra_json") or {})
            extra["source"] = "merged"
            extra["akshare_fallback_fields"] = filled
            row["extra_json"] = extra
        merged.append(row)
    merged.extend(fallback_by_date.values())
    return sorted(merged, key=lambda row: str(row["report_date"]), reverse=True)


def sync_fundamentals(
    symbols: Iterable[str] | None = None,
    *,
    pool_name: str | None = None,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    with SessionLocal() as db:
        target_symbols = list(symbols) if symbols is not None else []
        if not target_symbols and pool_name:
            target_symbols = list_pool_symbols(db, pool_name=pool_name)

        for symbol in target_symbols:
            item: dict[str, object] = {
                "symbol": symbol,
                "financial_snapshots": 0,
                "valuation_snapshots": 0,
                "status": "ok",
                "message": "",
            }
            try:
                source_errors = []
                try:
                    primary_rows = fetch_tushare_financial_snapshots(symbol)
                except Exception as exc:
                    primary_rows = []
                    source_errors.append(f"Tushare {type(exc).__name__}: {exc}")
                try:
                    fallback_rows = fetch_financial_indicator_snapshots(symbol)
                except Exception as exc:
                    fallback_rows = []
                    source_errors.append(f"AkShare {type(exc).__name__}: {exc}")
                if not primary_rows and not fallback_rows and len(source_errors) == 2:
                    raise RuntimeError("; ".join(source_errors))
                rows = merge_financial_sources(primary_rows, fallback_rows)
                item["financial_snapshots"] = upsert_fundamental_snapshots(db, rows)
                item["message"] = "; ".join(source_errors)
            except Exception as exc:
                db.rollback()
                item["status"] = "failed"
                item["message"] = f"{type(exc).__name__}: {exc}"
            results.append(item)
        db.commit()

    return {
        "symbols": len(target_symbols),
        "ok": sum(1 for item in results if item["status"] == "ok"),
        "failed": sum(1 for item in results if item["status"] == "failed"),
        "results": results,
    }


def sync_fundamentals_from_akshare(
    symbols: Iterable[str] | None = None,
    *,
    pool_name: str | None = None,
    include_valuation: bool = False,
) -> dict[str, object]:
    return sync_fundamentals(symbols, pool_name=pool_name)
