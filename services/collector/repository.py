from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from services.collector.akshare_client import AShareSecurity, DailyBarRow, IndexDailyRow
from services.shared.models import DailyBar, Security, TradingCalendar


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _limit_price(close: Decimal, ratio: Decimal) -> Decimal:
    return (close * ratio).quantize(Decimal("0.0001"))


def upsert_trade_calendar(db: Session, trade_dates: list[str]) -> int:
    if not trade_dates:
        return 0
    sorted_dates = sorted(_date(item) for item in trade_dates)
    rows = []
    for index, trade_date in enumerate(sorted_dates):
        rows.append(
            {
                "trade_date": trade_date,
                "is_open": True,
                "previous_trade_date": sorted_dates[index - 1] if index > 0 else None,
                "next_trade_date": sorted_dates[index + 1] if index < len(sorted_dates) - 1 else None,
            }
        )
    stmt = insert(TradingCalendar).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[TradingCalendar.trade_date],
        set_={
            "is_open": stmt.excluded.is_open,
            "previous_trade_date": stmt.excluded.previous_trade_date,
            "next_trade_date": stmt.excluded.next_trade_date,
        },
    )
    db.execute(stmt)
    return len(rows)


def upsert_securities(db: Session, securities: list[AShareSecurity]) -> int:
    if not securities:
        return 0
    now = datetime.utcnow()
    rows = [
        {
            "symbol": item.symbol,
            "name": item.name,
            "exchange": item.exchange,
            "is_st": item.is_st,
            "is_active": item.is_active,
            "updated_at": now,
        }
        for item in securities
    ]
    stmt = insert(Security).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Security.symbol],
        set_={
            "name": stmt.excluded.name,
            "exchange": stmt.excluded.exchange,
            "is_st": stmt.excluded.is_st,
            "is_active": stmt.excluded.is_active,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    db.execute(stmt)
    return len(rows)


def upsert_daily_bars(db: Session, bars: list[DailyBarRow | IndexDailyRow]) -> int:
    if not bars:
        return 0
    rows = []
    for bar in bars:
        close = bar.close
        rows.append(
            {
                "symbol": bar.symbol,
                "trade_date": _date(bar.trade_date),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": close,
                "pre_close": getattr(bar, "pre_close", None),
                "volume": bar.volume,
                "amount": bar.amount,
                "turnover_rate": getattr(bar, "turnover_rate", None),
                "limit_up": _limit_price(close, Decimal("1.10")),
                "limit_down": _limit_price(close, Decimal("0.90")),
                "is_suspended": False,
            }
        )
    stmt = insert(DailyBar).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_bars_symbol_date",
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "pre_close": stmt.excluded.pre_close,
            "volume": stmt.excluded.volume,
            "amount": stmt.excluded.amount,
            "turnover_rate": stmt.excluded.turnover_rate,
            "limit_up": stmt.excluded.limit_up,
            "limit_down": stmt.excluded.limit_down,
            "is_suspended": stmt.excluded.is_suspended,
        },
    )
    db.execute(stmt)
    return len(rows)
