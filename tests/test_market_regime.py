from services.engine.features.market_regime import classify_market_regime
from services.engine.research_pool.candidates import _passes_market_regime_gate


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
