from __future__ import annotations

import argparse
from pprint import pprint

from services.engine.plans.sync import generate_and_store_trade_plans


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate trade plans from latest features.")
    parser.add_argument("--plan-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--trade-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--feature-date", default=None, help="YYYY-MM-DD, defaults to plan-date")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    pprint(
        generate_and_store_trade_plans(
            plan_date=args.plan_date,
            trade_date=args.trade_date,
            feature_date=args.feature_date,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
