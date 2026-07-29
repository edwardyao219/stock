from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.shared.database import Base
from services.shared.models import FundamentalSnapshot
from services.shared.sync_schema import (
    _cleanup_legacy_mixed_fundamental_snapshots,
    _conservative_financial_available_date,
)


def test_conservative_financial_available_date_uses_reporting_deadlines() -> None:
    assert _conservative_financial_available_date(date(2026, 3, 31)) == date(2026, 4, 30)
    assert _conservative_financial_available_date(date(2026, 6, 30)) == date(2026, 8, 31)
    assert _conservative_financial_available_date(date(2026, 9, 30)) == date(2026, 10, 31)
    assert _conservative_financial_available_date(date(2025, 12, 31)) == date(2026, 4, 30)


def test_legacy_mixed_snapshot_cleanup_is_idempotent_and_keeps_pure_valuation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                FundamentalSnapshot(
                    symbol="002558",
                    report_date=date(2026, 3, 31),
                    available_date=date(2026, 3, 31),
                    profit_growth=Decimal("2.105"),
                    pe_ttm=Decimal("33.8"),
                    pb=Decimal("3.67"),
                    dividend_yield=Decimal("0.01"),
                    extra_json={"source": "akshare.stock_value_em"},
                ),
                FundamentalSnapshot(
                    symbol="002558",
                    report_date=date(2026, 3, 28),
                    available_date=date(2026, 3, 28),
                    pe_ttm=Decimal("32.0"),
                    pb=Decimal("3.5"),
                    extra_json={"source": "akshare.stock_value_em"},
                ),
            ]
        )
        db.commit()

        assert _cleanup_legacy_mixed_fundamental_snapshots(db) == 1
        db.commit()
        assert _cleanup_legacy_mixed_fundamental_snapshots(db) == 0
        db.commit()

        mixed = db.query(FundamentalSnapshot).filter_by(report_date=date(2026, 3, 31)).one()
        pure = db.query(FundamentalSnapshot).filter_by(report_date=date(2026, 3, 28)).one()

    assert mixed.available_date == date(2026, 4, 30)
    assert mixed.pe_ttm is None
    assert mixed.pb is None
    assert mixed.dividend_yield is None
    assert mixed.extra_json == {
        "source": "legacy_mixed_snapshot",
        "availability_quality": "legacy_conservative_date",
    }
    assert pure.pe_ttm == Decimal("32.000000")
    assert pure.extra_json == {"source": "akshare.stock_value_em"}
