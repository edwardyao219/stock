from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.paper.review import upsert_paper_trade_reviews
from services.shared.database import Base
from services.shared.models import PaperAlert, PaperPosition, PaperTradeReview, Security, TradePlan


def test_upsert_paper_trade_reviews_builds_structured_sample() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="000001", name="平安银行", exchange="SZ", industry="银行"))
        db.add(
            TradePlan(
                id=1,
                plan_date=date(2026, 1, 1),
                trade_date=date(2026, 1, 2),
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                sector_code="银行",
                entry_condition_json={
                    "snapshot": {"sector_code": "银行"},
                    "evidence": {
                        "tags": [
                            {"name": "high_position_volume_spike"},
                            {"name": "trend_alignment"},
                        ]
                    },
                },
                position_size=Decimal("0.10"),
                status="executed",
            )
        )
        db.add(
            PaperPosition(
                id=1,
                account_id=1,
                trade_plan_id=1,
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                entry_date=date(2026, 1, 2),
                entry_price=Decimal("10"),
                quantity=1000,
                initial_stop=Decimal("9.5"),
                current_stop=Decimal("9.8"),
                take_profit_1=Decimal("10.8"),
                take_profit_2=None,
                highest_price=Decimal("11"),
                lowest_price=Decimal("9.7"),
                max_holding_days=5,
                status="closed",
                exit_date=date(2026, 1, 5),
                exit_price=Decimal("10.2"),
                exit_reason="trailing_take_profit",
                pnl=Decimal("200"),
                pnl_pct=Decimal("0.020000"),
            )
        )
        db.add(
            PaperAlert(
                account_id=1,
                position_id=1,
                symbol="000001",
                alert_type="take_profit_touched",
                severity="medium",
                alert_time=datetime(2026, 1, 3, 10, 30),
                price=Decimal("10.8"),
                current_stop=Decimal("10.15"),
                pnl_pct=Decimal("0.08"),
                message="触及第一止盈",
            )
        )
        db.commit()

        changed = upsert_paper_trade_reviews(db, date(2026, 1, 10))
        db.commit()
        review = db.query(PaperTradeReview).one()

    assert changed == 1
    assert review.symbol == "000001"
    assert review.sector_code == "银行"
    assert review.holding_days == 4
    assert review.pnl_pct == Decimal("0.020000")
    assert review.mfe_pct == Decimal("0.100000")
    assert review.mae_pct == Decimal("-0.030000")
    assert review.giveback_pct == Decimal("0.080000")
    assert review.verdict == "profit_giveback"
    assert review.signal_tags_json["items"] == [
        "high_position_volume_spike",
        "trend_alignment",
    ]
    assert review.alert_summary_json["by_type"]["take_profit_touched"] == 1
    assert "回吐8.00%" in review.summary
