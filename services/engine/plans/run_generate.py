from __future__ import annotations

import argparse
from pprint import pprint

from services.engine.plans.sync import generate_and_store_trade_plans


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate trade plans from latest features.")
    parser.add_argument("--plan-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--trade-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--feature-date", default=None, help="YYYY-MM-DD, defaults to plan-date")
    parser.add_argument("--pool", default=None)
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--disable-learning-adjustments",
        action="store_true",
        help="Generate plans without paper-learning parameter adjustments.",
    )
    args = parser.parse_args()

    pprint(
        generate_and_store_trade_plans(
            plan_date=args.plan_date,
            trade_date=args.trade_date,
            feature_date=args.feature_date,
            symbols=args.symbols.split(",") if args.symbols else None,
            pool_name=args.pool,
            limit=args.limit,
            use_learning_adjustments=not args.disable_learning_adjustments,
        )
    )


if __name__ == "__main__":
    main()
