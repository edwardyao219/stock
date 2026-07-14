from services.engine.features.market_turn import classify_market_turn_state


def test_market_turn_stays_defensive_when_breadth_and_trend_are_weak() -> None:
    state = classify_market_turn_state(
        trend_score=28,
        breadth_score=22,
        emotion_score=24,
        liquidity_score=35,
        strong_trend_rate=5,
        up_signal_rate=1,
    )

    assert state.key == "defense"
    assert state.core_action_allowed is False


def test_market_turn_does_not_call_zero_breadth_a_repair() -> None:
    state = classify_market_turn_state(
        trend_score=36,
        breadth_score=0,
        emotion_score=0,
        liquidity_score=45,
        strong_trend_rate=0,
        up_signal_rate=0,
    )

    assert state.key == "defense"


def test_market_turn_allows_startup_watch_before_full_action_confirmation() -> None:
    state = classify_market_turn_state(
        trend_score=52,
        breadth_score=58,
        emotion_score=56,
        liquidity_score=55,
        strong_trend_rate=16,
        up_signal_rate=8,
    )

    assert state.key == "startup_allowed"
    assert state.startup_candidates_allowed is True
    assert state.core_action_allowed is False


def test_market_turn_requires_all_five_signals_for_actionable_state() -> None:
    state = classify_market_turn_state(
        trend_score=68,
        breadth_score=64,
        emotion_score=66,
        liquidity_score=64,
        strong_trend_rate=24,
        up_signal_rate=14,
    )

    assert state.key == "actionable"
    assert state.core_action_allowed is True
    assert len(state.confirmed_signals) == 5
