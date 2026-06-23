from __future__ import annotations

import argparse
from pprint import pprint

from services.collector.sync import (
    DEFAULT_INDEX_SYMBOLS,
    sync_calendar_and_securities,
    sync_industry_constituents,
    sync_index_daily_bars,
    sync_stock_daily_bars,
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

    args = parser.parse_args()

    if args.command == "bootstrap":
        pprint(sync_calendar_and_securities())
    elif args.command == "industries":
        pprint(sync_industry_constituents(limit=args.limit))
    elif args.command == "indexes":
        pprint(sync_index_daily_bars(args.start_date, args.end_date, args.symbols))
    elif args.command == "stocks":
        pprint(sync_stock_daily_bars(args.symbols, args.start_date, args.end_date))


if __name__ == "__main__":
    main()
