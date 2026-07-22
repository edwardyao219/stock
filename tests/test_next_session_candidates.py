from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from services.engine.research_pool import candidates as candidate_module
from services.engine.research_pool.candidates import (
    _regime_candidate_limit,
    _technical_factor_delta,
    discover_next_session_candidates,
)
from services.engine.research_pool.repository import list_pool_items
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    FundamentalSnapshot,
    MarketRegimeDaily,
    ParameterRecommendation,
    ResearchPoolItem,
    Security,
    StockFeatureDaily,
)


def _bar(symbol: str) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=date(2026, 6, 24),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9.8"),
        close=Decimal("10.8"),
        pre_close=Decimal("10"),
        volume=Decimal("100000"),
        amount=Decimal("1000000"),
        turnover_rate=Decimal("2"),
        limit_up=Decimal("11"),
        limit_down=Decimal("9"),
        is_suspended=False,
    )


def _feature(symbol: str, **overrides) -> StockFeatureDaily:
    features = {
        "trend_score": 78,
        "relative_strength_score": 72,
        "sector_strength_score": 70,
        "sector_breadth_score": 60,
        "sector_trend_continuity_score": 72,
        "sector_trend_resilience_score": 62,
        "sector_avg_return_20d": 0.11,
        "sector_positive_20d_rate": 62,
        "sector_stock_count": 30,
        "volume_confirmation_score": 66,
        "volume_score": 66,
        "risk_score": 28,
        "overheat_score": 52,
        "volume_trap_risk_score": 40,
        "distance_to_ma20": 0.02,
        "pullback_volume_ratio": 0.85,
        "return_1d": 0.05,
        "return_20d": 0.16,
    }
    features.update(overrides)
    return StockFeatureDaily(
        symbol=symbol,
        trade_date=date(2026, 6, 24),
        features=features,
    )


def _dated_bar(symbol: str, trade_date: date) -> DailyBar:
    item = _bar(symbol)
    item.trade_date = trade_date
    return item


def _dated_feature(symbol: str, trade_date: date, **overrides) -> StockFeatureDaily:
    item = _feature(symbol, **overrides)
    item.trade_date = trade_date
    return item


def test_discover_next_session_candidates_writes_strong_candidates_to_pool(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        candidate_module,
        "_candidate_data_evidence_risk",
        lambda db, feature_date: {"status": "ok", "reasons": []},
    )

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="强势股",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="000002",
                    name="过热股",
                    exchange="SZ",
                    industry="通信设备",
                    is_active=True,
                ),
                _bar("000001"),
                _bar("000002"),
                _feature(
                    "000001",
                    moneyflow_support_score=61,
                    sector_fund_flow_score=72,
                ),
                _feature("000002", overheat_score=90),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        db.commit()

        items = list_pool_items(db, pool_name="experiment")

    assert [item["symbol"] for item in result["candidates"]] == ["000001"]
    assert result["candidates"][0]["selected_rule_id"] == "R002"
    assert result["candidates"][0]["selection_mode"] == "formal_strategy"
    assert result["candidates"][0]["day_change_pct"] == 0.05
    assert result["candidates"][0]["trend_score"] == 78.0
    assert result["candidates"][0]["relative_strength_score"] == 72.0
    assert result["candidates"][0]["moneyflow_support_score"] == 61.0
    assert result["candidates"][0]["sector_fund_flow_score"] == 72.0
    assert result["candidates"][0]["volume_confirmation_score"] == 66.0
    assert result["candidates"][0]["price_volume_trend_score"] is None
    assert result["candidates"][0]["return_20d"] == 0.16
    assert result["candidates"][0]["distance_to_ma20"] == 0.02
    assert result["candidates"][0]["route_score"] is not None
    assert result["candidates"][0]["route_label"] is not None
    assert result["candidates"][0]["plan_availability"] == {
        "status": "planned",
        "label": "可生成计划",
        "reason": "正式策略命中且市场允许，等待计划生成与次日触发价确认。",
        "gaps": [],
    }
    assert result["written"] == 1
    assert items[0]["symbol"] == "000001"
    assert "after_close_candidate" in items[0]["tags"]
    assert "plan_status:planned" in items[0]["tags"]
    assert "plan_label:可生成计划" in items[0]["tags"]
    assert "rule:R002" in items[0]["tags"]
    assert "mode:formal_strategy" in items[0]["tags"]
    assert "style_horizon:10d" in items[0]["tags"]
    assert "风格周期：growth_cycle偏10日观察" in items[0]["note"]


def test_discover_next_session_candidates_can_skip_fundamentals(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            Security(
                symbol="600001",
                name="样本",
                exchange="SH",
                industry="半导体",
                is_active=True,
            )
        )
        db.add(_bar("600001"))
        db.add(_feature("600001"))
        db.commit()

        calls: list[bool] = []

        def fake_load_feature_contexts(*_args, include_fundamentals: bool = True, **_kwargs):
            calls.append(include_fundamentals)
            return []

        monkeypatch.setattr(candidate_module, "load_feature_contexts", fake_load_feature_contexts)

        discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            include_fundamentals=False,
        )

    assert calls == [False]


def test_discover_next_session_candidates_falls_back_from_low_coverage_feature_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    full_date = date(2026, 6, 24)
    low_coverage_date = date(2026, 6, 25)
    with Session(engine) as db:
        securities = [
            Security(
                symbol=symbol,
                name=f"候选{symbol}",
                exchange="SZ",
                industry="PCB",
                is_active=True,
            )
            for symbol in ("000001", "000002", "000003")
        ]
        db.add_all(securities)
        for symbol in ("000001", "000002", "000003"):
            db.add(_dated_bar(symbol, full_date))
            db.add(_dated_feature(symbol, full_date))
        db.add(_dated_bar("000001", low_coverage_date))
        db.add(_dated_feature("000001", low_coverage_date))
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-25",
            next_trade_date="2026-06-26",
            pool_name="experiment",
            limit=10,
            min_universe_size=0,
        )
        regimes = db.query(MarketRegimeDaily).all()

    assert result["feature_date"] == "2026-06-24"
    assert result["feature_coverage_ratio"] == 1.0
    assert result["requested_feature_date"] == "2026-06-25"
    assert len(result["candidates"]) == 3
    assert regimes == []


def test_discover_next_session_candidates_persists_regime_for_requested_feature_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    feature_date = date(2026, 6, 24)
    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="阶段样本",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                _dated_bar("000001", feature_date),
                _dated_feature("000001", feature_date),
            ]
        )
        db.commit()

        discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            min_universe_size=0,
        )
        db.commit()
        regime = db.get(MarketRegimeDaily, feature_date)

    assert regime is not None
    assert regime.trade_date == feature_date
    assert regime.source == "candidate_discovery"


def test_effective_feature_date_reuses_session_feature_count_cache_without_future_dates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    full_date = date(2026, 6, 24)
    low_coverage_date = date(2026, 6, 25)
    future_date = date(2026, 6, 27)
    with Session(engine) as db:
        for symbol in ("000001", "000002", "000003"):
            db.add(_dated_feature(symbol, full_date))
        db.add(_dated_feature("000001", low_coverage_date))
        for index in range(10):
            db.add(_dated_feature(f"300{index:03d}", future_date))
        db.commit()

        count_queries = 0

        def count_feature_count_query(*_args) -> None:
            nonlocal count_queries
            statement = str(_args[2]).lower()
            if "from stock_features_daily" in statement and "count" in statement:
                count_queries += 1

        event.listen(engine, "before_cursor_execute", count_feature_count_query)
        try:
            first = candidate_module._effective_feature_date(
                db,
                feature_date="2026-06-24",
                next_trade_date="2026-06-25",
            )
            second = candidate_module._effective_feature_date(
                db,
                feature_date="2026-06-25",
                next_trade_date="2026-06-26",
            )
        finally:
            event.remove(engine, "before_cursor_execute", count_feature_count_query)

    assert first == (full_date, "2026-06-24", 1.0)
    assert second == (full_date, "2026-06-25", 1.0)
    assert count_queries == 1


def test_discover_next_session_candidates_reports_emotion_gate_without_changing_core_pick() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="强趋势",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="000002",
                    name="弱情绪样本",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="000003",
                    name="弱情绪样本2",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="000004",
                    name="弱情绪样本3",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                _bar("000001"),
                _bar("000002"),
                _bar("000003"),
                _bar("000004"),
                _feature("000001", return_1d=0.02, return_5d=0.04),
                _feature(
                    "000002",
                    trend_score=20,
                    relative_strength_score=20,
                    sector_strength_score=20,
                    volume_confirmation_score=15,
                    risk_score=85,
                    return_1d=-0.08,
                    return_5d=-0.12,
                ),
                _feature(
                    "000003",
                    trend_score=18,
                    relative_strength_score=18,
                    sector_strength_score=18,
                    volume_confirmation_score=15,
                    risk_score=85,
                    return_1d=-0.07,
                    return_5d=-0.12,
                ),
                _feature(
                    "000004",
                    trend_score=16,
                    relative_strength_score=16,
                    sector_strength_score=16,
                    volume_confirmation_score=15,
                    risk_score=85,
                    return_1d=-0.06,
                    return_5d=-0.12,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert result["emotion_gate"]["state"] == "risk_off"
    assert result["emotion_gate"]["position_scale"] == 0.0
    assert result["market_regime_snapshot"]["emotion_gate"] == "risk_off"


def test_discover_next_session_candidates_downgrades_unconfirmed_rebound_to_observation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="修复日强票",
                    exchange="SZ",
                    industry="半导体",
                    is_active=True,
                ),
                _bar("000001"),
                _feature(
                    "000001",
                    trend_score=82,
                    relative_strength_score=72,
                    sector_strength_score=70,
                    volume_confirmation_score=66,
                    risk_score=32,
                    overheat_score=48,
                    return_1d=0.02,
                    return_5d=0.03,
                ),
            ]
        )
        for index in range(10):
            symbol = f"601{index:03d}"
            db.add_all(
                [
                    Security(
                        symbol=symbol,
                        name=f"修复背景{index}",
                        exchange="SH",
                        industry="普通行业",
                        is_active=True,
                    ),
                    _bar(symbol),
                    _feature(
                        symbol,
                        trend_score=25,
                        relative_strength_score=30,
                        sector_strength_score=30,
                        volume_confirmation_score=30,
                        risk_score=80,
                        return_1d=0.01 if index < 7 else -0.01,
                        return_5d=-0.06,
                    ),
                ]
            )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    selected = next(item for item in result["candidates"] if item["symbol"] == "000001")
    assert result["market_regime"] == "rebound_unconfirmed"
    assert result["emotion_gate"]["state"] == "caution"
    assert result["market_turn"]["key"] == "watch_repair"
    assert selected["selection_mode"] == "observation"
    assert all(item["selection_mode"] != "formal_strategy" for item in result["candidates"])


def test_discover_next_session_candidates_rejects_strong_stock_without_sector_mainline() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="弱板块强股",
                    exchange="SZ",
                    industry="弱势题材",
                    is_active=True,
                ),
                Security(
                    symbol="000002",
                    name="板块共振股",
                    exchange="SZ",
                    industry="半导体",
                    is_active=True,
                ),
                _bar("000001"),
                _bar("000002"),
                _feature(
                    "000001",
                    trend_score=96,
                    relative_strength_score=94,
                    sector_strength_score=82,
                    sector_trend_continuity_score=80,
                    sector_avg_return_20d=0.01,
                    sector_positive_20d_rate=38,
                    sector_stock_count=30,
                    volume_confirmation_score=78,
                    volume_score=78,
                    return_20d=0.14,
                ),
                _feature(
                    "000002",
                    trend_score=76,
                    relative_strength_score=68,
                    sector_strength_score=68,
                    sector_trend_continuity_score=70,
                    sector_avg_return_20d=0.10,
                    sector_positive_20d_rate=60,
                    sector_stock_count=30,
                    volume_confirmation_score=52,
                    volume_score=52,
                    return_20d=0.12,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert [item["symbol"] for item in result["candidates"]] == ["000002"]
    reasons = " ".join(result["candidates"][0]["reasons"])
    assert "板块主线确认且未明显过热" in reasons


def test_discover_next_session_candidates_prefers_sector_continuity_for_long_horizon() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="600111",
                    name="主线延续票",
                    exchange="SH",
                    industry="半导体设备",
                    analysis_framework="monthly_sector_trend",
                    holding_style="monthly_trend",
                    is_active=True,
                ),
                Security(
                    symbol="600222",
                    name="脉冲票",
                    exchange="SH",
                    industry="题材脉冲",
                    analysis_framework="monthly_sector_trend",
                    holding_style="monthly_trend",
                    is_active=True,
                ),
                _bar("600111"),
                _bar("600222"),
                _feature(
                    "600111",
                    sector_strength_score=72,
                    sector_breadth_score=63,
                    sector_momentum_score=65,
                    sector_leadership_score=75,
                    sector_trend_continuity_score=81,
                    sector_trend_resilience_score=74,
                    sector_avg_return_20d=0.12,
                    sector_positive_20d_rate=66,
                    sector_stock_count=40,
                    return_20d=0.18,
                    distance_to_ma20=0.01,
                    pullback_volume_ratio=0.92,
                ),
                _feature(
                    "600222",
                    sector_strength_score=74,
                    sector_breadth_score=56,
                    sector_momentum_score=61,
                    sector_leadership_score=68,
                    sector_trend_continuity_score=52,
                    sector_trend_resilience_score=46,
                    return_20d=0.17,
                    distance_to_ma20=0.04,
                    pullback_volume_ratio=1.15,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert len(result["candidates"]) >= 1
    assert result["candidates"][0]["symbol"] == "600111"
    assert any("板块中期趋势延续性较好" in reason for reason in result["candidates"][0]["reasons"])


def test_discover_next_session_candidates_prefers_monthly_sector_leadership() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="600111",
                    name="主线板块票",
                    exchange="SH",
                    industry="半导体",
                    is_active=True,
                ),
                Security(
                    symbol="600222",
                    name="普通板块票",
                    exchange="SH",
                    industry="普通制造",
                    is_active=True,
                ),
                _bar("600111"),
                _bar("600222"),
                _feature(
                    "600111",
                    sector_strength_score=68,
                    sector_breadth_score=62,
                    sector_momentum_score=74,
                    sector_trend_continuity_score=75,
                    sector_positive_20d_rate=68,
                    sector_avg_return_20d=0.11,
                    sector_stock_count=80,
                    return_20d=0.14,
                    distance_to_ma20=0.04,
                ),
                _feature(
                    "600222",
                    sector_strength_score=70,
                    sector_breadth_score=54,
                    sector_momentum_score=52,
                    sector_trend_continuity_score=54,
                    sector_positive_20d_rate=38,
                    sector_avg_return_20d=-0.02,
                    sector_stock_count=80,
                    return_20d=0.14,
                    distance_to_ma20=0.04,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert result["candidates"][0]["symbol"] == "600111"
    assert any("板块20日主线扩散较好" in reason for reason in result["candidates"][0]["reasons"])


def test_discover_next_session_candidates_surfaces_strong_sector_watch_gap_as_observation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="600333",
                    name="强板块补位票",
                    exchange="SH",
                    industry="半导体设备",
                    is_active=True,
                ),
                _bar("600333"),
                _feature(
                    "600333",
                    trend_score=78,
                    relative_strength_score=70,
                    sector_strength_score=72,
                    sector_breadth_score=66,
                    sector_momentum_score=68,
                    sector_trend_continuity_score=76,
                    sector_trend_resilience_score=67,
                    sector_avg_return_20d=0.21,
                    sector_positive_20d_rate=70,
                    sector_stock_count=50,
                    volume_confirmation_score=52,
                    volume_score=52,
                    risk_score=36,
                    overheat_score=56,
                    volume_trap_risk_score=42,
                    return_20d=0.15,
                    distance_to_ma20=0.04,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert result["candidates"][0]["symbol"] == "600333"
    assert result["candidates"][0]["selection_mode"] == "observation"
    reasons = " ".join(result["candidates"][0]["reasons"])
    assert "强板块趋势观察补位" in reasons
    assert "只观察不行动" in reasons


def test_discover_next_session_candidates_falls_back_to_observation_pool() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000003",
                    name="观察股",
                    exchange="SZ",
                    industry="光学光电子",
                    is_active=True,
                ),
                Security(
                    symbol="000004",
                    name="弱势股",
                    exchange="SZ",
                    industry="通信设备",
                    is_active=True,
                ),
                _bar("000003"),
                _bar("000004"),
                _feature(
                    "000003",
                    trend_score=64,
                    relative_strength_score=60,
                    sector_strength_score=58,
                    volume_confirmation_score=55,
                    return_20d=0.11,
                    distance_to_ma20=0.03,
                    pullback_volume_ratio=1.25,
                    route_score=54,
                    route_label="观察路线",
                    route_reason="趋势结构还在，风险没有明显失控",
                ),
                _feature(
                    "000004",
                    trend_score=52,
                    relative_strength_score=48,
                    sector_strength_score=45,
                    volume_confirmation_score=40,
                    route_score=40,
                    route_label="弱路线",
                    route_reason="只保留基础观察，不把噪音当信号",
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        db.commit()

        items = list_pool_items(db, pool_name="experiment")

    assert [item["symbol"] for item in result["candidates"]] == ["000003"]
    candidate = result["candidates"][0]
    assert candidate["selected_rule_id"] == "OBS001"
    assert candidate["selected_rule_name"] == "观察候选"
    assert candidate["selected_strategy_type"] == "watch_breakout"
    assert candidate["selection_mode"] == "observation"
    assert any("入选层级：观察候选" in reason for reason in candidate["reasons"])
    assert "入选理由：" in items[0]["note"]
    assert "风险提示：" in items[0]["note"]
    assert "rule:OBS001" in items[0]["tags"]
    assert "strategy:watch_breakout" in items[0]["tags"]
    assert "mode:observation" in items[0]["tags"]


def test_discover_next_session_candidates_keeps_sector_trend_exploration_pool() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        rows = []
        for index in range(1, 9):
            symbol = f"6008{index:02d}"
            rows.extend(
                [
                    Security(
                        symbol=symbol,
                        name=f"科技强票{index}",
                        exchange="SH",
                        industry="半导体",
                        is_active=True,
                    ),
                    _bar(symbol),
                    _feature(
                        symbol,
                        trend_score=76 + index,
                        relative_strength_score=64 + index,
                        sector_strength_score=76,
                        sector_breadth_score=68,
                        sector_trend_continuity_score=74,
                        sector_trend_resilience_score=66,
                        sector_avg_return_20d=0.16,
                        sector_positive_20d_rate=72,
                        sector_stock_count=40,
                        volume_confirmation_score=28,
                        volume_score=28,
                        risk_score=42,
                        overheat_score=58,
                        volume_trap_risk_score=44,
                        return_20d=0.18,
                        distance_to_ma20=0.035,
                        route_score=55,
                        route_label="趋势观察",
                        route_reason="板块强，个股趋势强，但量能未到正式买点",
                    ),
                ]
            )
        db.add_all(rows)
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        db.commit()

        items = list_pool_items(db, pool_name="experiment")

    candidates = result["candidates"]
    assert len(candidates) >= 6
    assert {item["selection_mode"] for item in candidates} == {"exploration"}
    assert all(item["selected_rule_id"] == "EXP001" for item in candidates)
    assert all("强板块趋势探索" in item["selected_rule_name"] for item in candidates)
    assert all("mode:exploration" in item["tags"] for item in items)
    assert all("rule:EXP001" in item["tags"] for item in items)


def test_discover_next_session_candidates_retires_stale_auto_candidates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000009",
                    status="active",
                    tags_json={"tags": ["after_close_candidate", "rank:1", "score:80.0"]},
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000010",
                    status="active",
                    tags_json={"tags": ["manual_focus", "after_close_candidate", "rank:2"]},
                ),
                Security(
                    symbol="000001",
                    name="新候选",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                _bar("000001"),
                _feature("000001"),
            ]
        )
        db.commit()

        first_result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        first_rows = {
            item.symbol: {
                "status": item.status,
                "tags": list((item.tags_json or {}).get("tags", [])),
            }
            for item in db.query(ResearchPoolItem).order_by(ResearchPoolItem.symbol).all()
        }
        db.commit()

        second_result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        second_rows = {
            item.symbol: {
                "status": item.status,
                "tags": list((item.tags_json or {}).get("tags", [])),
            }
            for item in db.query(ResearchPoolItem).order_by(ResearchPoolItem.symbol).all()
        }
        db.commit()

    assert first_result["retired"] == 0
    assert first_rows["000009"]["status"] == "active"
    assert "watch_keep:1" in first_rows["000009"]["tags"]
    assert "dropped:2026-06-24" in first_rows["000009"]["tags"]
    assert first_rows["000010"]["status"] == "active"
    assert first_rows["000001"]["status"] == "active"
    assert "hold_until:2026-06-25" in first_rows["000001"]["tags"]
    assert "rank:1" in first_rows["000001"]["tags"]
    assert any(tag.startswith("score:") for tag in first_rows["000001"]["tags"])
    assert second_result["retired"] == 1
    assert second_rows["000009"]["status"] == "retired"


def test_discover_next_session_candidates_retires_auto_candidates_when_batch_is_empty(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000009",
                    status="active",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "hold_until:2099-06-25",
                        ]
                    },
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000010",
                    status="active",
                    tags_json={"tags": ["manual_focus", "after_close_candidate"]},
                ),
                Security(
                    symbol="000001",
                    name="样本",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                _bar("000001"),
                _feature("000001"),
            ]
        )
        db.commit()
        monkeypatch.setattr(
            candidate_module,
            "_surface_fresh_potential_after_crowded_sector",
            lambda _items: [],
        )

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        rows = {item.symbol: item.status for item in db.query(ResearchPoolItem).all()}

    assert result["candidates"] == []
    assert result["retired"] == 1
    assert rows == {"000009": "retired", "000010": "active"}


def test_discover_next_session_candidates_respects_hold_until_for_active_candidates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000009",
                    status="active",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "hold_until:2099-06-25",
                            "rank:1",
                            "score:80.0",
                        ]
                    },
                ),
                Security(
                    symbol="000001",
                    name="新候选",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                _bar("000001"),
                _feature("000001"),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        current_rows = {
            item.symbol: {
                "status": item.status,
                "tags": list((item.tags_json or {}).get("tags", [])),
            }
            for item in db.query(ResearchPoolItem).order_by(ResearchPoolItem.symbol).all()
        }

    assert result["retired"] == 0
    assert current_rows["000009"]["status"] == "active"
    assert "watch_keep:1" not in current_rows["000009"]["tags"]
    assert "dropped:2026-06-24" not in current_rows["000009"]["tags"]


def test_discover_next_session_candidates_keeps_long_horizon_pullback_candidates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            Security(
                symbol="603083",
                name="中期趋势回调票",
                exchange="SH",
                industry="通信设备",
                sector_style="growth_cycle",
                holding_style="monthly_trend",
                analysis_framework="tech_growth_cycle",
                is_active=True,
            )
        )
        db.add(
            DailyBar(
                symbol="603083",
                trade_date=date(2026, 6, 24),
                open=Decimal("10"),
                high=Decimal("10.8"),
                low=Decimal("9.9"),
                close=Decimal("10.4"),
                pre_close=Decimal("10.2"),
                volume=Decimal("100000"),
                amount=Decimal("1000000"),
                turnover_rate=Decimal("2"),
                limit_up=Decimal("11.22"),
                limit_down=Decimal("9.18"),
                is_suspended=False,
            )
        )
        db.add(
            StockFeatureDaily(
                symbol="603083",
                trade_date=date(2026, 6, 24),
                features={
                    "trend_score": 78,
                    "relative_strength_score": 75,
                    "sector_strength_score": 72,
                    "sector_breadth_score": 60,
                    "sector_momentum_score": 62,
                    "sector_trend_continuity_score": 72,
                    "sector_trend_resilience_score": 62,
                    "sector_avg_return_20d": 0.10,
                    "sector_positive_20d_rate": 60,
                    "sector_stock_count": 40,
                    "ma_alignment_score": 72,
                    "trend_quality_score": 70,
                    "volume_confirmation_score": 43,
                    "volume_score": 43,
                    "risk_score": 34,
                    "overheat_score": 48,
                    "volume_trap_risk_score": 32,
                    "volatility_score": 55,
                    "max_drawdown_20d": -0.08,
                    "distance_to_ma20": -0.02,
                    "distance_to_20d_low": 0.05,
                    "pullback_volume_ratio": 0.95,
                    "return_1d": -0.01,
                    "return_20d": 0.12,
                    "analysis_framework": "tech_growth_cycle",
                },
            )
        )
        db.add(
            FundamentalSnapshot(
                symbol="603083",
                report_date=date(2026, 6, 1),
                available_date=date(2026, 6, 1),
                revenue_growth=Decimal("0.16"),
                profit_growth=Decimal("0.13"),
                roe=Decimal("0.14"),
                dividend_yield=Decimal("0.01"),
                pe_ttm=Decimal("34"),
                pb=Decimal("4.2"),
                gross_margin=Decimal("0.38"),
                net_margin=Decimal("0.18"),
                debt_ratio=Decimal("0.35"),
                extra_json={},
            )
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert result["candidates"][0]["symbol"] == "603083"
    assert result["candidates"][0]["selection_mode"] == "formal_strategy"
    assert result["candidates"][0]["selected_rule_id"] == "R004"
    assert any("先看板块主线" in reason for reason in result["candidates"][0]["reasons"])


def test_discover_next_session_candidates_adds_long_horizon_learning_reason() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            Security(
                symbol="603083",
                name="成长长持票",
                exchange="SH",
                industry="通信设备",
                sector_style="growth_cycle",
                holding_style="trend_with_catalyst",
                analysis_framework="tech_growth_cycle",
                is_active=True,
            )
        )
        db.add(
            DailyBar(
                symbol="603083",
                trade_date=date(2026, 6, 24),
                open=Decimal("10"),
                high=Decimal("10.8"),
                low=Decimal("9.9"),
                close=Decimal("10.4"),
                pre_close=Decimal("10.2"),
                volume=Decimal("100000"),
                amount=Decimal("1000000"),
                turnover_rate=Decimal("2"),
                limit_up=Decimal("11.22"),
                limit_down=Decimal("9.18"),
                is_suspended=False,
            )
        )
        db.add(
            StockFeatureDaily(
                symbol="603083",
                trade_date=date(2026, 6, 24),
                features={
                    "trend_score": 78,
                    "relative_strength_score": 75,
                    "sector_strength_score": 72,
                    "sector_breadth_score": 60,
                    "sector_trend_continuity_score": 72,
                    "sector_trend_resilience_score": 62,
                    "sector_avg_return_20d": 0.10,
                    "sector_positive_20d_rate": 60,
                    "sector_stock_count": 40,
                    "volume_confirmation_score": 41,
                    "volume_score": 41,
                    "risk_score": 34,
                    "overheat_score": 48,
                    "volume_trap_risk_score": 32,
                    "volatility_score": 55,
                    "max_drawdown_20d": -0.08,
                    "distance_to_ma20": -0.02,
                    "distance_to_20d_low": 0.05,
                    "pullback_volume_ratio": 0.95,
                    "return_1d": -0.01,
                    "return_20d": 0.12,
                    "analysis_framework": "tech_growth_cycle",
                },
            )
        )
        db.add(
            FundamentalSnapshot(
                symbol="603083",
                report_date=date(2026, 6, 1),
                available_date=date(2026, 6, 1),
                revenue_growth=Decimal("0.12"),
                profit_growth=Decimal("0.10"),
                roe=Decimal("0.14"),
                dividend_yield=Decimal("0.01"),
                pe_ttm=Decimal("35"),
                pb=Decimal("4.2"),
                gross_margin=Decimal("0.38"),
                net_margin=Decimal("0.18"),
                debt_ratio=Decimal("0.35"),
                extra_json={},
            )
        )
        db.add(
            ParameterRecommendation(
                report_date=date(2026, 6, 24),
                rule_id="R002",
                scope_type="symbol",
                scope_value="603083",
                target_type="time_exit",
                target_name="learned_long_horizon_hold",
                action="keep_or_test_small_priority_increase",
                priority="medium",
                rationale="sample",
                current_json={},
                proposed_json={
                    "max_holding_days_multiplier": 1.5,
                    "trailing_drawdown_pct_multiplier": 1.05,
                    "priority_score_delta": 1,
                    "source_rule_id": "R002",
                },
                guardrails_json={"items": []},
                source_report_type="backtest_learning_review",
                status="pending",
            )
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert result["candidates"][0]["symbol"] == "603083"
    assert any("长期学习：" in reason for reason in result["candidates"][0]["reasons"])


def test_discover_next_session_candidates_prefers_monthly_trend_over_short_term_noise() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="603083",
                    name="中期趋势票",
                    exchange="SH",
                    industry="通信设备",
                    sector_style="growth_cycle",
                    holding_style="monthly_trend",
                    analysis_framework="tech_growth_cycle",
                    is_active=True,
                ),
                Security(
                    symbol="002001",
                    name="短线突破票",
                    exchange="SZ",
                    industry="PCB",
                    sector_style="theme",
                    is_active=True,
                ),
                _bar("603083"),
                _bar("002001"),
                _feature(
                    "603083",
                    trend_score=76,
                    relative_strength_score=66,
                    sector_strength_score=70,
                    sector_breadth_score=60,
                    sector_momentum_score=61,
                    ma_alignment_score=72,
                    trend_quality_score=70,
                    volume_confirmation_score=48,
                    volume_score=48,
                    return_20d=0.12,
                    distance_to_ma20=0.03,
                    max_drawdown_20d=-0.08,
                    overheat_score=54,
                    volume_trap_risk_score=38,
                    analysis_framework="tech_growth_cycle",
                ),
                _feature(
                    "002001",
                    trend_score=82,
                    relative_strength_score=74,
                    sector_strength_score=76,
                    ma_alignment_score=62,
                    trend_quality_score=63,
                    volume_confirmation_score=72,
                    volume_score=72,
                    amount_percentile_60d=92,
                    distance_to_20d_high=0.01,
                    return_20d=0.20,
                    distance_to_ma20=0.10,
                    max_drawdown_20d=-0.05,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert [item["symbol"] for item in result["candidates"][:2]] == ["603083", "002001"]
    assert result["candidates"][0]["selected_rule_id"] == "R004"
    assert result["candidates"][1]["selected_strategy_type"] != "long_term"


def test_discover_next_session_candidates_prefers_strong_tech_mainline() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="603083",
                    name="科技顺势票",
                    exchange="SH",
                    industry="通信设备",
                    sector_style="growth_cycle",
                    analysis_framework="tech_growth_cycle",
                    is_active=True,
                ),
                Security(
                    symbol="600111",
                    name="普通强势票",
                    exchange="SH",
                    industry="普通制造",
                    sector_style="cyclical",
                    is_active=True,
                ),
                _bar("603083"),
                _bar("600111"),
                _feature(
                    "603083",
                    trend_score=76,
                    relative_strength_score=70,
                    sector_strength_score=72,
                    sector_breadth_score=64,
                    sector_momentum_score=68,
                    sector_trend_continuity_score=74,
                    sector_trend_resilience_score=66,
                    sector_avg_return_20d=0.12,
                    sector_positive_20d_rate=66,
                    sector_stock_count=80,
                    max_drawdown_20d=-0.08,
                    return_20d=0.13,
                ),
                _feature(
                    "600111",
                    trend_score=78,
                    relative_strength_score=72,
                    sector_strength_score=72,
                    sector_breadth_score=64,
                    sector_momentum_score=68,
                    sector_trend_continuity_score=74,
                    sector_trend_resilience_score=66,
                    sector_avg_return_20d=0.12,
                    sector_positive_20d_rate=66,
                    sector_stock_count=80,
                    max_drawdown_20d=-0.08,
                    return_20d=0.13,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert [item["symbol"] for item in result["candidates"][:2]] == ["603083", "600111"]
    assert any("科技成长主线顺势" in reason for reason in result["candidates"][0]["reasons"])


def test_technical_factor_delta_prefers_pullback_quality_over_overextension() -> None:
    stable_context = {
        "trend_score": 76,
        "relative_strength_score": 68,
        "sector_strength_score": 66,
        "volume_confirmation_score": 55,
        "trend_quality_score": 70,
        "distance_to_ma20": 0.03,
        "return_20d": 0.12,
        "pullback_volume_ratio": 0.92,
        "overheat_score": 54,
        "volume_trap_risk_score": 38,
    }
    hot_context = {
        **stable_context,
        "relative_strength_score": 82,
        "distance_to_ma20": 0.18,
        "return_20d": 0.34,
        "pullback_volume_ratio": 1.18,
        "overheat_score": 78,
    }

    assert _technical_factor_delta(stable_context) > _technical_factor_delta(hot_context)


def test_technical_factor_delta_softly_rewards_price_volume_trend_confirmation() -> None:
    base_context = {
        "trend_score": 76,
        "relative_strength_score": 68,
        "sector_strength_score": 66,
        "volume_confirmation_score": 56,
        "trend_quality_score": 68,
        "distance_to_ma20": 0.03,
        "return_20d": 0.12,
        "pullback_volume_ratio": 0.96,
        "overheat_score": 54,
        "volume_trap_risk_score": 38,
    }
    confirmed_context = {
        **base_context,
        "price_volume_trend_score": 82,
    }
    weak_confirmation_context = {
        **base_context,
        "price_volume_trend_score": 42,
        "volume_trap_risk_score": 66,
    }

    assert _technical_factor_delta(confirmed_context) > _technical_factor_delta(base_context)
    assert _technical_factor_delta(weak_confirmation_context) < _technical_factor_delta(
        base_context
    )


def test_discover_next_session_candidates_prefers_low_noise_observation_in_weak_market() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="603083",
                    name="低噪音观察",
                    exchange="SH",
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="002001",
                    name="高位热票",
                    exchange="SZ",
                    industry="通信设备",
                    is_active=True,
                ),
            ]
        )
        for idx in range(20):
            symbol = f"601{idx:03d}"
            db.add(
                Security(
                    symbol=symbol,
                    name=f"弱势样本{idx}",
                    exchange="SH",
                    industry="弱势",
                    is_active=True,
                )
            )
            db.add(_bar(symbol))
            db.add(
                _feature(
                    symbol,
                    trend_score=28,
                    relative_strength_score=42,
                    sector_strength_score=45,
                    volume_confirmation_score=35,
                    risk_score=64,
                    return_1d=0.002 if idx < 6 else -0.01,
                    return_5d=-0.03,
                    return_20d=-0.04,
                )
            )
        db.add_all([_bar("603083"), _bar("002001")])
        db.add(
            _feature(
                "603083",
                trend_score=78,
                relative_strength_score=68,
                sector_strength_score=66,
                sector_breadth_score=60,
                sector_momentum_score=61,
                trend_quality_score=70,
                volume_confirmation_score=46,
                volume_score=46,
                risk_score=35,
                overheat_score=54,
                volume_trap_risk_score=35,
                return_1d=0.01,
                return_5d=0.03,
                return_20d=0.12,
                distance_to_ma20=0.03,
                pullback_volume_ratio=0.92,
            )
        )
        db.add(
            _feature(
                "002001",
                trend_score=100,
                relative_strength_score=92,
                sector_strength_score=66,
                sector_breadth_score=60,
                sector_momentum_score=61,
                trend_quality_score=80,
                volume_confirmation_score=60,
                volume_score=60,
                risk_score=32,
                overheat_score=78,
                volume_trap_risk_score=45,
                return_1d=0.095,
                return_5d=0.20,
                return_20d=0.34,
                distance_to_ma20=0.20,
                pullback_volume_ratio=1.18,
            )
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert result["market_regime"] in {"weak_trend", "panic"}
    assert result["candidates"][0]["symbol"] == "603083"
    assert any("回调质量符合5月较稳因子" in reason for reason in result["candidates"][0]["reasons"])


def test_discover_next_session_candidates_keeps_defensive_observation_near_sector_gate() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            Security(
                symbol="603054",
                name="防守观察",
                exchange="SH",
                industry="半导体",
                is_active=True,
            )
        )
        db.add(_bar("603054"))
        db.add(
            _feature(
                "603054",
                trend_score=82,
                relative_strength_score=70,
                sector_strength_score=54,
                sector_breadth_score=60,
                sector_trend_continuity_score=62,
                sector_trend_resilience_score=58,
                sector_avg_return_20d=0.26,
                sector_positive_20d_rate=70,
                volume_confirmation_score=46,
                risk_score=35,
                overheat_score=54,
                volume_trap_risk_score=35,
                return_1d=0.01,
                return_5d=0.02,
                return_20d=0.13,
                distance_to_ma20=0.03,
                pullback_volume_ratio=0.92,
            )
        )
        for idx in range(24):
            symbol = f"601{idx:03d}"
            db.add(
                Security(
                    symbol=symbol,
                    name=f"弱势样本{idx}",
                    exchange="SH",
                    industry="弱势",
                    is_active=True,
                )
            )
            db.add(_bar(symbol))
            db.add(
                _feature(
                    symbol,
                    trend_score=28,
                    relative_strength_score=42,
                    sector_strength_score=45,
                    volume_confirmation_score=35,
                    risk_score=64,
                    return_1d=0.002 if idx < 6 else -0.01,
                    return_5d=-0.03,
                    return_20d=-0.04,
                )
            )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert result["market_regime"] == "weak_trend"
    assert result["candidates"][0]["symbol"] == "603054"
    assert result["candidates"][0]["selection_mode"] == "observation"


def test_discover_next_session_candidates_prefers_low_noise_in_weak_participation_range() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="603083",
                    name="震荡低噪音",
                    exchange="SH",
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="002001",
                    name="震荡高位热票",
                    exchange="SZ",
                    industry="通信设备",
                    is_active=True,
                ),
            ]
        )
        for idx in range(18):
            symbol = f"601{idx:03d}"
            db.add(
                Security(
                    symbol=symbol,
                    name=f"震荡背景{idx}",
                    exchange="SH",
                    industry="普通行业",
                    is_active=True,
                )
            )
            db.add(_bar(symbol))
            db.add(
                _feature(
                    symbol,
                    trend_score=45,
                    relative_strength_score=48,
                    sector_strength_score=50,
                    volume_confirmation_score=34,
                    volume_score=34,
                    amount_percentile_60d=30,
                    amount_ratio_5d=0.72,
                    recent_amount_ratio_20d=0.74,
                    risk_score=55,
                    return_1d=0.002 if idx < 8 else -0.004,
                    return_5d=-0.03,
                    return_20d=0.01,
                )
            )
        db.add_all([_bar("603083"), _bar("002001")])
        db.add(
            _feature(
                "603083",
                trend_score=78,
                relative_strength_score=68,
                sector_strength_score=66,
                sector_breadth_score=60,
                sector_momentum_score=61,
                trend_quality_score=70,
                volume_confirmation_score=46,
                volume_score=46,
                amount_percentile_60d=45,
                amount_ratio_5d=0.92,
                recent_amount_ratio_20d=0.95,
                risk_score=35,
                overheat_score=54,
                volume_trap_risk_score=35,
                return_1d=0.01,
                return_5d=0.03,
                return_20d=0.12,
                distance_to_ma20=0.03,
                pullback_volume_ratio=0.92,
            )
        )
        db.add(
            _feature(
                "002001",
                trend_score=100,
                relative_strength_score=92,
                sector_strength_score=66,
                sector_breadth_score=60,
                sector_momentum_score=61,
                trend_quality_score=82,
                volume_confirmation_score=62,
                volume_score=62,
                amount_percentile_60d=70,
                amount_ratio_5d=1.45,
                recent_amount_ratio_20d=1.32,
                risk_score=32,
                overheat_score=78,
                volume_trap_risk_score=45,
                return_1d=0.095,
                return_5d=0.20,
                return_20d=0.34,
                distance_to_ma20=0.20,
                pullback_volume_ratio=1.18,
            )
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert result["market_regime"] == "range"
    assert result["market_participation_snapshot"]["participation_score"] < 45
    assert result["candidates"][0]["symbol"] == "603083"


def test_discover_next_session_candidates_promotes_low_dimensional_mainline_first() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="603986",
                    name="低维主线",
                    exchange="SH",
                    industry="半导体",
                    sector_style="growth_cycle",
                    analysis_framework="tech_growth_cycle",
                    is_active=True,
                ),
                Security(
                    symbol="600900",
                    name="高分高位",
                    exchange="SH",
                    industry="火力发电",
                    is_active=True,
                ),
            ]
        )
        db.add_all([_bar("603986"), _bar("600900")])
        db.add(
            _feature(
                "603986",
                trend_score=78,
                relative_strength_score=68,
                sector_strength_score=66,
                sector_breadth_score=60,
                sector_momentum_score=61,
                sector_trend_continuity_score=72,
                sector_trend_resilience_score=64,
                trend_quality_score=70,
                volume_confirmation_score=46,
                volume_score=46,
                risk_score=35,
                overheat_score=54,
                volume_trap_risk_score=35,
                return_1d=0.01,
                return_5d=0.03,
                return_20d=0.12,
                sector_avg_return_20d=0.12,
                sector_positive_20d_rate=62,
                distance_to_ma20=0.03,
                pullback_volume_ratio=0.92,
            )
        )
        db.add(
            _feature(
                "600900",
                trend_score=96,
                relative_strength_score=90,
                sector_strength_score=70,
                sector_breadth_score=58,
                sector_momentum_score=58,
                sector_trend_continuity_score=70,
                sector_trend_resilience_score=60,
                trend_quality_score=82,
                volume_confirmation_score=78,
                volume_score=78,
                risk_score=30,
                overheat_score=70,
                volume_trap_risk_score=58,
                return_1d=0.08,
                return_5d=0.18,
                return_20d=0.34,
                sector_avg_return_20d=0.13,
                sector_positive_20d_rate=60,
                distance_to_ma20=0.17,
                pullback_volume_ratio=1.3,
            )
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=1,
            min_universe_size=0,
        )

    assert [item["symbol"] for item in result["candidates"]] == ["603986"]
    assert any("低维主线" in reason for reason in result["candidates"][0]["reasons"])
    assert any("回调质量符合5月较稳因子" in reason for reason in result["candidates"][0]["reasons"])


def test_discover_next_session_candidates_uses_paper_learning_to_downrank() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="纸面弱票",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="000002",
                    name="对照强票",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                _bar("000001"),
                _bar("000002"),
                _feature(
                    "000001",
                    trend_score=80,
                    relative_strength_score=75,
                    sector_strength_score=73,
                    volume_confirmation_score=68,
                ),
                _feature(
                    "000002",
                    trend_score=78,
                    relative_strength_score=72,
                    sector_strength_score=70,
                    volume_confirmation_score=66,
                ),
                ParameterRecommendation(
                    report_date=date(2026, 6, 24),
                    rule_id="R002",
                    scope_type="symbol",
                    scope_value="000001",
                    target_type="entry_filter",
                    target_name="learned_entry_quality",
                    action="tighten_entry_or_reduce_priority",
                    priority="high",
                    rationale="paper weak sample",
                    current_json={},
                    proposed_json={
                        "priority_score_delta": -8,
                        "require_extra_confirmation": True,
                        "source_rule_id": "R002",
                    },
                    guardrails_json={"items": []},
                    source_report_type="paper_learning_review",
                    status="pending",
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert [item["symbol"] for item in result["candidates"][:2]] == ["000002", "000001"]
    weak_candidate = next(item for item in result["candidates"] if item["symbol"] == "000001")
    assert any("纸面学习：" in reason for reason in weak_candidate["reasons"])


def test_discover_next_session_candidates_prefers_recent_learning_adjustments() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="近期学习票",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="000002",
                    name="旧学习票",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                _bar("000001"),
                _bar("000002"),
                _feature("000001"),
                _feature("000002"),
                ParameterRecommendation(
                    report_date=date(2026, 6, 23),
                    rule_id="R002",
                    scope_type="symbol",
                    scope_value="000001",
                    target_type="entry_filter",
                    target_name="learned_entry_quality",
                    action="keep_or_test_small_priority_increase",
                    priority="high",
                    rationale="recent learning",
                    current_json={},
                    proposed_json={
                        "priority_score_delta": 6,
                        "source_rule_id": "R002",
                    },
                    guardrails_json={"items": []},
                    source_report_type="backtest_learning_review",
                    status="pending",
                ),
                ParameterRecommendation(
                    report_date=date(2026, 5, 10),
                    rule_id="R002",
                    scope_type="symbol",
                    scope_value="000002",
                    target_type="entry_filter",
                    target_name="learned_entry_quality",
                    action="keep_or_test_small_priority_increase",
                    priority="high",
                    rationale="old learning",
                    current_json={},
                    proposed_json={
                        "priority_score_delta": 6,
                        "source_rule_id": "R002",
                    },
                    guardrails_json={"items": []},
                    source_report_type="backtest_learning_review",
                    status="pending",
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert [item["symbol"] for item in result["candidates"][:2]] == ["000001", "000002"]
    recent_candidate = result["candidates"][0]
    old_candidate = result["candidates"][1]
    assert any("（1天前）" in reason for reason in recent_candidate["reasons"])
    assert any("（45天前）" in reason for reason in old_candidate["reasons"])
    assert recent_candidate["score"] > old_candidate["score"]


def test_discover_next_session_candidates_keeps_validation_failed_sector_in_observation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="002558",
                    name="样本外转弱票",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="600673",
                    name="对照趋势票",
                    exchange="SH",
                    industry="通信设备",
                    is_active=True,
                ),
                _bar("002558"),
                _bar("600673"),
                _feature(
                    "002558",
                    trend_score=82,
                    relative_strength_score=76,
                    sector_strength_score=74,
                    sector_breadth_score=66,
                    volume_confirmation_score=70,
                    return_20d=0.16,
                ),
                _feature(
                    "600673",
                    trend_score=76,
                    relative_strength_score=70,
                    sector_strength_score=72,
                    sector_breadth_score=64,
                    volume_confirmation_score=66,
                    return_20d=0.14,
                ),
                ParameterRecommendation(
                    report_date=date(2026, 6, 24),
                    rule_id="R002",
                    scope_type="sector",
                    scope_value="PCB",
                    target_type="entry_filter",
                    target_name="backtest_validation_quality",
                    action="observe_or_require_fresh_confirmation",
                    priority="high",
                    rationale="validation weakened",
                    current_json={},
                    proposed_json={
                        "priority_score_delta": -3,
                        "require_extra_confirmation": True,
                        "source_rule_id": "R002",
                    },
                    guardrails_json={"items": []},
                    source_report_type="backtest_learning_review",
                    status="pending",
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        db.commit()
        pool_items = list_pool_items(db, pool_name="experiment")

    gated_candidate = next(item for item in result["candidates"] if item["symbol"] == "002558")
    assert gated_candidate["selection_mode"] == "observation"
    assert any("样本外验证转弱" in reason for reason in gated_candidate["reasons"])

    gated_pool_item = next(item for item in pool_items if item["symbol"] == "002558")
    assert "style_gate:stand_down" in gated_pool_item["tags"]
    assert any(
        tag.startswith("style_gate_reason:历史回归：PCB 样本外验证转弱")
        for tag in gated_pool_item["tags"]
    )


def test_discover_next_session_candidates_reduces_candidates_in_weak_market() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="普通趋势股",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="000002",
                    name="逆势强票",
                    exchange="SZ",
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="000003",
                    name="弱势样本",
                    exchange="SZ",
                    industry="通信设备",
                    is_active=True,
                ),
                Security(
                    symbol="000004",
                    name="弱势样本二",
                    exchange="SZ",
                    industry="电子",
                    is_active=True,
                ),
                Security(
                    symbol="000005",
                    name="弱势样本三",
                    exchange="SZ",
                    industry="传媒",
                    is_active=True,
                ),
                Security(
                    symbol="000006",
                    name="弱势样本四",
                    exchange="SZ",
                    industry="新能源",
                    is_active=True,
                ),
                Security(
                    symbol="000007",
                    name="弱势样本五",
                    exchange="SZ",
                    industry="计算机",
                    is_active=True,
                ),
                _bar("000001"),
                _bar("000002"),
                _bar("000003"),
                _bar("000004"),
                _bar("000005"),
                _bar("000006"),
                _bar("000007"),
                _feature(
                    "000001",
                    trend_score=62,
                    relative_strength_score=61,
                    sector_strength_score=60,
                    volume_confirmation_score=50,
                    risk_score=40,
                    return_1d=-0.02,
                    return_5d=-0.05,
                ),
                _feature(
                    "000002",
                    trend_score=82,
                    relative_strength_score=75,
                    sector_strength_score=72,
                    volume_confirmation_score=62,
                    risk_score=20,
                    return_1d=0.03,
                    return_5d=0.08,
                ),
                _feature(
                    "000003",
                    trend_score=20,
                    relative_strength_score=25,
                    sector_strength_score=30,
                    volume_confirmation_score=20,
                    risk_score=80,
                    return_1d=-0.04,
                    return_5d=-0.10,
                ),
                _feature(
                    "000004",
                    trend_score=18,
                    relative_strength_score=22,
                    sector_strength_score=24,
                    volume_confirmation_score=22,
                    risk_score=82,
                    return_1d=0.01,
                    return_5d=-0.12,
                ),
                _feature(
                    "000005",
                    trend_score=20,
                    relative_strength_score=28,
                    sector_strength_score=26,
                    volume_confirmation_score=24,
                    risk_score=78,
                    return_1d=0.005,
                    return_5d=-0.09,
                ),
                _feature(
                    "000006",
                    trend_score=21,
                    relative_strength_score=24,
                    sector_strength_score=22,
                    volume_confirmation_score=18,
                    risk_score=84,
                    return_1d=-0.06,
                    return_5d=-0.14,
                ),
                _feature(
                    "000007",
                    trend_score=19,
                    relative_strength_score=23,
                    sector_strength_score=20,
                    volume_confirmation_score=20,
                    risk_score=80,
                    return_1d=-0.04,
                    return_5d=-0.11,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    assert result["market_regime"] == "weak_trend"
    assert [item["symbol"] for item in result["candidates"]] == ["000002"]
    assert any("弱趋势" in reason for reason in result["candidates"][0]["reasons"])


def test_discover_next_session_candidates_caps_daily_list_to_fifteen() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        for idx in range(20):
            symbol = f"600{idx:03d}"
            db.add(
                Security(
                    symbol=symbol,
                    name=f"候选{idx}",
                    exchange="SH",
                    industry="PCB",
                    is_active=True,
                )
            )
            db.add(_bar(symbol))
            db.add(
                _feature(
                    symbol,
                    trend_score=90 - idx * 0.5,
                    relative_strength_score=82 - idx * 0.25,
                    sector_strength_score=78,
                    volume_confirmation_score=66,
                    volume_score=66,
                    amount_percentile_60d=90 - idx * 0.5,
                    amount_ratio_5d=1.08,
                    recent_amount_ratio_20d=1.02,
                    risk_score=24,
                    overheat_score=46,
                    volume_trap_risk_score=30,
                    return_1d=0.02,
                    return_5d=0.04,
                    return_20d=0.14,
                )
            )
        for idx in range(20):
            symbol = f"601{idx:03d}"
            db.add(
                Security(
                    symbol=symbol,
                    name=f"背景{idx}",
                    exchange="SH",
                    industry="普通行业",
                    is_active=True,
                )
            )
            db.add(_bar(symbol))
            db.add(
                _feature(
                    symbol,
                    trend_score=50,
                    relative_strength_score=50,
                    sector_strength_score=50,
                    volume_confirmation_score=50,
                    volume_score=50,
                    amount_percentile_60d=80,
                    amount_ratio_5d=1.0,
                    recent_amount_ratio_20d=1.0,
                    risk_score=42,
                    overheat_score=45,
                    volume_trap_risk_score=35,
                    return_1d=0.0,
                    return_5d=0.0,
                    return_20d=0.02,
                )
            )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=99,
        )
        db.commit()
        items = list_pool_items(db, pool_name="experiment")

    assert len(result["candidates"]) == 15
    assert result["requested_limit"] == 99
    assert result["effective_limit"] == 15
    assert result["written"] == 15
    assert len(items) == 15
    assert items[0]["tags"]
    assert "rank:1" in items[0]["tags"]
    assert "rank:15" in {tag for item in items for tag in item["tags"] if tag.startswith("rank:")}


def test_discover_next_session_candidates_softens_single_sector_crowding() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        for idx in range(8):
            symbol = f"600{idx:03d}"
            db.add(
                Security(
                    symbol=symbol,
                    name=f"半导体{idx}",
                    exchange="SH",
                    industry="半导体",
                    is_active=True,
                )
            )
            db.add(_bar(symbol))
            db.add(
                _feature(
                    symbol,
                    trend_score=90 - idx,
                    relative_strength_score=84 - idx * 0.5,
                    sector_strength_score=82,
                    sector_breadth_score=72,
                    sector_momentum_score=74,
                    sector_leadership_score=78,
                    sector_trend_continuity_score=80,
                    sector_trend_resilience_score=72,
                    volume_confirmation_score=66,
                    volume_score=66,
                    return_20d=0.15,
                )
            )

        for idx in range(4):
            symbol = f"601{idx:03d}"
            db.add(
                Security(
                    symbol=symbol,
                    name=f"医药{idx}",
                    exchange="SH",
                    industry="化学制药",
                    holding_style="monthly_trend",
                    analysis_framework="monthly_sector_trend",
                    is_active=True,
                )
            )
            db.add(_bar(symbol))
            db.add(
                _feature(
                    symbol,
                    trend_score=82 - idx,
                    relative_strength_score=76 - idx * 0.5,
                    sector_strength_score=75,
                    sector_breadth_score=66,
                    sector_momentum_score=67,
                    sector_leadership_score=74,
                    sector_trend_continuity_score=77,
                    sector_trend_resilience_score=70,
                    volume_confirmation_score=58,
                    volume_score=58,
                    return_20d=0.11,
                )
            )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    sectors = [item["sector"] for item in result["candidates"]]
    assert sectors[0] == "半导体"
    assert result["sector_groups"]
    assert result["sector_groups"][0]["sector"] == "半导体"
    assert result["sector_groups"][0]["count"] >= 1


def test_discover_next_session_candidates_marks_mainline_confirmation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="600360",
                    name="主线确认",
                    exchange="SH",
                    industry="半导体",
                    is_active=True,
                ),
                _bar("600360"),
                _feature(
                    "600360",
                    trend_score=88,
                    relative_strength_score=82,
                    sector_strength_score=76,
                    sector_trend_continuity_score=75,
                    sector_trend_resilience_score=62,
                    sector_avg_return_20d=0.11,
                    sector_positive_20d_rate=65,
                    sector_stock_count=180,
                    volume_confirmation_score=60,
                    volume_score=60,
                    return_20d=0.14,
                    distance_to_ma20=0.04,
                    overheat_score=54,
                    volume_trap_risk_score=38,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    reasons = " ".join(result["candidates"][0]["reasons"])
    assert "板块主线确认且未明显过热" in reasons


def test_discover_next_session_candidates_marks_long_horizon_strength() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="002859",
                    name="中期强者",
                    exchange="SZ",
                    industry="元器件",
                    is_active=True,
                ),
                _bar("002859"),
                _feature(
                    "002859",
                    trend_score=88,
                    relative_strength_score=88,
                    sector_strength_score=68,
                    sector_breadth_score=68,
                    sector_trend_continuity_score=70,
                    sector_trend_resilience_score=62,
                    sector_avg_return_20d=0.17,
                    sector_positive_20d_rate=72,
                    sector_stock_count=120,
                    volume_confirmation_score=62,
                    volume_score=62,
                    return_20d=0.20,
                    distance_to_ma20=0.06,
                    overheat_score=50,
                    volume_trap_risk_score=38,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    reasons = " ".join(result["candidates"][0]["reasons"])
    assert "中期强者：相对强度或板块扩散足够强" in reasons


def test_discover_next_session_candidates_marks_long_horizon_extension_as_watch() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="002860",
                    name="中期扩展",
                    exchange="SZ",
                    industry="元器件",
                    is_active=True,
                ),
                _bar("002860"),
                _feature(
                    "002860",
                    trend_score=78,
                    relative_strength_score=79,
                    sector_strength_score=64,
                    sector_breadth_score=58,
                    sector_trend_continuity_score=70,
                    sector_trend_resilience_score=62,
                    sector_avg_return_20d=0.11,
                    sector_positive_20d_rate=58,
                    sector_stock_count=80,
                    volume_confirmation_score=50,
                    volume_score=50,
                    return_20d=0.16,
                    distance_to_ma20=0.05,
                    overheat_score=55,
                    volume_trap_risk_score=42,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    reasons = " ".join(result["candidates"][0]["reasons"])
    assert "中期扩展观察：趋势连续性和相对强度接近中期强者" in reasons
    assert "中期强者：相对强度或板块扩散足够强" not in reasons


def test_discover_next_session_candidates_keeps_overextended_sector_as_observation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="600396",
                    name="过热主线",
                    exchange="SH",
                    industry="火力发电",
                    is_active=True,
                ),
                _bar("600396"),
                _feature(
                    "600396",
                    trend_score=92,
                    relative_strength_score=88,
                    sector_strength_score=86,
                    sector_trend_continuity_score=88,
                    sector_trend_resilience_score=58,
                    sector_avg_return_20d=0.28,
                    sector_positive_20d_rate=96,
                    sector_stock_count=31,
                    volume_confirmation_score=70,
                    volume_score=70,
                    return_20d=0.24,
                    distance_to_ma20=0.08,
                    overheat_score=62,
                    volume_trap_risk_score=42,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    reasons = " ".join(candidate["reasons"])
    assert candidate["selection_mode"] == "observation"
    assert "板块20日涨幅/扩散已偏拥挤" in reasons


def test_discover_next_session_candidates_adds_potential_watch_for_starting_stock() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        rows = []
        for index in range(3):
            symbol = f"6010{index}6"
            rows.extend(
                [
                    Security(
                        symbol=symbol,
                        name=f"证券强票{index}",
                        exchange="SH",
                        industry="证券",
                        is_active=True,
                    ),
                    _bar(symbol),
                    _feature(
                        symbol,
                        trend_score=82 - index,
                        relative_strength_score=74 - index,
                        sector_strength_score=76,
                        sector_breadth_score=70,
                        sector_trend_continuity_score=78,
                        sector_trend_resilience_score=68,
                        sector_avg_return_20d=0.12,
                        sector_positive_20d_rate=68,
                        sector_stock_count=50,
                        volume_confirmation_score=62,
                        volume_score=62,
                        return_20d=0.13,
                    ),
                ]
            )
        rows.extend(
            [
                Security(
                    symbol="603255",
                    name="高分潜力A",
                    exchange="SH",
                    industry="化工原料",
                    is_active=True,
                ),
                _bar("603255"),
                _feature(
                    "603255",
                    trend_score=96,
                    relative_strength_score=76,
                    sector_strength_score=58,
                    sector_breadth_score=64,
                    sector_trend_continuity_score=52,
                    sector_trend_resilience_score=60,
                    sector_avg_return_20d=0.07,
                    sector_positive_20d_rate=46,
                    sector_stock_count=80,
                    volume_confirmation_score=62,
                    volume_score=62,
                    price_volume_trend_score=70,
                    route_score=71,
                    route_label="可跟踪",
                    route_reason="趋势和资金都在同一方向",
                    return_1d=0.042,
                    return_20d=0.177,
                    distance_to_ma20=0.09,
                    overheat_score=42,
                    volume_trap_risk_score=32,
                    risk_score=35,
                ),
                Security(
                    symbol="603225",
                    name="高分潜力B",
                    exchange="SH",
                    industry="化纤",
                    is_active=True,
                ),
                _bar("603225"),
                _feature(
                    "603225",
                    trend_score=95,
                    relative_strength_score=69,
                    sector_strength_score=46,
                    sector_breadth_score=58,
                    sector_trend_continuity_score=44,
                    sector_trend_resilience_score=57,
                    sector_avg_return_20d=-0.02,
                    sector_positive_20d_rate=35,
                    sector_stock_count=32,
                    volume_confirmation_score=60,
                    volume_score=60,
                    price_volume_trend_score=68,
                    route_score=73,
                    route_label="可跟踪",
                    route_reason="趋势结构还在，风险没有明显失控",
                    return_1d=0.083,
                    return_20d=0.145,
                    distance_to_ma20=0.10,
                    overheat_score=35,
                    volume_trap_risk_score=30,
                    risk_score=34,
                ),
                Security(
                    symbol="600673",
                    name="东阳光",
                    exchange="SH",
                    industry="综合类",
                    is_active=True,
                ),
                _bar("600673"),
                _feature(
                    "600673",
                    trend_score=94,
                    relative_strength_score=48,
                    sector_strength_score=45,
                    sector_breadth_score=94,
                    sector_trend_continuity_score=38,
                    sector_trend_resilience_score=72,
                    sector_avg_return_20d=-0.0739,
                    sector_positive_20d_rate=29.4,
                    sector_stock_count=17,
                    volume_confirmation_score=55,
                    volume_score=55,
                    price_volume_trend_score=56,
                    route_score=61,
                    route_label="观察路线",
                    route_reason="资金参与顺，但还要看趋势是否跟上",
                    return_1d=0.1001,
                    return_20d=0.0371,
                    distance_to_ma20=0.0835,
                    overheat_score=8.5,
                    volume_trap_risk_score=27.2,
                    risk_score=36,
                ),
            ]
        )
        db.add_all(rows)
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        db.commit()

        items = list_pool_items(db, pool_name="experiment")

    potential = [item for item in result["candidates"] if item["symbol"] == "600673"]
    assert len(potential) == 1
    candidate = potential[0]
    assert candidate["selection_mode"] == "potential_watch"
    assert candidate["selected_rule_id"] == "POT001"
    assert candidate["selected_rule_name"] == "潜力启动观察"
    assert any(
        "潜力观察：个股启动但板块未确认，只观察不行动" in reason
        for reason in candidate["reasons"]
    )
    assert "综合类" in {item["sector"] for item in result["candidates"]}
    stock_tags = {item["symbol"]: item["tags"] for item in items}
    assert "mode:potential_watch" in stock_tags["600673"]
    assert "rule:POT001" in stock_tags["600673"]


def test_discover_next_session_candidates_marks_t_minus_one_startup_preheat() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="002558",
                    name="启动前夜",
                    exchange="SZ",
                    industry="互联网",
                    is_active=True,
                ),
                _bar("002558"),
                _feature(
                    "002558",
                    trend_score=76,
                    relative_strength_score=64,
                    sector_strength_score=52,
                    sector_breadth_score=58,
                    sector_trend_continuity_score=54,
                    sector_trend_resilience_score=62,
                    sector_avg_return_20d=0.015,
                    sector_positive_20d_rate=46,
                    sector_stock_count=38,
                    volume_confirmation_score=66,
                    volume_score=66,
                    price_volume_trend_score=72,
                    route_score=60,
                    route_label="观察路线",
                    route_reason="量价修复但仍需承接确认",
                    return_1d=0.038,
                    return_5d=0.026,
                    return_20d=0.052,
                    distance_to_ma20=0.018,
                    overheat_score=34,
                    volume_trap_risk_score=28,
                    risk_score=32,
                ),
                Security(
                    symbol="002559",
                    name="过热伪启动",
                    exchange="SZ",
                    industry="互联网",
                    is_active=True,
                ),
                _bar("002559"),
                _feature(
                    "002559",
                    trend_score=78,
                    relative_strength_score=66,
                    sector_strength_score=52,
                    sector_breadth_score=58,
                    sector_trend_continuity_score=54,
                    sector_trend_resilience_score=62,
                    sector_avg_return_20d=0.015,
                    sector_positive_20d_rate=46,
                    sector_stock_count=38,
                    volume_confirmation_score=68,
                    volume_score=68,
                    price_volume_trend_score=74,
                    route_score=62,
                    route_label="观察路线",
                    route_reason="量价修复但仍需承接确认",
                    return_1d=0.042,
                    return_5d=0.07,
                    return_20d=0.27,
                    distance_to_ma20=0.11,
                    overheat_score=67,
                    volume_trap_risk_score=40,
                    risk_score=34,
                ),
            ]
        )
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        db.commit()

        items = list_pool_items(db, pool_name="experiment")

    symbols = [item["symbol"] for item in result["candidates"]]
    assert "002558" in symbols
    assert "002559" not in symbols
    candidate = result["candidates"][symbols.index("002558")]
    assert candidate["selection_mode"] == "potential_watch"
    assert candidate["selected_rule_id"] == "POT001"
    assert candidate["startup_signal_label"] == "启动观察"
    assert candidate["startup_signal_score"] >= 70
    assert any("板块修复" in reason for reason in candidate["startup_signal_reasons"])
    assert any("量价修复" in reason for reason in candidate["startup_signal_reasons"])
    assert any("风险可控" in reason for reason in candidate["startup_signal_reasons"])
    assert any("不代表买点" in reason for reason in candidate["startup_signal_reasons"])
    assert any("启动前夜" in reason for reason in candidate["reasons"])
    assert any("成交量开始确认" in reason for reason in candidate["reasons"])
    assert any("T-1" in reason for reason in candidate["reasons"])
    assert any("启动观察" in reason and "不代表买点" in reason for reason in candidate["reasons"])
    stock_tags = {item["symbol"]: item["tags"] for item in items}
    assert "mode:potential_watch" in stock_tags["002558"]
    assert "mode:formal_strategy" not in stock_tags["002558"]
    assert "candidate_pool:startup_preheat" in stock_tags["002558"]
    assert any(tag.startswith("startup_signal_score:") for tag in stock_tags["002558"])
    assert "startup_signal_label:启动观察" in stock_tags["002558"]
    assert any(tag.startswith("startup_signal_reason:") for tag in stock_tags["002558"])


def test_potential_watch_rank_prefers_confirmed_startup_over_spike() -> None:
    def candidate(
        *,
        symbol: str,
        score: float,
        volume: float,
        price_volume: float,
        sector_return: float,
        return_20d: float,
        distance_to_ma20: float,
    ):
        return candidate_module.NextSessionCandidate(
            symbol=symbol,
            name=None,
            sector="元器件",
            sector_style="growth_cycle",
            suggested_horizon_days=10,
            horizon_reason="",
            day_change_pct=0.038,
            score=score,
            route_score=60,
            route_label="观察路线",
            route_reason="量价修复但仍需承接确认",
            selection_mode="potential_watch",
            selected_rule_id="POT001",
            selected_rule_name="潜力启动观察",
            selected_strategy_type="watch_breakout",
            trend_score=76,
            relative_strength_score=64,
            sector_strength_score=58,
            volume_confirmation_score=volume,
            price_volume_trend_score=price_volume,
            sector_avg_return_20d=sector_return,
            return_20d=return_20d,
            distance_to_ma20=distance_to_ma20,
            startup_signal_score=88,
            startup_signal_label="启动观察",
            startup_signal_reasons=["板块修复", "量价修复", "风险可控：不代表买点"],
            reasons=["启动前夜：T-1量价修复，20日涨幅仍不高，只观察次日承接"],
            risk_flags=[],
            matched_rules=[],
        )

    confirmed = candidate(
        symbol="600002",
        score=74,
        volume=82,
        price_volume=80,
        sector_return=0.03,
        return_20d=0.09,
        distance_to_ma20=0.02,
    )
    spike = candidate(
        symbol="600003",
        score=80,
        volume=64,
        price_volume=64,
        sector_return=-0.02,
        return_20d=0.18,
        distance_to_ma20=0.08,
    )

    assert candidate_module._potential_watch_rank_score(
        confirmed
    ) > candidate_module._potential_watch_rank_score(spike)


def test_rank_with_sector_balance_can_cap_sector_slots() -> None:
    def candidate(symbol: str, sector: str, score: float):
        return candidate_module.NextSessionCandidate(
            symbol=symbol,
            name=None,
            sector=sector,
            sector_style="growth_cycle",
            suggested_horizon_days=10,
            horizon_reason="",
            day_change_pct=0.02,
            score=score,
            route_score=60,
            route_label="观察路线",
            route_reason="",
            selection_mode="observation",
            selected_rule_id="OBS001",
            selected_rule_name="观察候选",
            selected_strategy_type="watch_breakout",
            trend_score=76,
            relative_strength_score=64,
            sector_strength_score=60,
            volume_confirmation_score=55,
            price_volume_trend_score=55,
            sector_avg_return_20d=0.03,
            return_20d=0.10,
            distance_to_ma20=0.02,
            startup_signal_score=None,
            startup_signal_label=None,
            startup_signal_reasons=[],
            reasons=[],
            risk_flags=[],
            matched_rules=[],
        )

    selected = candidate_module._rank_with_sector_balance(
        [
            candidate("600001", "半导体", 90),
            candidate("600002", "半导体", 88),
            candidate("600003", "半导体", 86),
            candidate("600004", "消费电子", 70),
        ],
        limit=3,
        max_per_sector=1,
    )

    assert [item.symbol for item in selected[:2]] == ["600001", "600004"]


def test_candidate_discovery_diagnostics_explains_weak_concentrated_pool() -> None:
    diagnostics = candidate_module._candidate_discovery_diagnostics(
        candidate_count=3,
        requested_limit=15,
        effective_limit=3,
        market_regime="weak_trend",
        market_regime_snapshot={"emotion_gate": "risk_off"},
        participation_snapshot={"participation_score": 42, "liquidity_score": 46},
        universe_size=3384,
        min_universe_size=3000,
        sector_groups=[{"sector": "半导体", "count": 3, "avg_score": 61.0}],
    )

    assert diagnostics["state"] == "limited"
    assert diagnostics["candidate_count"] == 3
    assert diagnostics["top_sector"] == "半导体"
    assert any("弱趋势" in reason for reason in diagnostics["reasons"])
    assert any("候选集中在半导体" in reason for reason in diagnostics["reasons"])
    assert any("候选上限" in reason for reason in diagnostics["reasons"])


def test_discover_next_session_candidates_surfaces_fresh_potential_after_crowded_sector() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        rows = []
        for index in range(3):
            symbol = f"60100{index}"
            rows.extend(
                [
                    Security(
                        symbol=symbol,
                        name=f"证券观察{index}",
                        exchange="SH",
                        industry="证券",
                        is_active=True,
                    ),
                    _bar(symbol),
                    _feature(
                        symbol,
                        trend_score=100,
                        relative_strength_score=74 - index,
                        sector_strength_score=82,
                        sector_breadth_score=76,
                        sector_trend_continuity_score=84,
                        sector_trend_resilience_score=66,
                        sector_avg_return_20d=0.28,
                        sector_positive_20d_rate=92,
                        sector_stock_count=50,
                        volume_confirmation_score=70,
                        volume_score=70,
                        route_score=74,
                        return_1d=0.04,
                        return_20d=0.20,
                        distance_to_ma20=0.05,
                        overheat_score=58,
                        volume_trap_risk_score=42,
                        risk_score=34,
                    ),
                ]
            )
        rows.extend(
            [
                Security(
                    symbol="600673",
                    name="东阳光",
                    exchange="SH",
                    industry="综合类",
                    is_active=True,
                ),
                _bar("600673"),
                _feature(
                    "600673",
                    trend_score=94,
                    relative_strength_score=48,
                    sector_strength_score=45,
                    sector_breadth_score=94,
                    sector_trend_continuity_score=38,
                    sector_trend_resilience_score=72,
                    sector_avg_return_20d=-0.0739,
                    sector_positive_20d_rate=29.4,
                    sector_stock_count=17,
                    volume_confirmation_score=55,
                    volume_score=55,
                    price_volume_trend_score=56,
                    route_score=61,
                    route_label="观察路线",
                    route_reason="资金参与顺，但还要看趋势是否跟上",
                    return_1d=0.1001,
                    return_20d=0.0371,
                    distance_to_ma20=0.0835,
                    overheat_score=8.5,
                    volume_trap_risk_score=27.2,
                    risk_score=36,
                ),
            ]
        )
        db.add_all(rows)
        db.commit()

        result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )

    symbols = [item["symbol"] for item in result["candidates"]]
    assert symbols.index("600673") < symbols.index("601002")
    assert result["candidates"][symbols.index("600673")]["selection_mode"] == "potential_watch"


def test_discover_next_session_candidates_keeps_observation_candidates_in_weaker_market() -> None:
    assert (
        _regime_candidate_limit(
            15,
            regime="weak_trend",
            quality_snapshot={
                "strong_trend_rate": 9.0,
                "up_signal_rate": 9.0,
                "weak_structure_rate": 80.0,
            },
            participation_snapshot={
                "participation_score": 30.0,
                "liquidity_score": 25.0,
            },
        )
        == 3
    )


def test_discover_next_session_candidates_excludes_growth_board_by_default() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="普通候选",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="300001",
                    name="创业板候选A",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                Security(
                    symbol="301001",
                    name="创业板候选B",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                _bar("000001"),
                _bar("300001"),
                _bar("301001"),
                _feature("000001"),
                _feature("300001"),
                _feature("301001"),
            ]
        )
        db.commit()

        default_result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
        )
        growth_result = discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=10,
            include_growth_board=True,
        )

    assert [item["symbol"] for item in default_result["candidates"]] == ["000001"]
    assert default_result["include_growth_board"] is False
    growth_symbols = {item["symbol"] for item in growth_result["candidates"]}
    assert {"000001", "300001", "301001"} <= growth_symbols
    assert growth_result["include_growth_board"] is True
