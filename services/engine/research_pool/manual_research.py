from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select

from services.collector.akshare_client import fetch_stock_security
from services.collector.repository import upsert_securities
from services.collector.sync import sync_stock_daily_bars
from services.engine.features.repository import load_daily_bars
from services.engine.features.sync import (
    compute_and_store_sector_features,
    compute_and_store_stock_features,
)
from services.engine.fundamental.sync import sync_fundamentals_from_akshare
from services.engine.plans.sync import generate_and_store_trade_plans
from services.engine.plans.watchlist import generate_watchlist_observation_plans
from services.shared.database import SessionLocal
from services.shared.models import Security, TradingCalendar


@dataclass(frozen=True)
class ManualResearchResult:
    symbol: str
    security_rows: int = 0
    daily_rows: int = 0
    feature_rows: int = 0
    sector_rows: int = 0
    fundamental_ok: int = 0
    formal_plan_rows: int = 0
    watch_plan_rows: int = 0
    feature_date: str | None = None
    warnings: list[str] = field(default_factory=list)


def _latest_bar_date(symbol: str) -> date | None:
    with SessionLocal() as db:
        bars = load_daily_bars(db, symbol=symbol)
    if not bars:
        return None
    return date.fromisoformat(bars[-1].trade_date)


def _next_trade_date(value: date) -> date:
    with SessionLocal() as db:
        calendar_item = db.get(TradingCalendar, value)
    if calendar_item and calendar_item.next_trade_date:
        return calendar_item.next_trade_date
    candidate = value + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _has_local_security(symbol: str) -> bool:
    with SessionLocal() as db:
        return db.execute(
            select(Security.symbol).where(Security.symbol == symbol).limit(1)
        ).scalar_one_or_none() is not None


def refresh_manual_stock_research(
    symbol: str,
    *,
    pool_name: str = "experiment",
    plan_date: str | None = None,
    trade_date: str | None = None,
) -> ManualResearchResult:
    warnings: list[str] = []
    security_rows = 0
    try:
        security = fetch_stock_security(symbol)
        with SessionLocal() as db:
            security_rows = upsert_securities(db, [security])
            db.commit()
    except Exception as exc:
        warnings.append(f"证券信息同步失败：{type(exc).__name__}: {exc}")
        if _has_local_security(symbol):
            security_rows = 1
            warnings.append("使用本地证券信息继续刷新。")

    daily_rows = 0
    sync_results = sync_stock_daily_bars(symbols=[symbol])
    for item in sync_results:
        daily_rows += item.rows
        if item.status != "ok":
            warnings.append(f"{item.dataset} 同步失败：{item.message or item.status}")

    latest_bar_date = _latest_bar_date(symbol)
    if latest_bar_date is None:
        return ManualResearchResult(
            symbol=symbol,
            security_rows=security_rows,
            daily_rows=daily_rows,
            warnings=[*warnings, "未获得日线数据，无法计算特征和策略计划。"],
        )

    feature_result = compute_and_store_stock_features(
        symbols=[symbol],
        start_date=latest_bar_date,
        end_date=latest_bar_date,
    )
    sector_result = compute_and_store_sector_features(
        start_date=latest_bar_date,
        end_date=latest_bar_date,
    )

    fundamental_result = sync_fundamentals_from_akshare(
        symbols=[symbol],
        include_valuation=True,
    )
    for item in fundamental_result["results"]:
        if item["status"] != "ok":
            warnings.append(f"基本面同步失败：{item['message']}")

    effective_plan_date = plan_date or latest_bar_date.isoformat()
    effective_trade_date = trade_date or _next_trade_date(latest_bar_date).isoformat()
    formal_plan_result = generate_and_store_trade_plans(
        plan_date=effective_plan_date,
        trade_date=effective_trade_date,
        feature_date=latest_bar_date.isoformat(),
        symbols=[symbol],
        limit=1,
        use_learning_adjustments=True,
    )
    with SessionLocal() as db:
        watch_plan_result = generate_watchlist_observation_plans(
            db=db,
            plan_date=effective_plan_date,
            trade_date=effective_trade_date,
            pool_name=pool_name,
            feature_date=latest_bar_date.isoformat(),
            symbols=[symbol],
        )
        db.commit()

    return ManualResearchResult(
        symbol=symbol,
        security_rows=security_rows,
        daily_rows=daily_rows,
        feature_rows=feature_result["rows"],
        sector_rows=sector_result["rows"],
        fundamental_ok=int(fundamental_result["ok"]),
        formal_plan_rows=formal_plan_result["written"],
        watch_plan_rows=int(watch_plan_result["written"]),
        feature_date=latest_bar_date.isoformat(),
        warnings=warnings,
    )
