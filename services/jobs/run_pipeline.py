import argparse
from pprint import pprint

from services.jobs.pipeline import run_daily_research_pipeline
from services.shared.time import now_local


def main() -> None:
    today = now_local().date().isoformat()
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default=today)
    parser.add_argument("--next-trade-date", default=today)
    args = parser.parse_args()

    result = run_daily_research_pipeline(args.trade_date, args.next_trade_date)
    pprint(result)


if __name__ == "__main__":
    main()
