from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.collector.akshare_client import RealtimeQuoteRow, fetch_sina_realtime_quotes
from services.collector.repository import upsert_realtime_quotes
from services.engine.paper.realtime import _realtime_exit_signal, _update_position_from_quote
from services.shared.database import Base
from services.shared.models import (
    PaperPosition,
    PaperTrade,
    PaperTradeReview,
    RealtimeQuote,
    TradePlan,
)


def _quote(symbol: str = "000001") -> RealtimeQuoteRow:
    return RealtimeQuoteRow(
        symbol=symbol,
        trade_date="2026-06-24",
        quote_time=datetime(2026, 6, 24, 10, 5),
        price=Decimal("10.3000"),
        open=Decimal("10.1000"),
        high=Decimal("11.0000"),
        low=Decimal("10.2000"),
        pre_close=Decimal("10.0000"),
        pct_change=Decimal("3.0000"),
        volume=Decimal("100000"),
        amount=Decimal("103000000"),
        turnover_rate=Decimal("1.2000"),
    )


def test_fetch_sina_realtime_quotes_parses_snapshot(monkeypatch) -> None:
    class Response:
        encoding = "utf-8"
        text = (
            'var hq_str_sz000001="平安银行,10.650,10.650,10.710,10.910,10.630,'
            '10.710,10.720,119060407,1285360400.380,363814,10.710,448200,'
            '10.700,524804,10.690,297800,10.680,205500,10.670,114900,10.720,'
            '163400,10.730,224000,10.740,173000,10.750,98400,10.760,'
            '2026-06-23,15:00:00,00";'
        )

        def raise_for_status(self) -> None:
            return None

    class Session:
        trust_env = True

        def get(self, url, headers, timeout):
            return Response()

    monkeypatch.setattr("services.collector.akshare_client.requests.Session", Session)

    rows = fetch_sina_realtime_quotes({"000001"})

    assert len(rows) == 1
    assert rows[0].symbol == "000001"
    assert rows[0].price == Decimal("10.710")
    assert rows[0].high == Decimal("10.910")
    assert rows[0].source == "sina.hq"


def test_upsert_realtime_quotes_writes_snapshot() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        written = upsert_realtime_quotes(db, [_quote()])
        db.commit()
        row = db.query(RealtimeQuote).one()

    assert written == 1
    assert row.symbol == "000001"
    assert row.price == Decimal("10.3000")
    assert row.trade_date == date(2026, 6, 24)


def test_update_position_from_quote_raises_trailing_stop_and_alerts() -> None:
    position = PaperPosition(
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
        highest_price=Decimal("10.0000"),
        lowest_price=Decimal("10.0000"),
        max_holding_days=5,
        status="open",
    )

    changed, alerts = _update_position_from_quote(position, _quote())

    assert changed is True
    assert position.highest_price == Decimal("11.0000")
    assert position.lowest_price == Decimal("10.0000")
    assert position.current_stop == Decimal("10.3400")
    assert [item.alert_type for item in alerts] == [
        "take_profit_touched",
        "stop_loss_touched",
        "limit_up_touched",
    ]
    assert alerts[0].alert_time == "2026-06-24T10:05:00"


def test_update_position_from_quote_uses_current_price_for_same_day_entry() -> None:
    position = PaperPosition(
        account_id=1,
        trade_plan_id=1,
        symbol="000001",
        rule_id="R001",
        strategy_type="short_term",
        entry_date=date(2026, 6, 24),
        entry_price=Decimal("10.0000"),
        quantity=1000,
        initial_stop=Decimal("9.5000"),
        current_stop=Decimal("9.5000"),
        take_profit_1=Decimal("10.5000"),
        take_profit_2=None,
        highest_price=Decimal("10.0000"),
        lowest_price=Decimal("10.0000"),
        max_holding_days=5,
        status="open",
    )

    changed, alerts = _update_position_from_quote(position, _quote())

    assert changed is True
    assert position.highest_price == Decimal("10.3000")
    assert position.lowest_price == Decimal("10.0000")
    assert position.current_stop == Decimal("9.5000")
    assert alerts == []


def test_realtime_exit_signal_uses_trailing_take_profit_after_profit_touch() -> None:
    position = PaperPosition(
        account_id=1,
        trade_plan_id=1,
        symbol="000001",
        rule_id="R001",
        strategy_type="short_term",
        entry_date=date(2026, 6, 24),
        entry_price=Decimal("10.0000"),
        quantity=1000,
        initial_stop=Decimal("9.5000"),
        current_stop=Decimal("10.3400"),
        take_profit_1=Decimal("10.5000"),
        take_profit_2=None,
        highest_price=Decimal("11.0000"),
        lowest_price=Decimal("10.0000"),
        max_holding_days=5,
        status="open",
    )

    should_exit, exit_price, reason = _realtime_exit_signal(position, _quote())

    assert should_exit is True
    assert exit_price == Decimal("10.3400")
    assert reason == "trailing_take_profit"


def test_realtime_monitor_can_execute_exit_and_create_review(monkeypatch) -> None:
    from services.engine.paper import realtime

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(realtime, "SessionLocal", session)

    with session() as db:
        db.add(
            PaperPosition(
                account_id=1,
                trade_plan_id=None,
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                entry_date=date(2026, 6, 24),
                entry_price=Decimal("10.0000"),
                quantity=1000,
                initial_stop=Decimal("9.5000"),
                current_stop=Decimal("10.3400"),
                take_profit_1=Decimal("10.5000"),
                take_profit_2=None,
                highest_price=Decimal("11.0000"),
                lowest_price=Decimal("10.0000"),
                max_holding_days=5,
                status="open",
            )
        )
        db.commit()

    result = realtime.monitor_paper_positions_realtime(
        trade_date="2026-06-24",
        account_name="default",
        quotes=[_quote()],
        quote_time=datetime(2026, 6, 24, 10, 5),
        execute_exits=True,
    )

    with session() as db:
        review = db.query(PaperTradeReview).one()
        position = db.query(PaperPosition).one()

    assert result.executed_exits == 1
    assert position.status == "closed"
    assert review.position_id == position.id
    assert review.exit_reason == "trailing_take_profit"


def test_realtime_monitor_can_execute_entry_from_plan(monkeypatch) -> None:
    from services.engine.paper import realtime

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(realtime, "SessionLocal", session)

    with session() as db:
        db.add(
            TradePlan(
                plan_date=date(2026, 6, 23),
                trade_date=date(2026, 6, 24),
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                sector_code=None,
                entry_condition_json={},
                entry_trigger_price=Decimal("10.2000"),
                max_gap_up_pct=Decimal("0.0600"),
                trailing_drawdown_pct=Decimal("0.0600"),
                initial_stop=Decimal("9.7000"),
                take_profit_1=Decimal("10.8000"),
                take_profit_2=None,
                max_holding_days=5,
                position_size=Decimal("0.1000"),
                confidence_score=Decimal("80.0000"),
                risk_notes=None,
                status="planned",
            )
        )
        db.commit()

    result = realtime.monitor_paper_positions_realtime(
        trade_date="2026-06-24",
        account_name="default",
        quotes=[_quote()],
        quote_time=datetime(2026, 6, 24, 10, 5),
        execute_entries=True,
        execute_exits=False,
    )

    with session() as db:
        position = db.query(PaperPosition).one()
        trade = db.query(PaperTrade).one()
        plan = db.query(TradePlan).one()

    assert result.executed_entries == 1
    assert position.status == "open"
    assert position.entry_price == Decimal("10.3000")
    assert trade.side == "buy"
    assert plan.status == "executed"
