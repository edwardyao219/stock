from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.review import monthly_summary
from services.shared.database import Base
from services.shared.models import (
    BacktestTradeRecord,
    DailyBar,
    PaperTradeReview,
    Security,
    TradePlan,
)


def _trade(
    *,
    run_date: date,
    rule_id: str,
    symbol: str,
    signal_date: date,
    entry_date: date,
    pnl: str,
    mfe: str,
    mae: str,
) -> BacktestTradeRecord:
    return BacktestTradeRecord(
        run_date=run_date,
        rule_id=rule_id,
        symbol=symbol,
        signal_date=signal_date,
        entry_date=entry_date,
        entry_price=Decimal("10"),
        exit_date=entry_date,
        exit_price=Decimal("10.5"),
        holding_days=2,
        pnl_pct=Decimal(pnl),
        mfe_pct=Decimal(mfe),
        mae_pct=Decimal(mae),
        exit_reason="time_exit",
    )


def _plan(
    *,
    plan_date: date,
    trade_date: date,
    rule_id: str,
    symbol: str,
    snapshot: dict[str, object],
) -> TradePlan:
    return TradePlan(
        plan_date=plan_date,
        trade_date=trade_date,
        symbol=symbol,
        rule_id=rule_id,
        strategy_type="short_term",
        sector_code="通信设备",
        entry_condition_json={"snapshot": snapshot},
        entry_trigger_price=Decimal("10"),
        max_gap_up_pct=Decimal("0.05"),
        trailing_drawdown_pct=Decimal("0.06"),
        initial_stop=Decimal("9.5"),
        take_profit_1=Decimal("10.8"),
        take_profit_2=Decimal("11.2"),
        max_holding_days=5,
        position_size=Decimal("0.10"),
        confidence_score=Decimal("80"),
        risk_notes=None,
        status="planned",
    )


def _review(
    *,
    symbol: str,
    exit_date: date,
    pnl: str,
) -> PaperTradeReview:
    return PaperTradeReview(
        position_id=1 if symbol == "600183" else 2,
        account_id=1,
        trade_plan_id=1,
        symbol=symbol,
        rule_id="R002",
        sector_code="PCB",
        strategy_type="short_term",
        entry_date=exit_date,
        exit_date=exit_date,
        holding_days=3,
        pnl_pct=Decimal(pnl),
        mfe_pct=Decimal("0.08"),
        mae_pct=Decimal("-0.02"),
        giveback_pct=Decimal("0.01"),
        exit_reason="time_exit",
        signal_tags_json={"items": ["trend_relative"]},
        alert_summary_json={"total": 0},
        evidence_json={},
        verdict="good_trade",
        summary="sample",
    )


def test_generate_monthly_trade_summary_filters_noise_and_compares_factors(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(monthly_summary, "SessionLocal", lambda: session())
    monkeypatch.setattr(monthly_summary, "load_sector_feature_map", lambda db, trade_date: {})

    june_3 = date(2026, 6, 3)
    june_4 = date(2026, 6, 4)
    june_10 = date(2026, 6, 10)
    june_11 = date(2026, 6, 11)
    june_17 = date(2026, 6, 17)
    june_18 = date(2026, 6, 18)
    may_6 = date(2026, 5, 6)
    may_7 = date(2026, 5, 7)
    may_14 = date(2026, 5, 14)
    may_15 = date(2026, 5, 15)

    with session() as db:
        db.add_all(
            [
                Security(symbol="600183", name="生益科技", exchange="SH", industry="PCB", is_active=True),
                Security(symbol="603083", name="剑桥科技", exchange="SH", industry="通信设备", is_active=True),
                Security(symbol="000001", name="平安银行", exchange="SZ", industry="银行", is_active=True),
            ]
        )
        db.add_all(
            [
                _plan(
                    plan_date=june_3,
                    trade_date=june_4,
                    rule_id="R002",
                    symbol="603083",
                    snapshot={
                        "trend_score": 78,
                        "relative_strength_score": 70,
                        "sector_strength_score": 68,
                        "volume_confirmation_score": 62,
                        "overheat_score": 60,
                        "volume_trap_risk_score": 30,
                        "distance_to_ma20": 0.05,
                        "return_20d": 0.12,
                    },
                ),
                _plan(
                    plan_date=june_10,
                    trade_date=june_11,
                    rule_id="R002",
                    symbol="600183",
                    snapshot={
                        "trend_score": 73,
                        "relative_strength_score": 66,
                        "sector_strength_score": 63,
                        "volume_confirmation_score": 57,
                        "overheat_score": 76,
                        "volume_trap_risk_score": 64,
                        "distance_to_ma20": 0.09,
                        "return_20d": 0.18,
                    },
                ),
                _plan(
                    plan_date=june_17,
                    trade_date=june_18,
                    rule_id="R002",
                    symbol="603083",
                    snapshot={
                        "trend_score": 74,
                        "relative_strength_score": 67,
                        "sector_strength_score": 65,
                        "volume_confirmation_score": 59,
                        "overheat_score": 61,
                        "volume_trap_risk_score": 31,
                        "distance_to_ma20": 0.06,
                        "return_20d": 0.13,
                    },
                ),
                _plan(
                    plan_date=may_6,
                    trade_date=may_7,
                    rule_id="R002",
                    symbol="603083",
                    snapshot={
                        "trend_score": 77,
                        "relative_strength_score": 68,
                        "sector_strength_score": 66,
                        "volume_confirmation_score": 61,
                        "overheat_score": 58,
                        "volume_trap_risk_score": 28,
                        "distance_to_ma20": 0.04,
                        "return_20d": 0.10,
                    },
                ),
                _plan(
                    plan_date=may_14,
                    trade_date=may_15,
                    rule_id="R002",
                    symbol="600183",
                    snapshot={
                        "trend_score": 71,
                        "relative_strength_score": 65,
                        "sector_strength_score": 61,
                        "volume_confirmation_score": 56,
                        "overheat_score": 64,
                        "volume_trap_risk_score": 38,
                        "distance_to_ma20": 0.08,
                        "return_20d": 0.14,
                    },
                ),
            ]
        )
        db.add_all(
            [
                _trade(
                    run_date=date(2026, 6, 30),
                    rule_id="R002",
                    symbol="603083",
                    signal_date=june_3,
                    entry_date=june_4,
                    pnl="0.04",
                    mfe="0.08",
                    mae="-0.02",
                ),
                _trade(
                    run_date=date(2026, 6, 30),
                    rule_id="R002",
                    symbol="600183",
                    signal_date=june_10,
                    entry_date=june_11,
                    pnl="-0.03",
                    mfe="0.05",
                    mae="-0.04",
                ),
                _trade(
                    run_date=date(2026, 6, 30),
                    rule_id="R002",
                    symbol="603083",
                    signal_date=june_17,
                    entry_date=june_18,
                    pnl="0.01",
                    mfe="0.04",
                    mae="-0.02",
                ),
                _trade(
                    run_date=date(2026, 5, 31),
                    rule_id="R002",
                    symbol="603083",
                    signal_date=may_6,
                    entry_date=may_7,
                    pnl="0.03",
                    mfe="0.06",
                    mae="-0.01",
                ),
                _trade(
                    run_date=date(2026, 5, 31),
                    rule_id="R002",
                    symbol="600183",
                    signal_date=may_14,
                    entry_date=may_15,
                    pnl="-0.02",
                    mfe="0.04",
                    mae="-0.03",
                ),
                _trade(
                    run_date=date(2026, 6, 30),
                    rule_id="R001",
                    symbol="000001",
                    signal_date=june_3,
                    entry_date=june_4,
                    pnl="0.10",
                    mfe="0.12",
                    mae="-0.01",
                ),
            ]
        )
        db.add_all(
            [
                DailyBar(
                    symbol="603083",
                    trade_date=june_3,
                    open=Decimal("10"),
                    high=Decimal("10.5"),
                    low=Decimal("9.9"),
                    close=Decimal("10.2"),
                    pre_close=Decimal("10"),
                    volume=Decimal("1000"),
                    amount=Decimal("10000"),
                    turnover_rate=Decimal("1.0"),
                    limit_up=None,
                    limit_down=None,
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="600183",
                    trade_date=june_10,
                    open=Decimal("10"),
                    high=Decimal("10.3"),
                    low=Decimal("9.8"),
                    close=Decimal("10.1"),
                    pre_close=Decimal("10"),
                    volume=Decimal("1000"),
                    amount=Decimal("10000"),
                    turnover_rate=Decimal("1.0"),
                    limit_up=None,
                    limit_down=None,
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="603083",
                    trade_date=may_6,
                    open=Decimal("10"),
                    high=Decimal("10.4"),
                    low=Decimal("9.9"),
                    close=Decimal("10.15"),
                    pre_close=Decimal("10"),
                    volume=Decimal("1000"),
                    amount=Decimal("10000"),
                    turnover_rate=Decimal("1.0"),
                    limit_up=None,
                    limit_down=None,
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="600183",
                    trade_date=may_14,
                    open=Decimal("10"),
                    high=Decimal("10.2"),
                    low=Decimal("9.85"),
                    close=Decimal("10.05"),
                    pre_close=Decimal("10"),
                    volume=Decimal("1000"),
                    amount=Decimal("10000"),
                    turnover_rate=Decimal("1.0"),
                    limit_up=None,
                    limit_down=None,
                    is_suspended=False,
                ),
            ]
        )
        db.add_all(
            [
                _review(symbol="600183", exit_date=date(2026, 6, 20), pnl="0.02"),
                _review(symbol="000001", exit_date=date(2026, 6, 21), pnl="-0.01"),
            ]
        )
        db.commit()

    summary = monthly_summary.generate_monthly_trade_summary("2026-06")

    assert summary.excluded_symbols == ["000001"]
    assert summary.backtest_trade_count == 3
    assert summary.paper_review_count == 1
    assert "000001" not in summary.content_md
    trend_factor = next(
        item for item in summary.factor_insights if item["factor_name"] == "趋势+相对强度"
    )
    assert trend_factor["sample_count"] == 2
    assert round(trend_factor["avg_return"], 4) == 0.005
    assert trend_factor["robustness_score"] is None
    assert trend_factor["note"] == "样本太少，只观察，不参与稳健排序"
    assert any(item["factor_name"] == "板块共振+回调质量" for item in summary.factor_insights)
    assert "对照月份 2026-05" in summary.content_md
    assert "最大回撤" in summary.content_md
    assert "稳健分" in summary.content_md


def test_generate_monthly_trade_summary_reuses_sector_feature_map(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    calls = {"sector": 0}

    def fake_sector_map(_db, trade_date):
        calls["sector"] += 1
        return {"通信设备": {"sector_strength_score": 70}}

    monkeypatch.setattr(monthly_summary, "SessionLocal", lambda: session())
    monkeypatch.setattr(monthly_summary, "load_sector_feature_map", fake_sector_map)

    with session() as db:
        db.add_all(
            [
                Security(symbol="600183", name="生益科技", exchange="SH", industry="PCB", is_active=True),
                Security(symbol="603083", name="剑桥科技", exchange="SH", industry="通信设备", is_active=True),
            ]
        )
        db.add_all(
            [
                _trade(
                    run_date=date(2026, 6, 30),
                    rule_id="R002",
                    symbol="603083",
                    signal_date=date(2026, 6, 3),
                    entry_date=date(2026, 6, 4),
                    pnl="0.01",
                    mfe="0.04",
                    mae="-0.02",
                ),
                _trade(
                    run_date=date(2026, 6, 30),
                    rule_id="R002",
                    symbol="600183",
                    signal_date=date(2026, 6, 3),
                    entry_date=date(2026, 6, 4),
                    pnl="0.02",
                    mfe="0.05",
                    mae="-0.01",
                ),
            ]
        )
        db.add_all(
            [
                DailyBar(
                    symbol="603083",
                    trade_date=date(2026, 6, 3),
                    open=Decimal("10"),
                    high=Decimal("10.5"),
                    low=Decimal("9.9"),
                    close=Decimal("10.2"),
                    pre_close=Decimal("10"),
                    volume=Decimal("1000"),
                    amount=Decimal("10000"),
                    turnover_rate=Decimal("1.0"),
                    limit_up=None,
                    limit_down=None,
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="600183",
                    trade_date=date(2026, 6, 3),
                    open=Decimal("10"),
                    high=Decimal("10.3"),
                    low=Decimal("9.8"),
                    close=Decimal("10.1"),
                    pre_close=Decimal("10"),
                    volume=Decimal("1000"),
                    amount=Decimal("10000"),
                    turnover_rate=Decimal("1.0"),
                    limit_up=None,
                    limit_down=None,
                    is_suspended=False,
                ),
            ]
        )
        db.commit()

    summary = monthly_summary.generate_monthly_trade_summary("2026-06")

    assert calls["sector"] == 1
    assert summary.paper_review_count == 0
    assert summary.backtest_trade_count == 2


def test_generate_monthly_trade_summary_batches_daily_bars(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    fallback_bar_queries = {"count": 0}

    original_build_factor_context = monthly_summary._build_factor_context

    def counted_build_factor_context(*args, **kwargs):
        before_missing = kwargs.get("bar_map") is None
        result = original_build_factor_context(*args, **kwargs)
        if before_missing:
            fallback_bar_queries["count"] += 1
        return result

    monkeypatch.setattr(monthly_summary, "SessionLocal", lambda: session())
    monkeypatch.setattr(monthly_summary, "load_sector_feature_map", lambda db, trade_date: {})
    monkeypatch.setattr(monthly_summary, "_build_factor_context", counted_build_factor_context)

    with session() as db:
        db.add_all(
            [
                Security(symbol="600183", name="生益科技", exchange="SH", industry="PCB", is_active=True),
                Security(symbol="603083", name="剑桥科技", exchange="SH", industry="通信设备", is_active=True),
            ]
        )
        for symbol in ["600183", "603083"]:
            db.add(
                _trade(
                    run_date=date(2026, 6, 30),
                    rule_id="R002",
                    symbol=symbol,
                    signal_date=date(2026, 6, 3),
                    entry_date=date(2026, 6, 4),
                    pnl="0.01",
                    mfe="0.04",
                    mae="-0.02",
                )
            )
            db.add(
                DailyBar(
                    symbol=symbol,
                    trade_date=date(2026, 6, 3),
                    open=Decimal("10"),
                    high=Decimal("10.5"),
                    low=Decimal("9.9"),
                    close=Decimal("10.2"),
                    pre_close=Decimal("10"),
                    volume=Decimal("1000"),
                    amount=Decimal("10000"),
                    turnover_rate=Decimal("1.0"),
                    limit_up=None,
                    limit_down=None,
                    is_suspended=False,
                )
            )
        db.commit()

    summary = monthly_summary.generate_monthly_trade_summary("2026-06")

    assert fallback_bar_queries["count"] == 0
    assert summary.backtest_trade_count == 2
