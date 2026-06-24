from __future__ import annotations

from collections.abc import Iterable

from services.engine.fundamental.akshare_client import (
    fetch_dividend_adjusted_valuation_snapshots,
    fetch_financial_indicator_snapshots,
    fetch_valuation_snapshots,
)
from services.engine.fundamental.repository import (
    upsert_fundamental_snapshots,
    upsert_valuation_snapshots,
)
from services.engine.research_pool.repository import list_pool_symbols
from services.shared.database import SessionLocal


def sync_fundamentals_from_akshare(
    symbols: Iterable[str] | None = None,
    *,
    pool_name: str | None = None,
    include_valuation: bool = True,
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
                rows = fetch_financial_indicator_snapshots(symbol)
                item["financial_snapshots"] = upsert_fundamental_snapshots(db, rows)
                if include_valuation:
                    try:
                        valuation_rows = fetch_dividend_adjusted_valuation_snapshots(symbol)
                    except Exception:
                        valuation_rows = fetch_valuation_snapshots(symbol)
                    item["valuation_snapshots"] = upsert_valuation_snapshots(db, valuation_rows)
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
