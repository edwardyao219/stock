from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.review.repository import load_trade_plans_for_date
from services.shared.database import Base
from services.shared.models import TradePlan


def test_load_trade_plans_for_date_filters_unknown_rule_ids() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add_all(
            [
                TradePlan(
                    plan_date=date(2026, 6, 23),
                    trade_date=date(2026, 6, 24),
                    symbol="000001",
                    rule_id="R001",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("80"),
                    status="planned",
                ),
                TradePlan(
                    plan_date=date(2026, 6, 23),
                    trade_date=date(2026, 6, 24),
                    symbol="000001",
                    rule_id="TEST",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("99"),
                    status="planned",
                ),
            ]
        )
        db.commit()

        plans = load_trade_plans_for_date(db, "2026-06-23")

    assert [item.rule_id for item in plans] == ["R001"]
