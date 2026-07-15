from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import ExternalMarketSignal


def load_external_market_signals(
    db: Session,
    *,
    signal_date: date,
) -> list[dict[str, object]]:
    start = datetime.combine(signal_date, time.min)
    end = start + timedelta(days=1)
    rows = list(
        db.execute(
            select(ExternalMarketSignal)
            .where(ExternalMarketSignal.observed_at >= start)
            .where(ExternalMarketSignal.observed_at < end)
            .order_by(ExternalMarketSignal.observed_at.desc(), ExternalMarketSignal.id.desc())
        ).scalars()
    )
    return [
        {
            "source": row.source,
            "title": row.title,
            "change_pct": row.change_pct,
            "a_share_sectors": list(row.a_share_sectors_json or []),
            "source_url": row.source_url,
            "observed_at": row.observed_at.isoformat(),
        }
        for row in rows
    ]


def build_external_challengers(
    *,
    signals: list[dict[str, Any]],
    sector_focus: list[dict[str, Any]],
) -> list[dict[str, object]]:
    focus_scores = {
        str(item.get("sector") or "").strip(): float(item.get("focus_score") or 0.0)
        for item in sector_focus
        if str(item.get("sector") or "").strip()
    }
    challengers: list[dict[str, object]] = []
    for signal in signals:
        sectors = [
            str(value).strip()
            for value in signal.get("a_share_sectors") or []
            if str(value).strip()
        ]
        if not sectors:
            continue
        challengers.append(
            {
                "source": str(signal.get("source") or "external"),
                "title": str(signal.get("title") or "外盘信号"),
                "change_pct": signal.get("change_pct"),
                "a_share_sectors": sectors,
                "mapped_focus_scores": {
                    sector: round(focus_scores[sector], 4)
                    for sector in sectors
                    if sector in focus_scores
                },
                "label": "外盘映射待确认",
                "startup_watch_allowed": False,
                "market_confirmed": False,
                "summary": "外盘异动仅列入观察，需等待A股板块扩散、量能和龙头承接确认。",
            }
        )
    return challengers
