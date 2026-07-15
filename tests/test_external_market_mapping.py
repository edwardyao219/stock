from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.news.external_mapping import (
    build_external_challengers,
    load_external_market_signals,
)
from services.shared.database import Base
from services.shared.models import ExternalMarketSignal


def test_external_market_mapping_creates_watch_only_challenger_without_promoting_sector() -> None:
    challengers = build_external_challengers(
        signals=[
            {
                "source": "user_reported",
                "title": "SK海力士大涨",
                "change_pct": 0.26,
                "a_share_sectors": ["半导体", "元器件", "通信设备"],
            }
        ],
        sector_focus=[
            {"sector": "半导体", "focus_score": 58.0},
            {"sector": "生物制药", "focus_score": 71.0},
        ],
    )

    assert challengers[0]["label"] == "外盘映射待确认"
    assert challengers[0]["a_share_sectors"] == ["半导体", "元器件", "通信设备"]
    assert challengers[0]["startup_watch_allowed"] is False
    assert challengers[0]["market_confirmed"] is False


def test_external_market_signals_are_limited_to_the_signal_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                ExternalMarketSignal(
                    observed_at=datetime(2026, 7, 15, 8, 30),
                    source="verified_feed",
                    title="存储链异动",
                    change_pct=0.26,
                    a_share_sectors_json=["半导体", "元器件"],
                ),
                ExternalMarketSignal(
                    observed_at=datetime(2026, 7, 16, 8, 30),
                    source="verified_feed",
                    title="次日事件",
                    change_pct=0.1,
                    a_share_sectors_json=["通信设备"],
                ),
            ]
        )
        db.commit()

        signals = load_external_market_signals(db, signal_date=date(2026, 7, 15))

    assert [item["title"] for item in signals] == ["存储链异动"]
