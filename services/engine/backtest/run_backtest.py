from __future__ import annotations

import argparse
from datetime import date
from pprint import pprint

from services.engine.backtest.sync import run_rules_backtest


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily rule backtest.")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--rules", nargs="*", default=None)
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    pprint(
        run_rules_backtest(
            symbols=args.symbols,
            rule_ids=args.rules,
            start_date=_parse_date(args.start_date),
            end_date=_parse_date(args.end_date),
            run_date=_parse_date(args.run_date),
            persist=args.persist,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
