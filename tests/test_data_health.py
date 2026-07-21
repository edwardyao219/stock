from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.features.health import (
    assess_trade_data_evidence_risk,
    inspect_daily_data_health,
    inspect_tushare_evidence_health,
)
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    MarketRegimeDaily,
    Security,
    StockFeatureDaily,
    TushareCyqPerf,
    TushareLimitListD,
    TushareMoneyflow,
    TushareMoneyflowDc,
)


def _daily_bar(
    symbol: str,
    trade_date: date,
    *,
    close: str = "10",
    volume: str = "100000000",
    amount: str | None = None,
) -> DailyBar:
    close_value = Decimal(close)
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=close_value,
        high=close_value,
        low=close_value,
        close=close_value,
        pre_close=close_value,
        volume=Decimal(volume),
        amount=Decimal(amount) if amount is not None else None,
        turnover_rate=None,
        limit_up=close_value * Decimal("1.1"),
        limit_down=close_value * Decimal("0.9"),
        is_suspended=False,
    )


def test_inspect_tushare_evidence_health_reports_exact_date_coverage() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    trade_date = date(2026, 7, 10)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol=f"{index:06d}",
                    name=f"样本{index}",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                )
                for index in range(100)
            ]
        )
        db.add_all(
            [_daily_bar(f"{index:06d}", trade_date, amount="1000000000") for index in range(100)]
        )
        db.add_all(
            [
                TushareMoneyflow(ts_code=f"{index:06d}.SZ", trade_date=trade_date)
                for index in range(95)
            ]
        )
        db.add_all(
            [
                TushareMoneyflowDc(ts_code=f"{index:06d}.SZ", trade_date=trade_date)
                for index in range(90)
            ]
        )
        db.add_all(
            [
                TushareCyqPerf(ts_code=f"{index:06d}.SZ", trade_date=trade_date)
                for index in range(80)
            ]
        )
        db.add_all(
            [
                TushareLimitListD(ts_code=f"{index:06d}.SZ", trade_date=trade_date)
                for index in range(7)
            ]
        )
        db.commit()

        health = inspect_tushare_evidence_health(db, trade_date)

    assert health == {
        "trade_date": "2026-07-10",
        "daily_symbol_count": 100,
        "datasets": [
            {
                "name": "moneyflow",
                "rows": 95,
                "matched_rows": 95,
                "coverage_ratio": 0.95,
                "status": "partial",
            },
            {
                "name": "moneyflow_dc",
                "rows": 90,
                "matched_rows": 90,
                "coverage_ratio": 0.9,
                "status": "partial",
            },
            {
                "name": "cyq_perf",
                "rows": 80,
                "matched_rows": 80,
                "coverage_ratio": 0.8,
                "status": "partial",
            },
            {
                "name": "limit_list_d",
                "rows": 7,
                "matched_rows": 7,
                "coverage_ratio": None,
                "status": "ok",
            },
        ],
    }


def test_inspect_tushare_evidence_health_accepts_empty_limit_events_after_sync() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(bind=engine)() as db:
        health = inspect_tushare_evidence_health(
            db,
            date(2026, 7, 10),
            sync_statuses={"limit_list_d": "ok"},
        )

    assert health["datasets"][-1]["status"] == "ok"


def test_assess_trade_data_evidence_risk_blocks_missing_tail_and_partial_tushare() -> None:
    risk = assess_trade_data_evidence_risk(
        {
            "datasets": [
                {"name": "moneyflow", "status": "ok"},
                {"name": "cyq_perf", "status": "partial"},
            ]
        },
        {"status": "missing", "message": "缺少尾盘市场快照"},
    )

    assert risk == {
        "status": "blocked",
        "reasons": ["尾盘行情：缺少尾盘市场快照", "筹码分布：数据覆盖不完整"],
        "tushare_statuses": {"moneyflow": "ok", "cyq_perf": "partial"},
        "late_market_status": "missing",
    }


def test_inspect_tushare_evidence_health_scopes_stock_moneyflow_to_hu_shen() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    trade_date = date(2026, 7, 10)

    with sessionmaker(bind=engine)() as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="深市样本",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
                Security(
                    symbol="600001",
                    name="沪市样本",
                    exchange="SH",
                    is_active=True,
                    is_st=False,
                ),
                Security(
                    symbol="920001",
                    name="北交样本",
                    exchange="BJ",
                    is_active=True,
                    is_st=False,
                ),
                _daily_bar("000001", trade_date, amount="1000000000"),
                _daily_bar("600001", trade_date, amount="1000000000"),
                _daily_bar("920001", trade_date, amount="1000000000"),
                TushareMoneyflow(ts_code="000001.SZ", trade_date=trade_date),
                TushareMoneyflow(ts_code="600001.SH", trade_date=trade_date),
                TushareMoneyflowDc(ts_code="000001.SZ", trade_date=trade_date),
                TushareMoneyflowDc(ts_code="600001.SH", trade_date=trade_date),
            ]
        )
        db.commit()
        health = inspect_tushare_evidence_health(db, trade_date)

    datasets = {item["name"]: item for item in health["datasets"]}
    assert datasets["moneyflow"]["coverage_ratio"] == 1.0
    assert datasets["moneyflow"]["status"] == "ok"
    assert datasets["moneyflow_dc"]["coverage_ratio"] == 1.0
    assert datasets["moneyflow_dc"]["status"] == "ok"


def test_inspect_daily_data_health_flags_amount_and_feature_anomalies() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="000001", name="样本1", exchange="SZ", is_active=True, is_st=False),
                Security(symbol="000002", name="样本2", exchange="SZ", is_active=True, is_st=False),
                Security(symbol="000003", name="样本3", exchange="SZ", is_active=True, is_st=False),
            ]
        )
        db.add_all(
            [
                _daily_bar("000001", date(2026, 6, 29), volume="1000000", amount="1000000000"),
                _daily_bar("000002", date(2026, 6, 29), volume="1000000", amount="1000000000"),
                _daily_bar("000003", date(2026, 6, 29), volume="1000000", amount="1000000000"),
                _daily_bar("000001", date(2026, 6, 30), amount=None),
                _daily_bar("000002", date(2026, 6, 30), amount=None),
                _daily_bar("000003", date(2026, 6, 30), amount="1000000000", volume="1000000"),
            ]
        )
        db.add_all(
            [
                StockFeatureDaily(
                    symbol="000001",
                    trade_date=date(2026, 6, 30),
                    features={"amount_ratio_5d": 0.03, "volume_confirmation_score": 12},
                ),
                StockFeatureDaily(
                    symbol="000002",
                    trade_date=date(2026, 6, 30),
                    features={"amount_ratio_5d": 0.04, "volume_confirmation_score": 15},
                ),
                StockFeatureDaily(
                    symbol="000003",
                    trade_date=date(2026, 6, 30),
                    features={"amount_ratio_5d": 0.05, "volume_confirmation_score": 18},
                ),
            ]
        )
        db.commit()

        report = inspect_daily_data_health(db, trade_date=date(2026, 6, 30))

    issue_codes = {issue.code for issue in report.issues}
    assert report.trade_date == date(2026, 6, 30)
    assert report.status == "warning"
    assert report.daily_bar_count == 3
    assert report.feature_count == 3
    assert report.amount_missing_ratio == 2 / 3
    assert report.amount_ratio_5d_median == 0.04
    assert "daily_amount_missing_high" in issue_codes
    assert "amount_ratio_5d_too_low" in issue_codes
    assert "amount_volume_multiplier_mixed" in issue_codes


def test_inspect_daily_data_health_reports_missing_market_regime() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    trade_date = date(2026, 7, 13)

    with sessionmaker(bind=engine)() as db:
        db.add(
            Security(symbol="000001", name="样本", exchange="SZ", is_active=True, is_st=False)
        )
        db.add(_daily_bar("000001", trade_date, amount="1000000000"))
        db.add(
            StockFeatureDaily(
                symbol="000001",
                trade_date=trade_date,
                features={"amount_ratio_5d": 1.0, "volume_confirmation_score": 60.0},
            )
        )
        db.commit()

        missing = inspect_daily_data_health(db, trade_date=trade_date)
        db.add(
            MarketRegimeDaily(
                trade_date=trade_date,
                regime="range",
                trend_score=50.0,
                breadth_score=50.0,
                emotion_score=50.0,
                volatility_score=50.0,
                risk_level="medium",
                source="test",
            )
        )
        db.commit()
        present = inspect_daily_data_health(db, trade_date=trade_date)

    assert missing.market_regime is None
    assert "market_regime_missing" in {issue.code for issue in missing.issues}
    assert present.market_regime == "range"
    assert "market_regime_missing" not in {issue.code for issue in present.issues}


def test_inspect_daily_data_health_flags_two_consecutive_market_regime_gaps() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    first_date = date(2026, 7, 10)
    second_date = date(2026, 7, 13)

    with sessionmaker(bind=engine)() as db:
        db.add(Security(symbol="000001", name="样本", exchange="SZ", is_active=True, is_st=False))
        for trade_date in (first_date, second_date):
            db.add(_daily_bar("000001", trade_date, amount="1000000000"))
            db.add(
                StockFeatureDaily(
                    symbol="000001",
                    trade_date=trade_date,
                    features={"amount_ratio_5d": 1.0, "volume_confirmation_score": 60.0},
                )
            )
        db.commit()

        report = inspect_daily_data_health(db, trade_date=second_date)

    assert "market_regime_consecutive_missing" in {issue.code for issue in report.issues}


def test_inspect_daily_data_health_blocks_candidates_below_daily_coverage_threshold() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    trade_date = date(2026, 7, 13)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol=f"{index:06d}",
                    name=f"样本{index}",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                )
                for index in range(100)
            ]
        )
        db.add_all(
            [
                _daily_bar(f"{index:06d}", trade_date, amount="1000000000")
                for index in range(97)
            ]
        )
        db.commit()

        report = inspect_daily_data_health(db, trade_date=trade_date)

    assert report.expected_security_count == 100
    assert report.eligible_daily_bar_count == 97
    assert report.daily_coverage_ratio == 0.97
    assert report.candidate_generation_allowed is False
    assert any("98%" in reason for reason in report.candidate_block_reasons)


def test_inspect_daily_data_health_allows_candidates_at_coverage_threshold() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    trade_date = date(2026, 7, 13)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol=f"{index:06d}",
                    name=f"样本{index}",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                )
                for index in range(100)
            ]
        )
        db.add_all(
            [
                _daily_bar(f"{index:06d}", trade_date, amount="1000000000")
                for index in range(98)
            ]
        )
        db.commit()

        report = inspect_daily_data_health(db, trade_date=trade_date)

    assert report.daily_coverage_ratio == 0.98
    assert report.amount_missing_ratio == 0
    assert report.candidate_generation_allowed is True
    assert report.candidate_block_reasons == []


def test_inspect_daily_data_health_blocks_candidates_when_amount_missing_reaches_threshold(
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    trade_date = date(2026, 7, 13)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol=f"{index:06d}",
                    name=f"样本{index}",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                )
                for index in range(100)
            ]
        )
        db.add_all(
            [
                _daily_bar(
                    f"{index:06d}",
                    trade_date,
                    amount=None if index == 0 else "1000000000",
                )
                for index in range(100)
            ]
        )
        db.commit()

        report = inspect_daily_data_health(db, trade_date=trade_date)

    assert report.daily_coverage_ratio == 1.0
    assert report.candidate_generation_allowed is False
    assert any("成交额缺失" in reason for reason in report.candidate_block_reasons)
