from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.main import create_app
from services.collector.akshare_client import DailyBarRow
from services.collector.repository import upsert_daily_bars
from services.engine.review import market_stress_recovery
from services.engine.review.market_stress_recovery import replay_market_stress_recovery
from services.shared.database import Base
from services.shared.models import (
    CandidateDiscoverySnapshot,
    DailyBar,
    TradingCalendar,
    TushareDatasetSyncReceipt,
)


def test_market_stress_recovery_replay_route_is_registered() -> None:
    schema = create_app().openapi()

    assert "/rules/market-stress-recovery-replay" in schema["paths"]


def test_replay_market_stress_recovery_compares_threshold_tradeoffs() -> None:
    snapshots = [
        {"trade_date": "2026-01-02", "up_ratio": 0.20, "avg_change_pct": -0.020},
        {"trade_date": "2026-01-05", "up_ratio": 0.48, "avg_change_pct": 0.001},
        {"trade_date": "2026-01-06", "up_ratio": 0.56, "avg_change_pct": 0.006},
        {"trade_date": "2026-01-07", "up_ratio": 0.58, "avg_change_pct": 0.008},
        {"trade_date": "2026-01-08", "up_ratio": 0.44, "avg_change_pct": 0.000},
        {"trade_date": "2026-01-09", "up_ratio": 0.25, "avg_change_pct": -0.015},
        {"trade_date": "2026-01-12", "up_ratio": 0.55, "avg_change_pct": 0.005},
        {"trade_date": "2026-01-13", "up_ratio": 0.57, "avg_change_pct": 0.007},
        {"trade_date": "2026-01-14", "up_ratio": 0.60, "avg_change_pct": 0.010},
        {"trade_date": "2026-01-15", "up_ratio": 0.55, "avg_change_pct": 0.005},
        {"trade_date": "2026-01-16", "up_ratio": 0.56, "avg_change_pct": 0.006},
        {"trade_date": "2026-01-19", "up_ratio": 0.50, "avg_change_pct": 0.001},
        {"trade_date": "2026-01-20", "up_ratio": 0.51, "avg_change_pct": 0.002},
        {"trade_date": "2026-01-21", "up_ratio": 0.49, "avg_change_pct": 0.001},
    ]

    report = replay_market_stress_recovery(snapshots, min_risk_events=1)

    rows = {row["threshold_label"]: row for row in report["rows"]}
    assert report["snapshot_count"] == 14
    assert rows["1/3"]["risk_event_count"] == 2
    assert rows["1/3"]["completed_recovery_count"] == 2
    assert rows["1/3"]["false_rebound_count"] == 1
    assert rows["1/3"]["false_rebound_rate"] == 0.5
    assert rows["2/4"]["completed_recovery_count"] == 1
    assert rows["2/4"]["false_rebound_count"] == 0
    assert rows["2/5"]["completed_recovery_count"] == 1
    assert rows["1/3"]["avg_recovery_days"] < rows["2/4"]["avg_recovery_days"]
    assert rows["2/4"]["avg_recovery_days"] < rows["2/5"]["avg_recovery_days"]
    assert rows["1/3"]["limited_opportunity_days"] < rows["2/4"][
        "limited_opportunity_days"
    ]
    assert rows["2/4"]["limited_opportunity_days"] < rows["2/5"][
        "limited_opportunity_days"
    ]
    assert report["recommendation"]["status"] == "keep_current"
    assert report["recommendation"]["threshold_label"] == "2/4"


def test_replay_market_stress_recovery_counts_consecutive_selloffs_as_one_event() -> None:
    report = replay_market_stress_recovery(
        [
            {"trade_date": "2026-01-02", "up_ratio": 0.20, "avg_change_pct": -0.020},
            {"trade_date": "2026-01-05", "up_ratio": 0.25, "avg_change_pct": -0.012},
            {"trade_date": "2026-01-06", "up_ratio": 0.48, "avg_change_pct": 0.001},
            {"trade_date": "2026-01-07", "up_ratio": 0.52, "avg_change_pct": 0.004},
            {"trade_date": "2026-01-08", "up_ratio": 0.55, "avg_change_pct": 0.005},
            {"trade_date": "2026-01-09", "up_ratio": 0.58, "avg_change_pct": 0.008},
        ]
    )

    current = next(row for row in report["rows"] if row["is_current"])
    assert current["risk_event_count"] == 1
    assert current["completed_recovery_count"] == 1
    assert current["unresolved_event_count"] == 0
    assert current["avg_recovery_days"] == 4.0


def test_replay_market_stress_recovery_excludes_right_censored_release() -> None:
    report = replay_market_stress_recovery(
        [
            {"trade_date": "2026-01-02", "up_ratio": 0.20, "avg_change_pct": -0.020},
            {"trade_date": "2026-01-05", "up_ratio": 0.48, "avg_change_pct": 0.001},
            {"trade_date": "2026-01-06", "up_ratio": 0.52, "avg_change_pct": 0.004},
            {"trade_date": "2026-01-07", "up_ratio": 0.55, "avg_change_pct": 0.005},
            {"trade_date": "2026-01-08", "up_ratio": 0.58, "avg_change_pct": 0.008},
        ]
    )

    current = next(row for row in report["rows"] if row["is_current"])
    assert current["completed_recovery_count"] == 1
    assert current["evaluated_recovery_count"] == 0
    assert current["false_rebound_count"] == 0
    assert current["false_rebound_rate"] is None


def test_replay_market_stress_recovery_resets_confirmation_on_data_gap() -> None:
    report = replay_market_stress_recovery(
        [
            {"trade_date": "2026-01-02", "up_ratio": 0.20, "avg_change_pct": -0.020},
            {"trade_date": "2026-01-05", "up_ratio": 0.48, "avg_change_pct": 0.001},
            {"trade_date": "2026-01-06", "up_ratio": 0.52, "avg_change_pct": 0.004},
            {
                "trade_date": "2026-01-07",
                "up_ratio": 0.55,
                "avg_change_pct": 0.005,
                "is_usable": False,
            },
            {"trade_date": "2026-01-08", "up_ratio": 0.58, "avg_change_pct": 0.008},
            {"trade_date": "2026-01-09", "up_ratio": 0.56, "avg_change_pct": 0.006},
        ]
    )

    current = next(row for row in report["rows"] if row["is_current"])
    assert current["completed_recovery_count"] == 0
    assert current["unresolved_event_count"] == 1
    assert report["data_gap_count"] == 1


def test_replay_market_stress_recovery_breaks_current_threshold_down_by_year() -> None:
    report = replay_market_stress_recovery(
        [
            {"trade_date": "2025-12-15", "up_ratio": 0.20, "avg_change_pct": -0.020},
            {"trade_date": "2025-12-16", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2025-12-17", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2025-12-18", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2025-12-19", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2025-12-22", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2025-12-23", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2025-12-24", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {
                "trade_date": "2025-12-25",
                "up_ratio": 0.50,
                "avg_change_pct": 0.001,
                "is_usable": False,
            },
            {"trade_date": "2026-01-05", "up_ratio": 0.20, "avg_change_pct": -0.020},
            {"trade_date": "2026-01-06", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-07", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-08", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-09", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-12", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-13", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-14", "up_ratio": 0.60, "avg_change_pct": 0.010},
        ]
    )

    assert report["yearly_rows"] == [
        {
            "year": 2026,
            "snapshot_count": 8,
            "observed_trade_day_count": 8,
            "data_gap_count": 0,
            "risk_event_count": 1,
            "completed_recovery_count": 1,
            "evaluated_recovery_count": 1,
            "unresolved_event_count": 0,
            "false_rebound_count": 0,
            "false_rebound_rate": 0.0,
            "avg_recovery_days": 4.0,
            "blocked_opportunity_days": 1,
            "limited_opportunity_days": 2,
        },
        {
            "year": 2025,
            "snapshot_count": 8,
            "observed_trade_day_count": 9,
            "data_gap_count": 1,
            "risk_event_count": 1,
            "completed_recovery_count": 1,
            "evaluated_recovery_count": 1,
            "unresolved_event_count": 0,
            "false_rebound_count": 0,
            "false_rebound_rate": 0.0,
            "avg_recovery_days": 4.0,
            "blocked_opportunity_days": 1,
            "limited_opportunity_days": 2,
        },
    ]


def test_replay_market_stress_recovery_assigns_cross_year_recovery_to_risk_year() -> None:
    report = replay_market_stress_recovery(
        [
            {"trade_date": "2025-12-29", "up_ratio": 0.20, "avg_change_pct": -0.020},
            {"trade_date": "2025-12-30", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2025-12-31", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-05", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-06", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-07", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-08", "up_ratio": 0.60, "avg_change_pct": 0.010},
            {"trade_date": "2026-01-09", "up_ratio": 0.60, "avg_change_pct": 0.010},
        ]
    )

    yearly = {row["year"]: row for row in report["yearly_rows"]}
    assert yearly[2025]["risk_event_count"] == 1
    assert yearly[2025]["completed_recovery_count"] == 1
    assert yearly[2025]["evaluated_recovery_count"] == 1
    assert yearly[2025]["avg_recovery_days"] == 4.0
    assert yearly[2026]["risk_event_count"] == 0
    assert yearly[2026]["completed_recovery_count"] == 0


def test_replay_market_stress_recovery_splits_current_threshold_by_risk_start_regime() -> None:
    report = replay_market_stress_recovery(
        [
            {
                "trade_date": "2026-01-02",
                "up_ratio": 0.20,
                "avg_change_pct": -0.020,
                "market_regime": "panic",
            },
            {
                "trade_date": "2026-01-05",
                "up_ratio": 0.60,
                "avg_change_pct": 0.010,
                "market_regime": "range",
            },
            {
                "trade_date": "2026-01-06",
                "up_ratio": 0.60,
                "avg_change_pct": 0.010,
                "market_regime": "range",
            },
            {
                "trade_date": "2026-01-07",
                "up_ratio": 0.60,
                "avg_change_pct": 0.010,
                "market_regime": "range",
            },
            {
                "trade_date": "2026-01-08",
                "up_ratio": 0.60,
                "avg_change_pct": 0.010,
                "market_regime": "range",
            },
            {
                "trade_date": "2026-01-09",
                "up_ratio": 0.20,
                "avg_change_pct": -0.020,
                "market_regime": "panic",
            },
        ]
    )

    regimes = {row["regime"]: row for row in report["regime_rows"]}
    assert report["market_regime_coverage_count"] == 6
    assert report["market_regime_gap_count"] == 0
    assert regimes["panic"] == {
        "regime": "panic",
        "snapshot_count": 2,
        "risk_event_count": 2,
        "completed_recovery_count": 1,
        "evaluated_recovery_count": 0,
        "unresolved_event_count": 1,
        "false_rebound_count": 0,
        "false_rebound_rate": None,
        "avg_recovery_days": 4.0,
    }
    assert regimes["range"]["snapshot_count"] == 4


def test_load_market_stress_recovery_regimes_rejects_conflicting_day_snapshots() -> None:
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
                    discovery_json={"market_regime": "panic"},
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=date(2026, 1, 2),
                    next_trade_date=date(2026, 1, 5),
                    candidate_limit=20,
                    include_fundamentals=False,
                    discovery_json={"market_regime": "panic"},
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=date(2026, 1, 5),
                    next_trade_date=date(2026, 1, 6),
                    candidate_limit=15,
                    include_fundamentals=False,
                    discovery_json={"market_regime": "range"},
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=date(2026, 1, 5),
                    next_trade_date=date(2026, 1, 6),
                    candidate_limit=20,
                    include_fundamentals=False,
                    discovery_json={"market_regime": "rebound"},
                ),
            ]
        )
        db.commit()

        regimes = market_stress_recovery.load_market_stress_recovery_regimes(
            db,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )

    assert regimes == {"2026-01-02": "panic"}


def test_load_market_stress_recovery_snapshots_marks_low_coverage_days() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        for trade_date, prices in (
            (date(2026, 1, 2), (Decimal("9"), Decimal("9"))),
            (date(2026, 1, 5), (Decimal("10.5"), Decimal("11"))),
            (date(2026, 1, 6), (Decimal("10.2"),)),
        ):
            for index, close in enumerate(prices, start=1):
                db.add(
                    DailyBar(
                        symbol=f"60000{index}",
                        trade_date=trade_date,
                        open=Decimal("10"),
                        high=max(Decimal("10"), close),
                        low=min(Decimal("10"), close),
                        close=close,
                        pre_close=Decimal("10"),
                        volume=Decimal("100"),
                        amount=Decimal("1000"),
                        turnover_rate=None,
                        limit_up=Decimal("11"),
                        limit_down=Decimal("9"),
                        is_suspended=False,
                    )
                )
        db.commit()

        assert hasattr(market_stress_recovery, "load_market_stress_recovery_snapshots")
        snapshots = market_stress_recovery.load_market_stress_recovery_snapshots(
            db,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )

    assert snapshots == [
        {
            "trade_date": "2026-01-02",
            "stock_count": 2,
            "coverage_ratio": 1.0,
            "up_ratio": 0.0,
            "avg_change_pct": -0.1,
            "is_usable": True,
        },
        {
            "trade_date": "2026-01-05",
            "stock_count": 2,
            "coverage_ratio": 1.0,
            "up_ratio": 1.0,
            "avg_change_pct": 0.075,
            "is_usable": True,
        },
        {
            "trade_date": "2026-01-06",
            "stock_count": 1,
            "coverage_ratio": 0.5,
            "up_ratio": 1.0,
            "avg_change_pct": 0.02,
            "is_usable": False,
        },
    ]


def test_market_stress_recovery_uses_calendar_to_preserve_zero_row_gap() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    trade_dates = [
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
    ]

    with Session(engine) as db:
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in trade_dates])
        for trade_date in [item for item in trade_dates if item != date(2026, 1, 6)]:
            close = Decimal("8") if trade_date == date(2026, 1, 2) else Decimal("10.1")
            db.add(
                DailyBar(
                    symbol="600001",
                    trade_date=trade_date,
                    open=Decimal("10"),
                    high=max(Decimal("10"), close),
                    low=min(Decimal("10"), close),
                    close=close,
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                )
            )
        db.commit()

        snapshots = market_stress_recovery.load_market_stress_recovery_snapshots(
            db,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )

    gap = next(item for item in snapshots if item["trade_date"] == "2026-01-06")
    assert gap["stock_count"] == 0
    assert gap["is_usable"] is False
    report = replay_market_stress_recovery(snapshots)
    current = next(row for row in report["rows"] if row["is_current"])
    assert report["data_gap_count"] == 1
    assert current["completed_recovery_count"] == 0


def test_upsert_daily_bars_records_replay_cache_revision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        upsert_daily_bars(
            db,
            [
                DailyBarRow(
                    symbol="600001",
                    trade_date="2026-01-30",
                    open=Decimal("10"),
                    high=Decimal("10"),
                    low=Decimal("9"),
                    close=Decimal("9"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                )
            ],
        )
        db.commit()
        receipt = db.query(TushareDatasetSyncReceipt).one()

    assert receipt.dataset == "daily_bars"
    assert receipt.trade_date == date(2026, 1, 30)
    assert receipt.row_count == 1
    assert receipt.completed_at is not None


def test_market_stress_recovery_report_cache_tracks_data_revisions(
    monkeypatch,
    tmp_path,
) -> None:
    assert hasattr(market_stress_recovery, "load_or_build_market_stress_recovery_report")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    calls = []

    def fake_build(db, **kwargs):
        calls.append(kwargs)
        return {
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "snapshot_count": 0,
            "rows": [],
            "recommendation": {},
        }

    monkeypatch.setattr(market_stress_recovery, "MARKET_STRESS_RECOVERY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(market_stress_recovery, "build_market_stress_recovery_report", fake_build)

    with Session(engine) as db:
        db.add(
            DailyBar(
                symbol="600001",
                trade_date=date(2026, 1, 30),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("9"),
                close=Decimal("9"),
                pre_close=Decimal("10"),
                volume=Decimal("100"),
                amount=Decimal("1000"),
                turnover_rate=None,
                limit_up=Decimal("11"),
                limit_down=Decimal("9"),
                is_suspended=False,
            )
        )
        db.add(
            TushareDatasetSyncReceipt(
                dataset="daily_bars",
                trade_date=date(2026, 1, 30),
                row_count=1,
                completed_at=datetime(2026, 1, 30, 16, 0),
            )
        )
        db.commit()
        first = market_stress_recovery.load_or_build_market_stress_recovery_report(
            db,
            start_date="2024-01-01",
            end_date="2026-01-31",
        )
        second = market_stress_recovery.load_or_build_market_stress_recovery_report(
            db,
            start_date="2024-01-01",
            end_date="2026-01-31",
        )
        bar = db.query(DailyBar).one()
        bar.close = Decimal("8")
        receipt = db.query(TushareDatasetSyncReceipt).one()
        receipt.completed_at = datetime(2026, 1, 30, 17, 0)
        db.commit()
        updated = market_stress_recovery.load_or_build_market_stress_recovery_report(
            db,
            start_date="2024-01-01",
            end_date="2026-01-31",
        )
        db.add(TradingCalendar(trade_date=date(2026, 1, 29), is_open=True))
        db.commit()
        calendar_updated = market_stress_recovery.load_or_build_market_stress_recovery_report(
            db,
            start_date="2024-01-01",
            end_date="2026-01-31",
        )
        refreshed = market_stress_recovery.load_or_build_market_stress_recovery_report(
            db,
            start_date="2024-01-01",
            end_date="2026-01-31",
            force_refresh=True,
        )

    assert len(calls) == 4
    assert first["cache"]["hit"] is False
    assert second["cache"]["hit"] is True
    assert updated["cache"]["hit"] is False
    assert calendar_updated["cache"]["hit"] is False
    assert refreshed["cache"]["hit"] is False
