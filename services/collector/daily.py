from services.collector.contracts import CollectionResult


def sync_daily_market_data(trade_date: str) -> list[CollectionResult]:
    """Placeholder for AKShare/Tushare daily market synchronization."""
    datasets = [
        "index_daily",
        "stock_daily",
        "sector_daily",
        "limit_up_down",
    ]
    return [
        CollectionResult(
            source="placeholder",
            dataset=dataset,
            trade_date=trade_date,
            rows=0,
            status="pending",
            message="Real data connector is not implemented yet.",
        )
        for dataset in datasets
    ]
