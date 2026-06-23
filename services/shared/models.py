from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator

from services.shared.database import Base


class PortableJSON(TypeDecorator):
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSON())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        import json

        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        import json

        return json.loads(value)


class Security(Base):
    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    exchange: Mapped[str] = mapped_column(String(16))
    list_date: Mapped[Optional[date]] = mapped_column(Date)
    industry: Mapped[Optional[str]] = mapped_column(String(64))
    sector_style: Mapped[Optional[str]] = mapped_column(String(64))
    analysis_framework: Mapped[Optional[str]] = mapped_column(String(64))
    holding_style: Mapped[Optional[str]] = mapped_column(String(64))
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
    features: Mapped[dict[str, Any]] = mapped_column(PortableJSON)


class SectorFeatureDaily(Base):
    __tablename__ = "sector_features_daily"
    __table_args__ = (
        UniqueConstraint("sector_code", "trade_date", name="uq_sector_features_code_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    features: Mapped[dict[str, Any]] = mapped_column(PortableJSON)


class SectorProfile(Base):
    __tablename__ = "sector_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sector_style: Mapped[str] = mapped_column(String(64), index=True)
    analysis_framework: Mapped[str] = mapped_column(String(64))
    default_strategy_type: Mapped[str] = mapped_column(String(32))
    preferred_holding_style: Mapped[str] = mapped_column(String(64))
    key_drivers_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON)
    risk_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FundamentalSnapshot(Base):
    __tablename__ = "fundamental_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "report_date", name="uq_fundamental_symbol_report"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    available_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    revenue_growth: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    profit_growth: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    roe: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    dividend_yield: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    pe_ttm: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    pb: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    gross_margin: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    net_margin: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    debt_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    extra_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StrategyRuleRecord(Base):
    __tablename__ = "strategy_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    strategy_type: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    rule_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RiskProfileRecord(Base):
    __tablename__ = "risk_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    scope_type: Mapped[str] = mapped_column(String(32), default="global")
    scope_value: Mapped[Optional[str]] = mapped_column(String(64))
    strategy_type: Mapped[Optional[str]] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TradePlan(Base):
    __tablename__ = "trade_plans"
    __table_args__ = (
        UniqueConstraint("plan_date", "trade_date", "symbol", "rule_id", name="uq_trade_plans_daily_rule"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    strategy_type: Mapped[str] = mapped_column(String(32))
    sector_code: Mapped[Optional[str]] = mapped_column(String(32))
    entry_condition_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON)
    entry_trigger_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    max_gap_up_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4))
    trailing_drawdown_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4))
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
    metrics_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BacktestTradeRecord(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (
        UniqueConstraint(
            "run_date",
            "rule_id",
            "symbol",
            "signal_date",
            name="uq_backtest_trades_run_rule_symbol_signal",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, index=True)
    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    signal_date: Mapped[date] = mapped_column(Date, index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    exit_date: Mapped[date] = mapped_column(Date, index=True)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    holding_days: Mapped[int] = mapped_column(Integer)
    pnl_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    mfe_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    mae_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    exit_reason: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RulePerformanceDaily(Base):
    __tablename__ = "rule_performance_daily"
    __table_args__ = (
        UniqueConstraint("rule_id", "trade_date", "window_days", name="uq_rule_perf_daily"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    window_days: Mapped[int] = mapped_column(Integer, default=0)
    trade_count: Mapped[int] = mapped_column(Integer)
    win_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    avg_return: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    expectancy: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    profit_factor: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    avg_mfe: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    avg_mae: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    score: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cash: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        UniqueConstraint("account_id", "trade_plan_id", "side", name="uq_paper_order_plan_side"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    trade_plan_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(16))
    order_date: Mapped[date] = mapped_column(Date, index=True)
    planned_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="created")
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("account_id", "symbol", "status", name="uq_paper_position_account_symbol_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    trade_plan_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    strategy_type: Mapped[str] = mapped_column(String(32))
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    quantity: Mapped[int] = mapped_column(Integer)
    initial_stop: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    current_stop: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    take_profit_1: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    take_profit_2: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    highest_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    lowest_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    max_holding_days: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    exit_date: Mapped[Optional[date]] = mapped_column(Date)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    exit_reason: Mapped[Optional[str]] = mapped_column(String(64))
    pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    pnl_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    position_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(16))
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    quantity: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
