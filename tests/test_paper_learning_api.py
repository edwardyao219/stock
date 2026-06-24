from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.main import create_app
from apps.api.app.routers.paper_learning import get_learning_overview, list_trade_reviews
from services.shared.database import Base
from services.shared.models import PaperTradeReview


def _session_with_reviews():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session()
    for index in range(3):
        db.add(
            PaperTradeReview(
                position_id=index + 1,
                account_id=1,
                trade_plan_id=None,
                symbol="000001",
                rule_id="R001",
                sector_code="银行",
                strategy_type="short_term",
                entry_date=date(2026, 1, 2),
                exit_date=date(2026, 1, 5),
                holding_days=4,
                pnl_pct=Decimal("0.010000"),
                mfe_pct=Decimal("0.080000"),
                mae_pct=Decimal("-0.020000"),
                giveback_pct=Decimal("0.060000"),
                exit_reason="trailing_take_profit",
                signal_tags_json={"items": ["trend_alignment"]},
                alert_summary_json={"total": 1},
                evidence_json={},
                verdict="profit_giveback",
                summary="sample",
            )
        )
    db.commit()
    return db


def test_paper_learning_routes_are_registered() -> None:
    schema = create_app().openapi()

    assert "/paper-learning/overview" in schema["paths"]
    assert "/paper-learning/reviews" in schema["paths"]


def test_get_learning_overview_returns_insights_and_reviews() -> None:
    db = _session_with_reviews()

    payload = get_learning_overview(db=db, report_date="2026-01-10")

    assert payload.latest_review_date == "2026-01-10"
    assert payload.insights
    assert payload.insights[0].sample_count >= 3
    assert payload.recent_reviews[0].symbol == "000001"
    db.close()


def test_list_trade_reviews_filters_symbol() -> None:
    db = _session_with_reviews()

    payload = list_trade_reviews(db=db, symbol="000001")

    assert len(payload) == 3
    assert payload[0].signal_tags == ["trend_alignment"]
    db.close()
