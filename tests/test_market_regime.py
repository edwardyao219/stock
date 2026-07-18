from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.features.market_regime import classify_market_regime
from services.engine.features.market_regime_repository import (
    backfill_market_regime_daily_from_candidate_snapshots,
)
from services.engine.research_pool.candidates import _passes_market_regime_gate
from services.shared.database import Base
from services.shared.models import CandidateDiscoverySnapshot, MarketRegimeDaily


def test_classify_market_regime_marks_warm_breadth_with_weak_trend_as_unconfirmed_rebound() -> None:
    assert classify_market_regime(
        trend_score=32,
        breadth_score=65,
        emotion_score=62,
        volatility_score=48,
    ) == "rebound_unconfirmed"


def test_unconfirmed_rebound_allows_only_high_quality_observation() -> None:
    context = {
        "trend_score": 82,
        "relative_strength_score": 72,
        "sector_strength_score": 70,
        "volume_confirmation_score": 66,
        "risk_score": 32,
        "overheat_score": 48,
    }

    assert not _passes_market_regime_gate(
        context,
        regime="rebound_unconfirmed",
        selection_mode="formal_strategy",
    )
    assert not _passes_market_regime_gate(
        context,
        regime="rebound_unconfirmed",
        selection_mode="potential_watch",
    )
    assert _passes_market_regime_gate(
        context,
        regime="rebound_unconfirmed",
        selection_mode="observation",
    )


def test_backfill_market_regime_daily_accepts_only_exact_consistent_snapshots() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=date(2026, 1, 2),
                    next_trade_date=date(2026, 1, 5),
                    candidate_limit=15,
                    include_fundamentals=False,
                    discovery_json={
                        "feature_date": "2026-01-02",
                        "market_regime": "panic",
                        "market_regime_snapshot": {
                            "trend_score": 22.0,
                            "breadth_score": 18.0,
                            "emotion_score": 20.0,
                            "volatility_score": 74.0,
                            "risk_level": "high",
                        },
                    },
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=date(2026, 1, 2),
                    next_trade_date=date(2026, 1, 5),
                    candidate_limit=20,
                    include_fundamentals=False,
                    discovery_json={
                        "feature_date": "2026-01-02",
                        "market_regime": "panic",
                        "market_regime_snapshot": {"risk_level": "high"},
                    },
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=date(2026, 1, 5),
                    next_trade_date=date(2026, 1, 6),
                    candidate_limit=15,
                    include_fundamentals=False,
                    discovery_json={"feature_date": "2026-01-02", "market_regime": "range"},
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=date(2026, 1, 6),
                    next_trade_date=date(2026, 1, 7),
                    candidate_limit=15,
                    include_fundamentals=False,
                    discovery_json={"feature_date": "2026-01-06", "market_regime": "range"},
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=date(2026, 1, 6),
                    next_trade_date=date(2026, 1, 7),
                    candidate_limit=20,
                    include_fundamentals=False,
                    discovery_json={"feature_date": "2026-01-06", "market_regime": "rebound"},
                ),
            ]
        )
        db.commit()

        written = backfill_market_regime_daily_from_candidate_snapshots(
            db,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        db.commit()
        rows = db.query(MarketRegimeDaily).all()

    assert written == 1
    assert len(rows) == 1
    assert rows[0].trade_date == date(2026, 1, 2)
    assert rows[0].regime == "panic"
    assert rows[0].trend_score == 22.0
    assert rows[0].risk_level == "high"
