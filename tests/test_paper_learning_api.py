from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.main import create_app
from apps.api.app.routers.paper_learning import (
    get_learning_overview,
    get_mechanical_review,
    get_monthly_summary,
    list_trade_reviews,
)
from services.shared.database import Base
from services.shared.models import PaperTradeReview, ReviewReport


def _session_with_reviews():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session()
    for index in range(3):
        db.add(
            PaperTradeReview(
                position_id=index + 1,
                account_id=1,
                trade_plan_id=None,
                symbol="000001",
                rule_id="R001",
                sector_code="银行",
                strategy_type="short_term",
                entry_date=date(2026, 1, 2),
                exit_date=date(2026, 1, 5),
                holding_days=4,
                pnl_pct=Decimal("0.010000"),
                mfe_pct=Decimal("0.080000"),
                mae_pct=Decimal("-0.020000"),
                giveback_pct=Decimal("0.060000"),
                exit_reason="trailing_take_profit",
                signal_tags_json={"items": ["trend_alignment"]},
                alert_summary_json={"total": 1},
                evidence_json={},
                verdict="profit_giveback",
                summary="sample",
            )
        )
    db.commit()
    return db


def test_paper_learning_routes_are_registered() -> None:
    schema = create_app().openapi()

    assert "/paper-learning/overview" in schema["paths"]
    assert "/paper-learning/reviews" in schema["paths"]
    assert "/paper-learning/mechanical-review" in schema["paths"]
    assert "/paper-learning/monthly-summary" in schema["paths"]


def test_get_learning_overview_returns_insights_and_reviews() -> None:
    db = _session_with_reviews()

    payload = get_learning_overview(db=db, report_date="2026-01-10")

    assert payload.latest_review_date == "2026-01-10"
    assert payload.insights
    assert payload.insights[0].sample_count >= 3
    assert payload.recent_reviews[0].symbol == "000001"
    db.close()


def test_list_trade_reviews_filters_symbol() -> None:
    db = _session_with_reviews()

    payload = list_trade_reviews(db=db, symbol="000001")

    assert len(payload) == 3
    assert payload[0].signal_tags == ["trend_alignment"]
    db.close()


def test_get_mechanical_review_returns_latest_report() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(
            ReviewReport(
                report_date=date(2026, 1, 10),
                report_type="daily_mechanical",
                scope="market",
                generator="mechanical",
                content_md="# 每日机械复盘\n\n## 昨日候选今日回看\n\n- 000001 表现稳定",
                metrics_json={"trade_plan_count": 1},
            )
        )
        db.commit()

        payload = get_mechanical_review(db=db)

    assert payload.found is True
    assert payload.report_date == "2026-01-10"
    assert "000001" in payload.content_md


def test_get_mechanical_review_backfills_market_summary_from_legacy_content() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(
            ReviewReport(
                report_date=date(2026, 7, 8),
                report_type="daily_mechanical",
                scope="market",
                generator="mechanical",
                content_md=(
                    "# 收盘总体复盘\n\n"
                    "- 请求日期 2026-07-08 / 数据日期 2026-07-07（已过期）\n"
                    "- 上涨 693 / 下跌 4797 / 平盘 27，上涨占比 12.56%，"
                    "平均涨跌 -2.63%，成交额 25984.7亿\n"
                    "- 较前日成交额 -16.51%\n"
                ),
                metrics_json={"data_health": {"status": "ok"}},
            )
        )
        db.commit()

        payload = get_mechanical_review(db=db)

    assert payload.metrics["market_summary"]["trade_date"] == "2026-07-07"
    assert payload.metrics["market_summary"]["up_count"] == 693
    assert payload.metrics["market_summary"]["down_count"] == 4797
    assert payload.metrics["market_summary"]["flat_count"] == 27
    assert payload.metrics["market_summary"]["up_ratio"] == 0.1256
    assert payload.metrics["market_summary"]["avg_change_pct"] == -0.0263
    assert payload.metrics["market_summary"]["total_amount"] == 2598470000000.0
    assert payload.metrics["market_summary"]["amount_change_pct"] == -0.1651


def test_get_monthly_summary_returns_web_only_payload(monkeypatch) -> None:
    class _Summary:
        month = "2026-06"
        paper_review_count = 3
        backtest_trade_count = 9
        winning_reviews = 2
        losing_reviews = 1
        total_pnl = 0.12
        avg_review_return = 0.04
        avg_backtest_return = 0.03
        top_symbols = [{"symbol": "600360", "name": "华微电子", "return": 0.08}]
        top_rules = [{"rule_id": "R007", "avg_return": 0.05}]
        factor_insights = [{"factor_name": "价量趋势", "avg_return": 0.051}]
        sector_opportunities = [{"sector": "半导体", "avg_return": 0.12}]
        excluded_symbols = ["000001"]
        content_md = "# 2026-06 交易总结"

    monkeypatch.setattr(
        "apps.api.app.routers.paper_learning.generate_monthly_trade_summary",
        lambda month: _Summary(),
    )

    payload = get_monthly_summary(month="2026-06")

    assert payload.month == "2026-06"
    assert payload.paper_review_count == 3
    assert payload.backtest_trade_count == 9
    assert payload.total_pnl == 0.12
    assert payload.factor_insights[0]["factor_name"] == "价量趋势"
    assert payload.content_md.startswith("# 2026-06")


def test_get_monthly_summary_allows_missing_average_returns(monkeypatch) -> None:
    class _Summary:
        month = "2026-06"
        paper_review_count = 0
        backtest_trade_count = 0
        winning_reviews = 0
        losing_reviews = 0
        total_pnl = 0.0
        avg_review_return = None
        avg_backtest_return = None
        top_symbols = []
        top_rules = []
        factor_insights = []
        sector_opportunities = []
        excluded_symbols = ["000001"]
        content_md = "# 2026-06 交易总结"

    monkeypatch.setattr(
        "apps.api.app.routers.paper_learning.generate_monthly_trade_summary",
        lambda month: _Summary(),
    )

    payload = get_monthly_summary(month="2026-06")

    assert payload.avg_review_return is None
    assert payload.avg_backtest_return is None
