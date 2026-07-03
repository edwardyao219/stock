import time
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.routers import market
from apps.api.app.routers.market import (
    get_data_health,
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
    MarketMessageSnapshot,
    SectorDaily,
    SectorFeatureDaily,
    Security,
    StockFeatureDaily,
    TushareMoneyflowIndDc,
)


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
    assert payload.indexes == []


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


def test_get_market_overview_live_falls_back_when_live_snapshot_is_slow(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
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

        def slow_live_snapshot() -> market.MarketOverviewResponse:
            time.sleep(0.2)
            return market.MarketOverviewResponse(
                trade_date=date(2026, 7, 2),
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
                message="slow live",
                indexes=[],
            )

        monkeypatch.setattr(market, "_LIVE_MARKET_CACHE", None)
        monkeypatch.setattr(market, "_cached_live_a_share_overview", slow_live_snapshot)
        monkeypatch.setattr(market, "_stored_market_overview", lambda db: stored_payload)
        monkeypatch.setattr(market, "LIVE_MARKET_TIMEOUT_SECONDS", 0.001, raising=False)

        started = time.monotonic()
        payload = get_market_overview(db=db, live=True)
        elapsed = time.monotonic() - started

    assert elapsed < 0.08
    assert payload.message == "stored"
    assert [item.code for item in payload.indexes] == ["sh000001"]


def test_get_data_health_returns_daily_feature_diagnostics() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
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
        db.commit()

        payload = get_data_health(db=db, trade_date="2026-06-30")

    assert payload.trade_date == date(2026, 6, 30)
    assert payload.status == "ok"
    assert payload.daily_bar_count == 1
    assert payload.feature_count == 1
    assert payload.amount_ratio_5d_median == 0.92


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
    assert payload.sectors[0].month_rank == 1
    assert round(payload.sectors[0].monthly_return_pct or 0, 4) == 0.18
    assert payload.sectors[0].fund_flow_net_amount == 350000000.0
    assert payload.sectors[0].sector_strength_score == 82.0


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
