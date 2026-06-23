from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.plans import repository
from services.engine.plans.generator import TradePlanCandidate
from services.shared.database import Base
from services.shared.models import TradePlan


def test_upsert_trade_plans_preserves_executed_status(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    captured_rows = []

    def fake_upsert_rows(db, model, rows, update_columns, constraint=None, index_elements=None):
        captured_rows.extend(rows)
        return len(rows)

    monkeypatch.setattr(repository, "upsert_rows", fake_upsert_rows)

    with session() as db:
        db.add(
            TradePlan(
                plan_date=date(2026, 6, 23),
                trade_date=date(2026, 6, 24),
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                sector_code="银行",
                entry_condition_json={},
                position_size=Decimal("0.10"),
                status="executed",
            )
        )
        db.commit()

        written = repository.upsert_trade_plans(
            db,
            [
                TradePlanCandidate(
                    plan_date="2026-06-23",
                    trade_date="2026-06-24",
                    symbol="000001",
                    rule_id="R001",
                    entry_summary="test",
                    initial_stop=9.5,
                    take_profit_1=10.8,
                    take_profit_2=None,
                    position_size=0.1,
                    confidence_score=80,
                    sector_code="银行",
                    entry_condition={"evidence": {"tags": []}},
                )
            ],
        )

    assert written == 1
    assert captured_rows[0]["status"] == "executed"
