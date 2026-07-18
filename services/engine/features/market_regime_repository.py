from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.features.market_regime import MarketRegimeSnapshot
from services.shared.models import CandidateDiscoverySnapshot, MarketRegimeDaily
from services.shared.upsert import upsert_rows


def store_market_regime_daily(
    db: Session,
    snapshot: MarketRegimeSnapshot,
    *,
    source: str = "candidate_discovery",
) -> int:
    now = datetime.utcnow()
    return upsert_rows(
        db,
        MarketRegimeDaily,
        [
            {
                "trade_date": date.fromisoformat(snapshot.trade_date),
                "regime": snapshot.regime,
                "trend_score": snapshot.trend_score,
                "breadth_score": snapshot.breadth_score,
                "emotion_score": snapshot.emotion_score,
                "volatility_score": snapshot.volatility_score,
                "risk_level": snapshot.risk_level,
                "source": source,
                "created_at": now,
                "updated_at": now,
            }
        ],
        update_columns=[
            "regime",
            "trend_score",
            "breadth_score",
            "emotion_score",
            "volatility_score",
            "risk_level",
            "source",
            "updated_at",
        ],
        index_elements=[MarketRegimeDaily.trade_date],
    )


def _market_regime_snapshot_from_discovery(
    discovery: dict[str, Any],
    *,
    signal_date: date,
) -> MarketRegimeSnapshot | None:
    regime_snapshot = discovery.get("market_regime_snapshot") or {}
    feature_date = str(discovery.get("feature_date") or regime_snapshot.get("trade_date") or "")
    regime = str(discovery.get("market_regime") or regime_snapshot.get("regime") or "")
    if feature_date != signal_date.isoformat() or not regime:
        return None
    try:
        return MarketRegimeSnapshot(
            trade_date=signal_date.isoformat(),
            regime=regime,  # type: ignore[arg-type]
            trend_score=float(regime_snapshot.get("trend_score") or 0.0),
            breadth_score=float(regime_snapshot.get("breadth_score") or 0.0),
            emotion_score=float(regime_snapshot.get("emotion_score") or 0.0),
            volatility_score=float(regime_snapshot.get("volatility_score") or 0.0),
            risk_level=str(regime_snapshot.get("risk_level") or "unknown"),
        )
    except (TypeError, ValueError):
        return None


def backfill_market_regime_daily_from_candidate_snapshots(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    cache_version: str = "candidate-v5-startup-signal",
) -> int:
    rows = db.execute(
        select(CandidateDiscoverySnapshot.signal_date, CandidateDiscoverySnapshot.discovery_json)
        .where(CandidateDiscoverySnapshot.cache_version == cache_version)
        .where(CandidateDiscoverySnapshot.signal_date >= date.fromisoformat(start_date))
        .where(CandidateDiscoverySnapshot.signal_date <= date.fromisoformat(end_date))
    ).all()
    snapshots_by_date: dict[date, list[MarketRegimeSnapshot]] = defaultdict(list)
    for signal_date, discovery in rows:
        if not isinstance(discovery, dict):
            continue
        snapshot = _market_regime_snapshot_from_discovery(discovery, signal_date=signal_date)
        if snapshot is not None:
            snapshots_by_date[signal_date].append(snapshot)

    written = 0
    for snapshots in snapshots_by_date.values():
        regimes = {snapshot.regime for snapshot in snapshots}
        if len(regimes) != 1:
            continue
        chosen = max(
            snapshots,
            key=lambda snapshot: sum(
                value != 0.0
                for value in (
                    snapshot.trend_score,
                    snapshot.breadth_score,
                    snapshot.emotion_score,
                    snapshot.volatility_score,
                )
            ),
        )
        written += store_market_regime_daily(db, chosen, source="candidate_snapshot_backfill")
    return written
