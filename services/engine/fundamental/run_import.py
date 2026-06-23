from __future__ import annotations

import argparse
import csv
from pprint import pprint

from services.engine.fundamental.repository import upsert_fundamental_snapshots
from services.shared.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Import fundamental snapshots from CSV.")
    parser.add_argument("csv_path")
    args = parser.parse_args()

    with open(args.csv_path, newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    with SessionLocal() as db:
        count = upsert_fundamental_snapshots(db, rows)
        db.commit()

    pprint({"fundamental_snapshots": count})


if __name__ == "__main__":
    main()
