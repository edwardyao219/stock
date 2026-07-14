from datetime import date, datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.collector.akshare_client import (
    RealtimeQuoteRow,
    _exchange_for_symbol,
    _market_prefix_for_symbol,
    fetch_sina_realtime_quotes,
)
from services.collector.repository import upsert_realtime_quotes
from services.engine.paper.realtime import (
    IntradayQuoteSnapshot,
    _build_intraday_quote_snapshot,
    _entry_quality_rejection_reason,
    _position_t_rhythm_alert,
    _realtime_exit_signal,
    _update_position_from_quote,
)
from services.shared.database import Base
from services.shared.models import (
    PaperPosition,
    PaperTrade,
    PaperTradeReview,
    RealtimeQuote,
    ResearchPoolItem,
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


def _entry_quote(symbol: str = "000001") -> RealtimeQuoteRow:
    return RealtimeQuoteRow(
        symbol=symbol,
        trade_date="2026-06-24",
        quote_time=datetime(2026, 6, 24, 10, 5),
        price=Decimal("10.3000"),
        open=Decimal("10.1000"),
        high=Decimal("10.3500"),
        low=Decimal("10.0800"),
        pre_close=Decimal("10.0000"),
        pct_change=Decimal("3.0000"),
        volume=Decimal("100000"),
        amount=Decimal("103000000"),
        turnover_rate=Decimal("1.2000"),
    )


def _strong_entry_condition() -> dict:
    return {
        "snapshot": {
            "trend_score": 76,
            "relative_strength_score": 70,
            "sector_strength_score": 66,
            "risk_score": 28,
        }
    }


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


def test_fetch_realtime_quotes_falls_back_to_sina_full_market_source(monkeypatch) -> None:
    from services.collector import akshare_client

    class _Akshare:
        def stock_zh_a_spot_em(self):
            raise RuntimeError("eastmoney unavailable")

        def stock_zh_a_spot(self):
            return pd.DataFrame(
                [
                    {
                        "代码": "000001",
                        "最新价": 10.5,
                        "今开": 10.2,
                        "最高": 10.8,
                        "最低": 10.1,
                        "昨收": 10,
                        "涨跌幅": 5,
                        "成交量": 100,
                        "成交额": 1050,
                        "换手率": 1.2,
                    }
                ]
            )

    monkeypatch.setattr(akshare_client, "_akshare", lambda: _Akshare())

    rows = akshare_client.fetch_realtime_quotes(quote_time=datetime(2026, 7, 14, 15, 5))

    assert len(rows) == 1
    assert rows[0].symbol == "000001"
    assert rows[0].source == "akshare.stock_zh_a_spot"


def test_north_exchange_92_prefix_uses_beijing_realtime_symbol() -> None:
    assert _exchange_for_symbol("920344") == "BJ"
    assert _market_prefix_for_symbol("920344") == "bj"
    assert _exchange_for_symbol("900001") == "SH"


def test_realtime_cutoff_is_earlier_than_close() -> None:
    from services.engine.paper import realtime

    assert realtime.INTRADAY_ENTRY_CUTOFF.hour == 14
    assert realtime.INTRADAY_ENTRY_CUTOFF.minute == 15


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


def test_realtime_exit_signal_gives_long_term_positions_more_room() -> None:
    position = PaperPosition(
        account_id=1,
        trade_plan_id=1,
        symbol="600000",
        rule_id="R004",
        strategy_type="long_term",
        entry_date=date(2026, 6, 23),
        entry_price=Decimal("10.0000"),
        quantity=1000,
        initial_stop=Decimal("9.7000"),
        current_stop=Decimal("10.0000"),
        take_profit_1=Decimal("10.5000"),
        take_profit_2=None,
        highest_price=Decimal("10.6000"),
        lowest_price=Decimal("9.9000"),
        max_holding_days=None,
        status="open",
    )
    quote = RealtimeQuoteRow(
        symbol="600000",
        trade_date="2026-06-24",
        quote_time=datetime(2026, 6, 24, 10, 5),
        price=Decimal("9.9500"),
        open=Decimal("10.0500"),
        high=Decimal("10.0500"),
        low=Decimal("9.9400"),
        pre_close=Decimal("10.0000"),
        pct_change=Decimal("-0.5000"),
        volume=Decimal("100000"),
        amount=Decimal("99500000"),
        turnover_rate=Decimal("1.0000"),
    )

    should_exit, exit_price, reason = _realtime_exit_signal(position, quote)

    assert should_exit is False
    assert exit_price is None
    assert reason == ""


def test_long_term_position_t_rhythm_reduce_watch() -> None:
    position = PaperPosition(
        account_id=1,
        trade_plan_id=1,
        symbol="600000",
        rule_id="R004",
        strategy_type="long_term",
        entry_date=date(2026, 6, 1),
        entry_price=Decimal("10.0000"),
        quantity=1000,
        initial_stop=Decimal("9.2000"),
        current_stop=Decimal("9.8000"),
        take_profit_1=Decimal("11.2000"),
        take_profit_2=None,
        highest_price=Decimal("11.5000"),
        lowest_price=Decimal("9.8000"),
        max_holding_days=None,
        status="open",
    )
    quote = RealtimeQuoteRow(
        symbol="600000",
        trade_date="2026-06-24",
        quote_time=datetime(2026, 6, 24, 10, 5),
        price=Decimal("11.1500"),
        open=Decimal("11.6000"),
        high=Decimal("11.6000"),
        low=Decimal("11.0000"),
        pre_close=Decimal("11.0000"),
        pct_change=Decimal("1.3636"),
        volume=Decimal("100000"),
        amount=Decimal("111500000"),
        turnover_rate=Decimal("1.0000"),
    )

    alert = _position_t_rhythm_alert(position=position, quote=quote)

    assert alert is not None
    assert alert.alert_type == "t_rhythm_reduce_watch"
    assert "机动仓可考虑减一档" in alert.message
    assert "t_reduce_zone" in alert.risk_flags


def test_long_term_position_t_rhythm_add_watch_after_repair() -> None:
    position = PaperPosition(
        account_id=1,
        trade_plan_id=1,
        symbol="600000",
        rule_id="R004",
        strategy_type="long_term",
        entry_date=date(2026, 6, 1),
        entry_price=Decimal("10.0000"),
        quantity=1000,
        initial_stop=Decimal("9.2000"),
        current_stop=Decimal("9.8000"),
        take_profit_1=Decimal("11.2000"),
        take_profit_2=None,
        highest_price=Decimal("11.5000"),
        lowest_price=Decimal("9.8000"),
        max_holding_days=None,
        status="open",
    )
    quote = RealtimeQuoteRow(
        symbol="600000",
        trade_date="2026-06-24",
        quote_time=datetime(2026, 6, 24, 10, 5),
        price=Decimal("10.8500"),
        open=Decimal("10.6000"),
        high=Decimal("11.6000"),
        low=Decimal("10.4000"),
        pre_close=Decimal("10.7000"),
        pct_change=Decimal("1.4019"),
        volume=Decimal("100000"),
        amount=Decimal("108500000"),
        turnover_rate=Decimal("1.0000"),
    )
    snapshot = IntradayQuoteSnapshot(
        symbol="600000",
        trade_date="2026-06-24",
        quote_time="2026-06-24T10:05:00",
        state="pullback_repair",
        label="回调修复",
        summary="盘中快照：回踩后修复",
        support_flags=["intraday_pullback_repair"],
        risk_flags=[],
    )

    alert = _position_t_rhythm_alert(position=position, quote=quote, snapshot=snapshot)

    assert alert is not None
    assert alert.alert_type == "t_rhythm_add_watch"
    assert "接回机动仓" in alert.message
    assert "t_add_zone" in alert.support_flags


def test_intraday_snapshot_marks_gap_down_repair_as_support_signal() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        upsert_realtime_quotes(
            db,
            [
                RealtimeQuoteRow(
                    symbol="600519",
                    trade_date="2026-06-30",
                    quote_time=datetime(2026, 6, 30, 9, 40),
                    price=Decimal("9.7600"),
                    open=Decimal("9.7000"),
                    high=Decimal("9.8000"),
                    low=Decimal("9.6500"),
                    pre_close=Decimal("10.0000"),
                    pct_change=Decimal("-2.4000"),
                    volume=Decimal("90000"),
                    amount=Decimal("87840000"),
                    turnover_rate=Decimal("0.9000"),
                ),
                RealtimeQuoteRow(
                    symbol="600519",
                    trade_date="2026-06-30",
                    quote_time=datetime(2026, 6, 30, 10, 0),
                    price=Decimal("9.9000"),
                    open=Decimal("9.7000"),
                    high=Decimal("9.9500"),
                    low=Decimal("9.6500"),
                    pre_close=Decimal("10.0000"),
                    pct_change=Decimal("-1.0000"),
                    volume=Decimal("120000"),
                    amount=Decimal("118800000"),
                    turnover_rate=Decimal("1.2000"),
                ),
            ],
        )
        db.commit()

        current_quote = RealtimeQuoteRow(
            symbol="600519",
            trade_date="2026-06-30",
            quote_time=datetime(2026, 6, 30, 10, 10),
            price=Decimal("10.0300"),
            open=Decimal("9.7000"),
            high=Decimal("10.0500"),
            low=Decimal("9.6500"),
            pre_close=Decimal("10.0000"),
            pct_change=Decimal("0.3000"),
            volume=Decimal("170000"),
            amount=Decimal("170510000"),
            turnover_rate=Decimal("1.7000"),
        )

        snapshot = _build_intraday_quote_snapshot(db, current_quote)

    assert snapshot is not None
    assert snapshot.state == "gap_down_repair"
    assert snapshot.label == "低开修复"
    assert "低开修复" in snapshot.summary
    assert "intraday_gap_down_repair" in snapshot.support_flags
    assert snapshot.risk_flags == []


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
        quotes=[_entry_quote()],
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


def test_realtime_monitor_does_not_use_same_quote_to_raise_and_exit(monkeypatch) -> None:
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

    result = realtime.monitor_paper_positions_realtime(
        trade_date="2026-06-24",
        account_name="default",
        quotes=[_quote()],
        quote_time=datetime(2026, 6, 24, 10, 5),
        execute_entries=False,
        execute_exits=True,
    )

    with session() as db:
        position = db.query(PaperPosition).one()

    assert result.executed_exits == 0
    assert position.status == "open"
    assert position.highest_price == Decimal("11.0000")
    assert position.current_stop == Decimal("10.3400")


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
                entry_condition_json=_strong_entry_condition(),
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
        quotes=[_entry_quote()],
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


def test_entry_quality_rejects_failed_breakout_pullback() -> None:
    plan = TradePlan(
        plan_date=date(2026, 6, 23),
        trade_date=date(2026, 6, 24),
        symbol="000001",
        rule_id="R006",
        strategy_type="swing",
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
    quote = RealtimeQuoteRow(
        symbol="000001",
        trade_date="2026-06-24",
        quote_time=datetime(2026, 6, 24, 10, 5),
        price=Decimal("10.2500"),
        open=Decimal("10.1000"),
        high=Decimal("10.7000"),
        low=Decimal("10.1500"),
        pre_close=Decimal("10.0000"),
        pct_change=Decimal("2.5000"),
        volume=Decimal("100000"),
        amount=Decimal("103000000"),
        turnover_rate=Decimal("1.2000"),
    )

    reason = _entry_quality_rejection_reason(plan, quote, Decimal("10.2000"))

    assert reason == "failed_breakout_pullback"


def test_entry_quality_rejects_spike_reversed_to_red() -> None:
    plan = TradePlan(
        plan_date=date(2026, 6, 26),
        trade_date=date(2026, 6, 29),
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
    quote = RealtimeQuoteRow(
        symbol="000001",
        trade_date="2026-06-29",
        quote_time=datetime(2026, 6, 29, 10, 5),
        price=Decimal("9.9800"),
        open=Decimal("10.5000"),
        high=Decimal("10.8500"),
        low=Decimal("9.9000"),
        pre_close=Decimal("10.0000"),
        pct_change=Decimal("-0.2000"),
        volume=Decimal("160000"),
        amount=Decimal("162000000"),
        turnover_rate=Decimal("1.8000"),
    )

    reason = _entry_quality_rejection_reason(plan, quote, Decimal("9.9000"))

    assert reason == "spike_reversed_to_flat_or_red"


def test_realtime_monitor_defers_entry_when_intraday_quality_is_weak(monkeypatch) -> None:
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
                rule_id="R006",
                strategy_type="swing",
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

    weak_quote = RealtimeQuoteRow(
        symbol="000001",
        trade_date="2026-06-24",
        quote_time=datetime(2026, 6, 24, 10, 5),
        price=Decimal("10.2500"),
        open=Decimal("10.1000"),
        high=Decimal("10.7000"),
        low=Decimal("10.1500"),
        pre_close=Decimal("10.0000"),
        pct_change=Decimal("2.5000"),
        volume=Decimal("100000"),
        amount=Decimal("103000000"),
        turnover_rate=Decimal("1.2000"),
    )
    result = realtime.monitor_paper_positions_realtime(
        trade_date="2026-06-24",
        account_name="default",
        quotes=[weak_quote],
        quote_time=datetime(2026, 6, 24, 10, 5),
        execute_entries=True,
        execute_exits=False,
    )

    with session() as db:
        assert db.query(PaperPosition).count() == 0
        assert db.query(PaperTrade).count() == 0
        plan = db.query(TradePlan).one()

    assert result.executed_entries == 0
    assert plan.status == "planned"
    assert [alert.alert_type for alert in result.alerts] == ["paper_entry_deferred"]


def test_realtime_monitor_defers_entry_when_intraday_snapshot_turns_weak(monkeypatch) -> None:
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
                entry_condition_json=_strong_entry_condition(),
                entry_trigger_price=Decimal("10.2000"),
                max_gap_up_pct=Decimal("0.0600"),
                trailing_drawdown_pct=Decimal("0.0600"),
                initial_stop=Decimal("9.7000"),
                take_profit_1=Decimal("10.8000"),
                take_profit_2=None,
                max_holding_days=5,
                position_size=Decimal("0.1000"),
                confidence_score=Decimal("88.0000"),
                risk_notes=None,
                status="planned",
            )
        )
        upsert_realtime_quotes(
            db,
            [
                RealtimeQuoteRow(
                    symbol="000001",
                    trade_date="2026-06-24",
                    quote_time=datetime(2026, 6, 24, 9, 55),
                    price=Decimal("10.2000"),
                    open=Decimal("10.1000"),
                    high=Decimal("10.2500"),
                    low=Decimal("10.0800"),
                    pre_close=Decimal("10.0000"),
                    pct_change=Decimal("2.0000"),
                    volume=Decimal("90000"),
                    amount=Decimal("91800000"),
                    turnover_rate=Decimal("0.9000"),
                ),
                RealtimeQuoteRow(
                    symbol="000001",
                    trade_date="2026-06-24",
                    quote_time=datetime(2026, 6, 24, 10, 0),
                    price=Decimal("10.3500"),
                    open=Decimal("10.1000"),
                    high=Decimal("10.4000"),
                    low=Decimal("10.2500"),
                    pre_close=Decimal("10.0000"),
                    pct_change=Decimal("3.5000"),
                    volume=Decimal("100000"),
                    amount=Decimal("103500000"),
                    turnover_rate=Decimal("1.0000"),
                ),
            ],
        )
        db.commit()

    current_quote = RealtimeQuoteRow(
        symbol="000001",
        trade_date="2026-06-24",
        quote_time=datetime(2026, 6, 24, 10, 5),
        price=Decimal("10.2500"),
        open=Decimal("10.1000"),
        high=Decimal("10.3000"),
        low=Decimal("10.2000"),
        pre_close=Decimal("10.0000"),
        pct_change=Decimal("2.5000"),
        volume=Decimal("140000"),
        amount=Decimal("143500000"),
        turnover_rate=Decimal("1.2000"),
    )
    result = realtime.monitor_paper_positions_realtime(
        trade_date="2026-06-24",
        account_name="default",
        quotes=[current_quote],
        quote_time=datetime(2026, 6, 24, 10, 5),
        execute_entries=True,
        execute_exits=False,
    )

    with session() as db:
        plan = db.query(TradePlan).one()
        positions = db.query(PaperPosition).all()

    assert result.executed_entries == 0
    assert plan.status == "planned"
    assert positions == []
    assert any("盘中快照" in alert.message for alert in result.alerts)
    assert any("放量分歧" in alert.message for alert in result.alerts)
    snapshot = result.alerts[0].intraday_snapshot
    assert snapshot is not None
    assert snapshot["label"] == "放量分歧"
    assert snapshot["session_change_pct"] == 0.025
    assert snapshot["open_gap_pct"] == 0.01
    assert snapshot["intraday_high_gain_pct"] == 0.03
    assert snapshot["pullback_from_high_pct"] > 0


def test_realtime_monitor_limits_daily_entries_and_requires_high_quality(monkeypatch) -> None:
    from services.engine.paper import realtime

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(realtime, "SessionLocal", session)

    with session() as db:
        for index in range(4):
            db.add(
                TradePlan(
                    plan_date=date(2026, 6, 23),
                    trade_date=date(2026, 6, 24),
                    symbol=f"00000{index + 1}",
                    rule_id="R001",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json=_strong_entry_condition() if index < 3 else {},
                    entry_trigger_price=Decimal("10.2000"),
                    max_gap_up_pct=Decimal("0.0600"),
                    trailing_drawdown_pct=Decimal("0.0600"),
                    initial_stop=Decimal("9.7000"),
                    take_profit_1=Decimal("10.8000"),
                    take_profit_2=None,
                    max_holding_days=5,
                    position_size=Decimal("0.1000"),
                    confidence_score=Decimal("80.0000" if index < 3 else "60.0000"),
                    risk_notes=None,
                    status="planned",
                )
            )
        db.commit()

    quotes = [
        RealtimeQuoteRow(
            symbol=f"00000{index + 1}",
            trade_date="2026-06-24",
            quote_time=datetime(2026, 6, 24, 10, 5),
            price=Decimal("10.3000"),
            open=Decimal("10.1000"),
            high=Decimal("10.3500"),
            low=Decimal("10.0800"),
            pre_close=Decimal("10.0000"),
            pct_change=Decimal("3.0000"),
            volume=Decimal("100000"),
            amount=Decimal("103000000"),
            turnover_rate=Decimal("1.2000"),
        )
        for index in range(4)
    ]

    result = realtime.monitor_paper_positions_realtime(
        trade_date="2026-06-24",
        account_name="default",
        quotes=quotes,
        quote_time=datetime(2026, 6, 24, 14, 10),
        execute_entries=True,
        execute_exits=False,
    )

    with session() as db:
        plans = db.query(TradePlan).order_by(TradePlan.symbol).all()
        positions = db.query(PaperPosition).order_by(PaperPosition.symbol).all()

    assert result.executed_entries == 2
    assert any("今日纸面买入笔数已达上限" in alert.message for alert in result.alerts)
    assert [plan.status for plan in plans] == ["executed", "executed", "planned", "planned"]
    assert len(positions) == 2


def test_realtime_monitor_requires_high_rank_or_high_confidence(monkeypatch) -> None:
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
                entry_condition_json=_strong_entry_condition(),
                entry_trigger_price=Decimal("10.2000"),
                max_gap_up_pct=Decimal("0.0600"),
                trailing_drawdown_pct=Decimal("0.0600"),
                initial_stop=Decimal("9.7000"),
                take_profit_1=Decimal("10.8000"),
                take_profit_2=None,
                max_holding_days=5,
                position_size=Decimal("0.1000"),
                confidence_score=Decimal("70.0000"),
                risk_notes=None,
                status="planned",
            )
        )
        db.commit()

    result = realtime.monitor_paper_positions_realtime(
        trade_date="2026-06-24",
        account_name="default",
        quotes=[_entry_quote()],
        quote_time=datetime(2026, 6, 24, 10, 5),
        execute_entries=True,
        execute_exits=False,
    )

    with session() as db:
        plan = db.query(TradePlan).one()
        positions = db.query(PaperPosition).all()

    assert result.executed_entries == 0
    assert plan.status == "planned"
    assert positions == []
    assert any("不是足够高质量的盘中计划" in alert.message for alert in result.alerts)


def test_realtime_monitor_allows_high_rank_candidate(monkeypatch) -> None:
    from services.engine.paper import realtime

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(realtime, "SessionLocal", session)

    with session() as db:
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="000001",
                status="active",
                tags_json={
                    "tags": ["after_close_candidate", "next_session", "rank:2", "score:86.0"]
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
                entry_trigger_price=Decimal("10.2000"),
                max_gap_up_pct=Decimal("0.0600"),
                trailing_drawdown_pct=Decimal("0.0600"),
                initial_stop=Decimal("9.7000"),
                take_profit_1=Decimal("10.8000"),
                take_profit_2=None,
                max_holding_days=5,
                position_size=Decimal("0.1000"),
                confidence_score=Decimal("65.0000"),
                risk_notes=None,
                status="planned",
            )
        )
        db.commit()

    result = realtime.monitor_paper_positions_realtime(
        trade_date="2026-06-24",
        account_name="default",
        quotes=[_entry_quote()],
        quote_time=datetime(2026, 6, 24, 10, 5),
        execute_entries=True,
        execute_exits=False,
    )

    with session() as db:
        plan = db.query(TradePlan).one()
        positions = db.query(PaperPosition).all()

    assert result.executed_entries == 1
    assert plan.status == "executed"
    assert len(positions) == 1


def test_realtime_monitor_blocks_entries_when_friday_candidates_retreat_on_monday(
    monkeypatch,
) -> None:
    from services.engine.paper import realtime

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(realtime, "SessionLocal", session)

    with session() as db:
        for index, symbol in enumerate(["000001", "000002", "000003", "000004", "000005"], start=1):
            db.add(
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol=symbol,
                    status="active",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-06-26",
                            "hold_until:2026-06-29",
                            f"rank:{index}",
                            "score:86.0",
                        ]
                    },
                )
            )
        db.add(
            TradePlan(
                plan_date=date(2026, 6, 26),
                trade_date=date(2026, 6, 29),
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                sector_code=None,
                entry_condition_json=_strong_entry_condition(),
                entry_trigger_price=Decimal("9.9000"),
                max_gap_up_pct=Decimal("0.0600"),
                trailing_drawdown_pct=Decimal("0.0600"),
                initial_stop=Decimal("9.3000"),
                take_profit_1=Decimal("10.8000"),
                take_profit_2=None,
                max_holding_days=5,
                position_size=Decimal("0.1000"),
                confidence_score=Decimal("88.0000"),
                risk_notes=None,
                status="planned",
            )
        )
        db.commit()

    quotes = [
        RealtimeQuoteRow(
            symbol="000001",
            trade_date="2026-06-29",
            quote_time=datetime(2026, 6, 29, 10, 5),
            price=Decimal("10.0500"),
            open=Decimal("10.5000"),
            high=Decimal("10.8500"),
            low=Decimal("9.9000"),
            pre_close=Decimal("10.0000"),
            pct_change=Decimal("0.5000"),
            volume=Decimal("180000"),
            amount=Decimal("181000000"),
            turnover_rate=Decimal("1.8000"),
        ),
        RealtimeQuoteRow(
            symbol="000002",
            trade_date="2026-06-29",
            quote_time=datetime(2026, 6, 29, 10, 5),
            price=Decimal("9.8000"),
            open=Decimal("10.4000"),
            high=Decimal("10.7500"),
            low=Decimal("9.7000"),
            pre_close=Decimal("10.0000"),
            pct_change=Decimal("-2.0000"),
            volume=Decimal("180000"),
            amount=Decimal("178000000"),
            turnover_rate=Decimal("1.8000"),
        ),
        RealtimeQuoteRow(
            symbol="000003",
            trade_date="2026-06-29",
            quote_time=datetime(2026, 6, 29, 10, 5),
            price=Decimal("9.7000"),
            open=Decimal("10.3000"),
            high=Decimal("10.6500"),
            low=Decimal("9.6500"),
            pre_close=Decimal("10.0000"),
            pct_change=Decimal("-3.0000"),
            volume=Decimal("180000"),
            amount=Decimal("176000000"),
            turnover_rate=Decimal("1.8000"),
        ),
        RealtimeQuoteRow(
            symbol="000004",
            trade_date="2026-06-29",
            quote_time=datetime(2026, 6, 29, 10, 5),
            price=Decimal("9.9000"),
            open=Decimal("10.2500"),
            high=Decimal("10.7000"),
            low=Decimal("9.8500"),
            pre_close=Decimal("10.0000"),
            pct_change=Decimal("-1.0000"),
            volume=Decimal("180000"),
            amount=Decimal("177000000"),
            turnover_rate=Decimal("1.8000"),
        ),
        RealtimeQuoteRow(
            symbol="000005",
            trade_date="2026-06-29",
            quote_time=datetime(2026, 6, 29, 10, 5),
            price=Decimal("10.1000"),
            open=Decimal("10.1500"),
            high=Decimal("10.2000"),
            low=Decimal("9.9500"),
            pre_close=Decimal("10.0000"),
            pct_change=Decimal("1.0000"),
            volume=Decimal("120000"),
            amount=Decimal("122000000"),
            turnover_rate=Decimal("1.2000"),
        ),
    ]

    result = realtime.monitor_paper_positions_realtime(
        trade_date="2026-06-29",
        account_name="default",
        quotes=quotes,
        quote_time=datetime(2026, 6, 29, 10, 5),
        execute_entries=True,
        execute_exits=False,
        market_overview={"up_ratio": 0.37, "avg_change_pct": -0.0066},
    )

    with session() as db:
        plan = db.query(TradePlan).one()
        positions = db.query(PaperPosition).all()

    assert result.executed_entries == 0
    assert plan.status == "planned"
    assert positions == []
    assert any("黑天鹅退潮" in alert.message for alert in result.alerts)


def test_realtime_monitor_blocks_new_entries_after_cutoff(monkeypatch) -> None:
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
                entry_condition_json=_strong_entry_condition(),
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
        quotes=[
            RealtimeQuoteRow(
                symbol="000001",
                trade_date="2026-06-24",
                quote_time=datetime(2026, 6, 24, 14, 45),
                price=Decimal("10.3000"),
                open=Decimal("10.1000"),
                high=Decimal("10.3500"),
                low=Decimal("10.0800"),
                pre_close=Decimal("10.0000"),
                pct_change=Decimal("3.0000"),
                volume=Decimal("100000"),
                amount=Decimal("103000000"),
                turnover_rate=Decimal("1.2000"),
            )
        ],
        quote_time=datetime(2026, 6, 24, 14, 45),
        execute_entries=True,
        execute_exits=False,
    )

    with session() as db:
        plan = db.query(TradePlan).one()
        positions = db.query(PaperPosition).all()

    assert result.executed_entries == 0
    assert plan.status == "cancelled"
    assert positions == []
    assert any("临近收盘，不再新开仓" in alert.message for alert in result.alerts)


def test_realtime_monitor_allows_entries_before_cutoff(monkeypatch) -> None:
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
                entry_condition_json=_strong_entry_condition(),
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
        quotes=[
            RealtimeQuoteRow(
                symbol="000001",
                trade_date="2026-06-24",
                quote_time=datetime(2026, 6, 24, 14, 10),
                price=Decimal("10.3000"),
                open=Decimal("10.1000"),
                high=Decimal("10.3500"),
                low=Decimal("10.0800"),
                pre_close=Decimal("10.0000"),
                pct_change=Decimal("3.0000"),
                volume=Decimal("100000"),
                amount=Decimal("103000000"),
                turnover_rate=Decimal("1.2000"),
            )
        ],
        quote_time=datetime(2026, 6, 24, 14, 10),
        execute_entries=True,
        execute_exits=False,
    )

    with session() as db:
        plan = db.query(TradePlan).one()
        positions = db.query(PaperPosition).all()

    assert result.executed_entries == 1
    assert plan.status == "executed"
    assert len(positions) == 1
