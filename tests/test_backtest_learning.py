from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.backtest.learning import persist_backtest_learning_report
from services.shared.database import Base
from services.shared.models import (
    BacktestTradeRecord,
    ParameterRecommendation,
    ReviewReport,
    Security,
)


def _trade(symbol: str, signal_day: int, pnl: str, mfe: str = "0.08") -> BacktestTradeRecord:
    return BacktestTradeRecord(
        run_date=date(2026, 6, 24),
        rule_id="R007",
        symbol=symbol,
        signal_date=date(2026, 1, signal_day),
        entry_date=date(2026, 1, signal_day + 1),
        entry_price=Decimal("10"),
        exit_date=date(2026, 1, signal_day + 5),
        exit_price=Decimal("9.5"),
        holding_days=5,
        pnl_pct=Decimal(pnl),
        mfe_pct=Decimal(mfe),
        mae_pct=Decimal("-0.06"),
        exit_reason="stop_loss",
    )


def _trade_on_dates(
    symbol: str,
    signal_date: date,
    pnl: str,
    *,
    mfe: str = "0.08",
    exit_offset_days: int = 5,
) -> BacktestTradeRecord:
    return BacktestTradeRecord(
        run_date=date(2026, 6, 24),
        rule_id="R007",
        symbol=symbol,
        signal_date=signal_date,
        entry_date=signal_date + timedelta(days=1),
        entry_price=Decimal("10"),
        exit_date=signal_date + timedelta(days=exit_offset_days),
        exit_price=Decimal("9.5"),
        holding_days=5,
        pnl_pct=Decimal(pnl),
        mfe_pct=Decimal(mfe),
        mae_pct=Decimal("-0.06"),
        exit_reason="stop_loss",
    )


def _add_sector_securities(db, industry: str = "半导体") -> None:
    db.add_all(
        [
            Security(
                symbol="603986",
                name="兆易创新",
                exchange="SH",
                list_date=None,
                industry=industry,
                is_active=True,
            ),
            Security(
                symbol="002371",
                name="北方华创",
                exchange="SZ",
                list_date=None,
                industry=industry,
                is_active=True,
            ),
            Security(
                symbol="300750",
                name="宁德时代",
                exchange="SZ",
                list_date=None,
                industry=industry,
                is_active=True,
            ),
            Security(
                symbol="002475",
                name="立讯精密",
                exchange="SZ",
                list_date=None,
                industry=industry,
                is_active=True,
            ),
        ]
    )


def _sector_insight(report: ReviewReport, scope_value: str = "半导体") -> dict:
    return next(
        item
        for item in report.metrics_json["insights"]
        if item["scope_type"] == "sector" and item["scope_value"] == scope_value
    )


def test_backtest_learning_generates_scope_adjustments() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol="603083",
                    name="剑桥科技",
                    exchange="SH",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="600000",
                    name="浦发银行",
                    exchange="SH",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="002837",
                    name="英维克",
                    exchange="SZ",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
            ]
        )
        db.add_all(
            [
                _trade("603083", 1, "-0.08"),
                _trade("603083", 2, "-0.06"),
                _trade("603083", 3, "-0.04"),
                _trade("603083", 4, "-0.03"),
                _trade("603083", 5, "-0.02"),
            ]
        )
        changed = persist_backtest_learning_report(db, "2026-06-24")
        db.commit()

        reports = db.query(ReviewReport).all()
        recommendations = (
            db.query(ParameterRecommendation)
            .order_by(ParameterRecommendation.id)
            .all()
        )

    assert changed >= 1
    assert reports[0].report_type == "backtest_learning_review"
    assert "盈亏因子" in reports[0].content_md
    assert reports[0].metrics_json["insights"][0]["evidence_quality"] == "concentrated"
    assert reports[0].metrics_json["insights"][0]["profit_factor"] >= 0
    assert recommendations[0].source_report_type == "backtest_learning_review"
    assert recommendations[0].target_name == "backtest_scope_quality"
    assert recommendations[0].proposed_json["require_extra_confirmation"] is True


def test_backtest_learning_blocks_positive_when_samples_are_concentrated() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol="603083",
                    name="剑桥科技",
                    exchange="SH",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="600000",
                    name="浦发银行",
                    exchange="SH",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="002837",
                    name="英维克",
                    exchange="SZ",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
            ]
        )
        db.add_all(
            [
                _trade("603083", 1, "0.03"),
                _trade("603083", 2, "0.04"),
                _trade("603083", 3, "0.05"),
                _trade("603083", 4, "0.02"),
                _trade("603083", 5, "0.03"),
                _trade("603083", 6, "0.04"),
                _trade("603083", 7, "0.05"),
                _trade("603083", 8, "0.03"),
                _trade("603083", 9, "0.02"),
                _trade("603083", 10, "0.04"),
            ]
        )
        persist_backtest_learning_report(db, "2026-06-24")
        db.commit()

        recommendations = (
            db.query(ParameterRecommendation)
            .filter(ParameterRecommendation.source_report_type == "backtest_learning_review")
            .all()
        )
        report = db.query(ReviewReport).one()

    assert report.metrics_json["insights"][0]["evidence_quality"] == "concentrated"
    assert report.metrics_json["insights"][0]["positive_learning_allowed"] is False
    assert not any(item.target_name == "backtest_scope_fit" for item in recommendations)
    assert not any(item.target_name == "learned_long_horizon_hold" for item in recommendations)


def test_backtest_learning_can_promote_when_evidence_is_broad() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol="603083",
                    name="剑桥科技",
                    exchange="SH",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="600000",
                    name="浦发银行",
                    exchange="SH",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="002837",
                    name="英维克",
                    exchange="SZ",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
            ]
        )
        db.add_all(
            [
                _trade_on_dates("603083", date(2026, 1, 6), "0.05", mfe="0.14"),
                _trade_on_dates("600000", date(2026, 1, 14), "0.04", mfe="0.13"),
                _trade_on_dates("002837", date(2026, 2, 3), "0.03", mfe="0.12"),
                _trade_on_dates("603083", date(2026, 3, 5), "0.02", mfe="0.11"),
                _trade_on_dates("600000", date(2026, 4, 8), "0.05", mfe="0.15"),
                _trade_on_dates("002837", date(2026, 4, 28), "0.04", mfe="0.14"),
                _trade_on_dates("603083", date(2026, 5, 9), "0.03", mfe="0.13"),
                _trade_on_dates("600000", date(2026, 5, 21), "0.04", mfe="0.14"),
                _trade_on_dates("002837", date(2026, 6, 9), "0.02", mfe="0.11"),
                _trade_on_dates("603083", date(2026, 6, 20), "-0.004", mfe="0.08"),
            ]
        )
        changed = persist_backtest_learning_report(db, "2026-06-24")
        db.commit()

        recommendations = db.query(ParameterRecommendation).all()
        report = db.query(ReviewReport).one()

    assert changed >= 1
    assert recommendations
    assert any(
        item.target_name == "backtest_scope_fit"
        and item.proposed_json["priority_score_delta"] == 1
        for item in recommendations
    )
    assert any(
        item.target_name == "learned_long_horizon_hold"
        and item.proposed_json["max_holding_days_multiplier"] == 1.5
        for item in recommendations
    )
    assert report.metrics_json["insights"][0]["evidence_quality"] == "broad"
    assert report.metrics_json["insights"][0]["positive_learning_allowed"] is True


def test_backtest_learning_ranks_stable_positive_candidates_first() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol="603083",
                    name="剑桥科技",
                    exchange="SH",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="600000",
                    name="浦发银行",
                    exchange="SH",
                    list_date=None,
                    industry="通信设备",
                    is_active=True,
                ),
            ]
        )
        db.add_all(
            [
                _trade_on_dates("603083", date(2026, 1, 6), "0.08", mfe="0.16"),
                _trade_on_dates("600000", date(2026, 2, 14), "0.07", mfe="0.15"),
                _trade_on_dates("603083", date(2026, 3, 5), "0.06", mfe="0.14"),
                _trade_on_dates("600000", date(2026, 4, 8), "0.05", mfe="0.13"),
                _trade_on_dates("603083", date(2026, 5, 9), "0.04", mfe="0.12"),
                _trade_on_dates("600000", date(2026, 6, 20), "-0.01", mfe="0.08"),
            ]
        )
        persist_backtest_learning_report(db, "2026-06-24")
        db.commit()

        report = db.query(ReviewReport).one()

    assert "稳健" in report.content_md
    assert "其余样本" not in report.content_md
    assert report.metrics_json["insights"][0]["max_drawdown"] <= 0
    assert report.metrics_json["insights"][0]["return_stability"] >= 0


def test_backtest_learning_blocks_positive_when_validation_fails() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_sector_securities(db)
        db.add_all(
            [
                _trade_on_dates("603986", date(2026, 1, 5), "0.05", mfe="0.12"),
                _trade_on_dates("002371", date(2026, 1, 20), "0.04", mfe="0.11"),
                _trade_on_dates("300750", date(2026, 2, 12), "0.03", mfe="0.10"),
                _trade_on_dates("002475", date(2026, 3, 8), "0.035", mfe="0.11"),
                _trade_on_dates("603986", date(2026, 4, 2), "0.045", mfe="0.13"),
                _trade_on_dates("002371", date(2026, 4, 20), "0.03", mfe="0.10"),
                _trade_on_dates("300750", date(2026, 5, 8), "0.04", mfe="0.12"),
                _trade_on_dates("002475", date(2026, 5, 25), "0.03", mfe="0.10"),
                _trade_on_dates("603986", date(2026, 6, 5), "-0.02", mfe="0.04"),
                _trade_on_dates("002371", date(2026, 6, 12), "-0.025", mfe="0.03"),
                _trade_on_dates("300750", date(2026, 6, 18), "-0.015", mfe="0.04"),
                _trade_on_dates("002475", date(2026, 6, 22), "-0.02", mfe="0.03"),
            ]
        )
        persist_backtest_learning_report(db, "2026-06-24")
        db.commit()

        recommendations = db.query(ParameterRecommendation).all()
        report = db.query(ReviewReport).one()

    insight = _sector_insight(report)
    target_names = {item.target_name for item in recommendations}

    assert insight["out_of_sample_status"] == "failed"
    assert insight["train_sample_count"] == 8
    assert insight["validation_sample_count"] == 4
    assert insight["train_avg_return"] > 0
    assert insight["validation_avg_return"] < 0
    assert insight["out_of_sample_passed"] is False
    assert insight["positive_learning_allowed"] is False
    assert "backtest_scope_fit" not in target_names
    assert "learned_long_horizon_hold" not in target_names
    assert "样本外" in report.content_md or "验证" in report.content_md


def test_backtest_learning_allows_positive_when_train_and_validation_pass() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_sector_securities(db)
        db.add_all(
            [
                _trade_on_dates("603986", date(2026, 1, 5), "0.05", mfe="0.14"),
                _trade_on_dates("002371", date(2026, 1, 20), "0.04", mfe="0.13"),
                _trade_on_dates("300750", date(2026, 2, 12), "0.03", mfe="0.12"),
                _trade_on_dates("002475", date(2026, 3, 8), "0.035", mfe="0.12"),
                _trade_on_dates("603986", date(2026, 4, 2), "0.045", mfe="0.14"),
                _trade_on_dates("002371", date(2026, 4, 20), "0.03", mfe="0.12"),
                _trade_on_dates("300750", date(2026, 5, 8), "0.04", mfe="0.13"),
                _trade_on_dates("002475", date(2026, 5, 25), "0.03", mfe="0.12"),
                _trade_on_dates("603986", date(2026, 6, 5), "0.04", mfe="0.13"),
                _trade_on_dates("002371", date(2026, 6, 12), "0.035", mfe="0.12"),
                _trade_on_dates("300750", date(2026, 6, 18), "0.03", mfe="0.11"),
                _trade_on_dates("002475", date(2026, 6, 22), "-0.005", mfe="0.08"),
            ]
        )
        persist_backtest_learning_report(db, "2026-06-24")
        db.commit()

        recommendations = db.query(ParameterRecommendation).all()
        report = db.query(ReviewReport).one()

    insight = _sector_insight(report)
    target_names = {item.target_name for item in recommendations}

    assert insight["out_of_sample_status"] == "passed"
    assert insight["out_of_sample_passed"] is True
    assert insight["positive_learning_allowed"] is True
    assert insight["train_avg_return"] > 0
    assert insight["validation_avg_return"] > 0
    assert "backtest_scope_fit" in target_names
    assert "learned_long_horizon_hold" in target_names
