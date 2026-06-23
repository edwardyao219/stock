from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from services.shared.models import FundamentalSnapshot
from services.shared.upsert import upsert_rows


FUNDAMENTAL_FIELDS = [
    "revenue_growth",
    "profit_growth",
    "roe",
    "dividend_yield",
    "pe_ttm",
    "pb",
    "gross_margin",
    "net_margin",
    "debt_ratio",
]


def _decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    return Decimal(str(value))


def upsert_fundamental_snapshots(db: Session, rows: list[dict[str, Any]]) -> int:
    payload = []
    for row in rows:
        extra = dict(row.get("extra_json") or {})
        report_date = date.fromisoformat(str(row["report_date"]))
        raw_available_date = row.get("available_date") or row.get("notice_date") or report_date
        payload.append(
            {
                "symbol": str(row["symbol"]),
                "report_date": report_date,
                "available_date": date.fromisoformat(str(raw_available_date)),
                **{field: _decimal(row.get(field)) for field in FUNDAMENTAL_FIELDS},
                "extra_json": extra,
            }
        )
    return upsert_rows(
        db,
        FundamentalSnapshot,
        payload,
        update_columns=["available_date", *FUNDAMENTAL_FIELDS, "extra_json"],
        constraint="uq_fundamental_symbol_report",
    )


def load_latest_fundamental_snapshot(
    db: Session,
    symbol: str,
    as_of_date: date,
) -> FundamentalSnapshot | None:
    stmt = (
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.symbol == symbol)
        .where(FundamentalSnapshot.available_date <= as_of_date)
        .order_by(desc(FundamentalSnapshot.available_date), desc(FundamentalSnapshot.report_date))
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def snapshot_to_context(snapshot: FundamentalSnapshot | None) -> dict[str, float | str | None]:
    if snapshot is None:
        return {}
    return {
        "fundamental_report_date": snapshot.report_date.isoformat(),
        "fundamental_available_date": snapshot.available_date.isoformat()
        if snapshot.available_date is not None
        else snapshot.report_date.isoformat(),
        **{
            field: float(getattr(snapshot, field)) if getattr(snapshot, field) is not None else None
            for field in FUNDAMENTAL_FIELDS
        },
        "fundamental_extra": snapshot.extra_json or {},
    }
