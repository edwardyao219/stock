from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.fundamental.akshare_client import market_symbol, snapshot_from_indicator_row
from services.engine.fundamental.repository import (
    load_latest_fundamental_snapshot,
    snapshot_to_context,
    upsert_fundamental_snapshots,
)
from services.shared.database import Base


def test_market_symbol_for_akshare_financial_indicator() -> None:
    assert market_symbol("600519") == "600519.SH"
    assert market_symbol("000001") == "000001.SZ"
    assert market_symbol("300750") == "300750.SZ"


def test_snapshot_from_indicator_row_maps_announcement_timing_and_bank_fields() -> None:
    snapshot = snapshot_from_indicator_row(
        "000001",
        {
            "REPORT_DATE": "2026-03-31",
            "NOTICE_DATE": "2026-04-24",
            "TOTALOPERATEREVETZ": "5.2",
            "PARENTNETPROFITTZ": "3.1",
            "ROEJQ": "11.5",
            "ZCFZL": "91.2",
            "NET_INTEREST_MARGIN": "2.03",
            "NONPERLOAN": "1.06",
            "LOAN_PROVISION_RATIO": "2.31",
        },
    )

    assert snapshot is not None
    assert snapshot["report_date"] == "2026-03-31"
    assert snapshot["available_date"] == "2026-04-24"
    assert snapshot["revenue_growth"] == Decimal("0.052")
    assert snapshot["profit_growth"] == Decimal("0.031")
    assert snapshot["roe"] == Decimal("0.115")
    assert snapshot["debt_ratio"] == Decimal("0.912")
    assert snapshot["extra_json"]["roe_annualized"] == "0.460"
    assert snapshot["extra_json"]["net_interest_margin"] == "0.0203"
    assert snapshot["extra_json"]["nonperforming_loan_ratio"] == "0.0106"
    assert snapshot["extra_json"]["loan_provision_ratio"] == "0.0231"


def test_load_latest_fundamental_snapshot_uses_available_date_to_avoid_leakage() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        upsert_fundamental_snapshots(
            db,
            [
                {
                    "symbol": "000001",
                    "report_date": "2025-12-31",
                    "available_date": "2026-03-20",
                    "roe": 0.10,
                },
                {
                    "symbol": "000001",
                    "report_date": "2026-03-31",
                    "available_date": "2026-04-24",
                    "roe": 0.12,
                },
            ],
        )
        db.commit()

        before_notice = load_latest_fundamental_snapshot(db, "000001", date(2026, 4, 1))
        after_notice = load_latest_fundamental_snapshot(db, "000001", date(2026, 4, 25))

    assert before_notice is not None
    assert before_notice.report_date == date(2025, 12, 31)
    assert float(before_notice.roe) == 0.10
    assert after_notice is not None
    assert after_notice.report_date == date(2026, 3, 31)
    assert snapshot_to_context(after_notice)["fundamental_available_date"] == "2026-04-24"
