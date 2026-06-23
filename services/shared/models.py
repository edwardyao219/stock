from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.shared.database import Base


class Security(Base):
    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    exchange: Mapped[str] = mapped_column(String(16))
    list_date: Mapped[Optional[date]] = mapped_column(Date)
    industry: Mapped[Optional[str]] = mapped_column(String(64))
    is_st: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TradingCalendar(Base):
    __tablename__ = "trading_calendar"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    previous_trade_date: Mapped[Optional[date]] = mapped_column(Date)
    next_trade_date: Mapped[Optional[date]] = mapped_column(Date)


class DailyBar(Base):
    __tablename__ = "daily_bars"
    __table_args__ = (UniqueConstraint("symbol", "trade_date", name="uq_daily_bars_symbol_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    pre_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    volume: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    turnover_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    limit_up: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    limit_down: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)


class SectorDaily(Base):
    __tablename__ = "sector_daily"
    __table_args__ = (UniqueConstraint("sector_code", "trade_date", name="uq_sector_daily_code_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(32), index=True)
    sector_name: Mapped[str] = mapped_column(String(64))
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    pct_change: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    up_count: Mapped[Optional[int]] = mapped_column(Integer)
    down_count: Mapped[Optional[int]] = mapped_column(Integer)
    limit_up_count: Mapped[Optional[int]] = mapped_column(Integer)
    limit_down_count: Mapped[Optional[int]] = mapped_column(Integer)
    new_high_count: Mapped[Optional[int]] = mapped_column(Integer)
    relative_strength: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))


class StockFeatureDaily(Base):
    __tablename__ = "stock_features_daily"
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", name="uq_stock_features_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)


class SectorFeatureDaily(Base):
    __tablename__ = "sector_features_daily"
    __table_args__ = (
        UniqueConstraint("sector_code", "trade_date", name="uq_sector_features_code_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)


class StrategyRuleRecord(Base):
    __tablename__ = "strategy_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    strategy_type: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    rule_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TradePlan(Base):
    __tablename__ = "trade_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    strategy_type: Mapped[str] = mapped_column(String(32))
    sector_code: Mapped[Optional[str]] = mapped_column(String(32))
    entry_condition_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    initial_stop: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    take_profit_1: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    take_profit_2: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    max_holding_days: Mapped[Optional[int]] = mapped_column(Integer)
    position_size: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4))
    risk_notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="planned")


class ReviewReport(Base):
    __tablename__ = "review_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    report_type: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(64), default="market")
    generator: Mapped[str] = mapped_column(String(64), default="mechanical")
    content_md: Mapped[str] = mapped_column(Text)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
