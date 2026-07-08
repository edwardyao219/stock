from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.paper.repository import load_trade_plans_for_trade_date
from services.shared.database import Base
from services.shared.models import TradePlan


def _plan(symbol: str, rule_id: str, strategy_type: str, score: str) -> TradePlan:
    return TradePlan(
        plan_date=date(2026, 7, 7),
        trade_date=date(2026, 7, 8),
        symbol=symbol,
        rule_id=rule_id,
        strategy_type=strategy_type,
        sector_code=None,
        entry_condition_json={},
        entry_trigger_price=Decimal("10.20"),
        max_gap_up_pct=Decimal("0.06"),
        trailing_drawdown_pct=Decimal("0.06"),
        initial_stop=Decimal("9.70"),
        take_profit_1=Decimal("10.80"),
        take_profit_2=Decimal("11.40"),
        max_holding_days=5,
        position_size=Decimal("0.10"),
        confidence_score=Decimal(score),
        status="planned",
    )


def test_load_trade_plans_for_trade_date_keeps_best_plan_per_symbol() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                _plan("603083", "R002", "short_term", "90"),
                _plan("603083", "R004", "long_term", "78"),
                _plan("002156", "R007", "swing", "75"),
            ]
        )
        db.commit()

        plans = load_trade_plans_for_trade_date(db, date(2026, 7, 8))

    assert [(plan.symbol, plan.rule_id) for plan in plans] == [
        ("603083", "R004"),
        ("002156", "R007"),
    ]
