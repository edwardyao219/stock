import argparse
from pprint import pprint

from services.jobs.pipeline import (
    prepare_next_trade_session,
    resolve_next_trade_date,
    run_after_close_session,
    run_daily_research_pipeline,
    run_intraday_trade_session,
)
from services.shared.database import require_primary_database
from services.shared.time import now_local


def main() -> None:
    today = now_local().date().isoformat()
    parser = argparse.ArgumentParser(description="Run local trading workflow stages.")
    parser.add_argument(
        "--stage",
        choices=["daily", "prepare", "intraday", "after-close"],
        default="daily",
    )
    parser.add_argument("--trade-date", default=today)
    parser.add_argument("--next-trade-date", default=None)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--account", default="default")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--full-market-sync", action="store_true")
    parser.add_argument("--disable-learning-adjustments", action="store_true")
    parser.add_argument("--dry-run-entries", action="store_true")
    parser.add_argument("--dry-run-exits", action="store_true")
    args = parser.parse_args()
    require_primary_database("run_pipeline")
    next_trade_date = args.next_trade_date or resolve_next_trade_date(args.trade_date)

    if args.stage == "prepare":
        result = prepare_next_trade_session(
            args.trade_date,
            next_trade_date,
            limit=args.limit,
            use_learning_adjustments=not args.disable_learning_adjustments,
            force=args.force,
            full_market_sync=args.full_market_sync,
        )
    elif args.stage == "intraday":
        result = run_intraday_trade_session(
            args.trade_date,
            account=args.account,
            execute_entries=not args.dry_run_entries,
            execute_exits=not args.dry_run_exits,
            force=args.force,
        )
    elif args.stage == "after-close":
        result = run_after_close_session(
            args.trade_date,
            next_trade_date,
            limit=args.limit,
            account=args.account,
            use_learning_adjustments=not args.disable_learning_adjustments,
            full_market_sync=args.full_market_sync,
        )
    else:
        result = run_daily_research_pipeline(args.trade_date, next_trade_date)
    pprint(result.to_dict())


if __name__ == "__main__":
    main()
