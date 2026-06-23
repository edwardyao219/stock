from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from services.collector.akshare_client import AShareSecurity, DailyBarRow, IndexDailyRow, IndustryConstituent
from services.engine.sector.repository import load_sector_profile, seed_sector_profiles
from services.shared.models import DailyBar, Security, TradingCalendar
from services.shared.upsert import upsert_rows


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
    return upsert_rows(
        db,
        TradingCalendar,
        rows,
        update_columns=["is_open", "previous_trade_date", "next_trade_date"],
        index_elements=[TradingCalendar.trade_date],
    )


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
    return upsert_rows(
        db,
        Security,
        rows,
        update_columns=["name", "exchange", "is_st", "is_active", "updated_at"],
        index_elements=[Security.symbol],
    )


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
    return upsert_rows(
        db,
        DailyBar,
        rows,
        update_columns=[
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "volume",
            "amount",
            "turnover_rate",
            "limit_up",
            "limit_down",
            "is_suspended",
        ],
        constraint="uq_daily_bars_symbol_date",
    )


def upsert_industry_constituents(db: Session, constituents: list[IndustryConstituent]) -> int:
    if not constituents:
        return 0

    seed_sector_profiles(db)
    now = datetime.utcnow()
    rows = []
    for item in constituents:
        profile = load_sector_profile(db, item.board_name)
        rows.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "exchange": item.exchange,
                "industry": item.board_name,
                "sector_style": profile.sector_style if profile else None,
                "analysis_framework": profile.analysis_framework if profile else None,
                "holding_style": profile.preferred_holding_style if profile else None,
                "is_st": item.is_st,
                "is_active": True,
                "updated_at": now,
            }
        )

    return upsert_rows(
        db,
        Security,
        rows,
        update_columns=[
            "name",
            "exchange",
            "industry",
            "sector_style",
            "analysis_framework",
            "holding_style",
            "is_st",
            "is_active",
            "updated_at",
        ],
        index_elements=[Security.symbol],
    )
