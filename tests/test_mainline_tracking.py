from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.tracking import mainline
from services.engine.tracking.mainline import (
    ConfirmedMainlineOutcome,
    MainlineHorizonOutcome,
    build_confirmed_mainline_candidate_bindings,
    list_confirmed_mainline_outcomes,
)
from services.shared.database import Base
from services.shared.models import DailyBar, IntradayMarketTurnSnapshot


def _bar(trade_date: date, close: str, symbol: str = "600001") -> DailyBar:
    value = Decimal(close)
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=value,
        high=value,
        low=value,
        close=value,
        pre_close=value,
        volume=Decimal("100000"),
        amount=Decimal("1000000"),
        turnover_rate=None,
        limit_up=value * Decimal("1.1"),
        limit_down=value * Decimal("0.9"),
        is_suspended=False,
    )


def test_confirmed_mainline_outcomes_use_1030_signal_close_and_trade_day_horizons() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)

    with Session(engine) as db:
        db.add(
            IntradayMarketTurnSnapshot(
                trade_date=signal_date,
                snapshot_time=datetime(2026, 7, 1, 10, 30),
                coverage_ratio=0.99,
                breadth_ratio=0.6,
                total_amount=100.0,
                index_change_pct=0.002,
                sector_expansion_count=3,
                state_json={
                    "cross_day_mainline": {
                        "status": "观察确认",
                        "checkpoint": "10:30复核",
                        "sectors": [
                            {
                                "sector": "半导体",
                                "status": "观察确认",
                                "current_leader_symbol": "600001",
                            }
                        ],
                    },
                    "confirmed_candidate_bindings": [
                        {"symbol": "600002", "sector": "半导体", "selection_tier": "formal"}
                    ],
                },
            )
        )
        db.add_all(
            [_bar(signal_date + timedelta(days=offset), str(10 + offset)) for offset in range(4)]
            + [
                _bar(signal_date + timedelta(days=offset), str(20 + offset * 2), "600002")
                for offset in range(4)
            ]
        )
        db.commit()

        rows = list_confirmed_mainline_outcomes(db)

    assert len(rows) == 1
    assert rows[0].sector == "半导体"
    assert rows[0].leader_symbol == "600001"
    assert rows[0].horizons[1].status == "completed"
    assert rows[0].horizons[1].return_pct == 0.1
    assert rows[0].horizons[3].return_pct == 0.3
    assert rows[0].horizons[5].status == "waiting"
    assert rows[0].candidate_bindings[0].symbol == "600002"
    assert rows[0].candidate_bindings[0].horizons[1].return_pct == 0.1


def test_mainline_candidate_bindings_keep_only_formal_candidates_in_confirmed_sectors() -> None:
    bindings = build_confirmed_mainline_candidate_bindings(
        candidates=[
            {"symbol": "600001", "sector": "半导体", "selection_tier": "formal"},
            {"symbol": "600002", "sector": "半导体", "selection_tier": "watch"},
            {"symbol": "600003", "sector": "通信设备", "selection_tier": "formal"},
        ],
        confirmed_sectors={"半导体"},
    )

    assert bindings == [{"symbol": "600001", "sector": "半导体", "selection_tier": "formal"}]


def test_strong_sector_benchmark_outcomes_use_persisted_snapshot_leader() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)

    with Session(engine) as db:
        db.add(
            IntradayMarketTurnSnapshot(
                trade_date=signal_date,
                snapshot_time=datetime(2026, 7, 1, 11, 30),
                coverage_ratio=0.99,
                breadth_ratio=0.6,
                total_amount=100.0,
                index_change_pct=0.002,
                sector_expansion_count=3,
                state_json={
                    "leading_sustained_sectors": [{
                        "sector": "通信设备",
                        "up_ratio": 0.8,
                        "avg_change_pct": 0.02,
                        "leader_symbol": "600001",
                        "leader_change_pct": 0.05,
                    }]
                },
            )
        )
        db.add_all([_bar(signal_date, "10"), _bar(signal_date + timedelta(days=1), "11")])
        db.commit()

        rows = list_confirmed_mainline_outcomes(db)

    assert len(rows) == 1
    assert rows[0].signal_type == "strong_benchmark"
    assert rows[0].sector == "通信设备"
    assert rows[0].horizons[1].return_pct == 0.1


def test_strong_benchmark_summary_uses_only_completed_horizons() -> None:
    def outcome(value: float | None) -> ConfirmedMainlineOutcome:
        return ConfirmedMainlineOutcome(
            signal_type="strong_benchmark",
            signal_date="2026-07-01",
            sector="通信设备",
            leader_symbol="600001",
            horizons={
                1: MainlineHorizonOutcome(
                    horizon=1,
                    status="completed" if value is not None else "waiting",
                    return_pct=value,
                )
            },
            candidate_bindings=[],
        )

    summary = mainline.summarize_mainline_outcomes(
        [outcome(0.1), outcome(-0.05), outcome(None)]
    )

    assert summary[1] == {
        "horizon": 1,
        "sample_count": 2,
        "minimum_sample_count": 20,
        "eligible_for_policy": False,
        "avg_return_pct": 0.025,
        "win_rate": 0.5,
        "failure_rate": 0.5,
    }


def test_strong_benchmark_breakdown_groups_three_day_results() -> None:
    def outcome(sector: str, market_state: str, value: float) -> ConfirmedMainlineOutcome:
        return ConfirmedMainlineOutcome(
            signal_type="strong_benchmark",
            signal_date="2026-07-01",
            sector=sector,
            leader_symbol="600001",
            horizons={
                3: MainlineHorizonOutcome(
                    horizon=3,
                    status="completed",
                    return_pct=value,
                )
            },
            candidate_bindings=[],
            market_state=market_state,
        )

    result = mainline.summarize_mainline_outcome_breakdowns(
        [
            outcome("通信设备", "repair_confirmed", 0.1),
            outcome("通信设备", "repair_confirmed", -0.02),
            outcome("影视音像", "watch_repair", 0.03),
        ]
    )

    assert result["sectors"][0] == {
        "key": "通信设备",
        "sample_count": 2,
        "minimum_sample_count": 20,
        "eligible_for_policy": False,
        "avg_return_pct": 0.04,
        "win_rate": 0.5,
        "failure_rate": 0.5,
    }
    assert result["market_states"][0]["key"] == "repair_confirmed"


def test_strong_benchmark_summary_unlocks_policy_at_twenty_samples() -> None:
    outcomes = [
        ConfirmedMainlineOutcome(
            signal_type="strong_benchmark",
            signal_date=f"2026-06-{day:02d}",
            sector="通信设备",
            leader_symbol="600001",
            horizons={
                3: MainlineHorizonOutcome(horizon=3, status="completed", return_pct=0.01)
            },
            candidate_bindings=[],
        )
        for day in range(1, 21)
    ]

    summary = mainline.summarize_mainline_outcomes(outcomes)
    breakdowns = mainline.summarize_mainline_outcome_breakdowns(outcomes)

    assert summary[3]["eligible_for_policy"] is True
    assert breakdowns["sectors"][0]["eligible_for_policy"] is True
