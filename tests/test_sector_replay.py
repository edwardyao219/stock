from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.review.sector_replay import replay_sector_month
from services.shared.database import Base
from services.shared.models import DailyBar, SectorFeatureDaily, Security, StockFeatureDaily


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


def test_replay_sector_month_finds_hot_signal_and_forward_returns(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(symbol="600001", name="强芯A", exchange="SH", industry="半导体", is_active=True, is_st=False),
                Security(symbol="600002", name="强芯B", exchange="SH", industry="半导体", is_active=True, is_st=False),
                Security(symbol="600003", name="弱股", exchange="SH", industry="玻璃", is_active=True, is_st=False),
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 6, 3),
                    features={
                        "sector_strength_score": 68,
                        "sector_trend_continuity_score": 72,
                        "sector_trend_resilience_score": 61,
                        "sector_avg_return_20d": 0.10,
                        "sector_positive_20d_rate": 66,
                        "sector_stock_count": 2,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 6, 4),
                    features={
                        "sector_strength_score": 82,
                        "sector_trend_continuity_score": 80,
                        "sector_trend_resilience_score": 58,
                        "sector_avg_return_20d": 0.28,
                        "sector_positive_20d_rate": 90,
                        "sector_stock_count": 2,
                    },
                ),
            ]
        )
        for symbol in ["600001", "600002", "600003"]:
            db.add(StockFeatureDaily(symbol=symbol, trade_date=date(2026, 6, 3), features={}))
        for symbol, closes in {
            "600001": ["10", "11", "12", "13"],
            "600002": ["20", "21", "22", "24"],
            "600003": ["30", "30", "30", "30"],
        }.items():
            for index, close in enumerate(closes, start=3):
                db.add(_bar(symbol, date(2026, 6, index), close))
        db.commit()

    monkeypatch.setattr("services.engine.review.sector_replay.SessionLocal", lambda: Session(engine))

    result = replay_sector_month("2026-06", sector="半导体", horizons=(1, 3))

    assert result.month == "2026-06"
    assert result.sector == "半导体"
    assert len(result.events) == 2
    event = result.events[0]
    assert event.trade_date == "2026-06-03"
    assert event.coverage_ratio == 1.0
    assert event.qualifies_hot is True
    assert event.setup_label == "mainline_confirmed"
    assert event.extension_risk == "normal"
    assert event.forward_returns[1] == 0.075
    assert event.forward_returns[3] == 0.25
    assert result.events[1].setup_label == "overextended"
    assert result.events[1].extension_risk == "high"
