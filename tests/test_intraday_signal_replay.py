from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.review.intraday_signal_replay import (
    replay_daily_gap_down_repair_proxy,
    replay_gap_down_repair,
)
from services.shared.database import Base
from services.shared.models import DailyBar, RealtimeQuote, SectorFeatureDaily, Security


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
        volume=Decimal("1000"),
        amount=Decimal("100000"),
        turnover_rate=Decimal("1"),
        limit_up=value * Decimal("1.1"),
        limit_down=value * Decimal("0.9"),
        is_suspended=False,
    )


def _ohlc_bar(
    symbol: str,
    trade_date: date,
    *,
    open_price: str,
    high: str,
    low: str,
    close: str,
    pre_close: str = "10",
) -> DailyBar:
    close_value = Decimal(close)
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=close_value,
        pre_close=Decimal(pre_close),
        volume=Decimal("1000"),
        amount=Decimal("100000"),
        turnover_rate=Decimal("1"),
        limit_up=close_value * Decimal("1.1"),
        limit_down=close_value * Decimal("0.9"),
        is_suspended=False,
    )


def _quote(
    symbol: str,
    quote_time: datetime,
    *,
    price: str,
    open_price: str,
    high: str,
    low: str,
    pre_close: str = "10",
) -> RealtimeQuote:
    return RealtimeQuote(
        symbol=symbol,
        trade_date=quote_time.date(),
        quote_time=quote_time,
        price=Decimal(price),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        pre_close=Decimal(pre_close),
        pct_change=Decimal("0"),
        volume=Decimal("100000"),
        amount=Decimal("1000000"),
        turnover_rate=Decimal("1"),
        source="test",
    )


def test_replay_gap_down_repair_groups_forward_returns_by_sector_strength(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="688001",
                    name="强科技",
                    exchange="SH",
                    industry="半导体",
                    is_active=True,
                    is_st=False,
                ),
                Security(
                    symbol="600001",
                    name="弱消费",
                    exchange="SH",
                    industry="零售",
                    is_active=True,
                    is_st=False,
                ),
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 78,
                        "sector_trend_continuity_score": 74,
                        "sector_avg_return_20d": 0.12,
                        "sector_positive_20d_rate": 66,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="零售",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 45,
                        "sector_trend_continuity_score": 42,
                        "sector_avg_return_20d": 0.01,
                        "sector_positive_20d_rate": 38,
                    },
                ),
            ]
        )
        db.add_all(
            [
                _quote(
                    "688001",
                    datetime(2026, 6, 30, 10, 10),
                    price="10.03",
                    open_price="9.70",
                    high="10.05",
                    low="9.65",
                ),
                _quote(
                    "600001",
                    datetime(2026, 6, 30, 10, 10),
                    price="10.02",
                    open_price="9.70",
                    high="10.04",
                    low="9.65",
                ),
            ]
        )
        db.add_all(
            [
                _bar("688001", date(2026, 6, 30), "10.03"),
                _bar("688001", date(2026, 7, 1), "10.60"),
                _bar("688001", date(2026, 7, 2), "11.00"),
                _bar("600001", date(2026, 6, 30), "10.02"),
                _bar("600001", date(2026, 7, 1), "9.90"),
                _bar("600001", date(2026, 7, 2), "9.82"),
            ]
        )
        db.commit()

    monkeypatch.setattr(
        "services.engine.review.intraday_signal_replay.SessionLocal",
        lambda: Session(engine),
    )

    result = replay_gap_down_repair(
        start_date="2026-06-30",
        end_date="2026-06-30",
        horizons=(1, 2),
    )

    assert result.event_count == 2
    assert result.groups["strong_sector"]["sample_count"] == 1
    assert result.groups["strong_sector"]["horizons"][2]["avg_return"] == 0.09671
    assert result.groups["weak_sector"]["sample_count"] == 1
    assert result.groups["weak_sector"]["horizons"][2]["avg_return"] == -0.01996
    assert result.events[0].sector_strength_group == "strong_sector"
    assert result.events[0].support_flags == ["intraday_gap_down_repair"]


def test_replay_gap_down_repair_keeps_missing_sector_features_separate(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            Security(
                symbol="603986",
                name="兆易创新",
                exchange="SH",
                industry="半导体",
                is_active=True,
                is_st=False,
            )
        )
        db.add(
            _quote(
                "603986",
                datetime(2026, 6, 30, 10, 10),
                price="10.03",
                open_price="9.70",
                high="10.05",
                low="9.65",
            )
        )
        db.add_all(
            [
                _bar("603986", date(2026, 6, 30), "10.03"),
                _bar("603986", date(2026, 7, 1), "10.60"),
            ]
        )
        db.commit()

    monkeypatch.setattr(
        "services.engine.review.intraday_signal_replay.SessionLocal",
        lambda: Session(engine),
    )

    result = replay_gap_down_repair(
        start_date="2026-06-30",
        end_date="2026-06-30",
        horizons=(1,),
    )

    assert result.event_count == 1
    assert result.events[0].sector_strength_group == "unknown_sector"
    assert result.groups["unknown_sector"]["sample_count"] == 1


def test_replay_daily_gap_down_repair_proxy_uses_daily_ohlc_history(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            Security(
                symbol="688001",
                name="强科技",
                exchange="SH",
                industry="半导体",
                is_active=True,
                is_st=False,
            )
        )
        db.add(
            SectorFeatureDaily(
                sector_code="半导体",
                trade_date=date(2026, 6, 30),
                features={
                    "sector_strength_score": 78,
                    "sector_trend_continuity_score": 74,
                    "sector_avg_return_20d": 0.12,
                    "sector_positive_20d_rate": 66,
                },
            )
        )
        db.add_all(
            [
                _ohlc_bar(
                    "688001",
                    date(2026, 6, 30),
                    open_price="9.70",
                    high="10.05",
                    low="9.65",
                    close="10.03",
                ),
                _bar("688001", date(2026, 7, 1), "10.60"),
                _bar("688001", date(2026, 7, 2), "11.00"),
            ]
        )
        db.commit()

    monkeypatch.setattr(
        "services.engine.review.intraday_signal_replay.SessionLocal",
        lambda: Session(engine),
    )

    result = replay_daily_gap_down_repair_proxy(
        start_date="2026-06-30",
        end_date="2026-06-30",
        horizons=(1, 2),
    )

    assert result.event_count == 1
    assert result.events[0].symbol == "688001"
    assert result.events[0].sector_strength_group == "strong_sector"
    assert result.events[0].trigger_price == 10.03
    assert result.events[0].forward_returns[2] == 0.09671
    assert result.events[0].support_flags == ["daily_gap_down_repair_proxy"]
