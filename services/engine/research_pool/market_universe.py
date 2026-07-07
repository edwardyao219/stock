from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select

from services.collector.sync import sync_calendar_and_securities, sync_stock_daily_bars
from services.collector.tushare_sync import sync_tushare_daily
from services.engine.features.sync import (
    compute_and_store_sector_features,
    compute_and_store_stock_features,
)
from services.shared.database import SessionLocal
from services.shared.models import Security, StockFeatureDaily

AKSHARE_DAILY_FALLBACK_SYMBOL_LIMIT = 300


@dataclass(frozen=True)
class MarketUniverseResult:
    symbols: int
    synced_daily_rows: int
    feature_rows: int
    sector_rows: int
    feature_symbols: int
    coverage_ratio: float
    warnings: list[str] = field(default_factory=list)


def _feature_symbol_count(feature_date: date) -> int:
    with SessionLocal() as db:
        return int(
            db.execute(
                select(func.count(func.distinct(StockFeatureDaily.symbol))).where(
                    StockFeatureDaily.trade_date == feature_date
                )
            ).scalar_one()
        )


def _sync_market_daily_bars(target_date: date, symbols: list[str]) -> tuple[int, list[str]]:
    warnings: list[str] = []
    try:
        with SessionLocal() as db:
            rows = sync_tushare_daily(
                db,
                trade_date=target_date.strftime("%Y%m%d"),
            )
            db.commit()
        return rows, warnings
    except Exception as exc:
        warnings.append(f"Tushare 当日全市场日线同步失败：{type(exc).__name__}: {exc}")

    if len(symbols) > AKSHARE_DAILY_FALLBACK_SYMBOL_LIMIT:
        warnings.append(
            "全市场股票数量过大，未执行逐只 Akshare 兜底；"
            "请先恢复 Tushare 授权或缩小同步范围。"
        )
        return 0, warnings

    lookback_start = target_date - timedelta(days=120)
    results = sync_stock_daily_bars(
        symbols=symbols,
        start_date=lookback_start.strftime("%Y%m%d"),
        end_date=target_date.strftime("%Y%m%d"),
    )
    synced_daily_rows = sum(item.rows for item in results)
    for item in results:
        if item.status != "ok":
            warnings.append(f"{item.dataset} 同步失败：{item.message or item.status}")
    return synced_daily_rows, warnings


def prepare_market_feature_universe(
    *,
    feature_date: str,
    limit: int | None = None,
    refresh_securities: bool = True,
    sync_daily: bool = True,
    daily_lookback_days: int = 180,
) -> MarketUniverseResult:
    target_date = date.fromisoformat(feature_date)
    warnings: list[str] = []

    if refresh_securities:
        try:
            sync_calendar_and_securities()
        except Exception as exc:
            warnings.append(f"全市场证券列表同步失败：{type(exc).__name__}: {exc}")

    with SessionLocal() as db:
        stmt = (
            select(Security.symbol)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
            .order_by(Security.symbol)
        )
        if limit:
            stmt = stmt.limit(limit)
        symbols = list(db.execute(stmt).scalars())

    synced_daily_rows = 0
    if sync_daily and symbols:
        synced_daily_rows, daily_warnings = _sync_market_daily_bars(target_date, symbols)
        warnings.extend(daily_warnings)

    feature_result = compute_and_store_stock_features(
        symbols=symbols,
        start_date=target_date,
        end_date=target_date,
    )
    sector_result = compute_and_store_sector_features(start_date=target_date, end_date=target_date)
    feature_symbols = _feature_symbol_count(target_date)
    coverage_ratio = feature_symbols / len(symbols) if symbols else 0.0
    if limit is None and symbols and coverage_ratio < 0.70:
        warnings.append(
            "全市场特征覆盖不足："
            f"可扫描 {feature_symbols} / 应覆盖 {len(symbols)}，"
            "候选结果只能作局部参考，不能当作当月热门板块结论。"
        )
    return MarketUniverseResult(
        symbols=len(symbols),
        synced_daily_rows=synced_daily_rows,
        feature_rows=feature_result["rows"],
        sector_rows=sector_result["rows"],
        feature_symbols=feature_symbols,
        coverage_ratio=round(coverage_ratio, 4),
        warnings=warnings,
    )
