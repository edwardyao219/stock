from __future__ import annotations

import argparse
from datetime import date
from pprint import pprint

from services.engine.features.sync import compute_and_store_stock_features


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute stock daily features.")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    pprint(
        compute_and_store_stock_features(
            symbols=args.symbols,
            start_date=_parse_date(args.start_date),
            end_date=_parse_date(args.end_date),
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
