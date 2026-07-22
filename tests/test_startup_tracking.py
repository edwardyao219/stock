from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.tracking.startup import (
    StartupCandidate,
    build_startup_historical_evidence,
    build_startup_tracking_rows,
)
from services.shared.database import Base
from services.shared.models import DailyBar, ResearchSignalLedger, TradePlan


def _bar(symbol: str, trade_date: date, close: str) -> DailyBar:
    value = Decimal(close)
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=value,
        high=value,
        low=value,
        close=value,
        pre_close=value,
        volume=Decimal("100000"),
        amount=Decimal("1000000"),
        turnover_rate=None,
        limit_up=value * Decimal("1.1"),
        limit_down=value * Decimal("0.9"),
        is_suspended=False,
    )


def test_startup_tracking_uses_signal_date_and_reports_horizon_progress() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)

    with Session(engine) as db:
        db.add_all(
            [_bar("000001", signal_date - timedelta(days=1), "8")]
            + [
                _bar(
                    "000001",
                    signal_date + timedelta(days=offset),
                    "10" if offset == 0 else "11",
                )
                for offset in range(6)
            ]
        )
        db.commit()

        rows = build_startup_tracking_rows(
            db,
            [
                StartupCandidate(
                    symbol="000001",
                    tags=(
                        "candidate_pool:startup_preheat",
                        "2026-07-01",
                        "startup_signal_score:78",
                        "startup_signal_reason:量价修复",
                    ),
                ),
                StartupCandidate(
                    symbol="000002",
                    tags=("candidate_pool:expansion_confirm", "2026-07-01"),
                ),
                StartupCandidate(symbol="000003", tags=("manual_focus", "2026-07-01")),
            ],
        )

    assert [row.symbol for row in rows] == ["000001", "000002"]
    assert rows[0].signal_type == "startup_preheat"
    assert rows[0].signal_label == "启动观察"
    assert rows[0].realised_return == 0.1
    assert rows[0].horizons[5].status == "completed"
    assert rows[0].horizons[10].status == "in_progress"
    assert rows[1].signal_type == "startup_confirmed"
    assert rows[1].signal_label == "启动确认"
    assert rows[1].realised_return is None


def test_startup_historical_evidence_reads_startup_scopes() -> None:
    evidence = build_startup_historical_evidence(
        {
            "scopes": {
                "startup_preheat": {
                    "horizons": {
                        5: {
                            "raw": {"sample_count": 2, "win_rate": 0.5, "avg_return": 0.03},
                            "guarded": {"sample_count": 2, "avg_return": 0.02},
                        }
                    }
                },
                "startup_confirmed": {
                    "horizons": {
                        5: {
                            "raw": {"sample_count": 1, "win_rate": 1.0, "avg_return": 0.08},
                            "guarded": {"sample_count": 1, "avg_return": 0.06},
                        }
                    }
                },
            }
        }
    )

    assert evidence["startup_preheat"][5]["sample_count"] == 2
    assert evidence["startup_preheat"][5]["win_rate"] == 0.5
    assert evidence["startup_preheat"][5]["raw_return"] == 0.03
    assert evidence["startup_confirmed"][5]["guarded_return"] == 0.06


def test_startup_tracking_prefers_latest_lifecycle_event_evidence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_time = datetime(2026, 7, 22, 14, 0)

    with Session(engine) as db:
        db.add(
            ResearchSignalLedger(
                source="startup_state",
                signal_type="startup_invalidated",
                signal_time=signal_time,
                signal_date=signal_time.date(),
                symbol="600001",
                signal_price=10.2,
                executable=False,
                evidence_json={
                    "confirmation_evidence": [],
                    "invalidation_reasons": ["板块转弱"],
                    "next_conditions": [],
                },
            )
        )
        db.commit()

        row = build_startup_tracking_rows(
            db,
            [
                StartupCandidate(
                    symbol="600001",
                    tags=(
                        "candidate_pool:startup_preheat",
                        "startup_state:probing",
                        "2026-07-22",
                    ),
                )
            ],
        )[0]

    assert row.state == "invalidated"
    assert row.signal_type == "startup_invalidated"
    assert row.signal_label == "启动失效"
    assert row.state_time == signal_time
    assert row.invalidation_reasons == ["板块转弱"]
    assert row.next_conditions == []
    assert row.plan_available is False


def test_startup_tracking_reports_confirmed_planned_trade_as_available() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 22)

    with Session(engine) as db:
        db.add(
            TradePlan(
                plan_date=signal_date - timedelta(days=1),
                trade_date=signal_date,
                symbol="600001",
                rule_id="R002",
                strategy_type="swing",
                sector_code="半导体",
                entry_condition_json={},
                position_size=Decimal("0.10"),
                status="planned",
            )
        )
        db.commit()

        row = build_startup_tracking_rows(
            db,
            [
                StartupCandidate(
                    symbol="600001",
                    tags=(
                        "candidate_pool:startup_preheat",
                        "startup_state:confirmed",
                        "2026-07-22",
                    ),
                )
            ],
        )[0]

    assert row.state == "confirmed"
    assert row.plan_available is True
