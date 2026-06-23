from __future__ import annotations

import argparse
from pprint import pprint

from services.collector.industry_mapping import update_security_industries


def main() -> None:
    parser = argparse.ArgumentParser(description="Update local security industry mappings.")
    parser.add_argument(
        "mappings",
        nargs="+",
        help="Mappings like 000001=银行 600519=白酒",
    )
    args = parser.parse_args()

    mapping = {}
    for item in args.mappings:
        symbol, industry = item.split("=", 1)
        mapping[symbol] = industry
    pprint(update_security_industries(mapping))


if __name__ == "__main__":
    main()
