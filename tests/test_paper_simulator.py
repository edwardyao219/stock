from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from services.engine.paper import simulator
from services.shared.database import Base
from services.shared.models import DailyBar, PaperOrder, PaperPosition, ResearchPoolItem, TradePlan


def _daily_bar(
    symbol: str,
    *,
    open_price: str = "10.10",
    high: str = "10.40",
    low: str = "10.00",
    close: str = "10.32",
    pre_close: str = "10.00",
) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=date(2026, 6, 24),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        pre_close=Decimal(pre_close),
        volume=Decimal("100000"),
        amount=Decimal("1200000"),
        turnover_rate=None,
        limit_up=Decimal("11.00"),
        limit_down=Decimal("9.00"),
        is_suspended=False,
    )


def _trade_plan(
    symbol: str,
    *,
    confidence_score: str = "65",
) -> TradePlan:
    return TradePlan(
        plan_date=date(2026, 6, 23),
        trade_date=date(2026, 6, 24),
        symbol=symbol,
        rule_id="R001",
        strategy_type="short_term",
        sector_code=None,
        entry_condition_json={},
        entry_trigger_price=Decimal("10.20"),
        max_gap_up_pct=Decimal("0.06"),
        trailing_drawdown_pct=Decimal("0.06"),
        initial_stop=Decimal("9.70"),
        take_profit_1=Decimal("10.80"),
        take_profit_2=Decimal("11.40"),
        max_holding_days=5,
        position_size=Decimal("0.10"),
        confidence_score=Decimal(confidence_score),
        status="planned",
    )


def test_daily_paper_simulation_skips_observation_plans(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(simulator, "SessionLocal", session)

    with session() as db:
        db.add(
            DailyBar(
                symbol="002745",
                trade_date=date(2026, 6, 24),
                open=Decimal("11.80"),
                high=Decimal("12.20"),
                low=Decimal("11.20"),
                close=Decimal("11.30"),
                pre_close=Decimal("11.60"),
                volume=Decimal("100000"),
                amount=Decimal("1200000"),
                turnover_rate=None,
                limit_up=Decimal("12.76"),
                limit_down=Decimal("10.44"),
                is_suspended=False,
            )
        )
        db.add(
            TradePlan(
                plan_date=date(2026, 6, 24),
                trade_date=date(2026, 6, 24),
                symbol="002745",
                rule_id="OBS001",
                strategy_type="watch_breakout",
                sector_code=None,
                entry_condition_json={},
                entry_trigger_price=Decimal("12.15"),
                max_gap_up_pct=Decimal("0.06"),
                trailing_drawdown_pct=Decimal("0.06"),
                initial_stop=Decimal("11.30"),
                take_profit_1=Decimal("13.00"),
                take_profit_2=Decimal("14.00"),
                max_holding_days=5,
                position_size=Decimal("0.03"),
                confidence_score=Decimal("70"),
                status="planned",
            )
        )
        db.commit()

    result = simulator.run_daily_paper_simulation("2026-06-24")

    with session() as db:
        positions = list(db.execute(select(PaperPosition)).scalars())

    assert result.opened == 0
    assert result.skipped == 1
    assert "OBS001 requires realtime monitor" in result.messages[0]
    assert positions == []


def test_daily_paper_simulation_keeps_exits_when_entries_are_disabled(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(simulator, "SessionLocal", session)

    with session() as db:
        db.add(_daily_bar("000001"))
        db.add(_daily_bar("000002", low="9.40"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="000001",
                status="active",
                tags_json={
                    "tags": [
                        "after_close_candidate",
                        "next_session",
                        "2026-06-23",
                        "rank:3",
                        "score:86.0",
                    ]
                },
            )
        )
        db.add(_trade_plan("000001"))
        db.add(
            PaperPosition(
                account_id=1,
                trade_plan_id=1,
                symbol="000002",
                rule_id="R001",
                strategy_type="short_term",
                entry_date=date(2026, 6, 23),
                entry_price=Decimal("10.0000"),
                quantity=1000,
                initial_stop=Decimal("9.5000"),
                current_stop=Decimal("9.5000"),
                take_profit_1=None,
                take_profit_2=None,
                highest_price=Decimal("10.0000"),
                lowest_price=Decimal("10.0000"),
                max_holding_days=5,
                status="open",
            )
        )
        db.commit()

    result = simulator.run_daily_paper_simulation("2026-06-24", execute_entries=False)

    with session() as db:
        buy_orders = list(
            db.execute(select(PaperOrder).where(PaperOrder.side == "buy")).scalars()
        )

    assert result.closed == 1
    assert result.opened == 0
    assert buy_orders == []


def test_daily_paper_simulation_uses_candidate_rank_gate(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(simulator, "SessionLocal", session)

    with session() as db:
        db.add(_daily_bar("000001"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="000001",
                status="active",
                tags_json={
                    "tags": [
                        "after_close_candidate",
                        "next_session",
                        "2026-06-23",
                        "rank:3",
                        "score:86.0",
                    ]
                },
            )
        )
        db.add(_trade_plan("000001", confidence_score="65"))
        db.commit()

    result = simulator.run_daily_paper_simulation("2026-06-24")

    with session() as db:
        positions = list(db.execute(select(PaperPosition)).scalars())

    assert result.opened == 1
    assert result.skipped == 0
    assert len(positions) == 1
    assert positions[0].entry_price == Decimal("10.2000")


def test_daily_paper_simulation_ignores_stale_candidate_rank(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(simulator, "SessionLocal", session)

    with session() as db:
        db.add(_daily_bar("000001"))
        db.add(_daily_bar("600171"))
        db.add_all(
            [
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000001",
                    status="active",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-06-23",
                            "hold_until:2026-06-24",
                            "rank:1",
                            "score:86.0",
                        ]
                    },
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="600171",
                    status="active",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-06-24",
                            "hold_until:2026-06-25",
                            "rank:1",
                            "score:84.0",
                        ]
                    },
                ),
            ]
        )
        db.add(_trade_plan("000001", confidence_score="65"))
        db.commit()

    result = simulator.run_daily_paper_simulation("2026-06-24")

    with session() as db:
        positions = list(db.execute(select(PaperPosition)).scalars())

    assert result.opened == 0
    assert result.skipped == 1
    assert positions == []
    assert "quality too weak" in result.messages[0]


def test_daily_paper_simulation_does_not_use_same_day_close_to_reject_entry(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(simulator, "SessionLocal", session)

    with session() as db:
        db.add(_daily_bar("000001", high="10.80", close="10.20"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="000001",
                status="active",
                tags_json={
                    "tags": [
                        "after_close_candidate",
                        "next_session",
                        "2026-06-23",
                        "rank:3",
                        "score:86.0",
                    ]
                },
            )
        )
        db.add(_trade_plan("000001", confidence_score="65"))
        db.commit()

    result = simulator.run_daily_paper_simulation("2026-06-24")

    with session() as db:
        positions = list(db.execute(select(PaperPosition)).scalars())

    assert result.opened == 1
    assert result.skipped == 0
    assert len(positions) == 1
    assert positions[0].entry_price == Decimal("10.2000")


def test_daily_paper_simulation_uses_prior_stop_before_same_day_high(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(simulator, "SessionLocal", session)

    with session() as db:
        db.add(
            DailyBar(
                symbol="000001",
                trade_date=date(2026, 6, 24),
                open=Decimal("10.10"),
                high=Decimal("10.90"),
                low=Decimal("10.30"),
                close=Decimal("10.70"),
                pre_close=Decimal("10.00"),
                volume=Decimal("100000"),
                amount=Decimal("1200000"),
                turnover_rate=None,
                limit_up=Decimal("11.00"),
                limit_down=Decimal("9.00"),
                is_suspended=False,
            )
        )
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="000001",
                status="active",
                tags_json={
                    "tags": [
                        "after_close_candidate",
                        "next_session",
                        "2026-06-23",
                        "rank:3",
                        "score:86.0",
                    ]
                },
            )
        )
        db.add(
            TradePlan(
                plan_date=date(2026, 6, 23),
                trade_date=date(2026, 6, 24),
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                sector_code=None,
                entry_condition_json={},
                entry_trigger_price=Decimal("10.20"),
                max_gap_up_pct=Decimal("0.06"),
                trailing_drawdown_pct=Decimal("0.06"),
                initial_stop=Decimal("9.70"),
                take_profit_1=Decimal("10.80"),
                take_profit_2=Decimal("11.40"),
                max_holding_days=5,
                position_size=Decimal("0.10"),
                confidence_score=Decimal("65"),
                status="planned",
            )
        )
        db.add(
            PaperPosition(
                account_id=1,
                trade_plan_id=1,
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                entry_date=date(2026, 6, 23),
                entry_price=Decimal("10.0000"),
                quantity=1000,
                initial_stop=Decimal("9.5000"),
                current_stop=Decimal("9.5000"),
                take_profit_1=Decimal("10.5000"),
                take_profit_2=None,
                highest_price=Decimal("10.8000"),
                lowest_price=Decimal("10.0000"),
                max_holding_days=5,
                status="open",
            )
        )
        db.commit()

    result = simulator.run_daily_paper_simulation("2026-06-24")

    with session() as db:
        position = db.query(PaperPosition).filter(PaperPosition.symbol == "000001").one()

    assert result.closed == 0
    assert position.status == "open"
    assert position.current_stop == Decimal("10.2460")


def test_daily_paper_simulation_does_not_pretend_same_day_trailing_exit_after_new_high(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(simulator, "SessionLocal", session)

    with session() as db:
        db.add(
            DailyBar(
                symbol="000001",
                trade_date=date(2026, 6, 24),
                open=Decimal("10.10"),
                high=Decimal("10.90"),
                low=Decimal("10.00"),
                close=Decimal("10.70"),
                pre_close=Decimal("10.00"),
                volume=Decimal("100000"),
                amount=Decimal("1200000"),
                turnover_rate=None,
                limit_up=Decimal("11.00"),
                limit_down=Decimal("9.00"),
                is_suspended=False,
            )
        )
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="000001",
                status="active",
                tags_json={
                    "tags": [
                        "after_close_candidate",
                        "next_session",
                        "2026-06-23",
                        "rank:3",
                        "score:86.0",
                    ]
                },
            )
        )
        db.add(
            TradePlan(
                plan_date=date(2026, 6, 23),
                trade_date=date(2026, 6, 24),
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                sector_code=None,
                entry_condition_json={},
                entry_trigger_price=Decimal("10.20"),
                max_gap_up_pct=Decimal("0.06"),
                trailing_drawdown_pct=Decimal("0.06"),
                initial_stop=Decimal("9.70"),
                take_profit_1=Decimal("10.80"),
                take_profit_2=Decimal("11.40"),
                max_holding_days=5,
                position_size=Decimal("0.10"),
                confidence_score=Decimal("65"),
                status="planned",
            )
        )
        db.commit()

    result = simulator.run_daily_paper_simulation("2026-06-24")

    assert result.opened == 1
    assert result.closed == 0
    assert result.skipped == 0
