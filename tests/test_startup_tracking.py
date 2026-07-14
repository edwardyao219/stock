from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.tracking.startup import StartupCandidate, build_startup_tracking_rows
from services.shared.database import Base
from services.shared.models import DailyBar


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
