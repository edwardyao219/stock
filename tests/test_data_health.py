from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.features.health import inspect_daily_data_health
from services.shared.database import Base
from services.shared.models import DailyBar, Security, StockFeatureDaily


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
