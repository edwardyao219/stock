from __future__ import annotations

import argparse
from pprint import pprint

from services.collector.sync import (
    DEFAULT_INDEX_SYMBOLS,
    TUSHARE_MARKET_DATASETS,
    backfill_tushare_market_data,
    sync_calendar_and_securities,
    sync_index_daily_bars,
    sync_industry_constituents,
    sync_recent_tushare_sector_moneyflow,
    sync_stock_daily_bars,
    sync_tushare_market_data,
)
from services.shared.config import get_settings


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Sync market data from AKShare.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("bootstrap", help="Sync trading calendar and securities.")

    industry_parser = subparsers.add_parser("industries", help="Sync industry constituents.")
    industry_parser.add_argument("--limit", type=int, default=None)

    index_parser = subparsers.add_parser("indexes", help="Sync index daily bars.")
    index_parser.add_argument("--start-date", default=settings.data_start_date)
    index_parser.add_argument("--end-date", default="20991231")
    index_parser.add_argument("--symbols", nargs="*", default=DEFAULT_INDEX_SYMBOLS)

    stock_parser = subparsers.add_parser("stocks", help="Sync selected stock daily bars.")
    stock_parser.add_argument("symbols", nargs="+")
    stock_parser.add_argument("--start-date", default=settings.data_start_date)
    stock_parser.add_argument("--end-date", default="20991231")

    tushare_parser = subparsers.add_parser("tushare", help="Sync market data from Tushare proxy.")
    tushare_parser.add_argument("--trade-date", required=True)
    tushare_parser.add_argument("--ts-code", default=None)

    tushare_backfill_parser = subparsers.add_parser(
        "tushare-backfill",
        help="Backfill Tushare proxy datasets over open trading dates.",
    )
    tushare_backfill_parser.add_argument("--start-date", required=True)
    tushare_backfill_parser.add_argument("--end-date", required=True)
    tushare_backfill_parser.add_argument(
        "--datasets",
        nargs="*",
        default=list(TUSHARE_MARKET_DATASETS),
    )
    tushare_backfill_parser.add_argument("--force", action="store_true")
    tushare_backfill_parser.add_argument("--ts-code", default=None)
    tushare_backfill_parser.add_argument("--skip-stock-basic", action="store_true")
    tushare_backfill_parser.add_argument("--sleep-seconds", type=float, default=0.2)

    tushare_sector_parser = subparsers.add_parser(
        "tushare-sector-flow",
        help="Backfill recent sector moneyflow from Tushare proxy.",
    )
    tushare_sector_parser.add_argument("--trade-date", required=True)
    tushare_sector_parser.add_argument("--lookback-open-days", type=int, default=8)

    args = parser.parse_args()

    if args.command == "bootstrap":
        pprint(sync_calendar_and_securities())
    elif args.command == "industries":
        pprint(sync_industry_constituents(limit=args.limit))
    elif args.command == "indexes":
        pprint(sync_index_daily_bars(args.start_date, args.end_date, args.symbols))
    elif args.command == "stocks":
        pprint(sync_stock_daily_bars(args.symbols, args.start_date, args.end_date))
    elif args.command == "tushare":
        pprint(sync_tushare_market_data(args.trade_date, ts_code=args.ts_code))
    elif args.command == "tushare-backfill":
        pprint(
            backfill_tushare_market_data(
                args.start_date,
                args.end_date,
                datasets=args.datasets,
                force=args.force,
                ts_code=args.ts_code,
                sync_stock_basic_once=not args.skip_stock_basic,
                sleep_seconds=args.sleep_seconds,
            )
        )
    elif args.command == "tushare-sector-flow":
        pprint(
            sync_recent_tushare_sector_moneyflow(
                args.trade_date,
                lookback_open_days=args.lookback_open_days,
            )
        )


if __name__ == "__main__":
    main()
