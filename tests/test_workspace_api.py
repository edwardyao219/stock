from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.routers.workspace import (
    ManualStockRequest,
    _early_hot_sector_quote_coverage,
    _intraday_snapshots_for_points,
    _sustained_startup_sectors,
    add_manual_stock,
    get_startup_tracking,
    get_workspace_stock,
    list_intraday_candidate_snapshots,
    list_intraday_candidates,
    list_workspace_stocks,
    refresh_workspace_stocks,
)
from services.collector.contracts import CollectionResult
from services.engine.research_pool import manual_research
from services.engine.workspace import repository as workspace_repository
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    IntradayMarketTurnSnapshot,
    PaperAccount,
    PaperPosition,
    RealtimeQuote,
    ResearchPoolItem,
    SectorFeatureDaily,
    Security,
    TradePlan,
)


def test_get_startup_tracking_excludes_manual_focus(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(
        "apps.api.app.routers.workspace.get_candidate_replay_effect",
        lambda: {"scopes": {}},
    )

    with session() as db:
        db.add_all(
            [
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000001",
                    status="active",
                    tags_json={"tags": ["candidate_pool:startup_preheat", "2026-07-01"]},
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000002",
                    status="active",
                    tags_json={"tags": ["candidate_pool:expansion_confirm", "2026-07-01"]},
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000003",
                    status="active",
                    tags_json={"tags": ["manual_focus", "2026-07-01"]},
                ),
            ]
        )
        db.commit()
        payload = get_startup_tracking(db=db)

    assert [row.symbol for row in payload] == ["000001", "000002"]
    assert payload[0].signal_label == "启动观察"
    assert payload[0].historical[5]["sample_count"] == 0
    assert payload[0].current_tracking["realised_return"] is None


def test_list_workspace_stocks_merges_auto_plans_and_manual_pool() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="000001", name="平安银行", exchange="SZ", industry="银行"))
        db.add(ResearchPoolItem(pool_name="manual", symbol="600519", tags_json={"tags": ["白酒"]}))
        db.add(Security(symbol="600519", name="贵州茅台", exchange="SH", industry="白酒"))
        for symbol in ["000001", "600519"]:
            for day in range(1, 22):
                db.add(
                    DailyBar(
                        symbol=symbol,
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
                )
        db.add(
            TradePlan(
                plan_date=date(2026, 1, 21),
                trade_date=date(2026, 1, 22),
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                sector_code=None,
                entry_condition_json={
                    "snapshot": {
                        "industry": "银行",
                        "trend_score": 80,
                        "volume_score": 75,
                        "amount_percentile_60d": 82,
                        "sector_strength_score": 70,
                        "fundamental_score": 72,
                        "fundamental_verdict": "supportive",
                        "fundamental_reasons": ["股息率较高"],
                        "risk_score": 30,
                        "return_5d": 0.02,
                        "return_20d": 0.05,
                        "distance_to_20d_high": -0.03,
                    }
                },
                position_size=Decimal("0.10"),
                confidence_score=Decimal("80"),
                status="planned",
            )
        )
        db.add(
            PaperAccount(
                id=1,
                name="default",
                initial_cash=Decimal("1000000"),
                cash=Decimal("1000000"),
            )
        )
        db.add(
            PaperPosition(
                account_id=1,
                trade_plan_id=1,
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                entry_date=date(2026, 1, 11),
                entry_price=Decimal("10"),
                quantity=1000,
                initial_stop=Decimal("9.5"),
                current_stop=Decimal("10.5"),
                take_profit_1=Decimal("11"),
                take_profit_2=None,
                highest_price=Decimal("11.5"),
                lowest_price=Decimal("9.7"),
                max_holding_days=5,
                status="closed",
                exit_date=date(2026, 1, 15),
                exit_price=Decimal("11"),
                exit_reason="take_profit",
                pnl=Decimal("1000"),
                pnl_pct=Decimal("0.10"),
            )
        )
        db.add(
            RealtimeQuote(
                symbol="000001",
                trade_date=date(2026, 1, 22),
                quote_time=datetime(2026, 1, 22, 10, 5),
                price=Decimal("22"),
                open=Decimal("21"),
                high=Decimal("22.5"),
                low=Decimal("20.5"),
                pre_close=Decimal("20"),
                pct_change=Decimal("10"),
                volume=Decimal("1000"),
                amount=Decimal("22000"),
                turnover_rate=Decimal("1"),
            )
        )
        db.commit()

        payload = list_workspace_stocks(db=db, pool_name="manual")

    assert [item.symbol for item in payload] == ["000001", "600519"]
    assert payload[0].source == "auto"
    assert payload[0].plans[0].rule_id == "R001"
    assert payload[0].plans[0].evidence[0].category == "技术面"
    assert payload[0].plans[0].evidence[3].verdict == "supportive"
    assert payload[0].paper_trade_summaries[0].win_rate == 1
    assert payload[0].paper_trade_summaries[0].closed_count == 1
    assert payload[0].recent_paper_trades[0].entry_date == "2026-01-11"
    assert payload[0].recent_paper_trades[0].highest_price == 11.5
    assert payload[0].current_price == 22
    assert payload[0].day_change_pct == 0.1
    assert payload[0].quote_time == "2026-01-22T10:05:00"
    assert payload[1].source == "manual"
    assert payload[1].manual_tags == ["白酒"]
    assert payload[0].return_5d is not None


def test_list_workspace_stocks_keeps_manual_symbol_without_security_profile() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="002558",
                tags_json={"tags": ["manual_focus"]},
                status="active",
            )
        )
        for day in range(1, 22):
            db.add(
                DailyBar(
                    symbol="002558",
                    trade_date=date(2026, 6, day),
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
            )
        db.commit()

        payload = list_workspace_stocks(db=db, pool_name="experiment")

    assert [item.symbol for item in payload] == ["002558"]
    assert payload[0].name is None
    assert payload[0].industry is None
    assert payload[0].source == "manual"
    assert payload[0].manual_tags == ["manual_focus"]
    assert payload[0].latest_trade_date == "2026-06-21"


def test_workspace_plan_defers_when_intraday_candidate_is_deferred(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="002558", name="巨人网络", exchange="SZ", industry="互联网"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="002558",
                tags_json={"tags": ["manual_focus", "after_close_candidate", "next_session"]},
                status="active",
            )
        )
        db.add(
            SectorFeatureDaily(
                sector_code="互联网",
                trade_date=date(2026, 6, 29),
                features={
                    "sector_strength_score": 35,
                    "sector_trend_continuity_score": 32,
                    "sector_momentum_score": 30,
                    "sector_breadth_score": 30,
                    "sector_avg_return_20d": -0.05,
                    "sector_positive_20d_rate": 28,
                    "sector_stock_count": 20,
                },
            )
        )
        for day in range(1, 22):
            db.add(
                DailyBar(
                    symbol="002558",
                    trade_date=date(2026, 6, day),
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
            )
        db.add(
            TradePlan(
                plan_date=date(2026, 6, 29),
                trade_date=date(2026, 6, 30),
                symbol="002558",
                rule_id="OBS001",
                strategy_type="watch_breakout",
                sector_code="互联网",
                entry_condition_json={"snapshot": {"industry": "互联网", "route_score": 66}},
                entry_trigger_price=Decimal("22"),
                position_size=Decimal("0.03"),
                confidence_score=Decimal("70"),
                status="planned",
            )
        )
        db.add(
            RealtimeQuote(
                symbol="002558",
                trade_date=date(2026, 6, 30),
                quote_time=datetime(2026, 6, 30, 13, 25),
                price=Decimal("22.6"),
                open=Decimal("22"),
                high=Decimal("23"),
                low=Decimal("21.8"),
                pre_close=Decimal("21.5"),
                pct_change=None,
                volume=Decimal("300000"),
                amount=Decimal("6800000"),
                turnover_rate=Decimal("1.2"),
            )
        )
        db.commit()

        monkeypatch.setattr(
            "services.engine.workspace.repository.now_local",
            lambda: datetime(2026, 6, 30, 13, 30),
        )
        monkeypatch.setattr(
            "apps.api.app.routers.workspace._live_market_stress_snapshot",
            lambda db: None,
            raising=False,
        )
        payload = list_workspace_stocks(db=db, pool_name="experiment")

    plan = payload[0].plans[0]
    assert plan.can_buy_now is False
    assert plan.execution_status == "intraday_defer"
    assert plan.execution_label == "盘中暂缓"
    assert "板块弱势" in plan.execution_note


def test_workspace_plan_defers_when_live_market_is_risk_off(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="002558", name="巨人网络", exchange="SZ", industry="互联网"))
        for day in range(1, 22):
            db.add(
                DailyBar(
                    symbol="002558",
                    trade_date=date(2026, 6, day),
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
            )
        db.add(
            TradePlan(
                plan_date=date(2026, 6, 29),
                trade_date=date(2026, 6, 30),
                symbol="002558",
                rule_id="OBS001",
                strategy_type="watch_breakout",
                sector_code="互联网",
                entry_condition_json={"snapshot": {"industry": "互联网", "route_score": 66}},
                entry_trigger_price=Decimal("22"),
                position_size=Decimal("0.03"),
                confidence_score=Decimal("70"),
                status="planned",
            )
        )
        db.commit()

        monkeypatch.setattr(
            "services.engine.workspace.repository.now_local",
            lambda: datetime(2026, 6, 30, 13, 30),
        )
        monkeypatch.setattr(
            "apps.api.app.routers.workspace._live_market_stress_snapshot",
            lambda db: {
                "stress_status": "risk_off",
                "stress_label": "压力大",
                "risk_action_label": "停止扩散，只做观察和风控",
                "stress_reasons": ["上涨占比仅12%，市场宽度明显不足"],
            },
            raising=False,
        )
        payload = list_workspace_stocks(db=db, pool_name="experiment")

    plan = payload[0].plans[0]
    assert plan.can_buy_now is False
    assert plan.execution_status == "market_risk_off"
    assert plan.execution_label == "市场压力暂缓"
    assert "上涨占比仅12%" in plan.execution_note


def test_add_manual_stock_uses_local_security_when_remote_security_sync_fails(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="002558", name="巨人网络", exchange="SZ", industry="互联网"))
        db.commit()

    class _DbFactory:
        def __call__(self):
            return session()

    def fake_sync_stock_daily_bars(symbols):
        assert symbols == ["002558"]
        with session() as db:
            for day in range(1, 22):
                db.add(
                    DailyBar(
                        symbol="002558",
                        trade_date=date(2026, 6, day),
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
                )
            db.commit()
        return [
            CollectionResult(
                source="test",
                dataset="stock_daily:002558",
                trade_date="2026-06-21",
                rows=21,
                status="ok",
            )
        ]

    monkeypatch.setattr(manual_research, "SessionLocal", _DbFactory())
    def fail_security_sync(_symbol):
        raise ConnectionError("remote down")

    monkeypatch.setattr(manual_research, "fetch_stock_security", fail_security_sync)
    monkeypatch.setattr(manual_research, "sync_stock_daily_bars", fake_sync_stock_daily_bars)
    monkeypatch.setattr(
        manual_research,
        "compute_and_store_stock_features",
        lambda **_kwargs: {"rows": 1},
    )
    monkeypatch.setattr(
        manual_research,
        "compute_and_store_sector_features",
        lambda **_kwargs: {"rows": 0},
    )
    monkeypatch.setattr(
        manual_research,
        "sync_fundamentals_from_akshare",
        lambda **_kwargs: {"ok": 0, "results": []},
    )
    monkeypatch.setattr(
        manual_research,
        "generate_and_store_trade_plans",
        lambda **_kwargs: {"written": 0},
    )
    monkeypatch.setattr(
        manual_research,
        "generate_watchlist_observation_plans",
        lambda **_kwargs: {"written": 0},
    )

    with session() as db:
        payload = add_manual_stock(
            payload=ManualStockRequest(
                symbol="002558",
                pool_name="experiment",
                refresh_research=True,
            ),
            db=db,
        )

    assert payload.symbol == "002558"
    assert payload.name == "巨人网络"
    assert payload.manual_refresh is not None
    assert payload.manual_refresh.security_rows == 1
    assert any("使用本地证券信息" in item for item in payload.manual_refresh.warnings)


def test_list_intraday_candidates_returns_live_candidate_watchlist(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="600001", name="盘中票", exchange="SH", industry="通信设备"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="600001",
                tags_json={
                    "tags": ["after_close_candidate", "next_session", "rank:1", "score:88"]
                },
                status="active",
            )
        )
        db.add(
            RealtimeQuote(
                symbol="600001",
                trade_date=date(2026, 1, 22),
                quote_time=datetime(2026, 1, 22, 10, 5),
                price=Decimal("10.6"),
                open=Decimal("10"),
                high=Decimal("10.8"),
                low=Decimal("9.9"),
                pre_close=Decimal("10"),
                pct_change=None,
                volume=Decimal("100000"),
                amount=Decimal("1000000"),
                turnover_rate=Decimal("1.2"),
            )
        )
        db.commit()

        monkeypatch.setattr(
            "apps.api.app.routers.workspace.now_local",
            lambda: datetime(2026, 1, 22, 10, 10),
            raising=False,
        )
        payload = list_intraday_candidates(db=db, pool_name="experiment")

    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["symbol"] == "600001"
    assert payload["candidates"][0]["intraday_score"] > 0


def test_sustained_startup_sectors_uses_latest_ready_snapshot() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(
            IntradayMarketTurnSnapshot(
                trade_date=date(2026, 1, 22),
                snapshot_time=datetime(2026, 1, 22, 10, 20),
                coverage_ratio=0.99,
                breadth_ratio=0.58,
                total_amount=123.0,
                index_change_pct=0.003,
                sector_expansion_count=3,
                state_json={
                    "data_ready": True,
                    "leading_sustained_sectors": [{"sector": "半导体"}],
                    "cross_day_mainline": {
                        "status": "观察确认",
                        "confirmed_sectors": ["半导体"],
                    },
                },
            )
        )
        db.commit()

        result = _sustained_startup_sectors(
            db,
            trade_date=date(2026, 1, 22),
            as_of=datetime(2026, 1, 22, 10, 30),
        )

    assert result == {"半导体"}


def test_sustained_startup_sectors_fails_closed_when_cross_day_mainline_is_unconfirmed() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(
            IntradayMarketTurnSnapshot(
                trade_date=date(2026, 1, 22),
                snapshot_time=datetime(2026, 1, 22, 9, 45),
                coverage_ratio=0.99,
                breadth_ratio=0.58,
                total_amount=123.0,
                index_change_pct=0.003,
                sector_expansion_count=3,
                state_json={
                    "data_ready": True,
                    "leading_sustained_sectors": [{"sector": "半导体"}],
                    "cross_day_mainline": {
                        "status": "未确认",
                        "confirmed_sectors": [],
                    },
                },
            )
        )
        db.commit()

        result = _sustained_startup_sectors(
            db,
            trade_date=date(2026, 1, 22),
            as_of=datetime(2026, 1, 22, 10, 0),
        )

    assert result == set()


def test_sustained_startup_sectors_fails_closed_without_a_ready_snapshot() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        result = _sustained_startup_sectors(
            db,
            trade_date=date(2026, 1, 22),
            as_of=datetime(2026, 1, 22, 10, 0),
        )

    assert result == set()


def test_intraday_candidate_snapshots_apply_the_same_fail_closed_mainline_gate(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def fake_discover(_db, **kwargs):
        tier = "watch" if kwargs.get("sustained_startup_sectors") == set() else "formal"
        return {"candidate_count": 1, "candidates": [{"symbol": "600001", "selection_tier": tier}]}

    with session() as db:
        monkeypatch.setattr(
            "apps.api.app.routers.workspace.discover_intraday_candidates",
            fake_discover,
        )
        snapshots = _intraday_snapshots_for_points(
            db,
            trade_date=date(2026, 1, 22),
            points=[("early_divergence", "早盘分歧", datetime(2026, 1, 22, 9, 45))],
            pool_name="experiment",
            limit=8,
            include_growth_board=False,
        )

    assert snapshots[0]["candidates"][0]["selection_tier"] == "watch"


def test_workspace_plan_guard_fails_closed_without_a_ready_mainline_snapshot(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def fake_discover(_db, **kwargs):
        tier = "watch" if kwargs.get("sustained_startup_sectors") == set() else "formal"
        return {
            "candidates": [
                {
                    "symbol": "600001",
                    "selection_tier": tier,
                    "selection_tier_label": "观察确认",
                    "selection_reason": "跨日主线未确认",
                    "intraday_label": "强势延续",
                    "sector_signal_label": "强势板块确认",
                }
            ]
        }

    with session() as db:
        monkeypatch.setattr(
            "services.engine.workspace.repository.now_local",
            lambda: datetime(2026, 1, 22, 10, 0),
        )
        monkeypatch.setattr(
            "services.engine.workspace.repository._is_open_trade_date",
            lambda _db, _trade_date: True,
        )
        monkeypatch.setattr(
            "services.engine.workspace.repository.discover_intraday_candidates",
            fake_discover,
        )
        guards = workspace_repository._load_intraday_plan_guards(
            db,
            pool_name="experiment",
            include_growth_board=False,
        )

    assert "600001" in guards


def test_list_intraday_candidates_honors_as_of_without_future_quotes(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="600001", name="午间票", exchange="SH", industry="通信设备"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="600001",
                tags_json={"tags": ["after_close_candidate", "next_session", "rank:1", "score:88"]},
                status="active",
            )
        )
        for quote_time, price in [
            (datetime(2026, 1, 22, 11, 20), "10.2"),
            (datetime(2026, 1, 22, 14, 50), "9.7"),
        ]:
            db.add(
                RealtimeQuote(
                    symbol="600001",
                    trade_date=quote_time.date(),
                    quote_time=quote_time,
                    price=Decimal(price),
                    open=Decimal("10"),
                    high=Decimal("10.8"),
                    low=Decimal("9.7"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100000"),
                    amount=Decimal("1000000"),
                    turnover_rate=Decimal("1.2"),
                )
            )
        db.commit()

        monkeypatch.setattr(
            "apps.api.app.routers.workspace.now_local",
            lambda: datetime(2026, 1, 22, 14, 55),
            raising=False,
        )
        payload = list_intraday_candidates(
            db=db,
            pool_name="experiment",
            as_of="2026-01-22T11:30:00",
        )

    assert payload["as_of"] == "2026-01-22T11:30:00"
    assert payload["candidates"][0]["quote_time"] == "2026-01-22T11:20:00"
    assert payload["candidates"][0]["review_window"] == "midday"


def test_list_intraday_candidates_defaults_as_of_to_current_time(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="600001", name="当前票", exchange="SH", industry="通信设备"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="600001",
                tags_json={"tags": ["after_close_candidate", "next_session", "rank:1", "score:88"]},
                status="active",
            )
        )
        for quote_time, price in [
            (datetime(2026, 1, 22, 10, 5), "10.2"),
            (datetime(2026, 1, 22, 14, 50), "9.7"),
        ]:
            db.add(
                RealtimeQuote(
                    symbol="600001",
                    trade_date=quote_time.date(),
                    quote_time=quote_time,
                    price=Decimal(price),
                    open=Decimal("10"),
                    high=Decimal("10.8"),
                    low=Decimal("9.7"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100000"),
                    amount=Decimal("1000000"),
                    turnover_rate=Decimal("1.2"),
                )
            )
        db.commit()

        monkeypatch.setattr(
            "apps.api.app.routers.workspace.now_local",
            lambda: datetime(2026, 1, 22, 10, 10),
            raising=False,
        )
        payload = list_intraday_candidates(db=db, pool_name="experiment")

    assert payload["as_of"] == "2026-01-22T10:10:00"
    assert payload["candidates"][0]["quote_time"] == "2026-01-22T10:05:00"
    assert payload["candidates"][0]["price"] == 10.2


def test_list_intraday_candidates_passes_live_market_stress_only_for_current(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    captured: list[dict] = []

    def fake_discover_intraday_candidates(db, **kwargs):
        captured.append(kwargs)
        return {
            "trade_date": kwargs["trade_date"].isoformat(),
            "as_of": kwargs["as_of"].isoformat(timespec="seconds"),
            "pool_name": kwargs["pool_name"],
            "candidate_count": 0,
            "candidate_batch": {
                "auto_feature_date": None,
                "auto_hold_until": None,
                "source_item_count": 0,
                "usable_item_count": 0,
                "current_auto_candidate_count": 0,
                "manual_focus_count": 0,
                "stale_auto_candidate_count": 0,
            },
            "market_stress": kwargs.get("market_stress"),
            "candidates": [],
        }

    with session() as db:
        monkeypatch.setattr(
            "apps.api.app.routers.workspace.now_local",
            lambda: datetime(2026, 1, 22, 10, 10),
            raising=False,
        )
        monkeypatch.setattr(
            "apps.api.app.routers.workspace.discover_intraday_candidates",
            fake_discover_intraday_candidates,
        )
        monkeypatch.setattr(
            "apps.api.app.routers.workspace._live_market_stress_snapshot",
            lambda db: {"stress_status": "risk_off", "stress_label": "压力大"},
            raising=False,
        )

        current_payload = list_intraday_candidates(db=db, pool_name="experiment")
        historical_payload = list_intraday_candidates(
            db=db,
            pool_name="experiment",
            as_of="2026-01-21T10:00:00",
        )

    assert current_payload["market_stress"]["stress_status"] == "risk_off"
    assert historical_payload["market_stress"] is None
    assert captured[0]["market_stress"]["stress_status"] == "risk_off"
    assert captured[1]["market_stress"] is None


def test_list_intraday_candidates_refresh_includes_quotes_returned_after_request_start(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="600001", name="盘中新票", exchange="SH", industry="通信设备"),
                Security(symbol="600216", name="热门板块票", exchange="SH", industry="机器人"),
                SectorFeatureDaily(
                    sector_code="机器人",
                    trade_date=date(2026, 1, 21),
                    features={
                        "sector_strength_score": 82,
                        "sector_trend_continuity_score": 78,
                        "sector_momentum_score": 75,
                        "sector_breadth_score": 68,
                        "sector_avg_return_20d": 0.12,
                        "sector_positive_20d_rate": 70,
                        "sector_stock_count": 12,
                    },
                ),
            ]
        )
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="600001",
                tags_json={"tags": ["after_close_candidate", "next_session", "rank:1", "score:88"]},
                status="active",
            )
        )
        db.commit()

        refreshed: dict[str, object] = {}
        rollback_calls = 0
        original_rollback = db.rollback

        def track_rollback():
            nonlocal rollback_calls
            rollback_calls += 1
            original_rollback()

        monkeypatch.setattr(db, "rollback", track_rollback)

        def fake_sync(symbols, quote_time=None):
            refreshed["symbols"] = set(symbols)
            refreshed["quote_time"] = quote_time
            db.add(
                RealtimeQuote(
                    symbol="600001",
                    trade_date=date(2026, 1, 22),
                    quote_time=datetime(2026, 1, 22, 10, 10, 20),
                    price=Decimal("10.8"),
                    open=Decimal("10"),
                    high=Decimal("10.9"),
                    low=Decimal("9.9"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("180000"),
                    amount=Decimal("1800000"),
                    turnover_rate=Decimal("1.2"),
                )
            )
            db.commit()
            return []

        monkeypatch.setattr("apps.api.app.routers.workspace.sync_realtime_quotes", fake_sync)
        clock = iter(
            [
                datetime(2026, 1, 22, 10, 10),
                datetime(2026, 1, 22, 10, 10, 30),
            ]
        )
        monkeypatch.setattr(
            "apps.api.app.routers.workspace.now_local",
            lambda: next(clock),
            raising=False,
        )
        payload = list_intraday_candidates(
            db=db,
            pool_name="experiment",
            refresh_quotes=True,
        )

    assert refreshed == {
        "symbols": {"600001", "600216"},
        "quote_time": datetime(2026, 1, 22, 10, 10),
    }
    assert rollback_calls == 1
    assert payload["as_of"] == "2026-01-22T10:10:30"
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["symbol"] == "600001"
    assert payload["candidates"][0]["quote_time"] == "2026-01-22T10:10:20"


def test_list_intraday_candidates_reports_early_hot_sector_quote_coverage(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="600216", name="已刷快照", exchange="SH", industry="机器人"),
                Security(symbol="600217", name="未刷快照", exchange="SH", industry="机器人"),
                Security(symbol="600218", name="陈旧快照", exchange="SH", industry="机器人"),
                Security(symbol="688216", name="科创默认不看", exchange="SH", industry="机器人"),
                SectorFeatureDaily(
                    sector_code="机器人",
                    trade_date=date(2026, 1, 21),
                    features={
                        "sector_strength_score": 82,
                        "sector_trend_continuity_score": 78,
                        "sector_momentum_score": 75,
                        "sector_breadth_score": 68,
                        "sector_avg_return_20d": 0.12,
                        "sector_positive_20d_rate": 70,
                        "sector_stock_count": 12,
                    },
                ),
                RealtimeQuote(
                    symbol="600216",
                    trade_date=date(2026, 1, 22),
                    quote_time=datetime(2026, 1, 22, 9, 44),
                    price=Decimal("10.6"),
                    open=Decimal("10"),
                    high=Decimal("10.8"),
                    low=Decimal("9.9"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100000"),
                    amount=Decimal("1000000"),
                    turnover_rate=Decimal("1.2"),
                ),
                RealtimeQuote(
                    symbol="600217",
                    trade_date=date(2026, 1, 22),
                    quote_time=datetime(2026, 1, 22, 9, 50),
                    price=Decimal("10.5"),
                    open=Decimal("10"),
                    high=Decimal("10.8"),
                    low=Decimal("9.9"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100000"),
                    amount=Decimal("1000000"),
                    turnover_rate=Decimal("1.2"),
                ),
                RealtimeQuote(
                    symbol="600218",
                    trade_date=date(2026, 1, 22),
                    quote_time=datetime(2026, 1, 22, 9, 30),
                    price=Decimal("10.5"),
                    open=Decimal("10"),
                    high=Decimal("10.8"),
                    low=Decimal("9.9"),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100000"),
                    amount=Decimal("1000000"),
                    turnover_rate=Decimal("1.2"),
                ),
            ]
        )
        db.commit()

        monkeypatch.setattr(
            "apps.api.app.routers.workspace.now_local",
            lambda: datetime(2026, 1, 22, 9, 45),
            raising=False,
        )
        payload = list_intraday_candidates(
            db=db,
            pool_name="experiment",
            as_of="2026-01-22T09:45:00",
        )

    coverage = payload["quote_coverage"]
    assert coverage["target_symbol_count"] == 3
    assert coverage["valid_quote_count"] == 1
    assert coverage["coverage_ratio"] == 0.3333
    assert coverage["latest_quote_time"] == "2026-01-22T09:44:00"
    assert coverage["missing_symbols"] == ["600217", "600218"]
    assert coverage["sectors"] == [
        {
            "sector": "机器人",
            "target_symbol_count": 3,
            "valid_quote_count": 1,
            "coverage_ratio": 0.3333,
            "missing_symbols": ["600217", "600218"],
        }
    ]


def test_list_intraday_candidates_uses_as_of_trade_date_across_dependencies(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    captured = {}

    def fake_sustained(db, *, trade_date, as_of):
        captured["sustained_trade_date"] = trade_date
        return set()

    def fake_discover(db, *, trade_date, **kwargs):
        captured["discover_trade_date"] = trade_date
        return {"candidates": []}

    def fake_coverage(db, *, trade_date, **kwargs):
        captured["coverage_trade_date"] = trade_date
        return {}

    monkeypatch.setattr(
        "apps.api.app.routers.workspace.now_local",
        lambda: datetime(2026, 1, 22, 10, 10),
    )
    monkeypatch.setattr(
        "apps.api.app.routers.workspace._sustained_startup_sectors",
        fake_sustained,
    )
    monkeypatch.setattr(
        "apps.api.app.routers.workspace.discover_intraday_candidates",
        fake_discover,
    )
    monkeypatch.setattr(
        "apps.api.app.routers.workspace._early_hot_sector_quote_coverage",
        fake_coverage,
    )

    with session() as db:
        list_intraday_candidates(
            db=db,
            pool_name="experiment",
            as_of="2026-01-21T10:00:00",
        )

    assert captured == {
        "sustained_trade_date": date(2026, 1, 21),
        "discover_trade_date": date(2026, 1, 21),
        "coverage_trade_date": date(2026, 1, 21),
    }


def test_early_hot_sector_quote_coverage_keeps_lunch_close_quote(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="600216", name="午休快照", exchange="SH", industry="机器人"))
        db.add(
            RealtimeQuote(
                symbol="600216",
                trade_date=date(2026, 1, 22),
                quote_time=datetime(2026, 1, 22, 11, 29),
                price=Decimal("10.6"),
                open=Decimal("10"),
                high=Decimal("10.8"),
                low=Decimal("9.9"),
                pre_close=Decimal("10"),
                pct_change=None,
                volume=Decimal("100000"),
                amount=Decimal("1000000"),
                turnover_rate=Decimal("1.2"),
            )
        )
        db.commit()
        monkeypatch.setattr(
            "apps.api.app.routers.workspace.early_sector_scan_symbols",
            lambda *args, **kwargs: ["600216"],
        )

        coverage = _early_hot_sector_quote_coverage(
            db,
            trade_date=date(2026, 1, 22),
            as_of=datetime(2026, 1, 22, 12, 15),
            include_growth_board=False,
        )

    assert coverage["valid_quote_count"] == 1
    assert coverage["latest_quote_time"] == "2026-01-22T11:29:00"


def test_early_hot_sector_quote_coverage_scans_sectors_at_as_of(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    captured = {}

    def fake_scan(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "apps.api.app.routers.workspace.early_sector_scan_symbols",
        fake_scan,
    )
    as_of = datetime(2026, 1, 22, 10, 15)
    with session() as db:
        _early_hot_sector_quote_coverage(
            db,
            trade_date=date(2026, 1, 22),
            as_of=as_of,
            include_growth_board=False,
        )

    assert captured["as_of"] == as_of


def test_list_intraday_candidate_snapshots_replays_without_future_quotes(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="600001", name="快照票", exchange="SH", industry="通信设备"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="600001",
                tags_json={"tags": ["after_close_candidate", "next_session", "rank:1", "score:88"]},
                status="active",
            )
        )
        for quote_time, price, high, low in [
            (datetime(2026, 1, 22, 9, 40), "10.45", "10.5", "9.9"),
            (datetime(2026, 1, 22, 10, 30), "10.0", "10.1", "9.9"),
            (datetime(2026, 1, 22, 11, 20), "10.2", "10.3", "9.9"),
            (datetime(2026, 1, 22, 14, 45), "9.8", "10.8", "9.8"),
            (datetime(2026, 1, 22, 15, 0), "10.6", "10.8", "9.8"),
            (datetime(2026, 1, 21, 9, 40), "10.45", "10.5", "9.9"),
            (datetime(2026, 1, 21, 10, 30), "10.0", "10.1", "9.9"),
            (datetime(2026, 1, 21, 11, 20), "10.2", "10.3", "9.9"),
            (datetime(2026, 1, 21, 14, 45), "10.4", "10.5", "9.9"),
            (datetime(2026, 1, 21, 15, 0), "10.5", "10.6", "9.9"),
        ]:
            db.add(
                RealtimeQuote(
                    symbol="600001",
                    trade_date=quote_time.date(),
                    quote_time=quote_time,
                    price=Decimal(price),
                    open=Decimal("10"),
                    high=Decimal(high),
                    low=Decimal(low),
                    pre_close=Decimal("10"),
                    pct_change=None,
                    volume=Decimal("100000"),
                    amount=Decimal("1000000"),
                    turnover_rate=Decimal("1.2"),
                )
            )
        db.commit()

        monkeypatch.setattr(
            "apps.api.app.routers.workspace.now_local",
            lambda: datetime(2026, 1, 22, 15, 5),
            raising=False,
        )
        payload = list_intraday_candidate_snapshots(db=db, pool_name="experiment", lookback_days=2)

    snapshots = {item["stage"]: item for item in payload["snapshots"]}
    assert payload["trade_date"] == "2026-01-22"
    assert snapshots["early_divergence"]["as_of"] == "2026-01-22T09:45:00"
    assert snapshots["early_divergence"]["candidates"][0]["quote_time"] == "2026-01-22T09:40:00"
    assert snapshots["midday"]["as_of"] == "2026-01-22T11:35:00"
    assert snapshots["midday"]["candidates"][0]["quote_time"] == "2026-01-22T11:20:00"
    assert snapshots["late_session"]["as_of"] == "2026-01-22T14:50:00"
    assert snapshots["late_session"]["candidates"][0]["quote_time"] == "2026-01-22T14:45:00"
    assert snapshots["latest"]["as_of"] == "2026-01-22T15:05:00"
    assert snapshots["latest"]["candidates"][0]["quote_time"] == "2026-01-22T15:00:00"
    assert payload["learning"][0]["symbol"] == "600001"
    assert payload["learning"][0]["from_stage"] == "early_divergence"
    assert payload["learning"][0]["to_stage"] == "midday"
    weakened = [item for item in payload["learning"] if item["verdict"] == "weakened"][0]
    assert weakened["from_stage"] == "midday"
    assert weakened["to_stage"] == "late_session"
    assert "午间到尾盘前转弱" in weakened["reason"]
    assert payload["learning_summary"]["sample_days"] == 2
    assert payload["learning_summary"]["transition_count"] == 6
    assert payload["learning_summary"]["verdict_counts"]["weakened"] == 1
    assert payload["learning_summary"]["verdict_counts"]["repaired"] == 1
    assert payload["learning_summary"]["verdict_counts"]["held_strength"] == 4
    assert payload["learning_summary"]["sector_verdicts"][0]["sector"] == "通信设备"
    assert "转弱" in payload["learning_summary"]["pattern_notes"][0]


def test_list_intraday_candidate_snapshots_does_not_emit_future_stages(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        monkeypatch.setattr(
            "apps.api.app.routers.workspace.now_local",
            lambda: datetime(2026, 1, 22, 12, 0),
            raising=False,
        )
        payload = list_intraday_candidate_snapshots(db=db, pool_name="experiment")

    assert [item["stage"] for item in payload["snapshots"]] == [
        "early_divergence",
        "midday",
        "latest",
    ]
    assert all(item["as_of"] <= "2026-01-22T12:00:00" for item in payload["snapshots"])


def test_list_intraday_candidate_snapshots_handles_timezone_aware_now(monkeypatch) -> None:
    from datetime import UTC

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        monkeypatch.setattr(
            "apps.api.app.routers.workspace.now_local",
            lambda: datetime(2026, 1, 22, 15, 5, tzinfo=UTC),
            raising=False,
        )
        payload = list_intraday_candidate_snapshots(db=db, pool_name="experiment")

    assert [item["stage"] for item in payload["snapshots"]] == [
        "early_divergence",
        "midday",
        "late_session",
        "latest",
    ]
    assert payload["snapshots"][0]["as_of"] == "2026-01-22T09:45:00+00:00"


def test_workspace_stock_detail_and_manual_add() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        added = add_manual_stock(
            payload=ManualStockRequest(
                symbol="000001",
                note="观察银行",
                tags=["银行"],
                refresh_research=False,
            ),
            db=db,
        )
        loaded = get_workspace_stock(symbol="000001", db=db, pool_name="manual")

    assert added.symbol == "000001"
    assert added.source == "manual"
    assert loaded.manual_note == "观察银行"
    assert loaded.manual_tags == ["银行", "manual_focus"]


def test_manual_add_to_experiment_pool_appears_in_experiment_list() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        added = add_manual_stock(
            payload=ManualStockRequest(
                symbol="600001",
                note="手动跟踪",
                tags=[],
                pool_name="experiment",
                refresh_research=False,
            ),
            db=db,
        )
        listed = list_workspace_stocks(db=db, pool_name="experiment")

    assert added.symbol == "600001"
    assert added.source == "manual"
    assert added.manual_tags == ["manual_focus"]
    assert [item.symbol for item in listed] == ["600001"]
    assert listed[0].manual_note == "手动跟踪"


def test_refresh_workspace_stocks_updates_realtime_quotes(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="000001", name="平安银行", exchange="SZ", industry="银行"))
        for day in range(1, 22):
            db.add(
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
            )
        db.add(
            TradePlan(
                plan_date=date(2026, 1, 21),
                trade_date=date(2026, 1, 22),
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                sector_code=None,
                entry_condition_json={"snapshot": {"industry": "银行"}},
                position_size=Decimal("0.10"),
                confidence_score=Decimal("80"),
                status="planned",
            )
        )
        db.commit()

        def fake_sync(symbols):
            db.add(
                RealtimeQuote(
                    symbol="000001",
                    trade_date=date(2026, 1, 22),
                    quote_time=datetime(2026, 1, 22, 10, 6),
                    price=Decimal("23"),
                    open=Decimal("21"),
                    high=Decimal("23"),
                    low=Decimal("20.5"),
                    pre_close=Decimal("20"),
                    pct_change=Decimal("15"),
                    volume=Decimal("1200"),
                    amount=Decimal("25000"),
                    turnover_rate=Decimal("1.2"),
                )
            )
            db.commit()
            return []

        monkeypatch.setattr("apps.api.app.routers.workspace.sync_realtime_quotes", fake_sync)

        payload = refresh_workspace_stocks(db=db, pool_name="experiment")

    assert payload[0].current_price == 23
    assert payload[0].day_change_pct == 0.15
    assert payload[0].quote_time == "2026-01-22T10:06:00"


def test_workspace_stocks_skip_growth_board_by_default_and_include_when_enabled(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="000001", name="平安银行", exchange="SZ", industry="银行"),
                Security(symbol="300001", name="创业板样本", exchange="SZ", industry="电子"),
                Security(symbol="688001", name="科创板样本", exchange="SH", industry="半导体"),
                DailyBar(
                    symbol="000001",
                    trade_date=date(2026, 1, 22),
                    open=Decimal("10"),
                    high=Decimal("10.5"),
                    low=Decimal("9.8"),
                    close=Decimal("10.2"),
                    pre_close=Decimal("10"),
                    volume=Decimal("1000"),
                    amount=Decimal("10000"),
                    turnover_rate=Decimal("1"),
                    limit_up=Decimal("11"),
                    limit_down=Decimal("9"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="300001",
                    trade_date=date(2026, 1, 22),
                    open=Decimal("20"),
                    high=Decimal("20.5"),
                    low=Decimal("19.8"),
                    close=Decimal("20.2"),
                    pre_close=Decimal("20"),
                    volume=Decimal("1000"),
                    amount=Decimal("10000"),
                    turnover_rate=Decimal("1"),
                    limit_up=Decimal("22"),
                    limit_down=Decimal("18"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="688001",
                    trade_date=date(2026, 1, 22),
                    open=Decimal("30"),
                    high=Decimal("30.5"),
                    low=Decimal("29.8"),
                    close=Decimal("30.2"),
                    pre_close=Decimal("30"),
                    volume=Decimal("1000"),
                    amount=Decimal("30000"),
                    turnover_rate=Decimal("1"),
                    limit_up=Decimal("36"),
                    limit_down=Decimal("24"),
                    is_suspended=False,
                ),
                TradePlan(
                    plan_date=date(2026, 1, 21),
                    trade_date=date(2026, 1, 22),
                    symbol="000001",
                    rule_id="R001",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={"snapshot": {"industry": "银行"}},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("80"),
                    status="planned",
                ),
                TradePlan(
                    plan_date=date(2026, 1, 21),
                    trade_date=date(2026, 1, 22),
                    symbol="300001",
                    rule_id="R001",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={"snapshot": {"industry": "电子"}},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("81"),
                    status="planned",
                ),
                TradePlan(
                    plan_date=date(2026, 1, 21),
                    trade_date=date(2026, 1, 22),
                    symbol="688001",
                    rule_id="R001",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={"snapshot": {"industry": "半导体"}},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("82"),
                    status="planned",
                ),
            ]
        )
        db.commit()

        default_payload = list_workspace_stocks(db=db, pool_name="manual")
        growth_payload = list_workspace_stocks(db=db, pool_name="manual", include_growth_board=True)

    assert [item.symbol for item in default_payload] == ["000001"]
    assert {item.symbol for item in growth_payload} == {"000001", "300001", "688001"}


def test_refresh_workspace_stocks_can_include_growth_board_when_enabled(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="000001", name="平安银行", exchange="SZ", industry="银行"),
                Security(symbol="300001", name="创业板样本", exchange="SZ", industry="电子"),
                TradePlan(
                    plan_date=date(2026, 1, 21),
                    trade_date=date(2026, 1, 22),
                    symbol="000001",
                    rule_id="R001",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={"snapshot": {"industry": "银行"}},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("80"),
                    status="planned",
                ),
                TradePlan(
                    plan_date=date(2026, 1, 21),
                    trade_date=date(2026, 1, 22),
                    symbol="300001",
                    rule_id="R001",
                    strategy_type="short_term",
                    sector_code=None,
                    entry_condition_json={"snapshot": {"industry": "电子"}},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("81"),
                    status="planned",
                ),
            ]
        )
        db.commit()

        def fake_sync(symbols):
            return []

        monkeypatch.setattr("apps.api.app.routers.workspace.sync_realtime_quotes", fake_sync)

        default_payload = refresh_workspace_stocks(db=db, pool_name="experiment")
        growth_payload = refresh_workspace_stocks(
            db=db,
            pool_name="experiment",
            include_growth_board=True,
        )

    assert [item.symbol for item in default_payload] == ["000001"]
    assert {item.symbol for item in growth_payload} == {"000001", "300001"}


def test_workspace_experiment_pool_merges_star_candidates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="002975", name="博杰股份", exchange="SZ", industry="消费电子"),
                Security(symbol="688003", name="天准科技", exchange="SH", industry="机器视觉"),
                DailyBar(
                    symbol="002975",
                    trade_date=date(2026, 6, 24),
                    open=Decimal("35"),
                    high=Decimal("36"),
                    low=Decimal("34"),
                    close=Decimal("35.8"),
                    pre_close=Decimal("34.9"),
                    volume=Decimal("1000"),
                    amount=Decimal("35000"),
                    turnover_rate=Decimal("1"),
                    limit_up=Decimal("38.39"),
                    limit_down=Decimal("31.41"),
                    is_suspended=False,
                ),
                DailyBar(
                    symbol="688003",
                    trade_date=date(2026, 6, 24),
                    open=Decimal("42"),
                    high=Decimal("43"),
                    low=Decimal("41"),
                    close=Decimal("42.6"),
                    pre_close=Decimal("41.8"),
                    volume=Decimal("900"),
                    amount=Decimal("38000"),
                    turnover_rate=Decimal("1"),
                    limit_up=Decimal("50.16"),
                    limit_down=Decimal("33.44"),
                    is_suspended=False,
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="002975",
                    note="候选理由：缩量回踩后重新转强",
                    tags_json={
                        "tags": ["after_close_candidate", "next_session", "rank:1", "score:88.4"]
                    },
                    status="active",
                ),
                ResearchPoolItem(
                    pool_name="experiment_star",
                    symbol="688003",
                    note="候选理由：科创板辨识度高，板块资金延续",
                    tags_json={
                        "tags": ["after_close_candidate", "next_session", "rank:2", "score:84.2"]
                    },
                    status="active",
                ),
            ]
        )
        db.commit()

        merged_payload = list_workspace_stocks(
            db=db,
            pool_name="experiment",
            include_growth_board=True,
        )

    assert [item.symbol for item in merged_payload] == ["002975", "688003"]
    assert merged_payload[0].candidate_rank == 1
    assert merged_payload[1].candidate_rank == 2
    assert "star_pool" in merged_payload[1].manual_tags


def test_list_workspace_stocks_returns_candidate_tier_metadata() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="603005", name="晶方科技", exchange="SH", industry="半导体"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="603005",
                note="候选理由：板块和个股趋势同时在线",
                tags_json={
                    "tags": [
                        "after_close_candidate",
                        "next_session",
                        "rank:1",
                        "score:88.4",
                        "tier:core_action",
                        "tier_reason:板块和个股趋势同时在线，盘中仍看承接。",
                        "startup_signal_score:82.5",
                        "startup_signal_label:启动观察",
                        "startup_signal_reason:板块修复：板块扩散和韧性转暖",
                        "startup_signal_reason:量价修复：T-1温和放量并靠近MA20",
                    ]
                },
                status="active",
            )
        )
        db.commit()

        payload = list_workspace_stocks(
            db=db,
            pool_name="experiment",
            include_growth_board=False,
        )

    assert payload[0].candidate_tier == "core_action"
    assert payload[0].candidate_tier_label == "核心行动"
    assert "盘中仍看承接" in payload[0].candidate_tier_reason
    assert payload[0].startup_signal_score == 82.5
    assert payload[0].startup_signal_label == "启动观察"
    assert payload[0].startup_signal_reasons == [
        "板块修复：板块扩散和韧性转暖",
        "量价修复：T-1温和放量并靠近MA20",
    ]


def test_list_workspace_stocks_hides_stale_auto_candidate_batches() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="600360", name="华微电子", exchange="SH", industry="半导体"),
                Security(symbol="002975", name="博杰股份", exchange="SZ", industry="元器件"),
                Security(symbol="002558", name="巨人网络", exchange="SZ", industry="互联网"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="600360",
                    note="候选理由：新批次",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-06-29",
                            "hold_until:2026-07-01",
                            "rank:1",
                            "score:77.06",
                        ]
                    },
                    status="active",
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="002975",
                    note="候选理由：旧批次",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-06-24",
                            "hold_until:2026-06-30",
                            "rank:1",
                            "score:88.4",
                        ]
                    },
                    status="active",
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="002558",
                    note="手动关注；旧候选理由保留",
                    tags_json={
                        "tags": [
                            "manual_focus",
                            "after_close_candidate",
                            "next_session",
                            "2026-06-24",
                            "hold_until:2026-06-30",
                            "rank:2",
                        ]
                    },
                    status="active",
                ),
            ]
        )
        db.commit()

        payload = list_workspace_stocks(db=db, pool_name="experiment")

    assert [item.symbol for item in payload] == ["600360", "002558"]
    assert payload[0].candidate_score == 77.06
    assert payload[1].manual_tags[0] == "manual_focus"


def test_list_workspace_stocks_hides_auto_candidates_from_older_feature_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="600360", name="华微电子", exchange="SH", industry="半导体"),
                Security(symbol="600171", name="上海贝岭", exchange="SH", industry="半导体"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="600360",
                    note="候选理由：6月29日批次",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-06-29",
                            "hold_until:2026-07-01",
                            "rank:1",
                            "score:77.06",
                        ]
                    },
                    status="active",
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="600171",
                    note="候选理由：6月30日批次",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-06-30",
                            "hold_until:2026-07-01",
                            "rank:1",
                            "score:75.32",
                        ]
                    },
                    status="active",
                ),
            ]
        )
        db.commit()

        payload = list_workspace_stocks(db=db, pool_name="experiment")

    assert [item.symbol for item in payload] == ["600171"]
    assert payload[0].candidate_score == 75.32


def test_list_workspace_stocks_hides_auto_only_plans_when_candidate_batch_exists() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                Security(symbol="603005", name="晶方科技", exchange="SH", industry="半导体"),
                Security(symbol="000963", name="华东医药", exchange="SZ", industry="化学制药"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="603005",
                    note="候选理由：板块和个股趋势同时在线",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-07-06",
                            "batch:2026-07-06T10:27:28",
                            "rank:1",
                            "score:88.4",
                            "tier:core_action",
                        ]
                    },
                    status="active",
                ),
                TradePlan(
                    plan_date=date(2026, 7, 6),
                    trade_date=date(2026, 7, 7),
                    symbol="000963",
                    rule_id="R002",
                    strategy_type="swing",
                    sector_code="化学制药",
                    entry_condition_json={"snapshot": {"industry": "化学制药"}},
                    position_size=Decimal("0.10"),
                    confidence_score=Decimal("75"),
                    status="planned",
                ),
            ]
        )
        db.commit()

        payload = list_workspace_stocks(db=db, pool_name="experiment")

    assert [item.symbol for item in payload] == ["603005"]
    assert payload[0].source == "manual"
