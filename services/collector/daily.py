from services.collector.contracts import CollectionResult


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

    try:
        from services.collector.sync import sync_calendar_and_securities, sync_index_daily_bars
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
        results.extend(sync_index_daily_bars(end_date=trade_date.replace("-", "")))
    except Exception as exc:
        results.append(_failed_result("index_daily", trade_date, exc))

    results.append(
        CollectionResult(
            source="akshare",
            dataset="stock_daily",
            trade_date=trade_date,
            rows=0,
            status="pending",
            message=(
                "Use sync_stock_daily_bars with selected symbols "
                "to avoid full-market slow sync."
            ),
        )
    )
    return results
