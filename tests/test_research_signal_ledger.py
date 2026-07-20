from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.shared.database import Base
from services.shared.models import (
    CandidateDiscoverySnapshot,
    DailyBar,
    PaperOrder,
    PaperPosition,
    TradePlan,
    TradingCalendar,
)


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
    assert report.execution_funnel.planned_count == 0
    assert report.execution_funnel.closed_count == 0


def test_market_api_exposes_historical_replay_separately() -> None:
    from apps.api.app.routers.market import (
        HistoricalReplaySignalResponse,
        get_historical_signal_replay,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        report = get_historical_signal_replay(db)

    assert report.source_type == "historical_replay"
    assert report.policy_eligible is False
    assert report.signal_count == 0
    assert report.available_snapshot_count == 0
    assert report.horizons[3].minimum_sample_count == 30
    assert report.stability.split_method == "chronological_70_30"
    assert report.stability.train.sample_count == 0
    assert report.stability.validation.sample_count == 0
    assert report.stability.combinations == []
    assert report.stability.validation_attribution.sample_count == 0
    assert report.stability.validation_attribution.market_state_coverage_ratio == 0.0
    assert report.stability.validation_attribution.selection_modes == []
    assert report.stability.validation_attribution.market_participation_known_count == 0
    assert report.stability.validation_attribution.stock_moneyflow_known_count == 0
    assert report.stability.validation_attribution.market_participation_bands == []
    assert report.stability.validation_attribution.stock_moneyflow_bands == []
    assert {
        "market_participation_score",
        "market_liquidity_score",
        "moneyflow_support_score",
        "sector_fund_flow_score",
    } <= HistoricalReplaySignalResponse.model_fields.keys()


def test_market_api_reuses_historical_replay_cache_by_database_limit_and_date(
    monkeypatch,
) -> None:
    from apps.api.app.routers import market

    calls = {"count": 0}
    current_time = {"value": datetime(2026, 7, 20, 16)}
    evaluate = market.evaluate_historical_signal_replay

    def counted_evaluate(db, *, current_time, snapshot_limit):
        calls["count"] += 1
        return evaluate(
            db,
            current_time=current_time,
            snapshot_limit=snapshot_limit,
        )

    monkeypatch.setattr(market, "_HISTORICAL_REPLAY_CACHE", None, raising=False)
    monkeypatch.setattr(market, "evaluate_historical_signal_replay", counted_evaluate)
    monkeypatch.setattr(market, "now_local", lambda: current_time["value"])
    monkeypatch.setattr(market, "monotonic", lambda: 1000.0)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = market.get_historical_signal_replay(db, snapshot_limit=120)
        second = market.get_historical_signal_replay(db, snapshot_limit=120)
        market.get_historical_signal_replay(db, snapshot_limit=60)
        current_time["value"] = datetime(2026, 7, 21, 9, 30)
        market.get_historical_signal_replay(db, snapshot_limit=60)

    assert first is second
    assert calls["count"] == 3


def test_daily_candidate_signal_builder_requires_current_feature_date_and_close_price() -> None:
    from services.engine.research_signal_ledger import build_daily_candidate_signals

    signal_time = datetime(2026, 7, 1, 15, 5)
    discovery = {
        "feature_date": "2026-07-01",
        "requested_feature_date": "2026-07-01",
        "market_regime": "range",
        "market_turn": {"key": "range"},
    }
    signals = build_daily_candidate_signals(
        discovery=discovery,
        candidates=[
            {
                "symbol": "600001",
                "name": "收盘候选",
                "sector": "通信设备",
                "selection_mode": "formal_strategy",
                "score": 81.0,
                "selected_rule_id": "R002",
                "reasons": ["板块扩散"],
                "risk_flags": [],
            },
            {"symbol": "600002", "selection_mode": "observation", "score": 70.0},
        ],
        signal_time=signal_time,
        prices_by_symbol={"600001": 10.2},
    )

    assert len(signals) == 1
    assert signals[0]["signal_type"] == "daily_formal_strategy"
    assert signals[0]["signal_price"] == 10.2
    assert signals[0]["evidence"]["candidate_score"] == 81.0
    assert build_daily_candidate_signals(
        discovery={**discovery, "feature_date": "2026-06-30"},
        candidates=[{"symbol": "600001", "selection_mode": "formal_strategy", "score": 81.0}],
        signal_time=signal_time,
        prices_by_symbol={"600001": 10.2},
    ) == []


def test_research_signal_ledger_links_daily_signals_to_paper_execution() -> None:
    from services.engine.research_signal_ledger import (
        evaluate_research_signal_ledger,
        record_research_signals,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_time = datetime(2026, 7, 1, 15, 5)
    with Session(engine) as db:
        record_research_signals(
            db,
            [
                {
                    "source": "daily_candidate_discovery",
                    "signal_type": "daily_formal_strategy",
                    "signal_time": signal_time,
                    "symbol": "600001",
                    "signal_price": 10.0,
                    "market_regime": "range",
                    "evidence": {"selected_rule_id": "R001"},
                },
                {
                    "source": "daily_candidate_discovery",
                    "signal_type": "daily_observation",
                    "signal_time": signal_time,
                    "symbol": "600002",
                    "signal_price": 10.0,
                    "market_regime": "range",
                },
                {
                    "source": "daily_candidate_discovery",
                    "signal_type": "daily_formal_strategy",
                    "signal_time": signal_time,
                    "symbol": "600003",
                    "signal_price": 10.0,
                    "market_regime": "range",
                    "evidence": {"selected_rule_id": "R001"},
                },
            ],
        )
        db.add_all(
            [
                TradePlan(
                    id=1,
                    plan_date=date(2026, 7, 1),
                    trade_date=date(2026, 7, 2),
                    symbol="600001",
                    rule_id="R001",
                    strategy_type="swing",
                    entry_condition_json={},
                    position_size=Decimal("0.1"),
                    status="executed",
                ),
                TradePlan(
                    id=2,
                    plan_date=date(2026, 7, 1),
                    trade_date=date(2026, 7, 2),
                    symbol="600003",
                    rule_id="R001",
                    strategy_type="swing",
                    entry_condition_json={},
                    position_size=Decimal("0.1"),
                    status="planned",
                ),
                PaperPosition(
                    id=1,
                    account_id=1,
                    trade_plan_id=1,
                    symbol="600001",
                    rule_id="R001",
                    strategy_type="swing",
                    entry_date=date(2026, 7, 2),
                    entry_price=Decimal("10.2"),
                    quantity=100,
                    highest_price=Decimal("11.5"),
                    lowest_price=Decimal("9.8"),
                    status="closed",
                    exit_date=date(2026, 7, 6),
                    exit_price=Decimal("11.22"),
                    exit_reason="time_exit",
                    pnl=Decimal("102"),
                    pnl_pct=Decimal("0.1"),
                ),
                PaperOrder(
                    account_id=1,
                    trade_plan_id=2,
                    symbol="600003",
                    side="buy",
                    order_date=date(2026, 7, 2),
                    quantity=0,
                    status="skipped",
                    reason="高开超过计划上限",
                ),
            ]
        )
        db.commit()

        report = evaluate_research_signal_ledger(
            db,
            current_time=datetime(2026, 7, 10, 16, 0),
        )

    assert report["execution_funnel"] == {
        "research_only_count": 1,
        "planned_count": 2,
        "waiting_entry_count": 0,
        "not_entered_count": 1,
        "open_count": 0,
        "closed_count": 1,
        "avg_entry_slippage_pct": 0.02,
        "closed_avg_pnl_pct": 0.1,
        "closed_win_rate": 1.0,
    }
    by_symbol = {item["symbol"]: item for item in report["signals"]}
    assert by_symbol["600001"]["execution"]["status"] == "closed"
    assert by_symbol["600001"]["execution"]["entry_slippage_pct"] == 0.02
    assert by_symbol["600002"]["execution"]["status"] == "research_only"
    assert by_symbol["600003"]["execution"]["status"] == "not_entered"
    assert by_symbol["600003"]["execution"]["order_reason"] == "高开超过计划上限"


def test_research_signal_ledger_compares_executed_missed_and_research_only_outcomes() -> None:
    from services.engine.research_signal_ledger import (
        evaluate_research_signal_ledger,
        record_research_signals,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)
    signal_time = datetime(2026, 7, 1, 15, 5)
    target_dates = [date(2026, 7, day) for day in (2, 3, 4)]
    with Session(engine) as db:
        db.add(TradingCalendar(trade_date=signal_date, is_open=True))
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in target_dates])
        for symbol, closes in {
            "600001": ("11", "12", "13"),
            "600002": ("9", "9", "9"),
            "600003": ("10.2", "10.3", "10.5"),
        }.items():
            db.add_all(
                [
                    _bar(symbol, trade_date, close)
                    for trade_date, close in zip(target_dates, closes, strict=True)
                ]
            )
        record_research_signals(
            db,
            [
                {
                    "source": "daily_candidate_discovery",
                    "signal_type": "daily_formal_strategy",
                    "signal_time": signal_time,
                    "symbol": "600001",
                    "signal_price": 10.0,
                    "market_regime": "range",
                    "evidence": {"selected_rule_id": "R001"},
                },
                {
                    "source": "daily_candidate_discovery",
                    "signal_type": "daily_observation",
                    "signal_time": signal_time,
                    "symbol": "600002",
                    "signal_price": 10.0,
                    "market_regime": "range",
                },
                {
                    "source": "daily_candidate_discovery",
                    "signal_type": "daily_formal_strategy",
                    "signal_time": signal_time,
                    "symbol": "600003",
                    "signal_price": 10.0,
                    "market_regime": "range",
                    "evidence": {"selected_rule_id": "R001"},
                },
            ],
        )
        db.add_all(
            [
                TradePlan(
                    id=1,
                    plan_date=signal_date,
                    trade_date=target_dates[0],
                    symbol="600001",
                    rule_id="R001",
                    strategy_type="swing",
                    entry_condition_json={},
                    position_size=Decimal("0.1"),
                    status="executed",
                ),
                TradePlan(
                    id=2,
                    plan_date=signal_date,
                    trade_date=target_dates[0],
                    symbol="600003",
                    rule_id="R001",
                    strategy_type="swing",
                    entry_condition_json={},
                    position_size=Decimal("0.1"),
                    status="planned",
                ),
                PaperPosition(
                    account_id=1,
                    trade_plan_id=1,
                    symbol="600001",
                    rule_id="R001",
                    strategy_type="swing",
                    entry_date=target_dates[0],
                    entry_price=Decimal("11"),
                    quantity=100,
                    highest_price=Decimal("13"),
                    lowest_price=Decimal("10.5"),
                    status="open",
                ),
            ]
        )
        db.commit()

        report = evaluate_research_signal_ledger(
            db,
            current_time=datetime(2026, 7, 10, 16, 0),
        )

    comparison = report["execution_outcomes"]
    assert comparison["executed"][3]["avg_return_pct"] == 0.3
    assert comparison["not_entered"][3]["avg_return_pct"] == 0.05
    assert comparison["research_only"][3]["avg_return_pct"] == -0.1
    assert comparison["executed"][3]["sample_count"] == 1
    assert comparison["executed"][3]["eligible_for_policy"] is False
    cohorts = report["execution_cohorts"]
    assert len(cohorts) == 2
    formal = next(item for item in cohorts if item["signal_type"] == "daily_formal_strategy")
    assert formal["market_regime"] == "range"
    assert formal["groups"]["executed"]["avg_return_pct"] == 0.3
    assert formal["groups"]["not_entered"]["avg_return_pct"] == 0.05
    assert formal["comparable"] is False


def test_historical_signal_replay_uses_only_exact_canonical_snapshots() -> None:
    from services.engine.research_signal_ledger import (
        evaluate_historical_signal_replay,
        evaluate_research_signal_ledger,
        record_research_signals,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)
    trade_dates = [signal_date + timedelta(days=index) for index in range(4)]
    with Session(engine) as db:
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in trade_dates])
        db.add_all(
            [
                _bar("600001", trade_dates[0], "10"),
                _bar("600001", trade_dates[1], "11"),
                _bar("600001", trade_dates[2], "12"),
                _bar("600001", trade_dates[3], "13"),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=trade_dates[0],
                    next_trade_date=trade_dates[1],
                    candidate_limit=15,
                    include_fundamentals=False,
                    discovery_json={
                        "feature_date": trade_dates[0].isoformat(),
                        "requested_feature_date": trade_dates[0].isoformat(),
                        "market_regime": "range",
                        "market_turn": {"key": "watch_repair"},
                        "market_participation_snapshot": {
                            "participation_score": 42,
                            "liquidity_score": 47,
                        },
                        "candidates": [
                            {
                                "symbol": "600001",
                                "name": "回放样本",
                                "sector": "半导体",
                                "selection_mode": "formal_strategy",
                                "score": 88,
                                "moneyflow_support_score": 62,
                                "sector_fund_flow_score": 58,
                            }
                        ],
                    },
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=trade_dates[1],
                    next_trade_date=trade_dates[2],
                    candidate_limit=15,
                    include_fundamentals=False,
                    discovery_json={
                        "feature_date": trade_dates[0].isoformat(),
                        "candidates": [{"symbol": "600099", "selection_mode": "observation"}],
                    },
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=trade_dates[2],
                    next_trade_date=trade_dates[3],
                    candidate_limit=15,
                    include_fundamentals=False,
                    discovery_json={
                        "feature_date": trade_dates[2].isoformat(),
                        "requested_feature_date": "invalid-date",
                        "candidates": [{"symbol": "600098", "selection_mode": "observation"}],
                    },
                ),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=trade_dates[0],
                    next_trade_date=trade_dates[2],
                    candidate_limit=15,
                    include_fundamentals=False,
                    discovery_json={
                        "feature_date": trade_dates[0].isoformat(),
                        "candidates": [{"symbol": "600097", "selection_mode": "observation"}],
                    },
                ),
            ]
        )
        record_research_signals(
            db,
            [
                {
                    "source": "daily_candidate_discovery",
                    "signal_type": "daily_formal_strategy",
                    "signal_time": datetime(2026, 7, 1, 15, 5),
                    "symbol": "600888",
                    "signal_price": 10,
                }
            ],
        )
        db.commit()

        replay = evaluate_historical_signal_replay(
            db,
            current_time=datetime(2026, 7, 10, 16),
        )
        real = evaluate_research_signal_ledger(
            db,
            current_time=datetime(2026, 7, 10, 16),
        )

    assert replay["source_type"] == "historical_replay"
    assert replay["source_snapshot_count"] == 4
    assert replay["evaluated_snapshot_count"] == 1
    assert replay["excluded_snapshot_count"] == 3
    assert replay["exclusion_reasons"] == {
        "feature_date_mismatch": 1,
        "invalid_next_trade_date": 1,
        "requested_feature_date_mismatch": 1,
    }
    assert replay["signal_count"] == 1
    assert replay["covered_month_count"] == 1
    assert replay["horizons"][3]["avg_return_pct"] == 0.3
    assert replay["selection_modes"][0]["key"] == "formal_strategy"
    assert replay["recent_signals"][0]["signal_price"] == 10.0
    assert replay["recent_signals"][0]["source_type"] == "historical_replay"
    assert replay["recent_signals"][0]["market_participation_score"] == 42.0
    assert replay["recent_signals"][0]["market_liquidity_score"] == 47.0
    assert replay["recent_signals"][0]["moneyflow_support_score"] == 62.0
    assert replay["recent_signals"][0]["sector_fund_flow_score"] == 58.0
    assert real["signal_count"] == 1


def test_historical_signal_replay_classifies_unclosed_suspended_and_missing_prices() -> None:
    from services.engine.research_signal_ledger import evaluate_historical_signal_replay

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)
    next_date = date(2026, 7, 2)
    with Session(engine) as db:
        db.add_all(
            [
                TradingCalendar(trade_date=signal_date, is_open=True),
                TradingCalendar(trade_date=next_date, is_open=True),
                _bar("600001", signal_date, "10"),
                _bar("600001", next_date, "11", suspended=True),
                CandidateDiscoverySnapshot(
                    cache_version="candidate-v5-startup-signal",
                    signal_date=signal_date,
                    next_trade_date=next_date,
                    candidate_limit=15,
                    include_fundamentals=False,
                    discovery_json={
                        "feature_date": signal_date.isoformat(),
                        "candidates": [
                            {"symbol": "600001", "selection_mode": "formal_strategy"},
                            {"symbol": "600002", "selection_mode": "observation"},
                        ],
                    },
                ),
            ]
        )
        db.commit()

        intraday = evaluate_historical_signal_replay(
            db,
            current_time=datetime(2026, 7, 2, 14, 50),
        )
        closed = evaluate_historical_signal_replay(
            db,
            current_time=datetime(2026, 7, 2, 16),
        )

    assert intraday["candidate_exclusion_reasons"] == {"missing_signal_close": 1}
    assert intraday["horizons"][1]["waiting_count"] == 1
    assert intraday["recent_signals"][0]["horizons"][1]["reason"] == "awaiting_closed_daily_bar"
    assert closed["horizons"][1]["unavailable_count"] == 1
    assert closed["recent_signals"][0]["horizons"][1]["reason"] == "suspended"


def test_historical_signal_replay_rejects_an_isolated_non_next_trade_date() -> None:
    from services.engine.research_signal_ledger import evaluate_historical_signal_replay

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    trade_dates = [date(2026, 7, day) for day in (1, 2, 3)]
    with Session(engine) as db:
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in trade_dates])
        db.add(
            CandidateDiscoverySnapshot(
                cache_version="candidate-v5-startup-signal",
                signal_date=trade_dates[0],
                next_trade_date=trade_dates[2],
                candidate_limit=15,
                include_fundamentals=False,
                discovery_json={
                    "feature_date": trade_dates[0].isoformat(),
                    "candidates": [{"symbol": "600001", "selection_mode": "observation"}],
                },
            )
        )
        db.commit()

        replay = evaluate_historical_signal_replay(
            db,
            current_time=datetime(2026, 7, 10, 16),
        )

    assert replay["evaluated_snapshot_count"] == 0
    assert replay["exclusion_reasons"] == {"invalid_next_trade_date": 1}


def test_historical_signal_replay_never_marks_mature_samples_policy_eligible() -> None:
    from services.engine.research_signal_ledger import evaluate_historical_signal_replay

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 1)
    trade_dates = [signal_date + timedelta(days=index) for index in range(4)]
    symbols = [f"60{index:04d}" for index in range(30)]
    with Session(engine) as db:
        db.add_all([TradingCalendar(trade_date=item, is_open=True) for item in trade_dates])
        db.add_all(
            [
                _bar(symbol, trade_date, str(10 + date_index))
                for symbol in symbols
                for date_index, trade_date in enumerate(trade_dates)
            ]
        )
        db.add(
            CandidateDiscoverySnapshot(
                cache_version="candidate-v5-startup-signal",
                signal_date=trade_dates[0],
                next_trade_date=trade_dates[1],
                candidate_limit=15,
                include_fundamentals=False,
                discovery_json={
                    "feature_date": trade_dates[0].isoformat(),
                    "candidates": [
                        {"symbol": symbol, "selection_mode": "formal_strategy"}
                        for symbol in symbols
                    ],
                },
            )
        )
        db.commit()

        replay = evaluate_historical_signal_replay(
            db,
            current_time=datetime(2026, 7, 10, 16),
        )

    assert replay["research_sample_sufficient"] is True
    assert replay["policy_eligible"] is False
    assert replay["horizons"][3]["eligible_for_policy"] is False
    assert replay["selection_modes"][0]["eligible_for_policy"] is False


def _replay_stability_signal(
    signal_date: date,
    *,
    selection_mode: str,
    sector: str,
    return_pct: float,
    market_regime: str = "range",
    market_state: str = "watch_repair",
    score: float = 80.0,
    rank: int = 1,
    market_participation_score: float | None = None,
    market_liquidity_score: float | None = None,
    moneyflow_support_score: float | None = None,
    sector_fund_flow_score: float | None = None,
) -> dict[str, object]:
    return {
        "signal_date": signal_date.isoformat(),
        "selection_mode": selection_mode,
        "market_regime": market_regime,
        "market_state": market_state,
        "sector": sector,
        "score": score,
        "rank": rank,
        "market_participation_score": market_participation_score,
        "market_liquidity_score": market_liquidity_score,
        "moneyflow_support_score": moneyflow_support_score,
        "sector_fund_flow_score": sector_fund_flow_score,
        "horizons": {
            3: {
                "status": "completed",
                "return_pct": return_pct,
            }
        },
    }


def test_historical_replay_stability_requires_positive_train_and_recent_segments() -> None:
    from services.engine.research_signal_ledger import summarize_historical_replay_stability

    signals = []
    start = date(2026, 1, 1)
    for day_index in range(40):
        signal_date = start + timedelta(days=day_index)
        is_recent = day_index >= 28
        for _ in range(3):
            signals.append(
                _replay_stability_signal(
                    signal_date,
                    selection_mode="formal_strategy",
                    sector="半导体",
                    return_pct=0.01 if is_recent else 0.02,
                )
            )
            signals.append(
                _replay_stability_signal(
                    signal_date,
                    selection_mode="observation",
                    sector="中成药",
                    return_pct=-0.01 if is_recent else 0.02,
                )
            )
            signals.append(
                _replay_stability_signal(
                    signal_date,
                    selection_mode="potential_watch",
                    sector="银行",
                    return_pct=0.0 if is_recent else 0.01,
                )
            )

    report = summarize_historical_replay_stability(signals)

    assert report["split_method"] == "chronological_70_30"
    assert report["train_end_date"] == "2026-01-28"
    assert report["validation_start_date"] == "2026-01-29"
    stable = next(
        item for item in report["combinations"] if item["key"] == "formal_strategy|range"
    )
    unstable = next(
        item for item in report["combinations"] if item["key"] == "observation|range"
    )
    assert stable["train"]["signal_day_count"] == 28
    assert stable["validation"]["signal_day_count"] == 12
    assert stable["comparable"] is True
    assert stable["stable_positive"] is True
    assert stable["validation_delta_pct"] == -0.01
    assert unstable["comparable"] is True
    assert unstable["stable_positive"] is False
    assert [item["key"] for item in report["combinations"][:3]] == [
        "formal_strategy|range",
        "potential_watch|range",
        "observation|range",
    ]
    assert len(report["monthly"]) == 2


def test_historical_replay_stability_rejects_many_stocks_from_too_few_days() -> None:
    from services.engine.research_signal_ledger import summarize_historical_replay_stability

    signals = [
        _replay_stability_signal(
            date(2026, 1, 2) if index < 30 else date(2026, 7, 1),
            selection_mode="formal_strategy",
            sector="半导体",
            return_pct=0.02,
        )
        for index in range(60)
    ]

    report = summarize_historical_replay_stability(signals)
    cohort = report["combinations"][0]

    assert cohort["train"]["sample_count"] == 30
    assert cohort["validation"]["sample_count"] == 30
    assert cohort["train"]["signal_day_count"] == 1
    assert cohort["validation"]["signal_day_count"] == 1
    assert cohort["comparable"] is False
    assert cohort["stable_positive"] is False


def test_historical_replay_stability_attributes_recent_return_drag() -> None:
    from services.engine.research_signal_ledger import summarize_historical_replay_stability

    signals = []
    start = date(2026, 1, 1)
    for day_index in range(40):
        signal_date = start + timedelta(days=day_index)
        recent_return = -0.02 if day_index >= 28 else 0.01
        signals.extend(
            [
                _replay_stability_signal(
                    signal_date,
                    selection_mode="formal_strategy",
                    sector="半导体",
                    return_pct=recent_return,
                    score=85,
                    rank=2,
                    market_participation_score=35,
                    market_liquidity_score=40,
                    moneyflow_support_score=38,
                    sector_fund_flow_score=42,
                ),
                _replay_stability_signal(
                    signal_date,
                    selection_mode="formal_strategy",
                    sector="半导体",
                    return_pct=-0.01 if day_index >= 28 else 0.01,
                    market_state="unknown",
                    score=75,
                    rank=5,
                    market_participation_score=50,
                    market_liquidity_score=52,
                ),
                _replay_stability_signal(
                    signal_date,
                    selection_mode="observation",
                    sector="中成药",
                    return_pct=0.01,
                    market_regime="panic",
                    market_state="unknown",
                    score=55,
                    rank=10,
                    market_participation_score=70,
                    market_liquidity_score=72,
                ),
            ]
        )

    attribution = summarize_historical_replay_stability(signals)[
        "validation_attribution"
    ]

    assert attribution["sample_count"] == 36
    assert attribution["signal_day_count"] == 12
    assert attribution["market_state_known_count"] == 12
    assert attribution["market_state_coverage_ratio"] == 0.333333
    formal = attribution["selection_modes"][0]
    assert formal["key"] == "formal_strategy"
    assert formal["sample_count"] == 24
    assert formal["sample_share"] == 0.666667
    assert formal["avg_return_pct"] == -0.015
    assert formal["return_contribution_pct"] == -0.01
    assert attribution["rank_bands"][0]["key"] == "1-3"
    assert attribution["score_bands"][0]["key"] == "80+"
    assert attribution["sectors"][0]["key"] == "半导体"
    assert attribution["market_participation_known_count"] == 36
    assert attribution["market_participation_coverage_ratio"] == 1.0
    assert attribution["stock_moneyflow_known_count"] == 12
    assert attribution["stock_moneyflow_coverage_ratio"] == 0.333333
    assert attribution["sector_moneyflow_known_count"] == 12
    assert attribution["sector_moneyflow_coverage_ratio"] == 0.333333
    assert attribution["market_participation_bands"][0]["key"] == "<40"
    assert attribution["market_liquidity_bands"][0]["key"] == "<45"
    assert {item["key"] for item in attribution["market_participation_bands"]} == {
        "<40",
        "40-54",
        "68+",
    }
    assert {item["key"] for item in attribution["market_liquidity_bands"]} == {
        "<45",
        "45-54",
        "68+",
    }
    assert attribution["stock_moneyflow_bands"][0]["key"] == "<45"
    assert attribution["stock_moneyflow_bands"][0]["sample_share"] == 0.333333
    assert attribution["stock_moneyflow_bands"][0]["return_contribution_pct"] == -0.006667
    assert attribution["sector_moneyflow_bands"][0]["key"] == "<45"
