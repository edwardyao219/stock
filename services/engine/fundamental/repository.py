from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from services.engine.fundamental.akshare_client import market_symbol
from services.shared.models import FundamentalSnapshot, TushareDailyBasic
from services.shared.upsert import upsert_rows

FUNDAMENTAL_FIELDS = [
    "revenue_growth",
    "profit_growth",
    "roe",
    "gross_margin",
    "net_margin",
    "debt_ratio",
    "operating_revenue",
    "parent_net_profit",
    "deducted_parent_net_profit",
    "operating_cash_flow",
]
VALUATION_FIELDS = ["pe_ttm", "pb", "dividend_yield"]


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
                **{field: None for field in VALUATION_FIELDS},
                "extra_json": extra,
            }
        )
    return upsert_rows(
        db,
        FundamentalSnapshot,
        payload,
        update_columns=[
            "available_date",
            *FUNDAMENTAL_FIELDS,
            *VALUATION_FIELDS,
            "extra_json",
        ],
        constraint="uq_fundamental_symbol_report",
        index_elements=[FundamentalSnapshot.symbol, FundamentalSnapshot.report_date],
    )


def upsert_valuation_snapshots(db: Session, rows: list[dict[str, Any]]) -> int:
    payload = []
    for row in rows:
        extra = dict(row.get("extra_json") or {})
        report_date = date.fromisoformat(str(row["report_date"]))
        raw_available_date = row.get("available_date") or report_date
        payload.append(
            {
                "symbol": str(row["symbol"]),
                "report_date": report_date,
                "available_date": date.fromisoformat(str(raw_available_date)),
                **{field: _decimal(row.get(field)) for field in VALUATION_FIELDS},
                "extra_json": extra,
            }
        )
    return upsert_rows(
        db,
        FundamentalSnapshot,
        payload,
        update_columns=["available_date", *VALUATION_FIELDS, "extra_json"],
        constraint="uq_fundamental_symbol_report",
        index_elements=[FundamentalSnapshot.symbol, FundamentalSnapshot.report_date],
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
        .where(
            (FundamentalSnapshot.revenue_growth.is_not(None))
            | (FundamentalSnapshot.profit_growth.is_not(None))
            | (FundamentalSnapshot.roe.is_not(None))
            | (FundamentalSnapshot.gross_margin.is_not(None))
            | (FundamentalSnapshot.net_margin.is_not(None))
            | (FundamentalSnapshot.debt_ratio.is_not(None))
            | (FundamentalSnapshot.operating_revenue.is_not(None))
            | (FundamentalSnapshot.parent_net_profit.is_not(None))
            | (FundamentalSnapshot.deducted_parent_net_profit.is_not(None))
            | (FundamentalSnapshot.operating_cash_flow.is_not(None))
        )
        .order_by(desc(FundamentalSnapshot.available_date), desc(FundamentalSnapshot.report_date))
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def load_latest_valuation_snapshot(
    db: Session,
    symbol: str,
    as_of_date: date,
) -> FundamentalSnapshot | None:
    stmt = (
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.symbol == symbol)
        .where(FundamentalSnapshot.available_date <= as_of_date)
        .where((FundamentalSnapshot.pb.is_not(None)) | (FundamentalSnapshot.pe_ttm.is_not(None)))
        .order_by(desc(FundamentalSnapshot.available_date), desc(FundamentalSnapshot.report_date))
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _fundamental_presence_filter():
    return (
        (FundamentalSnapshot.revenue_growth.is_not(None))
        | (FundamentalSnapshot.profit_growth.is_not(None))
        | (FundamentalSnapshot.roe.is_not(None))
        | (FundamentalSnapshot.gross_margin.is_not(None))
        | (FundamentalSnapshot.net_margin.is_not(None))
        | (FundamentalSnapshot.debt_ratio.is_not(None))
        | (FundamentalSnapshot.operating_revenue.is_not(None))
        | (FundamentalSnapshot.parent_net_profit.is_not(None))
        | (FundamentalSnapshot.deducted_parent_net_profit.is_not(None))
        | (FundamentalSnapshot.operating_cash_flow.is_not(None))
    )


def _valuation_presence_filter():
    return (FundamentalSnapshot.pb.is_not(None)) | (FundamentalSnapshot.pe_ttm.is_not(None))


def _latest_snapshots_by_symbol(
    db: Session,
    symbols: Sequence[str],
    as_of_date: date,
    presence_filter,
) -> dict[str, FundamentalSnapshot]:
    unique_symbols = sorted({symbol for symbol in symbols if symbol})
    if not unique_symbols:
        return {}
    rows = db.execute(
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.symbol.in_(unique_symbols))
        .where(FundamentalSnapshot.available_date <= as_of_date)
        .where(presence_filter)
        .order_by(
            FundamentalSnapshot.symbol,
            desc(FundamentalSnapshot.available_date),
            desc(FundamentalSnapshot.report_date),
        )
    ).scalars()
    snapshots: dict[str, FundamentalSnapshot] = {}
    for row in rows:
        snapshots.setdefault(row.symbol, row)
    return snapshots


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


def _snapshot_to_history(snapshot: FundamentalSnapshot) -> dict[str, Any]:
    return {
        "report_date": snapshot.report_date.isoformat(),
        "available_date": (
            snapshot.available_date.isoformat()
            if snapshot.available_date is not None
            else snapshot.report_date.isoformat()
        ),
        **{
            field: float(getattr(snapshot, field)) if getattr(snapshot, field) is not None else None
            for field in FUNDAMENTAL_FIELDS
        },
        "extra_json": snapshot.extra_json or {},
    }


def load_fundamental_history_map(
    db: Session,
    symbols: Sequence[str],
    as_of_date: date,
    *,
    limit: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    unique_symbols = sorted({symbol for symbol in symbols if symbol})
    if not unique_symbols or limit <= 0:
        return {}
    rows = db.execute(
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.symbol.in_(unique_symbols))
        .where(FundamentalSnapshot.available_date <= as_of_date)
        .where(_fundamental_presence_filter())
        .order_by(
            FundamentalSnapshot.symbol,
            desc(FundamentalSnapshot.report_date),
            desc(FundamentalSnapshot.available_date),
        )
    ).scalars()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        history = result.setdefault(row.symbol, [])
        if len(history) < limit:
            history.append(_snapshot_to_history(row))
    return result


def _years_ago(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def load_valuation_pe_history_map(
    db: Session,
    symbols: Sequence[str],
    as_of_date: date,
    *,
    years: int = 3,
) -> dict[str, list[float]]:
    code_to_symbol = {market_symbol(symbol): symbol for symbol in symbols if symbol}
    if not code_to_symbol or years <= 0:
        return {}
    rows = db.execute(
        select(TushareDailyBasic)
        .where(TushareDailyBasic.ts_code.in_(sorted(code_to_symbol)))
        .where(TushareDailyBasic.trade_date >= _years_ago(as_of_date, years))
        .where(TushareDailyBasic.trade_date <= as_of_date)
        .where(TushareDailyBasic.pe_ttm > 0)
        .order_by(TushareDailyBasic.ts_code, TushareDailyBasic.trade_date)
    ).scalars()
    result: dict[str, list[float]] = {}
    for row in rows:
        result.setdefault(code_to_symbol[row.ts_code], []).append(float(row.pe_ttm))
    return result


def load_fundamental_context_map(
    db: Session,
    symbols: Sequence[str],
    as_of_date: date,
) -> dict[str, dict[str, Any]]:
    unique_symbols = sorted({symbol for symbol in symbols if symbol})
    if not unique_symbols:
        return {}

    fundamental_snapshots = _latest_snapshots_by_symbol(
        db,
        unique_symbols,
        as_of_date,
        _fundamental_presence_filter(),
    )
    histories = load_fundamental_history_map(db, unique_symbols, as_of_date)

    contexts: dict[str, dict[str, Any]] = {}
    for symbol in unique_symbols:
        context = snapshot_to_context(fundamental_snapshots.get(symbol))
        if symbol in histories:
            context["fundamental_history"] = histories[symbol]
        if context:
            contexts[symbol] = context
    return contexts


def load_fundamental_context(db: Session, symbol: str, as_of_date: date) -> dict[str, Any]:
    context = snapshot_to_context(load_latest_fundamental_snapshot(db, symbol, as_of_date))
    history = load_fundamental_history_map(db, [symbol], as_of_date).get(symbol)
    if history:
        context["fundamental_history"] = history
    return context
