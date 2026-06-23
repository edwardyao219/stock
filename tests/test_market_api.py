from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.routers.market import get_symbol_candles
from services.shared.database import Base
from services.shared.models import DailyBar


def test_get_symbol_candles_returns_limited_ascending_bars_with_moving_average() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            DailyBar(
                symbol="000001",
                trade_date=date(2026, 1, day),
                open=Decimal(day),
                high=Decimal(day + 1),
                low=Decimal(day - 1),
                close=Decimal(day),
                pre_close=Decimal(day - 1) if day > 1 else None,
                volume=Decimal(day * 100),
                amount=Decimal(day * 1000),
                turnover_rate=None,
                limit_up=Decimal(day) * Decimal("1.1"),
                limit_down=Decimal(day) * Decimal("0.9"),
                is_suspended=False,
            )
            for day in range(1, 31)
        )
        db.commit()

        payload = get_symbol_candles(symbol="000001", db=db, limit=30)

    assert len(payload) == 30
    assert payload[0].time == date(2026, 1, 1)
    assert payload[-1].time == date(2026, 1, 30)
    assert payload[3].ma5 is None
    assert payload[4].ma5 == 3
    assert payload[-1].ma20 == 20.5
