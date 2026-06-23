from __future__ import annotations

import argparse
from pprint import pprint

from services.engine.fundamental.akshare_client import (
    fetch_financial_indicator_snapshots,
    fetch_valuation_snapshots,
)
from services.engine.fundamental.repository import (
    upsert_fundamental_snapshots,
    upsert_valuation_snapshots,
)
from services.shared.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync A-share fundamental snapshots from AKShare.")
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="A-share symbols, e.g. 000001 600519",
    )
    parser.add_argument("--include-valuation", action="store_true")
    args = parser.parse_args()

    results = []
    with SessionLocal() as db:
        for symbol in args.symbols:
            rows = fetch_financial_indicator_snapshots(symbol)
            count = upsert_fundamental_snapshots(db, rows)
            valuation_count = 0
            if args.include_valuation:
                valuation_rows = fetch_valuation_snapshots(symbol)
                valuation_count = upsert_valuation_snapshots(db, valuation_rows)
            results.append(
                {
                    "symbol": symbol,
                    "financial_snapshots": count,
                    "valuation_snapshots": valuation_count,
                }
            )
        db.commit()

    pprint({"source": "akshare", "fundamental_snapshots": results})


if __name__ == "__main__":
    main()
