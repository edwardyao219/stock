from __future__ import annotations

import argparse
from decimal import Decimal
from pprint import pprint

from services.engine.paper.simulator import run_daily_paper_simulation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily paper trading simulation.")
    parser.add_argument("--trade-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--account", default="default")
    parser.add_argument("--initial-cash", default="1000000")
    args = parser.parse_args()

    pprint(
        run_daily_paper_simulation(
            trade_date=args.trade_date,
            account_name=args.account,
            initial_cash=Decimal(args.initial_cash),
        )
    )


if __name__ == "__main__":
    main()
