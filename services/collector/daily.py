from services.collector.contracts import CollectionResult

TUSHARE_AFTER_CLOSE_DATASETS = (
    "daily",
    "daily_basic",
    "stk_limit",
    "moneyflow",
    "moneyflow_dc",
    "limit_list_d",
    "cyq_perf",
)


def _failed_result(dataset: str, trade_date: str, exc: Exception) -> CollectionResult:
    return CollectionResult(
        source="akshare",
        dataset=dataset,
        trade_date=trade_date,
        rows=0,
        status="failed",
        message=f"{type(exc).__name__}: {exc}",
    )


def sync_daily_market_data(
    trade_date: str,
    *,
    full_refresh: bool = False,
    force: bool = False,
) -> list[CollectionResult]:
    if not full_refresh:
        return [
            CollectionResult(
                source="local",
                dataset="daily_market_data",
                trade_date=trade_date,
                rows=0,
                status="skipped",
                message=(
                    "Lightweight run: skipped full-market Eastmoney sync and "
                    "used local database records."
                ),
            )
        ]

    compact_trade_date = trade_date.replace("-", "")

    try:
        from services.collector.sync import (
            sync_calendar_and_securities,
            sync_index_daily_bars,
            sync_tushare_market_data_resumable,
        )
    except ModuleNotFoundError as exc:
        return [
            CollectionResult(
                source="akshare",
                dataset="daily_market_data",
                trade_date=trade_date,
                rows=0,
                status="pending",
                message=f"Data dependencies are not installed yet: {exc.name}",
            )
        ]

    results = []
    try:
        results.extend(sync_calendar_and_securities())
    except Exception as exc:
        results.append(_failed_result("trading_calendar_and_securities", trade_date, exc))

    try:
        results.extend(sync_index_daily_bars(end_date=compact_trade_date))
    except Exception as exc:
        results.append(_failed_result("index_daily", trade_date, exc))

    try:
        results.extend(
            sync_tushare_market_data_resumable(
                compact_trade_date,
                datasets=TUSHARE_AFTER_CLOSE_DATASETS,
                force=force,
            )
        )
    except Exception as exc:
        results.append(_failed_result("tushare_after_close_market_data", trade_date, exc))

    return results
