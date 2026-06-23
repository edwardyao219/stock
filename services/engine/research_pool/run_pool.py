from __future__ import annotations

import argparse
from pprint import pprint

from services.engine.research_pool.service import add_manual_symbols, list_manual_pool, run_pool_research


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage manual stock research pools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add symbols to a research pool.")
    add_parser.add_argument("symbols", nargs="+")
    add_parser.add_argument("--pool", default="manual")
    add_parser.add_argument("--note", default=None)
    add_parser.add_argument("--tags", nargs="*", default=None)

    list_parser = subparsers.add_parser("list", help="List symbols in a research pool.")
    list_parser.add_argument("--pool", default="manual")

    run_parser = subparsers.add_parser("run", help="Sync data, compute features, and backtest a pool.")
    run_parser.add_argument("--pool", default="manual")
    run_parser.add_argument("--start-date", default=None, help="YYYYMMDD or YYYY-MM-DD")
    run_parser.add_argument("--end-date", default=None, help="YYYYMMDD or YYYY-MM-DD")
    run_parser.add_argument("--persist-backtest", action="store_true")
    run_parser.add_argument("--skip-sync", action="store_true", help="Use existing local bars only.")

    args = parser.parse_args()

    if args.command == "add":
        pprint(
            add_manual_symbols(
                symbols=args.symbols,
                pool_name=args.pool,
                note=args.note,
                tags=args.tags,
            )
        )
    elif args.command == "list":
        pprint(list_manual_pool(pool_name=args.pool))
    elif args.command == "run":
        pprint(
            run_pool_research(
                pool_name=args.pool,
                start_date=args.start_date,
                end_date=args.end_date,
                persist_backtest=args.persist_backtest,
                skip_sync=args.skip_sync,
            )
        )


if __name__ == "__main__":
    main()
