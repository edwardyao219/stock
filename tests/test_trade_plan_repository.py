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


def test_retire_unselected_trade_plans_keeps_terminal_statuses() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                TradePlan(
                    plan_date=date(2026, 7, 7),
                    trade_date=date(2026, 7, 8),
                    symbol="603083",
                    rule_id="R004",
                    strategy_type="long_term",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    status="planned",
                ),
                TradePlan(
                    plan_date=date(2026, 7, 7),
                    trade_date=date(2026, 7, 8),
                    symbol="002156",
                    rule_id="R007",
                    strategy_type="swing",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    status="planned",
                ),
                TradePlan(
                    plan_date=date(2026, 7, 7),
                    trade_date=date(2026, 7, 8),
                    symbol="600171",
                    rule_id="R004",
                    strategy_type="long_term",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    status="executed",
                ),
            ]
        )
        db.commit()

        retired = repository.retire_unselected_trade_plans(
            db,
            plan_date="2026-07-07",
            trade_date="2026-07-08",
            active_keys={("603083", "R004")},
        )
        db.commit()
        rows = {
            (item.symbol, item.rule_id): item.status
            for item in db.query(TradePlan).order_by(TradePlan.symbol).all()
        }

    assert retired == 1
    assert rows[("603083", "R004")] == "planned"
    assert rows[("002156", "R007")] == "retired"
    assert rows[("600171", "R004")] == "executed"


def test_retire_unselected_trade_plans_can_scope_by_trade_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                TradePlan(
                    plan_date=date(2026, 7, 7),
                    trade_date=date(2026, 7, 8),
                    symbol="000661",
                    rule_id="R002",
                    strategy_type="swing",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    status="planned",
                ),
                TradePlan(
                    plan_date=date(2026, 7, 8),
                    trade_date=date(2026, 7, 8),
                    symbol="002185",
                    rule_id="R004",
                    strategy_type="long_term",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    status="planned",
                ),
            ]
        )
        db.commit()

        retired = repository.retire_unselected_trade_plans(
            db,
            plan_date="2026-07-08",
            trade_date="2026-07-08",
            active_keys={("002185", "R004")},
            include_all_plan_dates=True,
        )
        db.commit()
        rows = {
            (item.plan_date.isoformat(), item.symbol): item.status
            for item in db.query(TradePlan).order_by(TradePlan.plan_date, TradePlan.symbol).all()
        }

    assert retired == 1
    assert rows[("2026-07-07", "000661")] == "retired"
    assert rows[("2026-07-08", "002185")] == "planned"
