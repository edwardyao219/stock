from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.collector.naver_finance import fetch_naver_realtime_quote
from services.shared.models import ExternalMarketSignal

SK_HYNIX_SYMBOL = "000660"
KOSPI_SYMBOL = "KOSPI"
SK_HYNIX_SIGNAL_MIN_CHANGE_PCT = 0.05
KOSPI_CONFIRMATION_MIN_CHANGE_PCT = 0.0
SK_HYNIX_A_SHARE_SECTORS = ["半导体", "元器件", "通信设备"]


def sync_korea_semiconductor_signal(db: Session) -> ExternalMarketSignal | None:
    hynix = fetch_naver_realtime_quote(SK_HYNIX_SYMBOL, kind="stock")
    kospi = fetch_naver_realtime_quote(KOSPI_SYMBOL, kind="index")
    observed_at = hynix.observed_at or kospi.observed_at
    if (
        observed_at is None
        or hynix.change_pct is None
        or hynix.change_pct < SK_HYNIX_SIGNAL_MIN_CHANGE_PCT
        or kospi.change_pct is None
        or kospi.change_pct < KOSPI_CONFIRMATION_MIN_CHANGE_PCT
    ):
        return None

    start = datetime.combine(observed_at.date(), time.min)
    end = start + timedelta(days=1)
    existing = db.execute(
        select(ExternalMarketSignal)
        .where(ExternalMarketSignal.source == hynix.source)
        .where(ExternalMarketSignal.title.like("SK海力士%"))
        .where(ExternalMarketSignal.observed_at >= start)
        .where(ExternalMarketSignal.observed_at < end)
        .order_by(ExternalMarketSignal.observed_at.desc(), ExternalMarketSignal.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    signal = ExternalMarketSignal(
        observed_at=observed_at,
        source=hynix.source,
        title=f"SK海力士 {hynix.change_pct:+.2%} / KOSPI {kospi.change_pct:+.2%}",
        change_pct=hynix.change_pct,
        a_share_sectors_json=SK_HYNIX_A_SHARE_SECTORS,
        source_url=(
            "https://polling.finance.naver.com/api/realtime/domestic/stock/000660"
        ),
    )
    db.add(signal)
    return signal
