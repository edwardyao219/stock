from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.review.repository import (
    insert_review_report,
    load_candidate_pool_items_for_review,
    load_latest_review_report,
    load_market_cross_section_for_report_date,
    load_market_indexes_for_report_date,
    load_market_summary_for_report_date,
    load_trade_plans_for_date,
    upsert_parameter_recommendations,
)
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    ParameterRecommendation,
    ResearchPoolItem,
    ReviewReport,
    Security,
    TradePlan,
    TradingCalendar,
    TushareMoneyflowIndDc,
)


def test_load_trade_plans_for_date_filters_unknown_rule_ids() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add_all(
            [
                TradePlan(
                    plan_date=date(2026, 6, 23),
                    trade_date=date(2026, 6, 24),
                    symbol="000001",
                    rule_id="R001",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("80"),
                    status="planned",
                ),
                TradePlan(
                    plan_date=date(2026, 6, 23),
                    trade_date=date(2026, 6, 24),
                    symbol="000001",
                    rule_id="TEST",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("99"),
                    status="planned",
                ),
            ]
        )
        db.commit()

        plans = load_trade_plans_for_date(db, "2026-06-23")

    assert [item.rule_id for item in plans] == ["R001"]


def test_load_candidate_pool_items_for_review_uses_previous_trade_date_tags() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add_all(
            [
                TradingCalendar(
                    trade_date=date(2026, 6, 24),
                    is_open=True,
                    previous_trade_date=date(2026, 6, 23),
                    next_trade_date=date(2026, 6, 25),
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000001",
                    status="active",
                    tags_json={"tags": ["after_close_candidate", "2026-06-23", "rank:1"]},
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000002",
                    status="active",
                    tags_json={"tags": ["after_close_candidate", "2026-06-22", "rank:2"]},
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000003",
                    status="active",
                    tags_json={"tags": ["manual_focus", "after_close_candidate", "2026-06-23"]},
                ),
            ]
        )
        db.commit()

        items = load_candidate_pool_items_for_review(db, "2026-06-24")

    assert [item["symbol"] for item in items] == ["000001", "000003"]


def test_load_market_summary_for_report_date_marks_stale_data() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="样本",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
                DailyBar(
                    symbol="000001",
                    trade_date=date(2026, 6, 23),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10.5"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
            ]
        )
        db.commit()

        summary = load_market_summary_for_report_date(db, "2026-06-24")

    assert summary["requested_date"] == "2026-06-24"
    assert summary["trade_date"] == "2026-06-23"
    assert summary["stale"] is True
    assert summary["stock_count"] == 1
    assert summary["up_count"] == 1
    assert summary["total_amount"] == 1000


def test_load_market_summary_suppresses_amount_change_when_previous_amount_is_sparse() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol=f"00000{index}",
                    name=f"样本{index}",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                )
                for index in range(1, 4)
            ]
        )
        db.add_all(
            [
                DailyBar(
                    symbol="000001",
                    trade_date=date(2026, 7, 6),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=None,
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="000002",
                    trade_date=date(2026, 7, 6),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=None,
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="000003",
                    trade_date=date(2026, 7, 6),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="000001",
                    trade_date=date(2026, 7, 7),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("11"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=Decimal("2000"),
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
            ]
        )
        db.commit()

        summary = load_market_summary_for_report_date(db, "2026-07-07")

    assert summary["amount_change_pct"] is None
    assert summary["amount_change_note"] == "前一交易日成交额覆盖不足，暂不计算成交额变化。"


def test_load_market_summary_excludes_prefixed_index_rows_from_stock_breadth() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add(
            Security(
                symbol="000001",
                name="样本股",
                exchange="SZ",
                is_active=True,
                is_st=False,
            )
        )
        db.add_all(
            [
                DailyBar(
                    symbol="000001",
                    trade_date=date(2026, 7, 7),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("11"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="sh000001",
                    trade_date=date(2026, 7, 7),
                    open=Decimal("3400"),
                    high=Decimal("3420"),
                    low=Decimal("3360"),
                    close=Decimal("3380"),
                    pre_close=Decimal("3400"),
                    volume=Decimal("100"),
                    amount=Decimal("999999"),
                    turnover_rate=None,
                    limit_up=Decimal("3740"),
                    limit_down=Decimal("3060"),
                    is_suspended=False,
                ),
            ]
        )
        db.commit()

        summary = load_market_summary_for_report_date(db, "2026-07-07")

    assert summary["stock_count"] == 1
    assert summary["up_count"] == 1
    assert summary["down_count"] == 0
    assert summary["total_amount"] == 1000


def test_load_market_indexes_uses_prefixed_index_symbols_not_stock_code_collision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add_all(
            [
                DailyBar(
                    symbol="000001",
                    trade_date=date(2026, 7, 7),
                    open=Decimal("12"),
                    high=Decimal("12"),
                    low=Decimal("11"),
                    close=Decimal("11.5"),
                    pre_close=Decimal("12"),
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    limit_up=Decimal("13.2"),
                    limit_down=Decimal("10.8"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="sh000001",
                    trade_date=date(2026, 7, 7),
                    open=Decimal("3400"),
                    high=Decimal("3420"),
                    low=Decimal("3360"),
                    close=Decimal("3380"),
                    pre_close=Decimal("3400"),
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    limit_up=Decimal("3740"),
                    limit_down=Decimal("3060"),
                    is_suspended=False,
                ),
            ]
        )
        db.commit()

        indexes = load_market_indexes_for_report_date(db, "2026-07-07")

    sh_index = indexes[0]
    assert sh_index["symbol"] == "sh000001"
    assert sh_index["name"] == "上证指数"
    assert sh_index["close"] == 3380.0
    assert sh_index["change_pct"] == -0.005882


def test_load_market_cross_section_attaches_sector_moneyflow() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        sectors = {
            "消费电子": [("002101", "11"), ("002102", "10.8"), ("002103", "10.6")],
            "半导体": [("603101", "9.5"), ("603102", "9.7"), ("603103", "9.9")],
        }
        for sector, rows in sectors.items():
            for symbol, close in rows:
                db.add(
                    Security(
                        symbol=symbol,
                        name=f"样本{symbol}",
                        exchange="SZ",
                        industry=sector,
                        is_active=True,
                        is_st=False,
                    )
                )
                db.add(
                    DailyBar(
                        symbol=symbol,
                        trade_date=date(2026, 7, 7),
                        open=Decimal("10"),
                        high=Decimal("11"),
                        low=Decimal("9"),
                        close=Decimal(close),
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
            TushareMoneyflowIndDc(
                trade_date=date(2026, 7, 7),
                content_type="行业",
                ts_code="BK0429",
                name="消费电子",
                pct_change=Decimal("3.2"),
                close=Decimal("1234"),
                net_amount=Decimal("123456789"),
                net_amount_rate=Decimal("4.2"),
            )
        )
        db.commit()

        cross_section = load_market_cross_section_for_report_date(db, "2026-07-07")

    strong = cross_section["strong_sectors"][0]
    assert strong["sector"] == "消费电子"
    assert strong["fund_flow_net_amount"] == 123456789.0
    assert strong["fund_flow_rate"] == 4.2
    assert strong["fund_flow_trade_date"] == "2026-07-07"
    assert strong["fund_flow_stale"] is False
    assert cross_section["sector_moneyflow_trade_date"] == "2026-07-07"
    assert cross_section["sector_moneyflow_stale"] is False
    assert cross_section["sector_moneyflow_total_count"] == 2
    assert cross_section["sector_moneyflow_matched_count"] == 1
    assert cross_section["sector_moneyflow_missing_count"] == 1
    assert cross_section["sector_moneyflow_coverage_ratio"] == 0.5


def test_load_market_cross_section_marks_stale_sector_moneyflow() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add(
            Security(
                symbol="002101",
                name="样本",
                exchange="SZ",
                industry="消费电子",
                is_active=True,
                is_st=False,
            )
        )
        db.add(
            DailyBar(
                symbol="002101",
                trade_date=date(2026, 7, 7),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("11"),
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
            TushareMoneyflowIndDc(
                trade_date=date(2026, 7, 6),
                content_type="行业",
                ts_code="BK0429",
                name="消费电子",
                pct_change=Decimal("3.2"),
                close=Decimal("1234"),
                net_amount=Decimal("80000000"),
                net_amount_rate=Decimal("2.1"),
            )
        )
        db.commit()

        cross_section = load_market_cross_section_for_report_date(
            db,
            "2026-07-07",
            min_sector_count=1,
        )

    strong = cross_section["strong_sectors"][0]
    assert strong["fund_flow_trade_date"] == "2026-07-06"
    assert strong["fund_flow_stale"] is True
    assert cross_section["sector_moneyflow_trade_date"] == "2026-07-06"
    assert cross_section["sector_moneyflow_stale"] is True
    assert cross_section["sector_moneyflow_total_count"] == 1
    assert cross_section["sector_moneyflow_matched_count"] == 1
    assert cross_section["sector_moneyflow_coverage_ratio"] == 1.0


def test_load_market_cross_section_matches_sector_moneyflow_alias() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add(
            Security(
                symbol="002103",
                name="样本",
                exchange="SZ",
                industry="元器件",
                is_active=True,
                is_st=False,
            )
        )
        db.add(
            DailyBar(
                symbol="002103",
                trade_date=date(2026, 7, 7),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("11"),
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
            TushareMoneyflowIndDc(
                trade_date=date(2026, 7, 7),
                content_type="行业",
                ts_code="BK0610",
                name="元件",
                pct_change=Decimal("3.2"),
                close=Decimal("1234"),
                net_amount=Decimal("90000000"),
                net_amount_rate=Decimal("3.5"),
            )
        )
        db.commit()

        cross_section = load_market_cross_section_for_report_date(
            db,
            "2026-07-07",
            min_sector_count=1,
        )

    strong = cross_section["strong_sectors"][0]
    assert strong["sector"] == "元器件"
    assert strong["fund_flow_net_amount"] == 90000000.0
    assert strong["fund_flow_rate"] == 3.5
    assert cross_section["sector_moneyflow_missing_count"] == 0


def test_load_market_cross_section_aggregates_mapped_sector_moneyflow() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add(
            Security(
                symbol="688101",
                name="样本",
                exchange="SH",
                industry="半导体",
                is_active=True,
                is_st=False,
            )
        )
        db.add(
            DailyBar(
                symbol="688101",
                trade_date=date(2026, 7, 7),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("11"),
                pre_close=Decimal("10"),
                volume=Decimal("100"),
                amount=Decimal("1000"),
                turnover_rate=None,
                limit_up=Decimal("11"),
                limit_down=Decimal("9"),
                is_suspended=False,
            )
        )
        db.add_all(
            [
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 7, 7),
                    content_type="行业",
                    ts_code="BK1001",
                    name="半导体设备",
                    pct_change=Decimal("3.2"),
                    close=Decimal("1234"),
                    net_amount=Decimal("100000000"),
                    net_amount_rate=Decimal("4.5"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 7, 7),
                    content_type="行业",
                    ts_code="BK1002",
                    name="集成电路设计",
                    pct_change=Decimal("-1.2"),
                    close=Decimal("1200"),
                    net_amount=Decimal("-25000000"),
                    net_amount_rate=Decimal("-1.1"),
                ),
            ]
        )
        db.commit()

        cross_section = load_market_cross_section_for_report_date(
            db,
            "2026-07-07",
            min_sector_count=1,
        )

    strong = cross_section["strong_sectors"][0]
    assert strong["sector"] == "半导体"
    assert strong["fund_flow_net_amount"] == 75000000.0
    assert strong["fund_flow_rate"] is None
    assert strong["fund_flow_source_count"] == 2


def test_load_market_cross_section_prefers_exact_sector_moneyflow_over_alias_sum() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        db.add(
            Security(
                symbol="688101",
                name="样本",
                exchange="SH",
                industry="半导体",
                is_active=True,
                is_st=False,
            )
        )
        db.add(
            DailyBar(
                symbol="688101",
                trade_date=date(2026, 7, 7),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("11"),
                pre_close=Decimal("10"),
                volume=Decimal("100"),
                amount=Decimal("1000"),
                turnover_rate=None,
                limit_up=Decimal("11"),
                limit_down=Decimal("9"),
                is_suspended=False,
            )
        )
        db.add_all(
            [
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 7, 7),
                    content_type="行业",
                    ts_code="BK0001",
                    name="半导体",
                    pct_change=Decimal("1.2"),
                    close=Decimal("1234"),
                    net_amount=Decimal("30000000"),
                    net_amount_rate=Decimal("0.6"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 7, 7),
                    content_type="行业",
                    ts_code="BK1001",
                    name="半导体设备",
                    pct_change=Decimal("3.2"),
                    close=Decimal("1234"),
                    net_amount=Decimal("100000000"),
                    net_amount_rate=Decimal("4.5"),
                ),
            ]
        )
        db.commit()

        cross_section = load_market_cross_section_for_report_date(
            db,
            "2026-07-07",
            min_sector_count=1,
        )

    strong = cross_section["strong_sectors"][0]
    assert strong["sector"] == "半导体"
    assert strong["fund_flow_net_amount"] == 30000000.0
    assert strong["fund_flow_rate"] == 0.6
    assert strong["fund_flow_source_count"] == 1
    assert strong["fund_flow_source_names"] == ["半导体"]


def test_insert_review_report_updates_same_day_type_without_duplicates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    with session() as db:
        assert (
            insert_review_report(
                db,
                "2026-06-24",
                "daily_mechanical",
                "old content",
                {"candidate_count": 3},
            )
            == 1
        )
        db.commit()

        assert (
            insert_review_report(
                db,
                "2026-06-24",
                "daily_mechanical",
                "new content",
                {"candidate_count": 5},
            )
            == 1
        )
        db.commit()

        rows = db.query(ReviewReport).all()
        latest = load_latest_review_report(db, "daily_mechanical")

    assert len(rows) == 1
    assert latest is not None
    assert latest.content_md == "new content"
    assert latest.metrics_json["candidate_count"] == 5


def test_upsert_parameter_recommendations_updates_pending_without_duplicates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    suggestion = {
        "target_type": "rule_condition",
        "target_name": "banking_compound_valuation",
        "action": "test_tighten",
        "rationale": "old",
        "priority": "medium",
        "scope_type": "rule",
        "scope_value": "R004",
        "current": {"pb_max": 1.0},
        "proposed": {"candidate_pb_max": 0.8},
        "guardrails": ["只作为候选参数，不自动应用"],
    }

    with session() as db:
        assert upsert_parameter_recommendations(db, "2026-06-23", [suggestion]) == 1
        db.commit()

        suggestion["rationale"] = "new"
        suggestion["priority"] = "high"
        assert upsert_parameter_recommendations(db, "2026-06-23", [suggestion]) == 1
        db.commit()

        rows = db.query(ParameterRecommendation).all()

    assert len(rows) == 1
    assert rows[0].rationale == "new"
    assert rows[0].priority == "high"
    assert rows[0].status == "pending"
    assert rows[0].guardrails_json["items"] == ["只作为候选参数，不自动应用"]


def test_upsert_parameter_recommendations_keeps_sources_separate() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    suggestion = {
        "target_type": "entry_filter",
        "target_name": "scope_quality",
        "action": "reduce_priority_or_require_confirmation",
        "rationale": "same target, different source",
        "priority": "medium",
        "scope_type": "symbol",
        "scope_value": "000001",
        "current": {},
        "proposed": {"priority_score_delta": -2},
        "guardrails": [],
    }

    with session() as db:
        assert (
            upsert_parameter_recommendations(
                db,
                "2026-06-23",
                [suggestion],
                source_report_type="paper_learning_review",
            )
            == 1
        )
        assert (
            upsert_parameter_recommendations(
                db,
                "2026-06-23",
                [suggestion],
                source_report_type="backtest_learning_review",
            )
            == 1
        )
        db.commit()

        rows = db.query(ParameterRecommendation).order_by(ParameterRecommendation.id).all()

    assert len(rows) == 2
    assert {row.source_report_type for row in rows} == {
        "paper_learning_review",
        "backtest_learning_review",
    }


def test_upsert_parameter_recommendations_isolated_by_source_report_type() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    suggestion = {
        "target_type": "entry_filter",
        "target_name": "cross_source_scope",
        "action": "reduce_priority_or_require_confirmation",
        "rationale": "paper source",
        "priority": "low",
        "scope_type": "symbol",
        "scope_value": "000001",
        "current": {"scope_quality": 1},
        "proposed": {"priority_score_delta": -2},
        "guardrails": ["paper only"],
    }

    with session() as db:
        assert (
            upsert_parameter_recommendations(
                db,
                "2026-06-23",
                [suggestion],
                source_report_type="paper_learning_review",
            )
            == 1
        )
        suggestion["rationale"] = "backtest source"
        suggestion["priority"] = "high"
        suggestion["guardrails"] = ["backtest only"]
        assert (
            upsert_parameter_recommendations(
                db,
                "2026-06-23",
                [suggestion],
                source_report_type="backtest_learning_review",
            )
            == 1
        )
        suggestion["rationale"] = "backtest source updated"
        assert (
            upsert_parameter_recommendations(
                db,
                "2026-06-23",
                [suggestion],
                source_report_type="backtest_learning_review",
            )
            == 1
        )
        db.commit()

        rows = db.query(ParameterRecommendation).order_by(ParameterRecommendation.id).all()

    assert len(rows) == 2
    backtest_row = [row for row in rows if row.source_report_type == "backtest_learning_review"][0]
    assert backtest_row.rationale == "backtest source updated"
    assert backtest_row.priority == "high"
    assert backtest_row.guardrails_json["items"] == ["backtest only"]


def test_upsert_parameter_recommendations_keeps_source_rule_ids_separate() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    suggestion = {
        "target_type": "entry_filter",
        "target_name": "backtest_scope_quality",
        "action": "reduce_priority_or_require_confirmation",
        "rationale": "same sector, different rule",
        "priority": "medium",
        "scope_type": "sector",
        "scope_value": "通信设备",
        "current": {},
        "proposed": {"priority_score_delta": -2, "source_rule_id": "R007"},
        "guardrails": [],
    }

    with session() as db:
        assert (
            upsert_parameter_recommendations(
                db,
                "2026-06-23",
                [suggestion],
                source_report_type="backtest_learning_review",
            )
            == 1
        )
        suggestion["proposed"] = {"priority_score_delta": -1, "source_rule_id": "R002"}
        assert (
            upsert_parameter_recommendations(
                db,
                "2026-06-23",
                [suggestion],
                source_report_type="backtest_learning_review",
            )
            == 1
        )
        db.commit()

        rows = db.query(ParameterRecommendation).order_by(ParameterRecommendation.rule_id).all()

    assert len(rows) == 2
    assert [row.rule_id for row in rows] == ["R002", "R007"]


def test_upsert_parameter_recommendations_does_not_overwrite_decided_items() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)

    suggestion = {
        "target_type": "risk_profile",
        "target_name": "position_sizing",
        "action": "test_reduce",
        "rationale": "system suggestion",
        "priority": "high",
        "scope_type": "rule",
        "scope_value": "R001",
        "current": {},
        "proposed": {"max_position_pct_multiplier": 0.8},
        "guardrails": [],
    }

    with session() as db:
        assert upsert_parameter_recommendations(db, "2026-06-23", [suggestion]) == 1
        db.commit()

        row = db.query(ParameterRecommendation).one()
        row.status = "approved"
        row.decision_reason = "manual decision"
        db.commit()

        suggestion["rationale"] = "new system suggestion"
        suggestion["priority"] = "medium"
        assert upsert_parameter_recommendations(db, "2026-06-23", [suggestion]) == 0
        db.commit()

        row = db.query(ParameterRecommendation).one()

    assert row.status == "approved"
    assert row.rationale == "system suggestion"
    assert row.priority == "high"
    assert row.decision_reason == "manual decision"
