from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator

from services.shared.database import Base

logger = logging.getLogger(__name__)
MYSQL_LONGTEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")


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

        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid JSON in %s; returning empty object.",
                self.__class__.__name__,
            )
            return {}


class LargePortableJSON(PortableJSON):
    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.LONGTEXT())
        return super().load_dialect_impl(dialect)


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


class RealtimeQuote(Base):
    __tablename__ = "realtime_quotes"
    __table_args__ = (
        UniqueConstraint("symbol", "quote_time", name="uq_realtime_quotes_symbol_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    quote_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    open: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    high: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    low: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    pre_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    pct_change: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    volume: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    turnover_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    source: Mapped[str] = mapped_column(String(64), default="akshare.stock_zh_a_spot_em")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class TushareDaily(Base):
    __tablename__ = "tushare_daily"
    __table_args__ = (UniqueConstraint("ts_code", "trade_date", name="uq_tushare_daily_code_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    high: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    low: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    pre_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    change: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    vol: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))


class TushareDailyBasic(Base):
    __tablename__ = "tushare_daily_basic"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_tushare_daily_basic_code_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    turnover_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    volume_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    pe_ttm: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    pb: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    total_mv: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 6))
    circ_mv: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 6))


class TushareStkLimit(Base):
    __tablename__ = "tushare_stk_limit"
    __table_args__ = (UniqueConstraint("ts_code", "trade_date", name="uq_tushare_stk_limit_code_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    up_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    down_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))


class TushareMoneyflow(Base):
    __tablename__ = "tushare_moneyflow"
    __table_args__ = (UniqueConstraint("ts_code", "trade_date", name="uq_tushare_moneyflow_code_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    buy_sm_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    sell_sm_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_md_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    sell_md_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_lg_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    sell_lg_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_elg_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    sell_elg_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    net_mf_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))


class TushareMoneyflowDc(Base):
    __tablename__ = "tushare_moneyflow_dc"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_tushare_moneyflow_dc_code_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(64))
    pct_change: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    net_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    buy_elg_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_elg_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    buy_lg_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_lg_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    buy_md_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_md_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    buy_sm_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_sm_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))


class TushareLimitListD(Base):
    __tablename__ = "tushare_limit_list_d"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_tushare_limit_list_d_code_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    industry: Mapped[Optional[str]] = mapped_column(String(64))
    name: Mapped[Optional[str]] = mapped_column(String(64))
    close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    limit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    float_mv: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    total_mv: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    turnover_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    fd_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    first_time: Mapped[Optional[str]] = mapped_column(String(16))
    last_time: Mapped[Optional[str]] = mapped_column(String(16))
    open_times: Mapped[Optional[int]] = mapped_column(Integer)
    up_stat: Mapped[Optional[str]] = mapped_column(String(32))
    limit_times: Mapped[Optional[int]] = mapped_column(Integer)
    limit: Mapped[Optional[str]] = mapped_column(String(4), index=True)


class TushareDatasetSyncReceipt(Base):
    __tablename__ = "tushare_dataset_sync_receipts"
    __table_args__ = (
        UniqueConstraint("dataset", "trade_date", name="uq_tushare_dataset_sync_receipt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TushareCyqPerf(Base):
    __tablename__ = "tushare_cyq_perf"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_tushare_cyq_perf_code_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    his_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    his_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    cost_5pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    cost_15pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    cost_50pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    cost_85pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    cost_95pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    weight_avg: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    winner_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))


class TushareMoneyflowIndDc(Base):
    __tablename__ = "tushare_moneyflow_ind_dc"
    __table_args__ = (
        UniqueConstraint("trade_date", "content_type", "ts_code", name="uq_tushare_moneyflow_ind_dc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    content_type: Mapped[str] = mapped_column(String(16), index=True)
    ts_code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(64))
    pct_change: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    net_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))


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


class LowDimensionalFeatureSnapshot(Base):
    __tablename__ = "low_dimensional_feature_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", name="uq_low_dim_symbol_date"),
        Index("ix_low_dim_trade_sector_strength", "trade_date", "sector_strength_score"),
        Index("ix_low_dim_symbol_date", "symbol", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    sector: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    trend_score: Mapped[Optional[float]] = mapped_column(Float)
    trend_quality_score: Mapped[Optional[float]] = mapped_column(Float)
    relative_strength_score: Mapped[Optional[float]] = mapped_column(Float)
    volume_confirmation_score: Mapped[Optional[float]] = mapped_column(Float)
    price_volume_trend_score: Mapped[Optional[float]] = mapped_column(Float)
    sector_strength_score: Mapped[Optional[float]] = mapped_column(Float)
    sector_avg_return_20d: Mapped[Optional[float]] = mapped_column(Float)
    sector_positive_20d_rate: Mapped[Optional[float]] = mapped_column(Float)
    sector_breadth_score: Mapped[Optional[float]] = mapped_column(Float)
    sector_trend_continuity_score: Mapped[Optional[float]] = mapped_column(Float)
    sector_trend_resilience_score: Mapped[Optional[float]] = mapped_column(Float)
    sector_stock_count: Mapped[Optional[float]] = mapped_column(Float)
    return_5d: Mapped[Optional[float]] = mapped_column(Float)
    return_20d: Mapped[Optional[float]] = mapped_column(Float)
    distance_to_ma20: Mapped[Optional[float]] = mapped_column(Float)
    distance_to_20d_low: Mapped[Optional[float]] = mapped_column(Float)
    max_drawdown_20d: Mapped[Optional[float]] = mapped_column(Float)
    overheat_score: Mapped[Optional[float]] = mapped_column(Float)
    volume_trap_risk_score: Mapped[Optional[float]] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MarketRegimeDaily(Base):
    __tablename__ = "market_regime_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    regime: Mapped[str] = mapped_column(String(32), index=True)
    trend_score: Mapped[Optional[float]] = mapped_column(Float)
    breadth_score: Mapped[Optional[float]] = mapped_column(Float)
    emotion_score: Mapped[Optional[float]] = mapped_column(Float)
    volatility_score: Mapped[Optional[float]] = mapped_column(Float)
    risk_level: Mapped[Optional[str]] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32), default="candidate_discovery")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StockTrackingSnapshot(Base):
    __tablename__ = "stock_tracking_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "snapshot_date", name="uq_stock_tracking_symbol_date"),
        Index("ix_stock_tracking_date_score", "snapshot_date", "tracking_score"),
        Index("ix_stock_tracking_symbol_date", "symbol", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    stage_label: Mapped[str] = mapped_column(String(32))
    tracking_score: Mapped[Optional[float]] = mapped_column(Float)
    name: Mapped[Optional[str]] = mapped_column(String(64))
    industry: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    sector_style: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    latest_trade_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    latest_close: Mapped[Optional[float]] = mapped_column(Float)
    current_price: Mapped[Optional[float]] = mapped_column(Float)
    day_change_pct: Mapped[Optional[float]] = mapped_column(Float)
    return_5d: Mapped[Optional[float]] = mapped_column(Float)
    return_20d: Mapped[Optional[float]] = mapped_column(Float)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    risks_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    source_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CandidateDiscoverySnapshot(Base):
    __tablename__ = "candidate_discovery_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "cache_version",
            "signal_date",
            "next_trade_date",
            "candidate_limit",
            "include_fundamentals",
            name="uq_candidate_discovery_snapshot_key",
        ),
        Index("ix_candidate_discovery_signal_date", "signal_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_version: Mapped[str] = mapped_column(String(32), index=True)
    signal_date: Mapped[date] = mapped_column(Date, index=True)
    next_trade_date: Mapped[date] = mapped_column(Date, index=True)
    candidate_limit: Mapped[int] = mapped_column(Integer)
    include_fundamentals: Mapped[bool] = mapped_column(Boolean, default=True)
    discovery_json: Mapped[dict[str, Any]] = mapped_column(LargePortableJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResearchSignalLedger(Base):
    __tablename__ = "research_signal_ledger"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "signal_type",
            "signal_time",
            "symbol",
            name="uq_research_signal_ledger_identity",
        ),
        Index("ix_research_signal_ledger_date_type", "signal_date", "signal_type"),
        Index("ix_research_signal_ledger_symbol_date", "symbol", "signal_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    signal_type: Mapped[str] = mapped_column(String(64), index=True)
    signal_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    signal_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(64))
    sector: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    signal_price: Mapped[float] = mapped_column(Float)
    market_regime: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    market_state: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    executable: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(LargePortableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MarketMessageSnapshot(Base):
    __tablename__ = "market_message_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text)
    raw_messages_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    catalysts_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ExternalMarketSignal(Base):
    __tablename__ = "external_market_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(256))
    change_pct: Mapped[Optional[float]] = mapped_column(Float)
    a_share_sectors_json: Mapped[list[str]] = mapped_column(PortableJSON, default=list)
    source_url: Mapped[Optional[str]] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IntradayMarketTurnSnapshot(Base):
    __tablename__ = "intraday_market_turn_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_time", name="uq_intraday_market_turn_snapshot_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    coverage_ratio: Mapped[float] = mapped_column(Float)
    breadth_ratio: Mapped[float] = mapped_column(Float)
    total_amount: Mapped[float] = mapped_column(Float)
    index_change_pct: Mapped[Optional[float]] = mapped_column(Float)
    sector_expansion_count: Mapped[int] = mapped_column(Integer)
    state_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    content_md: Mapped[str] = mapped_column(MYSQL_LONGTEXT)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(LargePortableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ParameterRecommendation(Base):
    __tablename__ = "parameter_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "report_date",
            "source_report_type",
            "rule_id",
            "scope_type",
            "scope_value",
            "target_type",
            "target_name",
            "action",
            name="uq_parameter_recommendation_daily_target",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    rule_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    scope_type: Mapped[str] = mapped_column(String(32), default="rule")
    scope_value: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64), index=True)
    target_name: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(32), default="medium", index=True)
    rationale: Mapped[str] = mapped_column(Text)
    current_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    proposed_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    guardrails_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    source_report_type: Mapped[str] = mapped_column(String(64), default="daily_mechanical")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class ResearchPoolItem(Base):
    __tablename__ = "research_pool_items"
    __table_args__ = (
        UniqueConstraint("pool_name", "symbol", name="uq_research_pool_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_name: Mapped[str] = mapped_column(String(64), index=True, default="manual")
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    note: Mapped[Optional[str]] = mapped_column(Text)
    tags_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class PaperAlert(Base):
    __tablename__ = "paper_alerts"
    __table_args__ = (
        UniqueConstraint("position_id", "alert_type", "alert_time", name="uq_paper_alert_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    position_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    alert_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    current_stop: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    pnl_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperTradeReview(Base):
    __tablename__ = "paper_trade_reviews"
    __table_args__ = (
        UniqueConstraint("position_id", name="uq_paper_trade_review_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[int] = mapped_column(Integer, index=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    trade_plan_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    sector_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    strategy_type: Mapped[str] = mapped_column(String(32), index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    exit_date: Mapped[date] = mapped_column(Date, index=True)
    holding_days: Mapped[int] = mapped_column(Integer)
    pnl_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    mfe_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    mae_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    giveback_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    exit_reason: Mapped[str] = mapped_column(String(64), index=True)
    signal_tags_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    alert_summary_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    verdict: Mapped[str] = mapped_column(String(32), index=True)
    summary: Mapped[str] = mapped_column(Text)
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
