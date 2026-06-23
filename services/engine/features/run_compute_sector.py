from __future__ import annotations

import argparse
from datetime import date
from pprint import pprint

from services.engine.features.sync import compute_and_store_sector_features


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute sector features from stock features.")
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD")
    args = parser.parse_args()

    pprint(
        compute_and_store_sector_features(
            start_date=_parse_date(args.start_date),
            end_date=_parse_date(args.end_date),
        )
    )


if __name__ == "__main__":
    main()
