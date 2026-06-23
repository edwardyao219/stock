from __future__ import annotations

import argparse
import json

from services.engine.paper.realtime import run_realtime_monitor_loop


def main() -> None:
    parser = argparse.ArgumentParser(description="Run realtime paper position monitor loop.")
    parser.add_argument("--trade-date", default=None)
    parser.add_argument("--account", default="default")
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--ticks", type=int, default=1)
    args = parser.parse_args()

    results = run_realtime_monitor_loop(
        interval_seconds=args.interval_seconds,
        max_ticks=args.ticks if args.ticks > 0 else None,
        trade_date=args.trade_date,
        account_name=args.account,
    )
    for result in results:
        print(json.dumps(result.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
