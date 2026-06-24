from __future__ import annotations

import argparse
from pprint import pprint

from services.engine.plans.watchlist import generate_watchlist_observation_plans
from services.shared.database import SessionLocal
from services.shared.time import now_local


def main() -> None:
    today = now_local().date().isoformat()
    parser = argparse.ArgumentParser(description="Generate observation plans for a research pool.")
    parser.add_argument("--plan-date", default=today)
    parser.add_argument("--trade-date", default=today)
    parser.add_argument("--feature-date", default=None)
    parser.add_argument("--pool", default="experiment")
    args = parser.parse_args()

    with SessionLocal() as db:
        result = generate_watchlist_observation_plans(
            db=db,
            plan_date=args.plan_date,
            trade_date=args.trade_date,
            feature_date=args.feature_date,
            pool_name=args.pool,
        )
        db.commit()
    pprint(result)


if __name__ == "__main__":
    main()
