from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from services.engine.news.catalysts import (
    SectorCatalyst,
    SectorCatalystReport,
)
from services.shared.models import MarketMessageSnapshot


def load_recent_message_snapshot(
    db: Session,
    *,
    as_of: datetime,
    max_age_seconds: float,
) -> MarketMessageSnapshot | None:
    min_time = as_of - timedelta(seconds=max_age_seconds)
    stmt = (
        select(MarketMessageSnapshot)
        .where(MarketMessageSnapshot.snapshot_time >= min_time)
        .where(MarketMessageSnapshot.snapshot_time <= as_of)
        .order_by(desc(MarketMessageSnapshot.snapshot_time), desc(MarketMessageSnapshot.id))
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def snapshot_to_report(
    snapshot: MarketMessageSnapshot,
    *,
    limit: int | None = None,
) -> SectorCatalystReport:
    catalysts = [
        SectorCatalyst(
            sector_name=str(item.get("sector_name") or ""),
            catalyst_score=float(item.get("catalyst_score") or 0),
            catalyst_label=str(item.get("catalyst_label") or "观察"),
            keywords=[str(value) for value in item.get("keywords", [])],
            related_sectors=[str(value) for value in item.get("related_sectors", [])],
            source_titles=[str(value) for value in item.get("source_titles", [])],
            risk_notes=[str(value) for value in item.get("risk_notes", [])],
        )
        for item in (snapshot.catalysts_json.get("catalysts") or [])
        if isinstance(item, dict)
    ]
    if limit is not None:
        catalysts = catalysts[:limit]
    return SectorCatalystReport(
        as_of=snapshot.snapshot_time,
        source_count=snapshot.source_count,
        catalysts=catalysts,
        message=snapshot.message,
        snapshot_id=snapshot.id,
        snapshot_trade_date=snapshot.trade_date.isoformat(),
        stored=True,
    )


def store_message_snapshot(
    db: Session,
    *,
    report: SectorCatalystReport,
    raw_messages: list[dict[str, Any]],
) -> MarketMessageSnapshot:
    snapshot = MarketMessageSnapshot(
        trade_date=report.as_of.date(),
        snapshot_time=report.as_of,
        source_count=report.source_count,
        message=report.message,
        raw_messages_json={"messages": raw_messages},
        catalysts_json={"catalysts": [item.to_dict() for item in report.catalysts]},
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot
