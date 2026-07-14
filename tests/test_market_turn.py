from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.features.market_turn import (
    classify_market_turn_state,
    classify_verified_market_turn_state,
)
from services.engine.research_pool.candidates import _verified_market_turn_snapshot
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    SectorFeatureDaily,
    Security,
    TushareDatasetSyncReceipt,
    TushareLimitListD,
)


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


def test_verified_market_turn_fails_closed_when_full_market_evidence_is_missing() -> None:
    state = classify_verified_market_turn_state(
        breadth_ratio=0.7,
        amount_change_pct=0.2,
        limit_down_count=0,
        index_change_pct=0.01,
        sector_expansion_count=4,
        data_ready=False,
    )

    assert state.key == "watch_repair"
    assert state.core_action_allowed is False


def test_verified_market_turn_requires_real_five_signal_confirmation() -> None:
    state = classify_verified_market_turn_state(
        breadth_ratio=0.65,
        amount_change_pct=0.08,
        limit_down_count=3,
        index_change_pct=0.012,
        sector_expansion_count=4,
        data_ready=True,
    )

    assert state.key == "actionable"
    assert state.core_action_allowed is True
    assert len(state.confirmed_signals) == 5


def test_verified_market_turn_defends_against_limit_down_expansion() -> None:
    state = classify_verified_market_turn_state(
        breadth_ratio=0.42,
        amount_change_pct=0.18,
        limit_down_count=35,
        index_change_pct=-0.018,
        sector_expansion_count=1,
        data_ready=True,
    )

    assert state.key == "defense"


def test_verified_market_turn_accepts_flat_index_and_flat_amount_for_startup_watch() -> None:
    state = classify_verified_market_turn_state(
        breadth_ratio=0.55,
        amount_change_pct=0.0,
        limit_down_count=12,
        index_change_pct=0.0,
        sector_expansion_count=2,
        data_ready=True,
    )

    assert state.key == "startup_allowed"


def test_verified_market_turn_rejects_local_sample_despite_complete_limit_receipt() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    feature_date = date(2026, 7, 13)
    previous_date = date(2026, 7, 10)

    def bar(symbol: str, trade_day: date, close: str, amount: str) -> DailyBar:
        return DailyBar(
            symbol=symbol,
            trade_date=trade_day,
            open=Decimal("10"),
            high=Decimal("12"),
            low=Decimal("9"),
            close=Decimal(close),
            pre_close=Decimal("10"),
            volume=Decimal("100"),
            amount=Decimal(amount),
            turnover_rate=Decimal("1"),
            limit_up=None,
            limit_down=None,
            is_suspended=False,
        )

    with Session(engine) as db:
        securities = [
            Security(
                symbol=f"{index:06d}",
                name=f"样本{index}",
                exchange="SZ",
                list_date=date(2020, 1, 1),
                industry=f"行业{index}",
            )
            for index in range(1, 106)
        ]
        db.add_all(securities)
        db.add_all(
            [
                bar(f"{index:06d}", previous_date, "10", "100")
                for index in range(1, 101)
            ]
            + [
                bar(f"{index:06d}", feature_date, "11", "110")
                for index in range(1, 101)
            ]
            + [
                bar("sh000001", previous_date, "10", "100"),
                bar("sh000001", feature_date, "10.1", "110"),
            ]
        )
        db.add_all(
            [
                SectorFeatureDaily(
                    sector_code=f"行业{index}",
                    trade_date=feature_date,
                    features={"sector_strength_score": 70, "sector_breadth_score": 60},
                )
                for index in range(1, 4)
            ]
            + [
                TushareLimitListD(
                    ts_code=f"{index:06d}.SZ",
                    trade_date=feature_date,
                    limit="U",
                )
                for index in range(600000, 600100)
            ]
            + [
                TushareDatasetSyncReceipt(
                    dataset="limit_list_d",
                    trade_date=feature_date,
                    row_count=100,
                )
            ]
        )
        db.commit()

        snapshot = _verified_market_turn_snapshot(
            db,
            feature_date=feature_date,
            contexts=[],
        )

    assert snapshot["data_ready"] is False
    assert snapshot["key"] == "watch_repair"
