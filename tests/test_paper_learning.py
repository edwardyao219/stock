from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.paper.learning import (
    learn_from_paper_trade_reviews,
    persist_paper_learning_report,
)
from services.shared.database import Base
from services.shared.models import (
    PaperTradeReview,
    ParameterRecommendation,
    ReviewReport,
)


def _add_review(db, *, position_id: int, verdict: str, pnl_pct: str, giveback_pct: str) -> None:
    db.add(
        PaperTradeReview(
            position_id=position_id,
            account_id=1,
            trade_plan_id=1,
            symbol="000001",
            rule_id="R001",
            sector_code="银行",
            strategy_type="short_term",
            entry_date=date(2026, 1, 2),
            exit_date=date(2026, 1, 5),
            holding_days=4,
            pnl_pct=Decimal(pnl_pct),
            mfe_pct=Decimal("0.080000"),
            mae_pct=Decimal("-0.020000"),
            giveback_pct=Decimal(giveback_pct),
            exit_reason="trailing_take_profit",
            signal_tags_json={"items": ["trend_alignment"]},
            alert_summary_json={"total": 1},
            evidence_json={},
            verdict=verdict,
            summary="sample",
        )
    )


def test_learn_from_paper_trade_reviews_suggests_tighter_trailing() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        for index in range(3):
            _add_review(
                db,
                position_id=index + 1,
                verdict="profit_giveback",
                pnl_pct="0.010000",
                giveback_pct="0.060000",
            )
        db.commit()

        insights = learn_from_paper_trade_reviews(db, "2026-01-10")

    rule = next(item for item in insights if item.scope_type == "rule")
    assert rule.scope_value == "R001"
    assert rule.avg_giveback == 0.06
    assert any(item.target_name == "learned_profit_protection" for item in rule.suggestions)
    assert any(
        item.scope_type == "signal" and item.scope_value == "trend_alignment"
        for item in insights
    )


def test_persist_paper_learning_report_writes_report_and_recommendations() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        for index in range(3):
            _add_review(
                db,
                position_id=index + 1,
                verdict="profit_giveback",
                pnl_pct="0.010000",
                giveback_pct="0.060000",
            )
        changed = persist_paper_learning_report(db, "2026-01-10")
        db.commit()
        reports = db.query(ReviewReport).all()
        recommendations = db.query(ParameterRecommendation).all()

    assert changed >= 1
    assert reports[0].report_type == "paper_learning_review"
    assert recommendations[0].source_report_type == "paper_learning_review"
