import time
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.routers import market
from apps.api.app.routers.market import (
    get_confirmed_mainline_outcomes,
    get_data_health,
    get_intraday_market_turn,
    get_market_overview,
    get_sector_catalysts,
    get_sector_overview,
    get_sector_replay,
    get_symbol_candles,
)
from services.engine.review.sector_replay import SectorReplayEvent, SectorReplayResult
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    IntradayMarketTurnSnapshot,
    MarketMessageSnapshot,
    MarketRegimeDaily,
    RealtimeQuote,
    SectorDaily,
    SectorFeatureDaily,
    Security,
    StockFeatureDaily,
    TushareMoneyflowIndDc,
)


def test_get_intraday_market_turn_returns_latest_current_snapshot() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    snapshot_time = datetime(2026, 7, 14, 10, 20)

    with session() as db:
        db.add(
            IntradayMarketTurnSnapshot(
                trade_date=date(2026, 7, 14),
                snapshot_time=snapshot_time,
                coverage_ratio=0.99,
                breadth_ratio=0.58,
                total_amount=123.0,
                index_change_pct=-0.003,
                sector_expansion_count=3,
                state_json={
                    "key": "repair_confirmed",
                    "label": "修复确认",
                    "summary": "允许跟踪启动观察。",
                    "startup_watch_allowed": True,
                    "core_action_allowed": False,
                    "quote_integrity": {
                        "expected_symbol_count": 100,
                        "valid_quote_count": 99,
                        "coverage_ratio": 0.99,
                        "source_counts": {"akshare.stock_zh_a_spot.retry": 99},
                        "retry_applied": True,
                    },
                    "expanding_sectors": [
                        {
                            "sector": "半导体",
                            "symbol_count": 18,
                            "up_count": 14,
                            "up_ratio": 0.777778,
                            "avg_change_pct": 0.023,
                        }
                    ],
                    "sustained_expanding_sectors": [
                        {
                            "sector": "半导体",
                            "symbol_count": 18,
                            "up_count": 14,
                            "up_ratio": 0.777778,
                            "avg_change_pct": 0.023,
                            "prior_up_ratio": 0.75,
                            "prior_avg_change_pct": 0.02,
                            "consecutive_snapshots": 2,
                        }
                    ],
                    "leading_sustained_sectors": [
                        {
                            "sector": "半导体",
                            "symbol_count": 18,
                            "up_count": 14,
                            "up_ratio": 0.777778,
                            "avg_change_pct": 0.023,
                            "total_amount": 123456789.0,
                            "leader_symbol": "600001",
                            "leader_change_pct": 0.061,
                            "prior_up_ratio": 0.75,
                            "prior_avg_change_pct": 0.02,
                            "consecutive_snapshots": 2,
                        }
                    ],
                    "cross_day_mainline": {
                        "status": "观察确认",
                        "summary": "昨日主线已获A股盘中扩散确认，仅用于观察候选绑定。",
                        "baseline_trade_date": "2026-07-13",
                        "checkpoint": "09:45首次核验",
                        "confirmed_sectors": ["半导体"],
                        "sectors": [
                            {
                                "sector": "半导体",
                                "status": "观察确认",
                                "reason": "真实全市场快照显示板块扩散、涨幅和龙头承接仍在。",
                                "baseline_up_ratio": 0.75,
                                "baseline_avg_change_pct": 0.02,
                                "baseline_leader_change_pct": 0.05,
                                "current_up_ratio": 0.78,
                                "current_avg_change_pct": 0.018,
                                "current_leader_change_pct": 0.04,
                            }
                        ],
                    },
                },
            )
        )
        db.commit()

        result = get_intraday_market_turn(db=db)

    assert result.key == "repair_confirmed"
    assert result.snapshot_time == snapshot_time
    assert result.expanding_sectors[0].sector == "半导体"
    assert result.sustained_expanding_sectors[0].consecutive_snapshots == 2
    assert result.leading_sustained_sectors[0].leader_symbol == "600001"
    assert result.cross_day_mainline.status == "观察确认"
    assert result.cross_day_mainline.confirmed_sectors == ["半导体"]
    assert result.quote_integrity["retry_applied"] is True
    assert result.quote_integrity["valid_quote_count"] == 99
    assert result.core_action_allowed is False


def test_get_confirmed_mainline_outcomes_returns_matured_leader_returns() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    signal_date = date(2026, 7, 1)

    with session() as db:
        db.add(
            IntradayMarketTurnSnapshot(
                trade_date=signal_date,
                snapshot_time=datetime(2026, 7, 1, 10, 30),
                coverage_ratio=0.99,
                breadth_ratio=0.6,
                total_amount=100.0,
                index_change_pct=0.002,
                sector_expansion_count=3,
                state_json={
                    "cross_day_mainline": {
                        "status": "观察确认",
                        "checkpoint": "10:30复核",
                        "sectors": [
                            {
                                "sector": "半导体",
                                "status": "观察确认",
                                "current_leader_symbol": "600001",
                            }
                        ],
                    }
                },
            )
        )
        for offset, close in enumerate(("10", "11")):
            db.add(
                DailyBar(
                    symbol="600001",
                    trade_date=signal_date + timedelta(days=offset),
                    open=Decimal(close),
                    high=Decimal(close),
                    low=Decimal(close),
                    close=Decimal(close),
                    pre_close=Decimal(close),
                    volume=Decimal("100000"),
                    amount=Decimal("1000000"),
                    turnover_rate=None,
                    limit_up=Decimal(close) * Decimal("1.1"),
                    limit_down=Decimal(close) * Decimal("0.9"),
                    is_suspended=False,
                )
            )
        db.commit()

        result = get_confirmed_mainline_outcomes(db=db)
        summary = market.get_mainline_outcome_summary(db=db)

    assert result[0].sector == "半导体"
    assert result[0].horizons[0].return_pct == 0.1
    assert result[0].horizons[0].reason is None
    assert summary.signal_type == "strong_benchmark"
    assert summary.window_limit == 120
    assert summary.horizons[0].sample_count == 0
    assert summary.horizons[0].total_signal_count == 0
    assert summary.horizons[0].completed_count == 0
    assert summary.horizons[0].waiting_count == 0
    assert summary.horizons[0].waiting_reasons == {}
    assert summary.horizons[0].unavailable_count == 0
    assert summary.horizons[0].unavailable_reasons == {}
    assert summary.minimum_sample_count == 20
    assert summary.policy_status == "insufficient"
    assert summary.policy_label == "样本不足，禁止调整策略"
    assert summary.breakdown_horizon == 3
    assert summary.sectors == []
    assert summary.market_states == []


def test_get_symbol_candles_returns_limited_ascending_bars_with_moving_average() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="样本1",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
                Security(
                    symbol="000002",
                    name="样本2",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
                Security(
                    symbol="000003",
                    name="无行情",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
            ]
        )
        db.add_all(
            DailyBar(
                symbol="000001",
                trade_date=date(2026, 1, day),
                open=Decimal(day),
                high=Decimal(day + 1),
                low=Decimal(day - 1),
                close=Decimal(day),
                pre_close=Decimal(day - 1) if day > 1 else None,
                volume=Decimal(day * 100),
                amount=Decimal(day * 1000),
                turnover_rate=None,
                limit_up=Decimal(day) * Decimal("1.1"),
                limit_down=Decimal(day) * Decimal("0.9"),
                is_suspended=False,
            )
            for day in range(1, 31)
        )
        db.commit()

        payload = get_symbol_candles(symbol="000001", db=db, limit=30)

    assert len(payload) == 30
    assert payload[0].time == date(2026, 1, 1)
    assert payload[-1].time == date(2026, 1, 30)
    assert payload[3].ma5 is None
    assert payload[4].ma5 == 3
    assert payload[-1].ma20 == 20.5


def test_get_market_overview_returns_breadth_and_amount_metrics(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="样本1",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
                Security(
                    symbol="000002",
                    name="样本2",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
                Security(
                    symbol="000003",
                    name="无行情",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
            ]
        )
        db.add_all(
            [
                DailyBar(
                    symbol="000001",
                    trade_date=date(2026, 1, 1),
                    open=Decimal("10"),
                    high=Decimal("10"),
                    low=Decimal("10"),
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
                    trade_date=date(2026, 1, 2),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("10"),
                    close=Decimal("11"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=Decimal("2000"),
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="000002",
                    trade_date=date(2026, 1, 2),
                    open=Decimal("10"),
                    high=Decimal("10"),
                    low=Decimal("9"),
                    close=Decimal("9"),
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

        monkeypatch.setattr(market, "_safe_live_market_indexes", lambda: [])
        payload = get_market_overview(db=db)

    assert payload.trade_date == date(2026, 1, 2)
    assert payload.up_count == 1
    assert payload.down_count == 1
    assert payload.up_ratio == 0.5
    assert payload.avg_change_pct == 0
    assert payload.total_amount == 3000
    assert payload.amount_change_pct == 2
    assert payload.active_security_count == 3
    assert payload.coverage_ratio == round(2 / 3, 6)
    assert payload.is_full_market is False
    assert payload.stress_status == "neutral"
    assert payload.stress_label == "中性"
    assert payload.risk_action_label == "按原计划精选"
    assert payload.indexes == []


def test_market_stress_policy_flags_broad_selloff() -> None:
    policy = market._market_stress_policy(
        up_ratio=0.18,
        avg_change_pct=-0.026,
        amount_change_pct=0.45,
    )

    assert policy["stress_status"] == "risk_off"
    assert policy["stress_label"] == "压力大"
    assert policy["risk_action_label"] == "停止扩散，只做观察和风控"
    assert any("上涨占比" in reason for reason in policy["stress_reasons"])
    assert any("放量下跌" in reason for reason in policy["stress_reasons"])


def test_market_stress_policy_marks_systemic_risk_from_breadth_and_major_indexes() -> None:
    policy = market._market_stress_policy(
        up_ratio=0.21,
        avg_change_pct=-0.0194,
        amount_change_pct=None,
        indexes=[
            market.MarketIndexResponse(
                code="sh000001",
                name="上证",
                quote_date=date(2026, 7, 17),
                price=3500,
                change_pct=-0.0234,
                amount=None,
                source="test",
            ),
            market.MarketIndexResponse(
                code="sz399001",
                name="深成",
                quote_date=date(2026, 7, 17),
                price=11000,
                change_pct=-0.0437,
                amount=None,
                source="test",
            ),
            market.MarketIndexResponse(
                code="sz399006",
                name="创业板",
                quote_date=date(2026, 7, 17),
                price=2200,
                change_pct=-0.0543,
                amount=None,
                source="test",
            ),
        ],
    )

    assert policy["stress_status"] == "risk_off"
    assert policy["stress_label"] == "系统性风险"
    assert policy["stress_score"] >= 85
    assert "暂停新开仓" in policy["risk_action_label"]
    assert policy["recovery_stage"] == "blocked"
    assert policy["recovery_snapshot_count"] == 0
    assert policy["recovery_required_count"] == 2
    assert any("深成" in reason and "创业板" in reason for reason in policy["stress_reasons"])


def test_market_stress_policy_does_not_raise_systemic_risk_without_broad_selloff() -> None:
    policy = market._market_stress_policy(
        up_ratio=0.48,
        avg_change_pct=-0.004,
        amount_change_pct=None,
        indexes=[
            market.MarketIndexResponse(
                code="sz399006",
                name="创业板",
                quote_date=date(2026, 7, 17),
                price=2200,
                change_pct=-0.05,
                amount=None,
                source="test",
            )
        ],
    )

    assert policy["stress_status"] != "risk_off"


def test_market_stress_recovery_policy_keeps_risk_off_after_one_recovery() -> None:
    policy = market._market_stress_recovery_policy(
        {
            "stress_status": "neutral",
            "stress_label": "中性",
            "stress_score": 0.0,
            "stress_reasons": ["没有明显全市场压力信号"],
            "risk_action_label": "按原计划精选",
        },
        [(0.29, -0.004), (0.48, 0.002)],
    )

    assert policy["stress_status"] == "risk_off"
    assert policy["stress_label"] == "风险解除待确认"
    assert policy["recovery_stage"] == "blocked"
    assert policy["recovery_snapshot_count"] == 1
    assert policy["recovery_required_count"] == 2
    assert "连续2次" in policy["stress_reasons"][0]
    assert "暂停新开仓" in policy["risk_action_label"]


def test_market_stress_recovery_policy_limits_core_after_two_recoveries() -> None:
    original = {
        "stress_status": "neutral",
        "stress_label": "中性",
        "stress_score": 0.0,
        "stress_reasons": ["没有明显全市场压力信号"],
        "risk_action_label": "按原计划精选",
    }

    policy = market._market_stress_recovery_policy(
        original,
        [(0.21, -0.0194), (0.48, 0.002), (0.52, 0.004)],
    )

    assert policy["stress_status"] == "caution"
    assert policy["stress_label"] == "恢复观察"
    assert policy["recovery_stage"] == "limited"
    assert policy["recovery_snapshot_count"] == 2
    assert policy["recovery_required_count"] == 4
    assert "最多1只核心候选" in policy["risk_action_label"]


def test_market_stress_recovery_policy_releases_normally_after_four_recoveries() -> None:
    original = {
        "stress_status": "neutral",
        "stress_label": "中性",
        "stress_score": 0.0,
        "stress_reasons": ["没有明显全市场压力信号"],
        "risk_action_label": "按原计划精选",
    }

    policy = market._market_stress_recovery_policy(
        original,
        [
            (0.21, -0.0194),
            (0.48, 0.002),
            (0.52, 0.004),
            (0.50, 0.001),
            (0.55, 0.006),
        ],
    )

    assert policy["stress_status"] == "neutral"
    assert policy["recovery_stage"] == "normal"
    assert policy["recovery_snapshot_count"] == 4
    assert policy["recovery_required_count"] == 4


def test_market_stress_recovery_policy_keeps_old_risk_resolved() -> None:
    original = {
        "stress_status": "neutral",
        "stress_label": "中性",
        "stress_score": 0.0,
        "stress_reasons": ["没有明显全市场压力信号"],
        "risk_action_label": "按原计划精选",
    }

    policy = market._market_stress_recovery_policy(
        original,
        [
            (0.21, -0.0194),
            (0.48, 0.002),
            (0.52, 0.004),
            (0.50, 0.001),
            (0.55, 0.006),
            (0.44, 0.0),
        ],
    )

    assert policy["stress_status"] == "neutral"
    assert policy["recovery_stage"] == "normal"
    assert policy["recovery_snapshot_count"] == 4
    assert policy["recovery_required_count"] == 4


def test_recent_full_market_stress_snapshots_group_persisted_quotes(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    quote_date = date(2026, 7, 20)
    quote_times = [
        datetime(2026, 7, 20, 9, 35),
        datetime(2026, 7, 20, 9, 40),
        datetime(2026, 7, 20, 9, 45),
    ]

    with session() as db:
        db.add_all(
            [
                Security(symbol="000001", name="样本1", exchange="SZ", is_active=True, is_st=False),
                Security(symbol="000002", name="样本2", exchange="SZ", is_active=True, is_st=False),
            ]
        )
        prices = [
            (Decimal("9"), Decimal("9")),
            (Decimal("11"), Decimal("10")),
            (Decimal("10.2"), Decimal("10.1")),
        ]
        db.add_all(
            [
                RealtimeQuote(
                    symbol=symbol,
                    trade_date=quote_date,
                    quote_time=quote_time,
                    price=price,
                    open=Decimal("10"),
                    high=price,
                    low=Decimal("9"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    source="test",
                )
                for quote_time, price_pair in zip(quote_times, prices, strict=True)
                for symbol, price in zip(("000001", "000002"), price_pair, strict=True)
            ]
        )
        db.commit()
        monkeypatch.setattr(market, "now_local", lambda: datetime(2026, 7, 20, 9, 46))

        snapshots = market._recent_full_market_stress_snapshots(db)

    assert snapshots == [(0.0, -0.1), (0.5, 0.05), (1.0, 0.015)]


def test_recent_full_market_stress_snapshots_survive_long_market_holiday(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(
            Security(
                symbol="000001",
                name="样本1",
                exchange="SZ",
                is_active=True,
                is_st=False,
            )
        )
        db.add(
            RealtimeQuote(
                symbol="000001",
                trade_date=date(2026, 1, 30),
                quote_time=datetime(2026, 1, 30, 14, 55),
                price=Decimal("9"),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("9"),
                pre_close=Decimal("10"),
                pct_change=None,
                volume=Decimal("100"),
                amount=Decimal("1000"),
                turnover_rate=None,
                source="test",
            )
        )
        db.commit()
        monkeypatch.setattr(market, "now_local", lambda: datetime(2026, 2, 10, 9, 30))

        snapshots = market._recent_full_market_stress_snapshots(db)

    assert snapshots == [(0.0, -0.1)]


def test_market_snapshot_scope_marks_stale_live_snapshot() -> None:
    scope = market._market_snapshot_scope(
        trade_date=date(2026, 7, 6),
        is_live=True,
        today=date(2026, 7, 7),
    )

    assert scope["is_live_snapshot"] is True
    assert scope["is_current_snapshot"] is False
    assert scope["snapshot_scope_label"] == "实时源非今日"
    assert scope["stress_scope_label"] == "最近交易日压力"


def test_get_market_overview_uses_latest_well_covered_daily_bar_date(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="000001", name="样本1", exchange="SZ", is_active=True, is_st=False),
                Security(symbol="000002", name="样本2", exchange="SZ", is_active=True, is_st=False),
                Security(
                    symbol="002558",
                    name="巨人网络",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
            ]
        )
        db.add_all(
            [
                DailyBar(
                    symbol="000001",
                    trade_date=date(2026, 6, 29),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("10"),
                    close=Decimal("11"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=Decimal("2000"),
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="000002",
                    trade_date=date(2026, 6, 29),
                    open=Decimal("10"),
                    high=Decimal("10"),
                    low=Decimal("9"),
                    close=Decimal("9"),
                    pre_close=Decimal("10"),
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="002558",
                    trade_date=date(2026, 6, 30),
                    open=Decimal("20"),
                    high=Decimal("21"),
                    low=Decimal("20"),
                    close=Decimal("21"),
                    pre_close=Decimal("20"),
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    limit_up=Decimal("22"),
                    limit_down=Decimal("18"),
                    is_suspended=False,
                ),
            ]
        )
        db.commit()

        monkeypatch.setattr(market, "_safe_live_market_indexes", lambda: [])
        payload = get_market_overview(db=db)

    assert payload.trade_date == date(2026, 6, 29)
    assert payload.stock_count == 2
    assert payload.up_count == 1
    assert payload.down_count == 1


def test_get_market_overview_live_uses_live_snapshot_on_sqlite(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        monkeypatch.setattr(market, "_LIVE_MARKET_CACHE", None)
        monkeypatch.setattr(market, "_LIVE_MARKET_FUTURE", None)
        monkeypatch.setattr(
            market,
            "_cached_live_a_share_overview",
            lambda: market.MarketOverviewResponse(
                trade_date=date(2026, 6, 25),
                stock_count=2,
                up_count=1,
                down_count=1,
                flat_count=0,
                up_ratio=0.5,
                avg_change_pct=0.01,
                total_amount=1234,
                amount_change_pct=None,
                active_security_count=2,
                coverage_ratio=1.0,
                is_full_market=True,
                message="live",
                indexes=[],
            ),
        )
        monkeypatch.setattr(
            market,
            "_stored_market_overview",
            lambda db: (_ for _ in ()).throw(RuntimeError("stored snapshot should not be used")),
        )
        payload = get_market_overview(db=db, live=True)

    assert payload.trade_date == date(2026, 6, 25)
    assert payload.message == "live"


def test_get_market_overview_keeps_recovering_live_snapshot_risk_off(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    live_payload = market.MarketOverviewResponse(
        trade_date=date(2026, 7, 20),
        stock_count=5000,
        up_count=2400,
        down_count=2500,
        flat_count=100,
        up_ratio=0.48,
        avg_change_pct=0.002,
        total_amount=1_000_000,
        amount_change_pct=None,
        active_security_count=5000,
        coverage_ratio=1.0,
        is_full_market=True,
        message="live",
    )

    with session() as db:
        monkeypatch.setattr(
            market,
            "_try_cached_live_a_share_overview",
            lambda timeout: live_payload,
        )
        monkeypatch.setattr(
            market,
            "_recent_full_market_stress_snapshots",
            lambda db: [(0.21, -0.0194), (0.48, 0.002)],
        )

        payload = get_market_overview(db=db, live=True)

    assert payload.stress_status == "risk_off"
    assert payload.stress_label == "风险解除待确认"
    assert payload.recovery_stage == "blocked"
    assert payload.recovery_snapshot_count == 1
    assert payload.recovery_required_count == 2
    assert "暂停新开仓" in payload.risk_action_label


def test_get_market_overview_live_uses_stored_snapshot_when_live_cache_is_slow(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="000001", name="样本1", exchange="SZ", is_active=True, is_st=False),
                Security(symbol="000002", name="样本2", exchange="SZ", is_active=True, is_st=False),
            ]
        )
        db.commit()
        stored_payload = market.MarketOverviewResponse(
            trade_date=date(2026, 7, 1),
            stock_count=2,
            up_count=2,
            down_count=0,
            flat_count=0,
            up_ratio=1.0,
            avg_change_pct=0.02,
            total_amount=3000,
            amount_change_pct=None,
            active_security_count=2,
            coverage_ratio=1.0,
            is_full_market=True,
            message="stored",
            indexes=[
                market.MarketIndexResponse(
                    code="sh000001",
                    name="上证",
                    quote_date=date(2026, 7, 2),
                    price=4000,
                    change_pct=0.01,
                    amount=100000000,
                    source="test",
                )
            ],
        )

        monkeypatch.setattr(market, "_try_cached_live_a_share_overview", lambda timeout: None)
        monkeypatch.setattr(
            market,
            "_try_sina_symbol_live_a_share_overview",
            lambda _db: (_ for _ in ()).throw(RuntimeError("blocking fallback must not run")),
        )
        monkeypatch.setattr(market, "_stored_market_overview", lambda db: stored_payload)
        monkeypatch.setattr(market, "LIVE_MARKET_TIMEOUT_SECONDS", 0.001, raising=False)

        started = time.monotonic()
        payload = get_market_overview(db=db, live=True)
        elapsed = time.monotonic() - started

    assert elapsed < 0.08
    assert payload.trade_date == date(2026, 7, 1)
    assert payload.message == "stored"


def test_get_market_overview_live_uses_current_full_market_archive_when_source_times_out(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    snapshot_time = datetime(2026, 7, 14, 15, 5)

    with session() as db:
        db.add_all(
            [
                Security(symbol="000001", name="样本1", exchange="SZ", is_active=True, is_st=False),
                Security(symbol="000002", name="样本2", exchange="SZ", is_active=True, is_st=False),
                Security(symbol="000003", name="样本3", exchange="SZ", is_active=True, is_st=False),
                Security(
                    symbol="000004",
                    name="旧样本",
                    exchange="SZ",
                    is_active=False,
                    is_st=False,
                ),
            ]
        )
        db.add_all(
            [
                RealtimeQuote(
                    symbol=symbol,
                    trade_date=date(2026, 7, 14),
                    quote_time=snapshot_time,
                    price=price,
                    open=Decimal("10"),
                    high=price,
                    low=Decimal("9"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100"),
                    amount=amount,
                    turnover_rate=None,
                    source="akshare.stock_zh_a_spot_em",
                )
                for symbol, price, amount in (
                    ("000001", Decimal("11"), Decimal("1000")),
                    ("000002", Decimal("9"), Decimal("2000")),
                    ("000003", Decimal("10"), Decimal("3000")),
                    ("000004", Decimal("20"), Decimal("9000")),
                )
            ]
        )
        db.commit()
        monkeypatch.setattr(market, "now_local", lambda: datetime(2026, 7, 14, 15, 10))
        monkeypatch.setattr(market, "_try_cached_live_a_share_overview", lambda timeout: None)
        monkeypatch.setattr(market, "_safe_live_market_indexes", lambda: [])

        payload = get_market_overview(db=db, live=True)

    assert payload.trade_date == date(2026, 7, 14)
    assert payload.is_full_market is True
    assert payload.is_current_snapshot is True
    assert payload.stock_count == 3
    assert payload.up_count == 1
    assert payload.down_count == 1
    assert payload.total_amount == 6000
    assert "归档" in payload.message


def test_get_market_overview_live_ignores_stale_full_market_archive(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    snapshot_time = datetime(2026, 7, 13, 15, 5)

    with session() as db:
        db.add(
            Security(symbol="000001", name="样本", exchange="SZ", is_active=True, is_st=False)
        )
        db.add(
            RealtimeQuote(
                symbol="000001",
                trade_date=date(2026, 7, 13),
                quote_time=snapshot_time,
                price=Decimal("11"),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("10"),
                pre_close=Decimal("10"),
                pct_change=None,
                volume=Decimal("100"),
                amount=Decimal("1000"),
                turnover_rate=None,
                source="akshare.stock_zh_a_spot_em",
            )
        )
        db.commit()
        expected = market.MarketOverviewResponse(
            trade_date=date(2026, 7, 10),
            stock_count=1,
            up_count=0,
            down_count=1,
            flat_count=0,
            up_ratio=0.0,
            avg_change_pct=-0.01,
            total_amount=1000,
            amount_change_pct=None,
            active_security_count=1,
            coverage_ratio=1.0,
            is_full_market=True,
            message="daily",
        )
        monkeypatch.setattr(market, "now_local", lambda: datetime(2026, 7, 14, 9, 0))
        monkeypatch.setattr(market, "_try_cached_live_a_share_overview", lambda timeout: None)
        monkeypatch.setattr(market, "_stored_market_overview", lambda db: expected)

        payload = get_market_overview(db=db, live=True)

    assert payload.message == "daily"


def test_sina_symbol_live_overview_filters_stale_quote_dates(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="000001", name="样本1", exchange="SZ", is_active=True, is_st=False),
                Security(symbol="000002", name="样本2", exchange="SZ", is_active=True, is_st=False),
                Security(
                    symbol="000003",
                    name="停牌旧样本",
                    exchange="SZ",
                    is_active=True,
                    is_st=False,
                ),
            ]
        )
        db.commit()
        monkeypatch.setattr(
            market,
            "fetch_sina_realtime_quotes",
            lambda symbols: [
                market.RealtimeQuoteRow(
                    symbol="000001",
                    trade_date="2026-07-02",
                    quote_time=datetime(2026, 7, 2, 13, 30),
                    price=Decimal("11"),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("10"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100"),
                    amount=Decimal("1000"),
                    turnover_rate=None,
                    source="sina.hq",
                ),
                market.RealtimeQuoteRow(
                    symbol="000002",
                    trade_date="2026-07-02",
                    quote_time=datetime(2026, 7, 2, 13, 30),
                    price=Decimal("9"),
                    open=Decimal("10"),
                    high=Decimal("10"),
                    low=Decimal("9"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100"),
                    amount=Decimal("2000"),
                    turnover_rate=None,
                    source="sina.hq",
                ),
                market.RealtimeQuoteRow(
                    symbol="000003",
                    trade_date="2026-06-19",
                    quote_time=datetime(2026, 6, 19, 15, 0),
                    price=Decimal("5"),
                    open=Decimal("5"),
                    high=Decimal("5"),
                    low=Decimal("5"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100"),
                    amount=Decimal("500"),
                    turnover_rate=None,
                    source="sina.hq",
                ),
            ],
        )
        monkeypatch.setattr(market, "_safe_live_market_indexes", lambda: [])

        payload = market._sina_symbol_live_a_share_overview(db)

    assert payload.trade_date == date(2026, 7, 2)
    assert payload.stock_count == 2
    assert payload.up_count == 1
    assert payload.down_count == 1
    assert payload.flat_count == 0
    assert payload.active_security_count == 3
    assert payload.coverage_ratio == round(2 / 3, 6)
    assert "旧日期 1" in payload.message


def test_get_data_health_returns_daily_feature_diagnostics() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(
            Security(
                symbol="002156",
                name="样本",
                exchange="SZ",
                is_active=True,
                is_st=False,
            )
        )
        db.add(
            DailyBar(
                symbol="002156",
                trade_date=date(2026, 6, 30),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("10"),
                close=Decimal("11"),
                pre_close=Decimal("10"),
                volume=Decimal("1000000"),
                amount=None,
                turnover_rate=None,
                limit_up=Decimal("11"),
                limit_down=Decimal("9"),
                is_suspended=False,
            )
        )
        db.add(
            StockFeatureDaily(
                symbol="002156",
                trade_date=date(2026, 6, 30),
                features={"amount_ratio_5d": 0.92, "volume_confirmation_score": 63},
            )
        )
        db.add(
            MarketRegimeDaily(
                trade_date=date(2026, 6, 30),
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

        payload = get_data_health(db=db, trade_date="2026-06-30")

    assert payload.trade_date == date(2026, 6, 30)
    assert payload.status == "ok"
    assert payload.daily_bar_count == 1
    assert payload.feature_count == 1
    assert payload.amount_ratio_5d_median == 0.92
    assert payload.expected_security_count == 1
    assert payload.eligible_daily_bar_count == 1
    assert payload.daily_coverage_ratio == 1.0
    assert payload.candidate_generation_allowed is False
    assert payload.candidate_block_reasons


def test_get_sector_overview_returns_month_rank_and_fund_flow() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                SectorDaily(
                    sector_code="半导体",
                    sector_name="半导体",
                    trade_date=date(2026, 6, 2),
                    close=Decimal("100"),
                    pct_change=Decimal("0.0100"),
                    amount=Decimal("1000000000"),
                    up_count=10,
                    down_count=3,
                    limit_up_count=1,
                    limit_down_count=0,
                    new_high_count=2,
                    relative_strength=Decimal("0.1200"),
                ),
                SectorDaily(
                    sector_code="半导体",
                    sector_name="半导体",
                    trade_date=date(2026, 6, 30),
                    close=Decimal("118"),
                    pct_change=Decimal("0.0300"),
                    amount=Decimal("1800000000"),
                    up_count=16,
                    down_count=4,
                    limit_up_count=2,
                    limit_down_count=0,
                    new_high_count=4,
                    relative_strength=Decimal("0.2200"),
                ),
                SectorDaily(
                    sector_code="银行",
                    sector_name="银行",
                    trade_date=date(2026, 6, 2),
                    close=Decimal("100"),
                    pct_change=Decimal("0.0000"),
                    amount=Decimal("900000000"),
                    up_count=6,
                    down_count=5,
                    limit_up_count=0,
                    limit_down_count=0,
                    new_high_count=0,
                    relative_strength=Decimal("0.0100"),
                ),
                SectorDaily(
                    sector_code="银行",
                    sector_name="银行",
                    trade_date=date(2026, 6, 30),
                    close=Decimal("104"),
                    pct_change=Decimal("0.0100"),
                    amount=Decimal("950000000"),
                    up_count=7,
                    down_count=4,
                    limit_up_count=0,
                    limit_down_count=0,
                    new_high_count=1,
                    relative_strength=Decimal("0.0300"),
                ),
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 82,
                        "sector_breadth_score": 74,
                        "sector_momentum_score": 78,
                        "sector_stock_count": 42,
                        "sector_up_count": 30,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="银行",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 58,
                        "sector_breadth_score": 52,
                        "sector_momentum_score": 49,
                        "sector_stock_count": 30,
                        "sector_up_count": 16,
                    },
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="行业",
                    ts_code="BK001",
                    name="半导体",
                    pct_change=Decimal("0.0300"),
                    close=Decimal("118"),
                    net_amount=Decimal("350000000"),
                    net_amount_rate=Decimal("0.0860"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="行业",
                    ts_code="BK002",
                    name="银行",
                    pct_change=Decimal("0.0100"),
                    close=Decimal("104"),
                    net_amount=Decimal("50000000"),
                    net_amount_rate=Decimal("0.0120"),
                ),
            ]
        )
        db.commit()

        payload = get_sector_overview(db=db)

    assert payload.trade_date == date(2026, 6, 30)
    assert payload.month_start_date == date(2026, 6, 1)
    assert [item.sector_name for item in payload.sectors[:2]] == ["半导体", "银行"]
    assert [item.sector_name for item in payload.monthly_rank[:2]] == ["半导体", "银行"]
    assert [item.sector_name for item in payload.activity_rank[:2]] == ["半导体", "银行"]
    assert [item.sector_name for item in payload.continuity_rank[:2]] == ["半导体", "银行"]
    assert payload.feature_sector_count == 2
    assert payload.overview_sector_count == 2
    assert payload.feature_coverage_ratio == 1
    assert payload.moneyflow_sector_count == 2
    assert payload.moneyflow_missing_count == 0
    assert payload.moneyflow_coverage_ratio == 1
    assert payload.moneyflow_reliability_label == "资金覆盖正常"
    assert payload.sector_gate_summary.main_allowed_count == 1
    assert payload.sector_gate_summary.observe_count == 1
    assert payload.sector_gate_summary.cooldown_count == 0
    assert payload.sector_gate_summary.unknown_count == 0
    assert payload.sectors[0].month_rank == 1
    assert round(payload.sectors[0].monthly_return_pct or 0, 4) == 0.18
    assert payload.sectors[0].fund_flow_net_amount == 350000000.0
    assert payload.sectors[0].sector_strength_score == 82.0
    assert payload.sectors[0].sector_gate_label == "主线允许"
    assert (payload.sectors[0].sector_gate_score or 0) >= 70
    assert "月度排名靠前" in payload.sectors[0].sector_gate_reasons
    bank = next(item for item in payload.sectors if item.sector_name == "银行")
    assert bank.sector_gate_label == "观察确认"
    assert "月度趋势转正" in bank.sector_gate_reasons


def test_get_sector_overview_uses_canonical_feature_name_for_moneyflow_alias() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 82,
                        "sector_breadth_score": 74,
                        "sector_momentum_score": 78,
                        "sector_stock_count": 42,
                        "sector_up_count": 30,
                    },
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="行业",
                    ts_code="BK001",
                    name="半导体设备",
                    pct_change=Decimal("0.0400"),
                    close=Decimal("143"),
                    net_amount=Decimal("350000000"),
                    net_amount_rate=Decimal("0.0860"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 2),
                    content_type="行业",
                    ts_code="BK001",
                    name="半导体设备",
                    pct_change=Decimal("0.0100"),
                    close=Decimal("100"),
                    net_amount=Decimal("10000000"),
                    net_amount_rate=Decimal("0.0100"),
                ),
            ]
        )
        db.commit()

        payload = get_sector_overview(db=db)

    item = payload.sectors[0]
    assert item.sector_name == "半导体设备"
    assert item.canonical_sector_name == "半导体"
    assert item.sector_strength_score == 82.0
    assert item.sector_momentum_score == 78.0


def test_get_sector_overview_maps_chip_design_and_packaging_to_semiconductor() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(
            SectorFeatureDaily(
                sector_code="半导体",
                trade_date=date(2026, 6, 30),
                features={
                    "sector_strength_score": 82,
                    "sector_breadth_score": 74,
                    "sector_momentum_score": 78,
                    "sector_stock_count": 42,
                    "sector_up_count": 30,
                },
            )
        )
        db.add_all(
            [
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="行业",
                    ts_code="BK001",
                    name="集成电路封测",
                    pct_change=Decimal("0.0400"),
                    close=Decimal("143"),
                    net_amount=Decimal("350000000"),
                    net_amount_rate=Decimal("0.0860"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="行业",
                    ts_code="BK002",
                    name="数字芯片设计",
                    pct_change=Decimal("0.0300"),
                    close=Decimal("139"),
                    net_amount=Decimal("220000000"),
                    net_amount_rate=Decimal("0.0410"),
                ),
            ]
        )
        db.commit()

        payload = get_sector_overview(db=db)

    items = {item.sector_name: item for item in payload.sectors}
    assert items["集成电路封测"].canonical_sector_name == "半导体"
    assert items["数字芯片设计"].canonical_sector_name == "半导体"
    assert items["集成电路封测"].sector_strength_score == 82.0
    assert items["数字芯片设计"].sector_momentum_score == 78.0


def test_get_sector_overview_maps_common_tech_subindustries_to_local_features() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                SectorFeatureDaily(
                    sector_code="软件服务",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 71,
                        "sector_breadth_score": 60,
                        "sector_momentum_score": 68,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="IT设备",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 61,
                        "sector_breadth_score": 55,
                        "sector_momentum_score": 58,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="元器件",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 66,
                        "sector_breadth_score": 62,
                        "sector_momentum_score": 64,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="电气设备",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 69,
                        "sector_breadth_score": 63,
                        "sector_momentum_score": 65,
                    },
                ),
            ]
        )
        mapped_names = ["横向通用软件", "其他计算机设备", "元件", "光伏设备"]
        for index, name in enumerate(mapped_names, start=1):
            db.add(
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="行业",
                    ts_code=f"BK{index:03d}",
                    name=name,
                    pct_change=Decimal("0.0200"),
                    close=Decimal("120"),
                    net_amount=Decimal("100000000"),
                    net_amount_rate=Decimal("0.0200"),
                )
            )
        db.commit()

        payload = get_sector_overview(db=db)

    items = {item.sector_name: item for item in payload.sectors}
    assert items["横向通用软件"].canonical_sector_name == "软件服务"
    assert items["横向通用软件"].sector_strength_score == 71.0
    assert items["其他计算机设备"].canonical_sector_name == "IT设备"
    assert items["其他计算机设备"].sector_strength_score == 61.0
    assert items["元件"].canonical_sector_name == "元器件"
    assert items["元件"].sector_strength_score == 66.0
    assert items["光伏设备"].canonical_sector_name == "电气设备"
    assert items["光伏设备"].sector_strength_score == 69.0


def test_get_sector_overview_reuses_short_cache(monkeypatch) -> None:
    calls = {"count": 0}

    def stored_overview(db) -> market.SectorOverviewResponse:
        calls["count"] += 1
        return market.SectorOverviewResponse(
            trade_date=date(2026, 7, 8),
            month_start_date=date(2026, 7, 1),
            feature_trade_date=date(2026, 7, 8),
            moneyflow_trade_date=date(2026, 7, 8),
            sectors=[],
        )

    monkeypatch.setattr(market, "_SECTOR_OVERVIEW_CACHE", None, raising=False)
    monkeypatch.setattr(market, "_stored_sector_overview", stored_overview)
    monkeypatch.setattr(market, "monotonic", lambda: 1000.0)

    first = get_sector_overview(db=object())
    second = get_sector_overview(db=object())

    assert calls["count"] == 1
    assert second.trade_date == first.trade_date


def test_get_sector_overview_uses_latest_well_covered_feature_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 6, 29),
                    features={
                        "sector_strength_score": 82,
                        "sector_breadth_score": 74,
                        "sector_momentum_score": 78,
                        "sector_stock_count": 42,
                        "sector_up_count": 30,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="银行",
                    trade_date=date(2026, 6, 29),
                    features={
                        "sector_strength_score": 58,
                        "sector_breadth_score": 52,
                        "sector_momentum_score": 49,
                        "sector_stock_count": 30,
                        "sector_up_count": 16,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="IT设备",
                    trade_date=date(2026, 6, 30),
                    features={
                        "sector_strength_score": 68,
                        "sector_breadth_score": 100,
                        "sector_momentum_score": 66,
                        "sector_stock_count": 1,
                        "sector_up_count": 1,
                    },
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="行业",
                    ts_code="BK001",
                    name="半导体",
                    pct_change=Decimal("0.0400"),
                    close=Decimal("143"),
                    net_amount=Decimal("350000000"),
                    net_amount_rate=Decimal("0.0860"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="行业",
                    ts_code="BK002",
                    name="银行",
                    pct_change=Decimal("0.0100"),
                    close=Decimal("104"),
                    net_amount=Decimal("50000000"),
                    net_amount_rate=Decimal("0.0120"),
                ),
            ]
        )
        db.commit()

        payload = get_sector_overview(db=db)

    sectors = {item.sector_name: item for item in payload.sectors}
    assert payload.feature_trade_date == date(2026, 6, 29)
    assert payload.feature_sector_count == 2
    assert payload.overview_sector_count == 2
    assert payload.feature_coverage_ratio == 1
    assert sectors["半导体"].sector_strength_score == 82.0
    assert sectors["半导体"].sector_momentum_score == 78.0
    assert "IT设备" not in sectors


def test_get_sector_overview_does_not_use_future_feature_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 6, 29),
                    features={
                        "sector_strength_score": 70,
                        "sector_breadth_score": 66,
                        "sector_momentum_score": 72,
                        "sector_stock_count": 42,
                        "sector_up_count": 26,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 7, 1),
                    features={
                        "sector_strength_score": 99,
                        "sector_breadth_score": 99,
                        "sector_momentum_score": 99,
                        "sector_stock_count": 42,
                        "sector_up_count": 42,
                    },
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="行业",
                    ts_code="BK001",
                    name="半导体",
                    pct_change=Decimal("0.0400"),
                    close=Decimal("143"),
                    net_amount=Decimal("350000000"),
                    net_amount_rate=Decimal("0.0860"),
                ),
            ]
        )
        db.commit()

        payload = get_sector_overview(db=db)

    item = payload.sectors[0]
    assert payload.trade_date == date(2026, 6, 30)
    assert payload.feature_trade_date == date(2026, 6, 29)
    assert item.sector_strength_score == 70.0
    assert item.sector_momentum_score == 72.0


def test_live_market_overview_keeps_breadth_when_index_source_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        market,
        "fetch_realtime_quotes",
        lambda: [
            market.RealtimeQuoteRow(
                symbol="000001",
                trade_date="2026-06-25",
                quote_time=datetime(2026, 6, 25, 10, 0),
                price=Decimal("11"),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("10"),
                pre_close=Decimal("10"),
                pct_change=Decimal("10"),
                volume=Decimal("100"),
                amount=Decimal("1000"),
                turnover_rate=None,
            ),
            market.RealtimeQuoteRow(
                symbol="000002",
                trade_date="2026-06-25",
                quote_time=datetime(2026, 6, 25, 10, 0),
                price=Decimal("9"),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("9"),
                pre_close=Decimal("10"),
                pct_change=Decimal("-10"),
                volume=Decimal("100"),
                amount=Decimal("2000"),
                turnover_rate=None,
            ),
        ],
    )
    monkeypatch.setattr(market, "_live_market_indexes", lambda: (_ for _ in ()).throw(RuntimeError))
    monkeypatch.setattr(
        market,
        "_sina_direct_live_market_indexes",
        lambda: (_ for _ in ()).throw(RuntimeError),
        raising=False,
    )
    monkeypatch.setattr(
        market,
        "_eastmoney_live_market_indexes",
        lambda: (_ for _ in ()).throw(RuntimeError),
        raising=False,
    )

    payload = market._eastmoney_a_share_overview()

    assert payload.up_count == 1
    assert payload.down_count == 1
    assert payload.indexes == []


def test_safe_live_market_indexes_falls_back_to_eastmoney_when_sina_fails(monkeypatch) -> None:
    expected = [
        market.MarketIndexResponse(
            code="399001",
            name="深成",
            quote_date=date(2026, 6, 25),
            price=101.5,
            change_pct=0.0123,
            amount=123000000.0,
            source="akshare.stock_zh_index_spot_em",
        )
    ]
    monkeypatch.setattr(
        market,
        "_live_market_indexes",
        lambda: (_ for _ in ()).throw(RuntimeError("sina returned html")),
    )
    monkeypatch.setattr(
        market,
        "_sina_direct_live_market_indexes",
        lambda: (_ for _ in ()).throw(RuntimeError("direct sina timeout")),
        raising=False,
    )
    monkeypatch.setattr(market, "_eastmoney_live_market_indexes", lambda: expected, raising=False)

    payload = market._safe_live_market_indexes()

    assert payload == expected


def test_safe_live_market_indexes_falls_back_to_direct_sina_when_akshare_sina_fails(
    monkeypatch,
) -> None:
    expected = [
        market.MarketIndexResponse(
            code="sh000001",
            name="上证",
            quote_date=date(2026, 6, 25),
            price=3000.5,
            change_pct=0.0123,
            amount=123000000.0,
            source="sina.hq.sinajs.cn",
        )
    ]
    monkeypatch.setattr(
        market,
        "_live_market_indexes",
        lambda: (_ for _ in ()).throw(RuntimeError("akshare sina returned html")),
    )
    monkeypatch.setattr(
        market,
        "_sina_direct_live_market_indexes",
        lambda: expected,
        raising=False,
    )
    monkeypatch.setattr(
        market,
        "_eastmoney_live_market_indexes",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney disconnected")),
        raising=False,
    )

    payload = market._safe_live_market_indexes()

    assert payload == expected


def test_sina_direct_live_market_indexes_parses_quote_response(monkeypatch) -> None:
    class FakeResponse:
        content = (
            'var hq_str_sh000001="上证指数,3000.00,2970.00,3006.00,3010.00,2960.00,'
            '0,0,100000,120000000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
            '2026-06-25,14:30:00,00,";\n'
            'var hq_str_sz399001="深证成指,10000.00,10100.00,9999.00,10200.00,9900.00,'
            '0,0,200000,220000000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
            '2026-06-25,14:30:00,00";\n'
            'var hq_str_sz399006="创业板指,2000.00,2000.00,2040.00,2050.00,1980.00,'
            '0,0,300000,330000000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
            '2026-06-25,14:30:00,00";'
        ).encode("gbk")

        def raise_for_status(self) -> None:
            return None

    captured: dict[str, object] = {}

    def fake_get(url: str, *, headers: dict[str, str], timeout: int) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)

    rows = market._sina_direct_live_market_indexes()

    assert captured["url"] == "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006"
    assert captured["timeout"] == 8
    assert [item.code for item in rows] == ["sh000001", "sz399001", "sz399006"]
    assert rows[0].price == 3006.0
    assert rows[0].change_pct == round(3006.0 / 2970.0 - 1, 6)
    assert rows[1].change_pct == round(9999.0 / 10100.0 - 1, 6)
    assert rows[2].amount == 330000000.0
    assert {item.source for item in rows} == {"sina.hq.sinajs.cn"}


def test_market_index_rows_use_canonical_order_and_tolerate_blank_values() -> None:
    df = pd.DataFrame(
        [
            {"代码": "399006", "最新价": "--", "涨跌幅": "--", "成交额": "--"},
            {"代码": "000001", "最新价": "3000.5", "涨跌幅": "1.23", "成交额": "100"},
            {"代码": "399001", "最新价": "12000", "涨跌幅": "-0.50", "成交额": "200"},
        ]
    )

    rows = market._market_index_rows_from_spot(df, source="test")

    assert [item.code for item in rows] == ["sh000001", "sz399001", "sz399006"]
    assert [item.name for item in rows] == ["上证", "深成", "创业板"]
    assert rows[0].price == 3000.5
    assert rows[0].change_pct == 0.0123
    assert rows[1].change_pct == -0.005
    assert rows[2].price is None
    assert rows[2].change_pct is None
    assert rows[2].amount is None


def test_get_sector_replay_returns_mainline_events(monkeypatch) -> None:
    monkeypatch.setattr(
        market,
        "replay_sector_month",
        lambda month, sector, horizons: SectorReplayResult(
            month=month,
            sector=sector,
            events=[
                SectorReplayEvent(
                    trade_date="2026-06-18",
                    coverage_ratio=0.90,
                    qualifies_hot=True,
                    setup_label="mainline_confirmed",
                    extension_risk="normal",
                    strength_score=75.3,
                    continuity_score=76.4,
                    resilience_score=63.0,
                    avg_return_20d=0.11,
                    positive_20d_rate=65.2,
                    stock_count=188,
                    forward_returns={5: 0.07, 10: None},
                )
            ],
        ),
    )

    payload = get_sector_replay(month="2026-06", sector="半导体")

    assert payload.month == "2026-06"
    assert payload.sector == "半导体"
    assert payload.events[0].setup_label == "mainline_confirmed"
    assert payload.events[0].forward_returns[5] == 0.07


def test_get_sector_catalysts_groups_messages_without_overriding_trend(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        market,
        "fetch_market_hot_messages",
        lambda: [
            {
                "source": "akshare.stock_hot_keyword_em",
                "keyword": "暑期文旅",
                "title": "暑期文旅消费和酒店预订热度上行",
                "heat": 92,
            },
            {
                "source": "akshare.stock_hot_keyword_em",
                "keyword": "电影票房",
                "title": "电影票房带动影视院线活跃",
                "heat": 70,
            },
            {
                "source": "akshare.stock_hot_rank_em",
                "keyword": "AI算力",
                "title": "算力和半导体热度仍在前排",
                "heat": 64,
            },
            {
                "source": "noise",
                "keyword": "利好",
                "title": "市场消息较多",
                "heat": 99,
            },
        ],
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        payload = get_sector_catalysts(db=db, limit=5)

    sectors = {item.sector_name: item for item in payload.catalysts}
    assert "消费" in sectors
    assert "科技" in sectors
    assert "利好" not in sectors
    assert sectors["消费"].catalyst_score > sectors["科技"].catalyst_score
    assert "暑期文旅" in sectors["消费"].keywords
    assert "旅游酒店" in sectors["消费"].related_sectors
    assert any("消息只做催化" in note for note in sectors["消费"].risk_notes)


def test_get_sector_catalysts_reuses_short_cache(monkeypatch) -> None:
    calls = {"count": 0}

    def fetch_messages() -> list[dict[str, object]]:
        calls["count"] += 1
        return [
            {
                "source": "akshare.stock_hot_keyword_em",
                "keyword": "暑期消费",
                "title": "暑期消费热度上行",
                "heat": 88,
            }
        ]

    monkeypatch.setattr(market, "_SECTOR_CATALYST_CACHE", None)
    monkeypatch.setattr(market, "fetch_market_hot_messages", fetch_messages)
    monkeypatch.setattr(market, "monotonic", lambda: 1000.0)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        first = get_sector_catalysts(db=db, limit=3)
        second = get_sector_catalysts(db=db, limit=3)

    assert calls["count"] == 1
    assert first.catalysts[0].sector_name == "消费"
    assert second.catalysts[0].sector_name == "消费"


def test_get_sector_catalysts_persists_and_reuses_database_snapshot(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    calls = {"count": 0}

    def fetch_messages() -> list[dict[str, object]]:
        calls["count"] += 1
        return [
            {
                "source": "akshare.stock_hot_keyword_em",
                "keyword": "暑期消费",
                "title": "暑期文旅消费热度上行",
                "heat": 90,
            }
        ]

    monkeypatch.setattr(market, "_SECTOR_CATALYST_CACHE", None)
    monkeypatch.setattr(market, "fetch_market_hot_messages", fetch_messages)
    monkeypatch.setattr(market, "now_local", lambda: datetime(2026, 7, 1, 10, 30))
    monkeypatch.setattr(market, "monotonic", lambda: 1000.0)

    with session() as db:
        first = get_sector_catalysts(db=db, limit=3)
        monkeypatch.setattr(market, "_SECTOR_CATALYST_CACHE", None)
        second = get_sector_catalysts(db=db, limit=3)
        stored_count = db.query(MarketMessageSnapshot).count()

    assert calls["count"] == 1
    assert stored_count == 1
    assert first.catalysts[0].sector_name == "消费"
    assert second.catalysts[0].sector_name == "消费"
    assert second.snapshot_id == first.snapshot_id


def test_get_sector_catalysts_applies_limit_to_reused_snapshot(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(market, "_SECTOR_CATALYST_CACHE", None)
    monkeypatch.setattr(market, "now_local", lambda: datetime(2026, 7, 1, 10, 30))
    monkeypatch.setattr(market, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(
        market,
        "fetch_market_hot_messages",
        lambda: [
            {"source": "hot", "keyword": "暑期消费", "title": "消费热", "heat": 90},
            {"source": "hot", "keyword": "AI算力", "title": "科技热", "heat": 88},
            {"source": "hot", "keyword": "黄金有色", "title": "周期热", "heat": 80},
        ],
    )

    with session() as db:
        get_sector_catalysts(db=db, limit=3)
        monkeypatch.setattr(market, "_SECTOR_CATALYST_CACHE", None)
        reused = get_sector_catalysts(db=db, limit=1)

    assert len(reused.catalysts) == 1
