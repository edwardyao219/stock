from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.collector.external_market import sync_korea_semiconductor_signal
from services.collector.naver_finance import NaverRealtimeQuote
from services.shared.database import Base
from services.shared.models import ExternalMarketSignal


def test_korea_semiconductor_signal_requires_hynix_and_kospi_confirmation(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    quotes = {
        ("000660", "stock"): NaverRealtimeQuote(
            symbol="000660",
            name="SK하이닉스",
            price=2118000,
            previous_close_change=205000,
            change_pct=0.1072,
            observed_at=datetime(2026, 7, 15, 9, 42),
            market_status="OPEN",
            source="naver.finance.realtime.stock",
        ),
        ("KOSPI", "index"): NaverRealtimeQuote(
            symbol="KOSPI",
            name="코스피",
            price=7291.58,
            previous_close_change=434.75,
            change_pct=0.0634,
            observed_at=datetime(2026, 7, 15, 9, 42),
            market_status="OPEN",
            source="naver.finance.realtime.index",
        ),
    }
    monkeypatch.setattr(
        "services.collector.external_market.fetch_naver_realtime_quote",
        lambda symbol, *, kind: quotes[(symbol, kind)],
    )

    with Session(engine) as db:
        signal = sync_korea_semiconductor_signal(db)
        db.commit()

        stored = db.query(ExternalMarketSignal).one()

    assert signal is not None
    assert stored.source == "naver.finance.realtime.stock"
    assert stored.a_share_sectors_json == ["半导体", "元器件", "通信设备"]
