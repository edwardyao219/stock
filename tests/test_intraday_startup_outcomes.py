from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine import intraday
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    IntradayMarketTurnSnapshot,
    MarketRegimeDaily,
    ResearchSignalLedger,
    TradingCalendar,
)


def _bar(symbol: str, trade_date: date, close: str) -> DailyBar:
    value = Decimal(close)
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=value,
        high=value + Decimal("0.5"),
        low=value - Decimal("0.5"),
        close=value,
        pre_close=value - Decimal("0.2"),
        volume=Decimal("100000"),
        amount=Decimal("1000000"),
        turnover_rate=None,
        limit_up=None,
        limit_down=None,
        is_suspended=False,
    )


def _snapshot(
    *,
    as_of: datetime,
    stage: str,
    startup_stage: str,
    startup_label: str,
    price: float,
) -> dict:
    return {
        "trade_date": as_of.date().isoformat(),
        "as_of": as_of.isoformat(),
        "stage": stage,
        "stage_label": stage,
        "candidates": [
            {
                "symbol": "600001",
                "name": "测试股份",
                "sector": "电力",
                "price": price,
                "startup_stage": startup_stage,
                "startup_label": startup_label,
                "startup_score": 92.0,
            }
        ],
    }


def _market_snapshot(
    snapshot_time: datetime,
    *,
    breadth_ratio: float,
    index_change_pct: float,
) -> IntradayMarketTurnSnapshot:
    return IntradayMarketTurnSnapshot(
        trade_date=snapshot_time.date(),
        snapshot_time=snapshot_time,
        coverage_ratio=0.99,
        breadth_ratio=breadth_ratio,
        total_amount=1000000,
        index_change_pct=index_change_pct,
        sector_expansion_count=1,
        state_json={"data_ready": True},
    )


def test_intraday_startup_outcomes_use_first_signal_and_trade_day_horizons() -> None:
    builder = getattr(intraday, "build_intraday_startup_outcomes", None)
    assert callable(builder)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)
    open_dates = [signal_date + timedelta(days=offset) for offset in range(8)]

    with Session(engine) as db:
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in open_dates])
        bars = [_bar("600001", item, str(10 + index)) for index, item in enumerate(open_dates)]
        bars[1].low = Decimal("9.5")
        db.add_all(bars)
        db.add(
            _market_snapshot(
                datetime(2026, 7, 1, 9, 45),
                breadth_ratio=0.2,
                index_change_pct=-0.018,
            )
        )
        db.commit()

        result = builder(
            db,
            [
                [
                    _snapshot(
                        as_of=datetime(2026, 7, 1, 9, 45),
                        stage="early_divergence",
                        startup_stage="starting",
                        startup_label="刚启动",
                        price=10.0,
                    ),
                    _snapshot(
                        as_of=datetime(2026, 7, 1, 11, 35),
                        stage="midday",
                        startup_stage="accelerating",
                        startup_label="加速中",
                        price=11.0,
                    ),
                ]
            ],
            current_time=datetime(2026, 7, 8, 16, 0),
        )

    assert result["signal_count"] == 1
    assert result["outcomes"][0]["startup_label"] == "刚启动"
    assert result["outcomes"][0]["signal_price"] == 10.0
    assert result["outcomes"][0]["market_context"] == "systemic_risk"
    assert result["outcomes"][0]["horizons"][1]["return_pct"] == 0.1
    assert result["outcomes"][0]["horizons"][3]["return_pct"] == 0.3
    assert result["outcomes"][0]["horizons"][5]["return_pct"] == 0.5
    assert result["outcomes"][0]["horizons"][5]["max_gain_pct"] == 0.55
    assert result["outcomes"][0]["horizons"][5]["max_drawdown_pct"] == -0.05
    assert result["summary"][5]["sample_count"] == 1
    assert result["summary"][5]["win_rate"] == 1.0
    assert result["completed_count"] == 1
    assert result["waiting_count"] == 0
    assert result["unavailable_count"] == 0


def test_intraday_startup_outcomes_keep_current_signal_waiting() -> None:
    builder = getattr(intraday, "build_intraday_startup_outcomes", None)
    assert callable(builder)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 17)

    with Session(engine) as db:
        db.add_all(
            [
                TradingCalendar(trade_date=signal_date, is_open=True),
                TradingCalendar(trade_date=date(2026, 7, 20), is_open=True),
                TradingCalendar(trade_date=date(2026, 7, 21), is_open=True),
            ]
        )
        db.add(
            _market_snapshot(
                datetime(2026, 7, 17, 10, 30),
                breadth_ratio=0.21,
                index_change_pct=-0.0136,
            )
        )
        db.add(_bar("600001", date(2026, 7, 20), "11"))
        db.commit()

        result = builder(
            db,
            [
                [
                    _snapshot(
                        as_of=datetime(2026, 7, 17, 10, 30),
                        stage="latest",
                        startup_stage="starting",
                        startup_label="刚启动",
                        price=10.0,
                    )
                ]
            ],
            current_time=datetime(2026, 7, 17, 13, 30),
        )

    outcome = result["outcomes"][0]
    assert outcome["market_context"] == "systemic_risk"
    assert outcome["horizons"][1]["status"] == "waiting"
    assert outcome["horizons"][3]["status"] == "waiting"
    assert outcome["horizons"][5]["status"] == "waiting"
    assert result["summary"][1]["sample_count"] == 0
    assert result["waiting_count"] == 1


def test_intraday_startup_outcomes_reject_incomplete_price_path() -> None:
    builder = getattr(intraday, "build_intraday_startup_outcomes", None)
    assert callable(builder)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)
    open_dates = [signal_date + timedelta(days=offset) for offset in range(6)]

    with Session(engine) as db:
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in open_dates])
        db.add_all(
            [
                _bar("600001", open_dates[0], "10"),
                _bar("600001", open_dates[1], "11"),
                _bar("600001", open_dates[3], "12"),
                _bar("600001", open_dates[4], "13"),
                _bar("600001", open_dates[5], "14"),
            ]
        )
        db.add(
            _market_snapshot(
                datetime(2026, 7, 1, 9, 45),
                breadth_ratio=0.6,
                index_change_pct=0.002,
            )
        )
        db.commit()

        result = builder(
            db,
            [
                [
                    _snapshot(
                        as_of=datetime(2026, 7, 1, 9, 45),
                        stage="early_divergence",
                        startup_stage="starting",
                        startup_label="刚启动",
                        price=10.0,
                    )
                ]
            ],
            current_time=datetime(2026, 7, 6, 16, 0),
        )

    outcome = result["outcomes"][0]
    assert outcome["horizons"][1]["status"] == "completed"
    assert outcome["horizons"][3]["status"] == "unavailable"
    assert outcome["horizons"][5]["status"] == "unavailable"
    assert result["summary"][1]["sample_count"] == 1
    assert result["summary"][3]["sample_count"] == 0
    assert result["unavailable_count"] == 1


def test_intraday_startup_outcomes_group_completed_returns_by_regime_transition() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    open_dates = [
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
        date(2026, 7, 13),
        date(2026, 7, 14),
        date(2026, 7, 15),
    ]
    signal_dates = [date(2026, 7, 1), date(2026, 7, 6), date(2026, 7, 8)]

    with Session(engine) as db:
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in open_dates])
        db.add_all(
            [
                _bar("600001", item, str(10 + index))
                for index, item in enumerate(open_dates)
            ]
        )
        db.add_all(
            [
                MarketRegimeDaily(trade_date=date(2026, 6, 30), regime="range", source="test"),
                MarketRegimeDaily(trade_date=date(2026, 7, 1), regime="rebound", source="test"),
                MarketRegimeDaily(trade_date=date(2026, 7, 3), regime="range", source="test"),
                MarketRegimeDaily(trade_date=date(2026, 7, 6), regime="rebound", source="test"),
                MarketRegimeDaily(trade_date=date(2026, 7, 7), regime="range", source="test"),
                MarketRegimeDaily(trade_date=date(2026, 7, 8), regime="rebound", source="test"),
            ]
        )
        db.commit()

        result = intraday.build_intraday_startup_outcomes(
            db,
            [
                [
                    _snapshot(
                        as_of=datetime.combine(signal_date, datetime.min.time()).replace(hour=10),
                        stage="latest",
                        startup_stage="starting",
                        startup_label="刚启动",
                        price=10.0,
                    )
                ]
                for signal_date in signal_dates
            ],
            current_time=datetime(2026, 7, 13, 16, 0),
        )

    transition = next(
        item["regime_transition"]
        for item in result["outcomes"]
        if item["signal_date"] == "2026-07-01"
    )
    assert transition == "range -> rebound"
    one_day_rows = result["regime_transition_summary"][1]
    assert one_day_rows == [
        {
            "regime_transition": "range -> rebound",
            "sample_count": 3,
            "win_rate": 1.0,
            "avg_return_pct": 0.466667,
            "is_sufficient_samples": True,
        }
    ]


def test_intraday_startup_outcomes_use_lifecycle_events_and_report_conversions() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 22)
    open_dates = [signal_date + timedelta(days=offset) for offset in range(6)]

    def event(symbol: str, state: str, signal_time: datetime, price: float):
        return ResearchSignalLedger(
            source="startup_state",
            signal_type=f"startup_{state}",
            signal_time=signal_time,
            signal_date=signal_date,
            symbol=symbol,
            signal_price=price,
            executable=False,
            evidence_json={"startup_label": f"启动{state}"},
        )

    with Session(engine) as db:
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in open_dates])
        db.add_all(
            [
                _bar(symbol, trade_date, str(base + index))
                for symbol, base in (("600001", 10), ("600002", 20))
                for index, trade_date in enumerate(open_dates)
            ]
        )
        db.add_all(
            [
                event("600001", "probing", datetime(2026, 7, 22, 9, 45), 10.0),
                event("600001", "confirmed", datetime(2026, 7, 22, 10, 30), 10.5),
                event("600001", "invalidated", datetime(2026, 7, 22, 14, 0), 10.2),
                event("600002", "probing", datetime(2026, 7, 22, 9, 45), 20.0),
            ]
        )
        db.commit()

        report = intraday.build_intraday_startup_outcomes(
            db,
            [
                [
                    _snapshot(
                        as_of=datetime(2026, 7, 22, 9, 45),
                        stage="early_divergence",
                        startup_stage="starting",
                        startup_label="刚启动",
                        price=9.8,
                    )
                ]
            ],
            current_time=datetime(2026, 7, 28, 16, 0),
        )

    assert report["signal_count"] == 4
    assert report["state_summary"]["confirmed"][1]["sample_count"] == 1
    assert report["state_summary"]["probing"][1]["sample_count"] == 2
    assert report["probing_to_confirmed_rate"] == 0.5
    assert report["confirmed_to_invalidated_rate"] == 1.0
    confirmed = next(
        item for item in report["outcomes"] if item["startup_stage"] == "confirmed"
    )
    assert confirmed["signal_price"] == 10.5
