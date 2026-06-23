from __future__ import annotations

import argparse

from services.engine.review.mechanical import generate_daily_mechanical_review


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mechanical review report.")
    parser.add_argument("--report-date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    review = generate_daily_mechanical_review(args.report_date)
    print(review.content_md)


if __name__ == "__main__":
    main()
