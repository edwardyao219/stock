from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import IntradayMarketTurnSnapshot

LATE_MARKET_TURN_MIN_COVERAGE = 0.80


def late_market_turn_snapshot(db: Session, trade_date: date) -> IntradayMarketTurnSnapshot | None:
    cutoff = datetime.combine(trade_date, datetime.min.time()).replace(hour=14, minute=50)
    return db.execute(
        select(IntradayMarketTurnSnapshot)
        .where(IntradayMarketTurnSnapshot.trade_date == trade_date)
        .where(IntradayMarketTurnSnapshot.snapshot_time >= cutoff)
        .order_by(IntradayMarketTurnSnapshot.snapshot_time.desc())
        .limit(1)
    ).scalar_one_or_none()


def late_market_turn_health(snapshot: IntradayMarketTurnSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {"status": "missing", "message": "缺少尾盘市场快照"}
    ready = snapshot.coverage_ratio >= LATE_MARKET_TURN_MIN_COVERAGE and bool(
        (snapshot.state_json or {}).get("data_ready")
    )
    return {
        "status": "ok" if ready else "warning",
        "coverage_ratio": float(snapshot.coverage_ratio),
        "message": "尾盘市场快照正常" if ready else "尾盘市场快照覆盖不足或未就绪",
    }


def late_market_turn_history_health(db: Session, limit: int = 20) -> dict[str, int]:
    trade_dates = list(
        db.execute(
            select(IntradayMarketTurnSnapshot.trade_date)
            .group_by(IntradayMarketTurnSnapshot.trade_date)
            .order_by(IntradayMarketTurnSnapshot.trade_date.desc())
            .limit(max(1, limit))
        ).scalars()
    )
    healthy_days = sum(
        late_market_turn_health(late_market_turn_snapshot(db, trade_date))["status"] == "ok"
        for trade_date in trade_dates
    )
    return {"observed_days": len(trade_dates), "healthy_days": healthy_days}
