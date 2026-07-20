from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import date
from time import sleep

from sqlalchemy import func, select

from services.collector.akshare_client import (
    fetch_a_share_securities,
    fetch_index_daily_bars,
    fetch_industry_boards,
    fetch_industry_constituents,
    fetch_stock_daily_bars,
    fetch_trade_dates,
)
from services.collector.contracts import CollectionResult
from services.collector.repository import (
    upsert_daily_bars,
    upsert_industry_constituents,
    upsert_securities,
    upsert_trade_calendar,
)
from services.collector.tushare_sync import (
    sync_tushare_cyq_perf,
    sync_tushare_daily,
    sync_tushare_daily_basic,
    sync_tushare_index_daily,
    sync_tushare_limit_list_d,
    sync_tushare_moneyflow,
    sync_tushare_moneyflow_dc,
    sync_tushare_moneyflow_ind_dc,
    sync_tushare_stk_limit,
    sync_tushare_stock_basic,
)
from services.shared.config import get_settings
from services.shared.database import SessionLocal
from services.shared.models import (
    TradingCalendar,
    TushareCyqPerf,
    TushareDaily,
    TushareDailyBasic,
    TushareDatasetSyncReceipt,
    TushareLimitListD,
    TushareMoneyflow,
    TushareMoneyflowDc,
    TushareMoneyflowIndDc,
    TushareStkLimit,
)

DEFAULT_INDEX_SYMBOLS = ["000001", "399001", "399006"]
INDEX_SYMBOL_MAP = {
    "000001": ("sh000001", "000001.SH"),
    "399001": ("sz399001", "399001.SZ"),
    "399006": ("sz399006", "399006.SZ"),
}


def _index_symbol_pair(symbol: str) -> tuple[str, str]:
    if symbol in INDEX_SYMBOL_MAP:
        return INDEX_SYMBOL_MAP[symbol]
    if symbol.startswith(("sh", "sz")):
        bare = symbol[2:]
        return symbol, f"{bare}.{'SH' if symbol.startswith('sh') else 'SZ'}"
    return symbol, symbol


def sync_calendar_and_securities() -> list[CollectionResult]:
    with SessionLocal() as db:
        trade_dates = fetch_trade_dates()
        calendar_rows = upsert_trade_calendar(db, trade_dates)

        securities = fetch_a_share_securities()
        security_rows = upsert_securities(db, securities)

        db.commit()

    latest_trade_date = trade_dates[-1] if trade_dates else ""
    return [
        CollectionResult(
            source="akshare",
            dataset="trading_calendar",
            trade_date=latest_trade_date,
            rows=calendar_rows,
            status="ok",
        ),
        CollectionResult(
            source="akshare",
            dataset="securities",
            trade_date=latest_trade_date,
            rows=security_rows,
            status="ok",
        ),
    ]


def sync_current_tushare_securities(trade_date: str) -> CollectionResult:
    with SessionLocal() as db:
        try:
            rows = sync_tushare_stock_basic(db)
            db.commit()
        except Exception as exc:
            db.rollback()
            return CollectionResult(
                source="tushare_proxy",
                dataset="stock_basic",
                trade_date=trade_date,
                rows=0,
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
    return CollectionResult(
        source="tushare_proxy",
        dataset="stock_basic",
        trade_date=trade_date,
        rows=rows,
        status="ok" if rows else "failed",
        message="" if rows else "empty stock_basic response",
    )


def sync_index_daily_bars(
    start_date: str | None = None,
    end_date: str | None = None,
    symbols: Iterable[str] = DEFAULT_INDEX_SYMBOLS,
) -> list[CollectionResult]:
    settings = get_settings()
    start = start_date or settings.data_start_date
    end = end_date or "20991231"
    results: list[CollectionResult] = []
    with SessionLocal() as db:
        for symbol in symbols:
            storage_symbol, ts_code = _index_symbol_pair(symbol)
            fetch_symbol = storage_symbol[2:] if storage_symbol.startswith(("sh", "sz")) else symbol
            try:
                bars = fetch_index_daily_bars(
                    symbol=fetch_symbol,
                    start_date=start,
                    end_date=end,
                )
                rows = upsert_daily_bars(
                    db,
                    [replace(item, symbol=storage_symbol) for item in bars],
                )
                db.commit()
                results.append(
                    CollectionResult(
                        source="akshare",
                        dataset=f"index_daily:{storage_symbol}",
                        trade_date=end,
                        rows=rows,
                        status="ok",
                    )
                )
            except Exception as exc:
                db.rollback()
                try:
                    rows = sync_tushare_index_daily(
                        db,
                        ts_code=ts_code,
                        start_date=start,
                        end_date=end,
                        symbol=storage_symbol,
                    )
                    db.commit()
                    results.append(
                        CollectionResult(
                            source="tushare_proxy",
                            dataset=f"index_daily:{storage_symbol}",
                            trade_date=end,
                            rows=rows,
                            status="ok",
                            message=f"fallback from Akshare: {type(exc).__name__}: {exc}",
                        )
                    )
                except Exception as fallback_exc:
                    db.rollback()
                    results.append(
                        CollectionResult(
                            source="tushare_proxy",
                            dataset=f"index_daily:{storage_symbol}",
                            trade_date=end,
                            rows=0,
                            status="failed",
                            message=(
                                f"Akshare {type(exc).__name__}: {exc}; "
                                f"Tushare {type(fallback_exc).__name__}: {fallback_exc}"
                            ),
                        )
                    )
    return results


def sync_stock_daily_bars(
    symbols: Iterable[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[CollectionResult]:
    settings = get_settings()
    start = start_date or settings.data_start_date
    end = end_date or "20991231"
    results: list[CollectionResult] = []
    with SessionLocal() as db:
        for symbol in symbols:
            try:
                bars = fetch_stock_daily_bars(symbol=symbol, start_date=start, end_date=end)
                rows = upsert_daily_bars(db, bars)
                db.commit()
                results.append(
                    CollectionResult(
                        source="akshare",
                        dataset=f"stock_daily:{symbol}",
                        trade_date=end,
                        rows=rows,
                        status="ok",
                    )
                )
            except Exception as exc:
                db.rollback()
                results.append(
                    CollectionResult(
                        source="akshare",
                        dataset=f"stock_daily:{symbol}",
                        trade_date=end,
                        rows=0,
                        status="failed",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )
    return results


def sync_industry_constituents(limit: int | None = None) -> list[CollectionResult]:
    try:
        boards = fetch_industry_boards()
    except Exception as exc:
        return [
            CollectionResult(
                source="akshare",
                dataset="industry_constituents",
                trade_date="",
                rows=0,
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
        ]
    if limit:
        boards = boards[:limit]

    results: list[CollectionResult] = []
    with SessionLocal() as db:
        for board in boards:
            try:
                constituents = fetch_industry_constituents(board)
                rows = upsert_industry_constituents(db, constituents)
                results.append(
                    CollectionResult(
                        source="akshare",
                        dataset=f"industry_constituents:{board.name}",
                        trade_date="",
                        rows=rows,
                        status="ok",
                        message=board.code,
                    )
                )
            except Exception as exc:
                results.append(
                    CollectionResult(
                        source="akshare",
                        dataset=f"industry_constituents:{board.name}",
                        trade_date="",
                        rows=0,
                        status="failed",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )
        db.commit()
    return results


def sync_tushare_market_data(
    trade_date: str,
    *,
    ts_code: str | None = None,
) -> list[CollectionResult]:
    results: list[CollectionResult] = []
    with SessionLocal() as db:
        try:
            stock_basic_rows = sync_tushare_stock_basic(db)
            daily_rows = sync_tushare_daily(db, trade_date=trade_date, ts_code=ts_code)
            daily_basic_rows = sync_tushare_daily_basic(db, trade_date=trade_date)
            limit_rows = sync_tushare_stk_limit(db, trade_date=trade_date)
            moneyflow_rows = sync_tushare_moneyflow(db, trade_date=trade_date)
            industry_moneyflow_rows = sync_tushare_moneyflow_ind_dc(db, trade_date=trade_date)
            db.commit()
            results.extend(
                [
                    CollectionResult(
                        "tushare_proxy",
                        "stock_basic",
                        trade_date,
                        stock_basic_rows,
                        "ok",
                    ),
                    CollectionResult("tushare_proxy", "daily", trade_date, daily_rows, "ok"),
                    CollectionResult(
                        "tushare_proxy",
                        "daily_basic",
                        trade_date,
                        daily_basic_rows,
                        "ok",
                    ),
                    CollectionResult("tushare_proxy", "stk_limit", trade_date, limit_rows, "ok"),
                    CollectionResult(
                        "tushare_proxy",
                        "moneyflow",
                        trade_date,
                        moneyflow_rows,
                        "ok",
                    ),
                    CollectionResult(
                        "tushare_proxy",
                        "moneyflow_ind_dc",
                        trade_date,
                        industry_moneyflow_rows,
                        "ok",
                    ),
                ]
            )
        except Exception as exc:
            db.rollback()
            results.append(
                CollectionResult(
                    source="tushare_proxy",
                    dataset="market_data",
                    trade_date=trade_date,
                    rows=0,
                    status="failed",
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
    return results


TUSHARE_MARKET_DATASETS = (
    "daily",
    "daily_basic",
    "stk_limit",
    "moneyflow",
    "moneyflow_ind_dc",
    "moneyflow_dc",
    "limit_list_d",
    "cyq_perf",
)


def _parse_trade_date(value: str) -> date:
    text = str(value).strip()
    if "-" in text:
        return date.fromisoformat(text)
    return date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:8]}")


def _format_trade_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _tushare_dataset_registry() -> dict[str, tuple[type, Callable]]:
    return {
        "daily": (TushareDaily, sync_tushare_daily),
        "daily_basic": (TushareDailyBasic, sync_tushare_daily_basic),
        "stk_limit": (TushareStkLimit, sync_tushare_stk_limit),
        "moneyflow": (TushareMoneyflow, sync_tushare_moneyflow),
        "moneyflow_ind_dc": (TushareMoneyflowIndDc, sync_tushare_moneyflow_ind_dc),
        "moneyflow_dc": (TushareMoneyflowDc, sync_tushare_moneyflow_dc),
        "limit_list_d": (TushareLimitListD, sync_tushare_limit_list_d),
        "cyq_perf": (TushareCyqPerf, sync_tushare_cyq_perf),
    }


def _existing_tushare_rows(db, model: type, trade_date: date) -> int:
    return db.execute(
        select(func.count()).select_from(model).where(model.trade_date == trade_date)
    ).scalar_one()


def _has_completed_tushare_dataset(db, dataset: str, trade_date: date) -> bool:
    return bool(
        db.execute(
            select(TushareDatasetSyncReceipt.id)
            .where(TushareDatasetSyncReceipt.dataset == dataset)
            .where(TushareDatasetSyncReceipt.trade_date == trade_date)
        ).scalar_one_or_none()
    )


def sync_tushare_market_data_resumable(
    trade_date: str,
    *,
    datasets: Iterable[str] = TUSHARE_MARKET_DATASETS,
    force: bool = False,
    ts_code: str | None = None,
) -> list[CollectionResult]:
    trade_day = _parse_trade_date(trade_date)
    trade_date_text = _format_trade_date(trade_day)
    registry = _tushare_dataset_registry()
    results: list[CollectionResult] = []

    with SessionLocal() as db:
        for dataset in datasets:
            if dataset not in registry:
                results.append(
                    CollectionResult(
                        source="tushare_proxy",
                        dataset=dataset,
                        trade_date=trade_date_text,
                        rows=0,
                        status="failed",
                        message="unknown dataset",
                    )
                )
                continue

            model, sync_func = registry[dataset]
            existing_rows = _existing_tushare_rows(db, model, trade_day)
            is_complete = dataset != "limit_list_d" or _has_completed_tushare_dataset(
                db,
                dataset,
                trade_day,
            )
            if not force and is_complete and (existing_rows or dataset == "limit_list_d"):
                results.append(
                    CollectionResult(
                        source="tushare_proxy",
                        dataset=dataset,
                        trade_date=trade_date_text,
                        rows=existing_rows,
                        status="skipped",
                        message="already present",
                    )
                )
                continue

            try:
                if dataset == "daily":
                    rows = sync_func(db, trade_date=trade_date_text, ts_code=ts_code)
                else:
                    rows = sync_func(db, trade_date=trade_date_text)
                db.commit()
                if dataset == "moneyflow" and rows == 0:
                    results.append(
                        CollectionResult(
                            source="tushare_proxy",
                            dataset=dataset,
                            trade_date=trade_date_text,
                            rows=0,
                            status="pending",
                            message="dataset not published yet",
                        )
                    )
                    continue
                results.append(
                    CollectionResult(
                        source="tushare_proxy",
                        dataset=dataset,
                        trade_date=trade_date_text,
                        rows=rows,
                        status="ok",
                    )
                )
            except Exception as exc:
                db.rollback()
                results.append(
                    CollectionResult(
                        source="tushare_proxy",
                        dataset=dataset,
                        trade_date=trade_date_text,
                        rows=0,
                        status="failed",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )
    return results


def _open_trade_dates_between(db, *, start_date: date, end_date: date) -> list[date]:
    dates = db.execute(
        select(TradingCalendar.trade_date)
        .where(TradingCalendar.trade_date >= start_date)
        .where(TradingCalendar.trade_date <= end_date)
        .where(TradingCalendar.is_open.is_(True))
        .order_by(TradingCalendar.trade_date)
    ).scalars().all()
    if dates:
        return list(dates)
    return [start_date] if start_date == end_date else []


def backfill_tushare_market_data(
    start_date: str,
    end_date: str,
    *,
    datasets: Iterable[str] = TUSHARE_MARKET_DATASETS,
    force: bool = False,
    ts_code: str | None = None,
    sync_stock_basic_once: bool = True,
    sleep_seconds: float = 0,
) -> list[CollectionResult]:
    start_day = _parse_trade_date(start_date)
    end_day = _parse_trade_date(end_date)
    results: list[CollectionResult] = []

    with SessionLocal() as db:
        trade_dates = _open_trade_dates_between(db, start_date=start_day, end_date=end_day)
        if sync_stock_basic_once:
            try:
                rows = sync_tushare_stock_basic(db)
                db.commit()
                results.append(
                    CollectionResult(
                        source="tushare_proxy",
                        dataset="stock_basic",
                        trade_date=_format_trade_date(end_day),
                        rows=rows,
                        status="ok",
                    )
                )
            except Exception as exc:
                db.rollback()
                results.append(
                    CollectionResult(
                        source="tushare_proxy",
                        dataset="stock_basic",
                        trade_date=_format_trade_date(end_day),
                        rows=0,
                        status="failed",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )

    for index, current_date in enumerate(trade_dates):
        results.extend(
            sync_tushare_market_data_resumable(
                _format_trade_date(current_date),
                datasets=datasets,
                force=force,
                ts_code=ts_code,
            )
        )
        if sleep_seconds > 0 and index < len(trade_dates) - 1:
            sleep(sleep_seconds)

    return results


def _recent_open_trade_dates(
    db,
    *,
    target_date: date,
    lookback_open_days: int,
) -> list[date]:
    dates = list(
        reversed(
            db.execute(
                select(TradingCalendar.trade_date)
                .where(TradingCalendar.trade_date <= target_date)
                .where(TradingCalendar.is_open.is_(True))
                .order_by(TradingCalendar.trade_date.desc())
                .limit(max(1, lookback_open_days))
            ).scalars().all()
        )
    )
    if dates:
        return dates
    return [target_date]


def sync_recent_tushare_sector_moneyflow(
    trade_date: str,
    *,
    lookback_open_days: int = 8,
) -> list[CollectionResult]:
    target_date = date.fromisoformat(trade_date)
    results: list[CollectionResult] = []
    with SessionLocal() as db:
        latest_stored_date = db.execute(
            select(func.max(TushareMoneyflowIndDc.trade_date)).where(
                TushareMoneyflowIndDc.content_type == "行业"
            )
        ).scalar_one_or_none()
        candidate_dates = _recent_open_trade_dates(
            db,
            target_date=target_date,
            lookback_open_days=lookback_open_days,
        )
        if latest_stored_date is not None:
            candidate_dates = [item for item in candidate_dates if item > latest_stored_date]

        if not candidate_dates:
            return [
                CollectionResult(
                    source="tushare_proxy",
                    dataset="moneyflow_ind_dc_recent",
                    trade_date=trade_date,
                    rows=0,
                    status="skipped",
                    message="行业资金流已是最近交易日，无需补齐。",
                )
            ]

        for current_date in candidate_dates:
            current_trade_date = current_date.strftime("%Y%m%d")
            try:
                rows = sync_tushare_moneyflow_ind_dc(db, trade_date=current_trade_date)
                db.commit()
                results.append(
                    CollectionResult(
                        source="tushare_proxy",
                        dataset="moneyflow_ind_dc",
                        trade_date=current_date.isoformat(),
                        rows=rows,
                        status="ok",
                    )
                )
            except Exception as exc:
                db.rollback()
                results.append(
                    CollectionResult(
                        source="tushare_proxy",
                        dataset="moneyflow_ind_dc",
                        trade_date=current_date.isoformat(),
                        rows=0,
                        status="failed",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )
    return results
