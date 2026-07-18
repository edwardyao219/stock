from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.shared.database import Base
from services.shared.models import DailyBar, TradingCalendar


def _bar(symbol: str, trade_date: date, close: str, *, suspended: bool = False) -> DailyBar:
    value = Decimal(close)
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=value,
        high=value * Decimal("1.1"),
        low=value * Decimal("0.9"),
        close=value,
        pre_close=value,
        volume=Decimal("1000"),
        amount=Decimal("100000"),
        turnover_rate=Decimal("1"),
        limit_up=value * Decimal("1.1"),
        limit_down=value * Decimal("0.9"),
        is_suspended=suspended,
    )


def test_research_signal_ledger_preserves_first_evidence_and_evaluates_complete_horizons() -> None:
    from services.engine.research_signal_ledger import (
        evaluate_research_signal_ledger,
        record_research_signals,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)
    signal_time = datetime(2026, 7, 1, 10, 30)
    trade_dates = [signal_date + timedelta(days=index) for index in range(7)]

    with Session(engine) as db:
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in trade_dates])
        db.add_all(
            [
                _bar("600001", trade_dates[1], "11"),
                _bar("600001", trade_dates[2], "12"),
                _bar("600001", trade_dates[3], "13"),
                _bar("600001", trade_dates[4], "14"),
                _bar("600001", trade_dates[5], "15"),
                _bar("600002", trade_dates[1], "11"),
                _bar("600002", trade_dates[2], "12", suspended=True),
                _bar("600002", trade_dates[3], "13"),
            ]
        )
        record_research_signals(
            db,
            [
                {
                    "source": "intraday_market_turn",
                    "signal_type": "startup_starting",
                    "signal_time": signal_time,
                    "symbol": "600001",
                    "name": "测试一号",
                    "sector": "半导体",
                    "signal_price": 10.0,
                    "market_regime": "range",
                    "market_state": "normal_market",
                    "executable": False,
                    "evidence": {"startup_score": 88.0},
                },
                {
                    "source": "intraday_market_turn",
                    "signal_type": "startup_accelerating",
                    "signal_time": signal_time,
                    "symbol": "600002",
                    "signal_price": 10.0,
                    "market_regime": "panic",
                    "market_state": "systemic_risk",
                    "executable": False,
                    "evidence": {"startup_score": 92.0},
                },
            ],
        )
        # Duplicate delivery must not overwrite the original evidence captured at signal time.
        record_research_signals(
            db,
            [
                {
                    "source": "intraday_market_turn",
                    "signal_type": "startup_starting",
                    "signal_time": signal_time,
                    "symbol": "600001",
                    "signal_price": 10.0,
                    "evidence": {"startup_score": 1.0},
                }
            ],
        )
        db.commit()

        report = evaluate_research_signal_ledger(
            db,
            current_time=datetime(2026, 7, 8, 16, 0),
        )

    assert report["signal_count"] == 2
    assert report["horizons"][1]["completed_count"] == 2
    assert report["horizons"][3]["completed_count"] == 1
    assert report["horizons"][3]["unavailable_count"] == 1
    assert report["horizons"][3]["avg_return_pct"] == 0.3
    assert report["policy_status"] == "insufficient"
    first = next(item for item in report["signals"] if item["symbol"] == "600001")
    assert first["evidence"]["startup_score"] == 88.0
    assert first["horizons"][5]["return_pct"] == 0.5


def test_research_signal_ledger_does_not_use_unclosed_daily_bar() -> None:
    from services.engine.research_signal_ledger import (
        evaluate_research_signal_ledger,
        record_research_signals,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)
    with Session(engine) as db:
        db.add_all(
            [
                TradingCalendar(trade_date=signal_date, is_open=True),
                TradingCalendar(trade_date=date(2026, 7, 2), is_open=True),
            ]
        )
        db.add(_bar("600001", date(2026, 7, 2), "11"))
        record_research_signals(
            db,
            [
                {
                    "source": "intraday_market_turn",
                    "signal_type": "startup_starting",
                    "signal_time": datetime(2026, 7, 1, 10, 30),
                    "symbol": "600001",
                    "signal_price": 10.0,
                    "executable": False,
                }
            ],
        )
        db.commit()
        report = evaluate_research_signal_ledger(
            db,
            current_time=datetime(2026, 7, 2, 14, 50),
        )

    assert report["horizons"][1]["waiting_count"] == 1
    assert report["signals"][0]["horizons"][1]["reason"] == "awaiting_closed_daily_bar"


def test_intraday_market_turn_signal_builder_records_only_real_startups_and_mainlines() -> None:
    from services.engine.research_signal_ledger import build_intraday_market_turn_signals

    signal_time = datetime(2026, 7, 1, 10, 30)
    signals = build_intraday_market_turn_signals(
        snapshot={
            "key": "normal_market",
            "cross_day_mainline": {
                "checkpoint": "10:30复核",
                "status": "观察确认",
                "sectors": [
                    {
                        "sector": "半导体",
                        "status": "观察确认",
                        "current_leader_symbol": "600001",
                        "leader_price": 10.0,
                        "leader_change_pct": 0.05,
                    }
                ],
            },
        },
        candidates=[
            {
                "symbol": "600002",
                "name": "启动股",
                "sector": "半导体",
                "price": 10.5,
                "startup_stage": "starting",
                "startup_score": 85,
                "selection_tier": "watch",
            },
            {
                "symbol": "600003",
                "price": 11.0,
                "startup_stage": "watch",
            },
        ],
        signal_time=signal_time,
        market_regime="range",
    )

    assert {(item["signal_type"], item["symbol"]) for item in signals} == {
        ("startup_starting", "600002"),
        ("confirmed_mainline", "600001"),
    }
    startup = next(item for item in signals if item["symbol"] == "600002")
    assert startup["executable"] is False
    assert startup["evidence"]["startup_score"] == 85


def test_market_api_exposes_research_signal_ledger_report() -> None:
    from apps.api.app.routers.market import get_research_signal_ledger

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        report = get_research_signal_ledger(db)

    assert report.signal_count == 0
    assert report.policy_status == "insufficient"
    assert report.horizons[3].minimum_sample_count == 30
