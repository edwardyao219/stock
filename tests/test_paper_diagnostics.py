from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.paper.diagnostics import (
    diagnose_paper_trading,
    persist_paper_trading_review,
)
from services.shared.database import Base
from services.shared.models import (
    PaperPosition,
    ParameterRecommendation,
    ReviewReport,
    Security,
    TradePlan,
)


def _add_position(
    db,
    *,
    symbol: str,
    rule_id: str,
    pnl_pct: str,
    highest_price: str,
    lowest_price: str,
    exit_reason: str = "time_exit",
    trade_plan_id: int | None = None,
) -> None:
    db.add(
        PaperPosition(
            account_id=1,
            trade_plan_id=trade_plan_id,
            symbol=symbol,
            rule_id=rule_id,
            strategy_type="short_term",
            entry_date=date(2026, 1, 2),
            entry_price=Decimal("10"),
            quantity=1000,
            initial_stop=Decimal("9.5"),
            current_stop=Decimal("9.5"),
            take_profit_1=Decimal("11"),
            take_profit_2=None,
            highest_price=Decimal(highest_price),
            lowest_price=Decimal(lowest_price),
            max_holding_days=5,
            status="closed",
            exit_date=date(2026, 1, 6),
            exit_price=Decimal("10") * (Decimal("1") + Decimal(pnl_pct)),
            exit_reason=exit_reason,
            pnl=Decimal("10000") * Decimal(pnl_pct),
            pnl_pct=Decimal(pnl_pct),
        )
    )


def test_diagnose_paper_trading_detects_profit_giveback() -> None:
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
                    "snapshot": {
                        "amount_percentile_60d": 95,
                        "distance_to_20d_high": -0.01,
                        "return_5d": 0.10,
                    },
                    "evidence": {
                        "tags": [
                            {
                                "name": "high_position_volume_spike",
                                "direction": "risk",
                                "severity": "high",
                                "rationale": "高位放量风险",
                                "values": {"amount_percentile_60d": 95},
                            }
                        ],
                        "risk_flags": ["high_position_volume_spike"],
                        "support_flags": [],
                    },
                },
                position_size=Decimal("0.10"),
                status="executed",
            )
        )
        for index in range(10):
            _add_position(
                db,
                symbol="000001",
                rule_id="R001",
                pnl_pct="-0.005",
                highest_price="10.8",
                lowest_price="9.8",
                exit_reason="time_exit" if index < 8 else "stop_loss",
                trade_plan_id=1,
            )
        db.commit()

        diagnostics = diagnose_paper_trading(db, "2026-01-10")

    rule = next(item for item in diagnostics if item.scope_type == "rule")
    assert rule.scope_value == "R001"
    assert rule.trade_count == 10
    assert rule.avg_giveback > 0.02
    assert rule.volume_trap_rate == 1
    assert any(item.target_name == "profit_giveback" for item in rule.parameter_suggestions)
    assert any(item.target_name == "high_volume_chase" for item in rule.parameter_suggestions)
    assert any(item.scope_type == "sector" and item.scope_value == "银行" for item in diagnostics)
    signal = next(
        item
        for item in diagnostics
        if item.scope_type == "signal" and item.scope_value == "high_position_volume_spike"
    )
    assert any(
        item.target_type == "evidence_thresholds"
        and item.action == "test_tighten_or_filter"
        for item in signal.parameter_suggestions
    )


def test_persist_paper_trading_review_writes_report_and_recommendations() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="000001", name="平安银行", exchange="SZ", industry="银行"))
        for _ in range(3):
            _add_position(
                db,
                symbol="000001",
                rule_id="R001",
                pnl_pct="-0.03",
                highest_price="10.2",
                lowest_price="9.3",
                exit_reason="stop_loss",
            )
        changed = persist_paper_trading_review(db, "2026-01-10")
        db.commit()

        reports = db.query(ReviewReport).all()
        recommendations = db.query(ParameterRecommendation).all()

    assert changed >= 1
    assert reports[0].report_type == "paper_trading_review"
    assert recommendations
    assert recommendations[0].source_report_type == "paper_trading_review"
