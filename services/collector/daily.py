from services.collector.contracts import CollectionResult


def sync_daily_market_data(trade_date: str) -> list[CollectionResult]:
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
    results.extend(sync_calendar_and_securities())
    results.extend(sync_index_daily_bars(end_date=trade_date.replace("-", "")))
    results.append(
        CollectionResult(
            source="akshare",
            dataset="stock_daily",
            trade_date=trade_date,
            rows=0,
            status="pending",
            message="Use sync_stock_daily_bars with selected symbols to avoid full-market slow sync.",
        )
    )
    return results
