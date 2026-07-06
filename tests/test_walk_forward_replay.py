from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from services.engine.backtest import walk_forward
from services.engine.backtest.walk_forward import (
    WalkForwardCandidate,
    WalkForwardDay,
    WalkForwardReplayResult,
    compare_candidate_walk_forward_scopes,
    run_low_dimensional_walk_forward_replay,
    run_trend_factor_walk_forward_replay,
    summarize_walk_forward_replay,
)
from services.shared.database import Base
from services.shared.models import (
    CandidateDiscoverySnapshot,
    DailyBar,
    LowDimensionalFeatureSnapshot,
    SectorFeatureDaily,
    Security,
    StockFeatureDaily,
)


def _bar(
    symbol: str,
    trade_date: date,
    close: str,
    pre_close: str | None = None,
    open_price: str | None = None,
) -> DailyBar:
    value = Decimal(close)
    open_value = Decimal(open_price) if open_price is not None else value
    previous = Decimal(pre_close) if pre_close is not None else value
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=open_value,
        high=value,
        low=value,
        close=value,
        pre_close=previous,
        volume=Decimal("1000"),
        amount=Decimal("100000"),
        turnover_rate=Decimal("1"),
        limit_up=value * Decimal("1.1"),
        limit_down=value * Decimal("0.9"),
        is_suspended=False,
    )


def _feature(symbol: str, trade_date: date) -> StockFeatureDaily:
    return StockFeatureDaily(
        symbol=symbol,
        trade_date=trade_date,
        features={
            "trend_score": 90,
            "relative_strength_score": 82,
            "sector_strength_score": 78,
            "volume_confirmation_score": 66,
            "volume_score": 66,
            "risk_score": 20,
            "overheat_score": 40,
            "volume_trap_risk_score": 30,
            "distance_to_ma20": 0.02,
            "pullback_volume_ratio": 0.9,
            "return_1d": 0.02,
            "return_20d": 0.12,
            "sector_avg_return_20d": 0.11,
            "sector_positive_20d_rate": 65,
            "sector_breadth_score": 60,
            "sector_trend_continuity_score": 74,
            "sector_trend_resilience_score": 62,
            "sector_stock_count": 30,
        },
    )


def _security(symbol: str, name: str, industry: str) -> Security:
    return Security(
        symbol=symbol,
        name=name,
        exchange="SH",
        industry=industry,
        is_active=True,
        is_st=False,
    )


def test_walk_forward_replay_uses_signal_day_candidates_and_future_returns(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "样本", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", "10", open_price="10"),
                _bar("600001", date(2026, 1, 6), "12", "11"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-06",
        limit=3,
        horizons=(1, 2),
    )

    assert result.start_date == "2026-01-02"
    assert result.end_date == "2026-01-06"
    assert result.days[0].signal_date == "2026-01-02"
    assert result.days[0].next_trade_date == "2026-01-05"
    assert result.days[0].feature_coverage_ratio == 1.0
    assert result.days[0].candidates[0].symbol == "600001"
    assert result.days[0].candidates[0].entry_date == "2026-01-05"
    assert result.days[0].candidates[0].forward_returns[1] == 0.1
    assert result.days[0].candidates[0].forward_returns[2] == 0.2


def test_candidate_walk_forward_replay_tracks_guarded_returns(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "风控样本", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 3), "10", open_price="10"),
                _bar("600001", date(2026, 1, 4), "10.5"),
                _bar("600001", date(2026, 1, 5), "9.3"),
                _bar("600001", date(2026, 1, 6), "11"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "discover_next_session_candidates",
        lambda *_args, **_kwargs: {
            "universe_size": 1,
            "candidates": [
                {
                    "symbol": "600001",
                    "name": "风控样本",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 80,
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                }
            ],
        },
    )

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-06",
        limit=3,
        horizons=(4,),
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
    )

    candidate = result.days[0].candidates[0]
    assert candidate.forward_returns[4] == 0.1
    assert candidate.guarded_forward_returns[4] == -0.07
    assert candidate.guard_exit_days[4] == 3
    assert candidate.guard_exit_reasons[4] == "stop_loss"


def test_candidate_walk_forward_replay_can_skip_fundamentals(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "样本", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    calls: list[bool] = []

    def fake_discover(*_args, include_fundamentals: bool = True, **_kwargs):
        calls.append(include_fundamentals)
        return {
            "universe_size": 1,
            "candidates": [
                {
                    "symbol": "600001",
                    "name": "样本",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 80,
                    "reasons": [],
                    "risk_flags": [],
                }
            ],
        }

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(walk_forward, "discover_next_session_candidates", fake_discover)

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        include_fundamentals=False,
    )

    assert calls == [False]
    assert result.days[0].candidates[0].symbol == "600001"


def test_candidate_walk_forward_replay_can_use_action_candidates(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "观察样本", "证券"),
                _security("600002", "行动样本", "半导体"),
            ]
        )
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "9", "10", open_price="10"),
                _bar("600002", date(2026, 1, 2), "10"),
                _bar("600002", date(2026, 1, 5), "12", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
                _feature("600002", date(2026, 1, 2)),
            ]
        )
        db.commit()

    discovery = {
        "universe_size": 2,
        "candidates": [
            {
                "symbol": "600001",
                "name": "观察样本",
                "sector": "证券",
                "selection_mode": "observation",
                "score": 70,
                "reasons": [],
                "risk_flags": ["板块20日涨幅/扩散已偏拥挤"],
            },
            {
                "symbol": "600002",
                "name": "行动样本",
                "sector": "半导体",
                "selection_mode": "formal_strategy",
                "score": 80,
                "reasons": ["低维主线：板块趋势和个股强度共振"],
                "risk_flags": [],
            },
        ],
    }
    selected_calls: list[int] = []

    def fake_select_action_candidates(discovery_arg, candidates_arg, *, max_items):
        selected_calls.append(max_items)
        assert discovery_arg is discovery
        assert len(candidates_arg) == 2
        return [discovery["candidates"][1]]

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "discover_next_session_candidates",
        lambda *_args, **_kwargs: discovery,
    )
    monkeypatch.setattr(
        walk_forward,
        "select_action_candidates",
        fake_select_action_candidates,
        raising=False,
    )

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        candidate_scope="action",
    )

    assert selected_calls == [3]
    assert [item.symbol for item in result.days[0].candidates] == ["600002"]
    assert result.days[0].candidates[0].forward_returns[1] == 0.2


def test_candidate_walk_forward_replay_can_use_potential_watch_candidates(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "正式样本", "半导体"),
                _security("600002", "潜力样本", "玻璃"),
            ]
        )
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "9", "10", open_price="10"),
                _bar("600002", date(2026, 1, 2), "10"),
                _bar("600002", date(2026, 1, 5), "13", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
                _feature("600002", date(2026, 1, 2)),
            ]
        )
        db.commit()

    discovery = {
        "universe_size": 2,
        "candidates": [
            {
                "symbol": "600001",
                "name": "正式样本",
                "sector": "半导体",
                "selection_mode": "formal_strategy",
                "score": 80,
                "reasons": ["低维主线：板块趋势和个股强度共振"],
                "risk_flags": [],
            },
            {
                "symbol": "600002",
                "name": "潜力样本",
                "sector": "玻璃",
                "selection_mode": "potential_watch",
                "score": 70,
                "reasons": ["潜力启动：20日涨幅仍低，今日向上启动，后续看承接确认"],
                "risk_flags": [],
            },
        ],
    }

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "discover_next_session_candidates",
        lambda *_args, **_kwargs: discovery,
    )

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        candidate_scope="potential_watch",
    )

    assert [item.symbol for item in result.days[0].candidates] == ["600002"]
    assert result.days[0].candidates[0].forward_returns[1] == 0.3


def test_candidate_walk_forward_replay_can_use_startup_preheat_candidates(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "普通潜力", "玻璃"),
                _security("600002", "启动前夜", "互联网"),
            ]
        )
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", "10", open_price="10"),
                _bar("600002", date(2026, 1, 2), "10"),
                _bar("600002", date(2026, 1, 5), "12", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
                _feature("600002", date(2026, 1, 2)),
            ]
        )
        db.commit()

    discovery = {
        "universe_size": 2,
        "candidates": [
            {
                "symbol": "600001",
                "name": "普通潜力",
                "sector": "玻璃",
                "selection_mode": "potential_watch",
                "score": 70,
                "reasons": ["潜力启动：20日涨幅仍低，今日向上启动，后续看承接确认"],
                "risk_flags": [],
            },
            {
                "symbol": "600002",
                "name": "启动前夜",
                "sector": "互联网",
                "selection_mode": "potential_watch",
                "score": 72,
                "reasons": [
                    "启动前夜：T-1量价修复，20日涨幅仍不高，只观察次日承接",
                    "成交量开始确认：温和放量配合价格修复，但未进入核心行动",
                ],
                "risk_flags": [],
            },
        ],
    }

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "discover_next_session_candidates",
        lambda *_args, **_kwargs: discovery,
    )

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        candidate_scope="startup_preheat",
    )

    assert [item.symbol for item in result.days[0].candidates] == ["600002"]
    assert result.days[0].candidates[0].forward_returns[1] == 0.2


def test_candidate_walk_forward_replay_can_use_long_horizon_action_candidates(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "普通行动", "证券"),
                _security("600002", "中期行动", "元器件"),
            ]
        )
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "9", "10", open_price="10"),
                _bar("600002", date(2026, 1, 2), "10"),
                _bar("600002", date(2026, 1, 5), "12", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
                _feature("600002", date(2026, 1, 2)),
            ]
        )
        db.commit()

    discovery = {
        "universe_size": 2,
        "candidates": [
            {
                "symbol": "600001",
                "name": "普通行动",
                "sector": "证券",
                "selection_mode": "formal_strategy",
                "score": 90,
                "reasons": ["趋势+相对强度因子仍有支撑"],
                "risk_flags": [],
            },
            {
                "symbol": "600002",
                "name": "中期行动",
                "sector": "元器件",
                "selection_mode": "formal_strategy",
                "score": 80,
                "reasons": ["中期强者：相对强度或板块扩散足够强"],
                "risk_flags": [],
            },
        ],
    }

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "discover_next_session_candidates",
        lambda *_args, **_kwargs: discovery,
    )
    monkeypatch.setattr(
        walk_forward,
        "select_action_candidates",
        lambda _discovery, candidates, *, max_items: candidates,
    )

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        candidate_scope="action_long",
    )

    assert [item.symbol for item in result.days[0].candidates] == ["600002"]
    assert result.days[0].candidates[0].forward_returns[1] == 0.2


def test_candidate_walk_forward_replay_reuses_discovery_cache_across_scopes(
    monkeypatch,
    tmp_path,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "普通行动", "半导体"),
                _security("600002", "中期行动", "元器件"),
            ]
        )
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", "10", open_price="10"),
                _bar("600002", date(2026, 1, 2), "10"),
                _bar("600002", date(2026, 1, 5), "12", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
                _feature("600002", date(2026, 1, 2)),
            ]
        )
        db.commit()

    calls = 0
    discovery = {
        "universe_size": 2,
        "candidates": [
            {
                "symbol": "600001",
                "name": "普通行动",
                "sector": "半导体",
                "selection_mode": "formal_strategy",
                "score": 84,
                "reasons": ["低维主线：板块趋势和个股强度共振"],
                "risk_flags": [],
            },
            {
                "symbol": "600002",
                "name": "中期行动",
                "sector": "元器件",
                "selection_mode": "formal_strategy",
                "score": 80,
                "reasons": ["中期强者：相对强度或板块扩散足够强"],
                "risk_flags": [],
            },
        ],
    }

    def fake_discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return discovery

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(walk_forward, "discover_next_session_candidates", fake_discover)

    action = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        candidate_scope="action",
        discovery_cache_dir=tmp_path,
    )
    long_action = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        candidate_scope="action_long",
        discovery_cache_dir=tmp_path,
    )

    assert calls == 1
    assert [item.symbol for item in action.days[0].candidates] == ["600001", "600002"]
    assert [item.symbol for item in long_action.days[0].candidates] == ["600002"]


def test_compare_candidate_walk_forward_scopes_reuses_discovery_cache(
    monkeypatch,
    tmp_path,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "普通行动", "半导体"),
                _security("600002", "中期行动", "元器件"),
            ]
        )
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", "10", open_price="10"),
                _bar("600002", date(2026, 1, 2), "10"),
                _bar("600002", date(2026, 1, 5), "12", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
                _feature("600002", date(2026, 1, 2)),
            ]
        )
        db.commit()

    calls = 0
    discovery = {
        "universe_size": 2,
        "candidates": [
            {
                "symbol": "600001",
                "name": "普通行动",
                "sector": "半导体",
                "selection_mode": "formal_strategy",
                "score": 84,
                "reasons": ["低维主线：板块趋势和个股强度共振"],
                "risk_flags": [],
            },
            {
                "symbol": "600002",
                "name": "中期行动",
                "sector": "元器件",
                "selection_mode": "formal_strategy",
                "score": 80,
                "reasons": ["中期强者：相对强度或板块扩散足够强"],
                "risk_flags": [],
            },
        ],
    }

    def fake_discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return discovery

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(walk_forward, "discover_next_session_candidates", fake_discover)

    comparison = compare_candidate_walk_forward_scopes(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        scopes=("all", "action", "action_long"),
        discovery_cache_dir=tmp_path,
    )

    assert calls == 1
    assert comparison["scopes"]["all"]["candidate_count"] == 2
    assert comparison["scopes"]["action"]["candidate_count"] == 2
    assert comparison["scopes"]["action_long"]["candidate_count"] == 1
    assert comparison["scopes"]["action_long"]["horizons"][1]["raw"]["total_return"] == 0.2


def test_candidate_walk_forward_replay_reuses_database_discovery_cache(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "普通行动", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    calls = 0

    def fake_discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "universe_size": 1,
            "candidates": [
                {
                    "symbol": "600001",
                    "name": "普通行动",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 84,
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                }
            ],
        }

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(walk_forward, "discover_next_session_candidates", fake_discover)

    first = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        candidate_scope="all",
        discovery_cache_dir=None,
    )
    second = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        candidate_scope="action",
        discovery_cache_dir=None,
    )

    assert calls == 1
    assert [item.symbol for item in first.days[0].candidates] == ["600001"]
    assert [item.symbol for item in second.days[0].candidates] == ["600001"]


def test_candidate_walk_forward_replay_ignores_future_feature_date_db_cache(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "未来缓存票", "半导体"),
                _security("600002", "当前候选票", "元器件"),
            ]
        )
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "9", "10", open_price="10"),
                _bar("600002", date(2026, 1, 2), "10"),
                _bar("600002", date(2026, 1, 5), "12", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
                _feature("600002", date(2026, 1, 2)),
                CandidateDiscoverySnapshot(
                    cache_version=walk_forward.CANDIDATE_DISCOVERY_CACHE_VERSION,
                    signal_date=date(2026, 1, 2),
                    next_trade_date=date(2026, 1, 5),
                    candidate_limit=3,
                    include_fundamentals=True,
                    discovery_json={
                        "feature_date": "2026-01-06",
                        "universe_size": 2,
                        "candidates": [
                            {
                                "symbol": "600001",
                                "name": "未来缓存票",
                                "sector": "半导体",
                                "selection_mode": "formal_strategy",
                                "score": 99,
                                "reasons": ["未来特征污染"],
                                "risk_flags": [],
                            }
                        ],
                    },
                ),
            ]
        )
        db.commit()

    calls = 0

    def fake_discover(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "feature_date": "2026-01-02",
            "universe_size": 2,
            "candidates": [
                {
                    "symbol": "600002",
                    "name": "当前候选票",
                    "sector": "元器件",
                    "selection_mode": "formal_strategy",
                    "score": 84,
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                }
            ],
        }

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(walk_forward, "discover_next_session_candidates", fake_discover)

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        discovery_cache_dir=None,
    )

    assert calls == 1
    assert [item.symbol for item in result.days[0].candidates] == ["600002"]
    assert result.days[0].candidates[0].forward_returns[1] == 0.2


def test_candidate_walk_forward_replay_rejects_generated_future_feature_date(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "未来生成票", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    def fake_discover(*_args, **_kwargs):
        return {
            "feature_date": "2026-01-06",
            "universe_size": 1,
            "candidates": [
                {
                    "symbol": "600001",
                    "name": "未来生成票",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 84,
                    "reasons": ["未来特征污染"],
                    "risk_flags": [],
                }
            ],
        }

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(walk_forward, "discover_next_session_candidates", fake_discover)

    with pytest.raises(ValueError, match="future feature"):
        walk_forward.run_candidate_walk_forward_replay(
            start_date="2026-01-02",
            end_date="2026-01-05",
            limit=3,
            horizons=(1,),
            discovery_cache_dir=None,
        )


def test_candidate_walk_forward_replay_carries_sector_strength_context(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "强板块候选", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", "10", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    def fake_discover(*_args, **_kwargs):
        return {
            "feature_date": "2026-01-02",
            "universe_size": 1,
            "candidates": [
                {
                    "symbol": "600001",
                    "name": "强板块候选",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 84,
                    "sector_strength_score": 72,
                    "sector_avg_return_20d": 0.11,
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                }
            ],
        }

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(walk_forward, "discover_next_session_candidates", fake_discover)

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
        discovery_cache_dir=None,
    )
    summary = summarize_walk_forward_replay(result, horizons=(1,))

    candidate = result.days[0].candidates[0]
    assert candidate.sector_strength_score == 72
    assert candidate.sector_return_20d == 0.11
    monthly = summary["monthly_horizons"][1]["2026-01"]
    assert monthly["sector_leadership"]["strong_sector_sample_share"] == 1.0
    assert monthly["sector_leadership"]["strong_sector"]["raw"]["total_return"] == 0.1


def test_candidate_discovery_snapshot_uses_large_mysql_json_storage() -> None:
    dialect_impl = CandidateDiscoverySnapshot.__table__.c.discovery_json.type.dialect_impl(
        mysql.dialect()
    )

    assert isinstance(dialect_impl.impl, mysql.LONGTEXT)


def test_candidate_discovery_cache_version_fits_database_column() -> None:
    assert len(walk_forward.CANDIDATE_DISCOVERY_CACHE_VERSION) <= 32


def test_candidate_walk_forward_replay_batches_feature_coverage(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "样本", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "_feature_coverage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("slow per-day coverage")),
    )
    monkeypatch.setattr(
        walk_forward,
        "discover_next_session_candidates",
        lambda *_args, **_kwargs: {
            "universe_size": 1,
            "candidates": [
                {
                    "symbol": "600001",
                    "name": "样本",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 80,
                    "reasons": [],
                    "risk_flags": [],
                }
            ],
        },
    )

    result = walk_forward.run_candidate_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
    )

    assert result.days[0].feature_rows == 1
    assert result.days[0].active_symbols == 1
    assert result.days[0].feature_coverage_ratio == 1.0


def test_low_dimensional_walk_forward_uses_core_sector_features(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "主线A", "半导体"),
                _security("600002", "过热B", "火力发电"),
            ]
        )
        for symbol, closes in {"600001": ["10", "11", "12"], "600002": ["10", "9", "8"]}.items():
            for offset, close in enumerate(closes):
                db.add(_bar(symbol, date(2026, 1, 2 + offset), close))
        db.add(
            _feature(
                "600001",
                date(2026, 1, 2),
            )
        )
        db.add(
            StockFeatureDaily(
                symbol="600002",
                trade_date=date(2026, 1, 2),
                features={
                    **_feature("600002", date(2026, 1, 2)).features,
                    "sector_avg_return_20d": 0.28,
                    "sector_positive_20d_rate": 95,
                },
            )
        )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    result = run_low_dimensional_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-04",
        limit=5,
        horizons=(2,),
    )

    assert [item.symbol for item in result.days[0].candidates] == ["600001"]
    assert result.days[0].candidates[0].forward_returns[2] == round(12 / 11 - 1, 6)
    assert result.days[0].candidates[0].sector_style == "growth_cycle"


def test_low_dimensional_walk_forward_batches_feature_coverage(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "主线A", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "_feature_coverage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("slow per-day coverage")),
    )

    result = run_low_dimensional_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
    )

    assert result.days[0].feature_rows == 1
    assert result.days[0].active_symbols == 1
    assert result.days[0].feature_coverage_ratio == 1.0


def test_replay_data_coverage_report_flags_sparse_early_months(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            _security(f"60000{index}", f"样本{index}", "半导体")
            for index in range(1, 6)
        )
        sparse_day = date(2024, 1, 2)
        full_day = date(2025, 1, 2)
        db.add(_bar("600001", sparse_day, "10"))
        db.add(_feature("600001", sparse_day))
        db.add(
            SectorFeatureDaily(
                sector_code="半导体",
                trade_date=sparse_day,
                features={"sector_strength_score": 60},
            )
        )
        for index in range(1, 6):
            symbol = f"60000{index}"
            db.add(_bar(symbol, full_day, "10"))
            db.add(_feature(symbol, full_day))
        for sector in ("半导体", "通信设备", "PCB"):
            db.add(
                SectorFeatureDaily(
                    sector_code=sector,
                    trade_date=full_day,
                    features={"sector_strength_score": 70},
                )
            )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    report = walk_forward.build_replay_data_coverage_report(
        start_date="2024-01-01",
        end_date="2025-01-31",
        min_trade_days=1,
        min_active_feature_coverage=0.70,
        min_sector_rows=2,
    )

    sparse_month = report["months"][0]
    full_month = report["months"][1]
    assert sparse_month["month"] == "2024-01"
    assert sparse_month["grade"] == "partial"
    assert sparse_month["avg_feature_active_coverage"] == 0.2
    assert any("样本偏窄" in warning for warning in sparse_month["warnings"])
    assert full_month["month"] == "2025-01"
    assert full_month["grade"] == "strong"
    assert report["overall"]["warning_months"] == 1


def test_replay_data_coverage_report_uses_range_counts(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "样本", "半导体"))
        db.add(_bar("600001", date(2024, 1, 2), "10"))
        db.add(_feature("600001", date(2024, 1, 2)))
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "_trade_dates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("coverage report should aggregate by date range")
        ),
    )

    report = walk_forward.build_replay_data_coverage_report(
        start_date="2024-01-01",
        end_date="2024-01-31",
        min_trade_days=1,
        min_active_feature_coverage=0.70,
        min_sector_rows=0,
    )

    assert report["months"][0]["month"] == "2024-01"
    assert report["months"][0]["avg_feature_active_coverage"] == 1.0


def test_replay_data_coverage_report_does_not_downgrade_incomplete_tail_month(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            _security(f"60000{index}", f"样本{index}", "半导体")
            for index in range(1, 6)
        )
        tail_day = date(2026, 7, 1)
        for index in range(1, 6):
            symbol = f"60000{index}"
            db.add(_bar(symbol, tail_day, "10"))
            db.add(_feature(symbol, tail_day))
        for sector in ("半导体", "通信设备"):
            db.add(
                SectorFeatureDaily(
                    sector_code=sector,
                    trade_date=tail_day,
                    features={"sector_strength_score": 70},
                )
            )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    report = walk_forward.build_replay_data_coverage_report(
        start_date="2026-07-01",
        end_date="2026-07-03",
        min_trade_days=10,
        min_active_feature_coverage=0.70,
        min_sector_rows=2,
    )

    assert report["overall"]["grade"] == "strong"
    assert report["overall"]["warning_months"] == 0
    assert report["months"][0]["is_incomplete_tail_month"] is True
    assert report["months"][0]["grade"] == "strong"


def test_low_dimensional_walk_forward_batches_candidate_scan(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "主线A", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "_low_dimensional_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("slow per-day candidates")),
    )

    result = run_low_dimensional_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
    )

    assert [item.symbol for item in result.days[0].candidates] == ["600001"]
    assert result.days[0].candidates[0].forward_returns[1] == 0.1


def test_low_dimensional_walk_forward_uses_snapshot_cache_without_json_decode(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "主线A", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "11", open_price="10"),
                _feature("600001", date(2026, 1, 2)),
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 1, 2),
                    features={
                        "sector_strength_score": 80,
                        "sector_avg_return_20d": 0.12,
                        "sector_positive_20d_rate": 66,
                        "sector_breadth_score": 62,
                        "sector_trend_continuity_score": 76,
                        "sector_trend_resilience_score": 64,
                        "sector_stock_count": 30,
                    },
                ),
            ]
        )
        db.commit()
        synced = walk_forward.sync_low_dimensional_feature_snapshots(
            db,
            start=date(2026, 1, 2),
            end=date(2026, 1, 2),
        )
        db.commit()

    assert synced == 1

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        walk_forward,
        "_feature_text_passes_low_dimensional_prefilter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("raw feature text should not be scanned")
        ),
    )
    monkeypatch.setattr(
        walk_forward.json,
        "loads",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("raw feature JSON should not be decoded")
        ),
    )

    result = run_low_dimensional_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-05",
        limit=3,
        horizons=(1,),
    )

    assert db.execute(select(LowDimensionalFeatureSnapshot)).scalars().all()
    assert [item.symbol for item in result.days[0].candidates] == ["600001"]
    assert result.days[0].candidates[0].forward_returns[1] == 0.1


def test_trend_factor_walk_forward_compares_factor_keys_under_same_sector_gate(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "普通趋势", "半导体"),
                _security("600002", "质量趋势", "半导体"),
            ]
        )
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 5), "10", "10", open_price="10"),
                _bar("600001", date(2026, 1, 6), "9"),
                _bar("600002", date(2026, 1, 2), "10"),
                _bar("600002", date(2026, 1, 5), "10", "10", open_price="10"),
                _bar("600002", date(2026, 1, 6), "12"),
            ]
        )
        weak_quality = _feature("600001", date(2026, 1, 2))
        weak_quality.features = {
            **weak_quality.features,
            "trend_score": 96,
            "trend_quality_score": 58,
            "route_trend_score": 60,
        }
        strong_quality = _feature("600002", date(2026, 1, 2))
        strong_quality.features = {
            **strong_quality.features,
            "trend_score": 82,
            "trend_quality_score": 92,
            "route_trend_score": 90,
        }
        db.add_all([weak_quality, strong_quality])
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    result = run_trend_factor_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-06",
        factor_keys=("trend_score", "trend_quality_score"),
        limit=1,
        horizons=(2,),
    )

    assert result["factors"]["trend_score"]["candidate_count"] == 1
    assert result["factors"]["trend_score"]["top_symbols"] == ["600001"]
    assert result["factors"]["trend_score"]["horizons"][2]["avg_return"] == -0.1
    assert result["factors"]["trend_score"]["horizons"][2]["total_return"] == -0.1
    assert "compounded_return" not in result["factors"]["trend_score"]["horizons"][2]
    assert result["factors"]["trend_quality_score"]["candidate_count"] == 1
    assert result["factors"]["trend_quality_score"]["top_symbols"] == ["600002"]
    assert result["factors"]["trend_quality_score"]["horizons"][2]["avg_return"] == 0.2
    assert result["factors"]["trend_quality_score"]["horizons"][2]["total_return"] == 0.2


def test_low_dimensional_walk_forward_tracks_guarded_returns(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "风控样本", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 3), "10", open_price="10"),
                _bar("600001", date(2026, 1, 4), "10.5"),
                _bar("600001", date(2026, 1, 5), "9.3"),
                _bar("600001", date(2026, 1, 6), "11"),
                _feature("600001", date(2026, 1, 2)),
            ]
        )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    result = run_low_dimensional_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-06",
        limit=5,
        horizons=(4,),
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
    )

    candidate = result.days[0].candidates[0]
    assert candidate.forward_returns[4] == 0.1
    assert candidate.guarded_forward_returns[4] == -0.07
    assert candidate.guard_exit_days[4] == 3
    assert candidate.guard_exit_reasons[4] == "stop_loss"


def test_low_dimensional_walk_forward_batches_daily_bar_return_queries(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "一号", "半导体"),
                _security("600002", "二号", "半导体"),
                _security("600003", "三号", "半导体"),
            ]
        )
        for symbol in ("600001", "600002", "600003"):
            db.add_all(
                [
                    _bar(symbol, date(2026, 1, 2), "10"),
                    _bar(symbol, date(2026, 1, 5), "10", open_price="10"),
                    _bar(symbol, date(2026, 1, 6), "11"),
                ]
            )
            db.add(_feature(symbol, date(2026, 1, 2)))
        db.commit()

    daily_bar_selects = 0

    @event.listens_for(engine, "before_cursor_execute")
    def count_daily_bar_selects(_conn, _cursor, statement, _params, _context, _executemany):
        nonlocal daily_bar_selects
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and "from daily_bars" in normalized:
            daily_bar_selects += 1

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    result = run_low_dimensional_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-06",
        limit=3,
        horizons=(2,),
    )

    assert len(result.days[0].candidates) == 3
    assert daily_bar_selects <= 3


def test_low_dimensional_feature_prefilter_uses_text_fallback_for_mysql() -> None:
    stmt = walk_forward._low_dimensional_feature_prefilter_stmt(
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        dialect_name="mysql",
    )

    sql = str(
        stmt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()

    assert "json_extract" not in sql
    assert "features_text" in sql


def test_low_dimensional_feature_prefilter_pushes_core_stock_filters_to_sqlite() -> None:
    stmt = walk_forward._low_dimensional_feature_prefilter_stmt(
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        dialect_name="sqlite",
    )

    sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()

    assert "json_extract" in sql
    assert "$.trend_score" in sql
    assert "$.relative_strength_score" in sql
    assert "$.return_20d" in sql
    assert "$.distance_to_ma20" in sql
    assert "json_unquote" not in sql


def test_low_dimensional_feature_text_prefilter_matches_core_stock_filters() -> None:
    passing_features = (
        '{"trend_score": 72, "relative_strength_score": 64, '
        '"return_20d": 0.12, "distance_to_ma20": 0.03}'
    )
    weak_trend_features = (
        '{"trend_score": 69, "relative_strength_score": 90, '
        '"return_20d": 0.12, "distance_to_ma20": 0.03}'
    )
    overextended_features = (
        '{"trend_score": 90, "relative_strength_score": 90, '
        '"return_20d": 0.30, "distance_to_ma20": 0.03}'
    )
    assert walk_forward._feature_text_passes_low_dimensional_prefilter(
        passing_features
    )
    assert not walk_forward._feature_text_passes_low_dimensional_prefilter(
        weak_trend_features
    )
    assert not walk_forward._feature_text_passes_low_dimensional_prefilter(
        overextended_features
    )


def test_low_dimensional_walk_forward_loosens_guard_for_persistent_mainline(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "强趋势样本", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 3), "10", open_price="10"),
                _bar("600001", date(2026, 1, 4), "12"),
                _bar("600001", date(2026, 1, 5), "10.9"),
                _bar("600001", date(2026, 1, 6), "14"),
            ]
        )
        strong_mainline = _feature("600001", date(2026, 1, 2))
        strong_mainline.features = {
            **strong_mainline.features,
            "sector_avg_return_20d": 0.15,
            "sector_strength_score": 82,
            "sector_trend_continuity_score": 82,
            "sector_breadth_score": 68,
            "sector_trend_resilience_score": 70,
            "price_volume_trend_score": 78,
            "volume_confirmation_score": 74,
            "overheat_score": 45,
            "volume_trap_risk_score": 35,
        }
        db.add(strong_mainline)
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    result = run_low_dimensional_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-06",
        limit=5,
        horizons=(4,),
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
    )

    candidate = result.days[0].candidates[0]
    assert candidate.forward_returns[4] == 0.4
    assert candidate.guarded_forward_returns[4] == 0.4
    assert candidate.guard_exit_days[4] == 4
    assert candidate.guard_exit_reasons[4] == "horizon"


def test_guard_parameters_keep_default_when_volume_does_not_confirm() -> None:
    features = {
        **_feature("600001", date(2026, 1, 2)).features,
        "sector_trend_continuity_score": 76,
        "sector_breadth_score": 78,
        "sector_trend_resilience_score": 72,
        "volume_confirmation_score": 42,
        "price_volume_trend_score": 44,
        "overheat_score": 20,
        "volume_trap_risk_score": 35,
    }

    assert walk_forward._guard_parameters_for_features(
        features,
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
    ) == (0.06, 0.08)


def test_guard_parameters_loosen_for_durable_mainline_with_standard_sector_strength() -> None:
    features = {
        **_feature("600001", date(2026, 1, 2)).features,
        "sector_strength_score": 75,
        "sector_trend_continuity_score": 74,
        "sector_breadth_score": 78,
        "sector_trend_resilience_score": 70,
        "volume_confirmation_score": 68,
        "price_volume_trend_score": 68,
        "overheat_score": 25,
        "volume_trap_risk_score": 40,
    }

    stop_loss, trailing_drawdown = walk_forward._guard_parameters_for_features(
        features,
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
    )

    assert round(stop_loss, 4) == 0.06
    assert round(trailing_drawdown, 4) == 0.12


def test_low_dimensional_walk_forward_merges_sector_features(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(_security("600001", "主线A", "半导体"))
        db.add_all(
            [
                _bar("600001", date(2026, 1, 2), "10"),
                _bar("600001", date(2026, 1, 3), "11"),
                StockFeatureDaily(
                    symbol="600001",
                    trade_date=date(2026, 1, 2),
                    features={
                        "trend_score": 90,
                        "relative_strength_score": 82,
                        "volume_confirmation_score": 66,
                        "volume_score": 66,
                        "risk_score": 20,
                        "overheat_score": 40,
                        "volume_trap_risk_score": 30,
                        "distance_to_ma20": 0.02,
                        "return_20d": 0.12,
                    },
                ),
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=date(2026, 1, 2),
                    features={
                        "sector_strength_score": 78,
                        "sector_avg_return_20d": 0.11,
                        "sector_positive_20d_rate": 65,
                        "sector_breadth_score": 60,
                        "sector_trend_continuity_score": 74,
                        "sector_trend_resilience_score": 62,
                        "sector_stock_count": 30,
                    },
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    result = run_low_dimensional_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-03",
        limit=5,
        horizons=(1,),
    )

    assert [item.symbol for item in result.days[0].candidates] == ["600001"]


def test_low_dimensional_walk_forward_rejects_strong_stock_in_weak_sector(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "弱板块强股", "弱势题材"),
                _security("600002", "强板块稳股", "半导体"),
            ]
        )
        for symbol in ("600001", "600002"):
            db.add_all(
                [
                    _bar(symbol, date(2026, 1, 2), "10"),
                    _bar(symbol, date(2026, 1, 3), "11"),
                ]
            )
        weak_stock = _feature("600001", date(2026, 1, 2))
        weak_stock.features = {
            **weak_stock.features,
            "trend_score": 96,
            "relative_strength_score": 94,
            "sector_strength_score": 52,
            "sector_trend_continuity_score": 50,
            "sector_avg_return_20d": 0.01,
            "sector_positive_20d_rate": 38,
            "sector_stock_count": 40,
        }
        strong_sector_stock = _feature("600002", date(2026, 1, 2))
        strong_sector_stock.features = {
            **strong_sector_stock.features,
            "trend_score": 74,
            "relative_strength_score": 66,
            "sector_strength_score": 68,
            "sector_trend_continuity_score": 70,
            "sector_avg_return_20d": 0.10,
            "sector_positive_20d_rate": 60,
            "sector_stock_count": 40,
        }
        db.add_all([weak_stock, strong_sector_stock])
        db.commit()

    monkeypatch.setattr(walk_forward, "SessionLocal", lambda: Session(engine))

    result = run_low_dimensional_walk_forward_replay(
        start_date="2026-01-02",
        end_date="2026-01-03",
        limit=5,
        horizons=(1,),
    )

    assert [item.symbol for item in result.days[0].candidates] == ["600002"]


def test_walk_forward_summary_breaks_returns_down_by_sector_style() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-01-31",
        processed_days=1,
        days=[
            WalkForwardDay(
                signal_date="2026-01-02",
                next_trade_date="2026-01-05",
                universe_size=2,
                feature_rows=2,
                active_symbols=2,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="600001",
                        name="科技样本",
                        sector="半导体",
                        sector_style="growth_cycle",
                        selection_mode="low_dimensional_mainline",
                        score=80,
                        entry_date="2026-01-05",
                        forward_returns={20: 0.2},
                        guarded_forward_returns={20: 0.15},
                    ),
                    WalkForwardCandidate(
                        symbol="600002",
                        name="周期样本",
                        sector="铜",
                        sector_style="cyclical",
                        selection_mode="low_dimensional_mainline",
                        score=78,
                        entry_date="2026-01-05",
                        forward_returns={20: -0.1},
                        guarded_forward_returns={20: -0.06},
                    ),
                ],
            )
        ],
    )

    summary = summarize_walk_forward_replay(result, horizons=(20,))

    assert summary["style_counts"] == [
        {"style": "cyclical", "count": 1},
        {"style": "growth_cycle", "count": 1},
    ]
    assert summary["style_horizons"][20]["growth_cycle"]["raw"]["total_return"] == 0.2
    assert summary["style_horizons"][20]["cyclical"]["guarded"]["total_return"] == -0.06
    assert (
        summary["monthly_style_horizons"][20]["2026-01"]["growth_cycle"]["raw"][
            "total_return"
        ]
        == 0.2
    )
    assert (
        summary["monthly_style_horizons"][20]["2026-01"]["cyclical"]["guarded"][
            "total_return"
        ]
        == -0.06
    )


def test_walk_forward_summary_recommends_style_horizon_by_guarded_avg() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-01-31",
        processed_days=1,
        days=[
            WalkForwardDay(
                signal_date="2026-01-02",
                next_trade_date="2026-01-05",
                universe_size=2,
                feature_rows=2,
                active_symbols=2,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="600001",
                        name="科技样本",
                        sector="半导体",
                        sector_style="growth_cycle",
                        selection_mode="low_dimensional_mainline",
                        score=80,
                        entry_date="2026-01-05",
                        forward_returns={5: 0.08, 10: -0.02, 20: -0.08},
                        guarded_forward_returns={5: 0.08, 10: -0.01, 20: -0.05},
                    ),
                    WalkForwardCandidate(
                        symbol="600002",
                        name="周期样本",
                        sector="铜",
                        sector_style="cyclical",
                        selection_mode="low_dimensional_mainline",
                        score=78,
                        entry_date="2026-01-05",
                        forward_returns={5: 0.01, 10: 0.03, 20: 0.12},
                        guarded_forward_returns={5: 0.01, 10: 0.03, 20: 0.12},
                    ),
                ],
            )
        ],
    )

    summary = summarize_walk_forward_replay(result, horizons=(5, 10, 20))

    assert summary["style_horizon_preferences"]["growth_cycle"] == {
        "preferred_horizon": 5,
        "preferred_metric": "guarded_avg_return",
        "sample_count": 1,
        "avg_return": 0.08,
        "total_return": 0.08,
        "actionable": False,
        "reason": "样本不足或收益不正，只作观察",
    }
    assert summary["style_horizon_preferences"]["cyclical"]["preferred_horizon"] == 20
    assert summary["style_horizon_preferences"]["cyclical"]["avg_return"] == 0.12


def test_walk_forward_style_horizon_preference_marks_thin_samples_non_actionable() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-01-31",
        processed_days=1,
        days=[
            WalkForwardDay(
                signal_date="2026-01-02",
                next_trade_date="2026-01-05",
                universe_size=1,
                feature_rows=1,
                active_symbols=1,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="600001",
                        name="题材样本",
                        sector="AI算力",
                        sector_style="theme",
                        selection_mode="low_dimensional_mainline",
                        score=80,
                        entry_date="2026-01-05",
                        forward_returns={5: -0.03, 10: -0.02},
                        guarded_forward_returns={5: -0.03, 10: -0.02},
                    ),
                ],
            )
        ],
    )

    summary = summarize_walk_forward_replay(result, horizons=(5, 10))

    assert summary["style_horizon_preferences"]["theme"]["actionable"] is False
    assert summary["style_horizon_preferences"]["theme"]["reason"] == "样本不足或收益不正，只作观察"


def test_low_dimensional_score_ranks_sector_before_stock_strength() -> None:
    strong_stock_weak_sector = {
        "trend_score": 95,
        "relative_strength_score": 92,
        "sector_strength_score": 52,
        "sector_trend_continuity_score": 50,
        "sector_avg_return_20d": 0.01,
        "sector_positive_20d_rate": 38,
        "sector_stock_count": 30,
        "return_20d": 0.14,
        "distance_to_ma20": 0.03,
    }
    steady_stock_strong_sector = {
        "trend_score": 74,
        "relative_strength_score": 66,
        "sector_strength_score": 70,
        "sector_trend_continuity_score": 72,
        "sector_trend_resilience_score": 62,
        "sector_avg_return_20d": 0.10,
        "sector_positive_20d_rate": 62,
        "sector_breadth_score": 58,
        "sector_stock_count": 30,
        "return_20d": 0.12,
        "distance_to_ma20": 0.03,
    }

    assert not walk_forward._is_low_dimensional_candidate(strong_stock_weak_sector)
    assert walk_forward._is_low_dimensional_candidate(steady_stock_strong_sector)


def test_low_dimensional_score_keeps_auxiliary_noise_below_sector_trend() -> None:
    stronger_sector_trend_with_messy_auxiliary = {
        "trend_score": 78,
        "relative_strength_score": 68,
        "sector_strength_score": 76,
        "sector_trend_continuity_score": 76,
        "sector_trend_resilience_score": 62,
        "sector_avg_return_20d": 0.10,
        "sector_positive_20d_rate": 62,
        "sector_breadth_score": 58,
        "sector_stock_count": 30,
        "return_20d": 0.12,
        "distance_to_ma20": 0.03,
        "max_drawdown_20d": -0.20,
        "overheat_score": 70,
        "volume_trap_risk_score": 70,
    }
    weaker_core_with_clean_auxiliary = {
        **stronger_sector_trend_with_messy_auxiliary,
        "trend_score": 70,
        "relative_strength_score": 62,
        "sector_strength_score": 60,
        "sector_trend_continuity_score": 65,
        "max_drawdown_20d": -0.06,
        "overheat_score": 20,
        "volume_trap_risk_score": 20,
    }

    assert walk_forward._is_low_dimensional_candidate(stronger_sector_trend_with_messy_auxiliary)
    assert walk_forward._is_low_dimensional_candidate(weaker_core_with_clean_auxiliary)
    assert walk_forward._low_dimensional_score(
        stronger_sector_trend_with_messy_auxiliary
    ) > walk_forward._low_dimensional_score(weaker_core_with_clean_auxiliary)


def test_low_dimensional_score_uses_volume_as_confirmation_not_primary_factor() -> None:
    base = {
        "trend_score": 78,
        "relative_strength_score": 68,
        "sector_strength_score": 76,
        "sector_trend_continuity_score": 76,
        "sector_trend_resilience_score": 62,
        "sector_avg_return_20d": 0.10,
        "sector_positive_20d_rate": 62,
        "sector_breadth_score": 58,
        "sector_stock_count": 30,
        "return_20d": 0.12,
        "distance_to_ma20": 0.03,
        "max_drawdown_20d": -0.08,
        "overheat_score": 35,
        "volume_trap_risk_score": 35,
    }
    confirmed_volume = {
        **base,
        "volume_confirmation_score": 76,
        "price_volume_trend_score": 78,
    }
    weak_volume = {
        **base,
        "volume_confirmation_score": 36,
        "price_volume_trend_score": 40,
    }

    assert walk_forward._is_low_dimensional_candidate(confirmed_volume)
    assert walk_forward._is_low_dimensional_candidate(weak_volume)
    assert walk_forward._low_dimensional_score(
        confirmed_volume
    ) > walk_forward._low_dimensional_score(weak_volume)


def test_low_dimensional_walk_forward_rejects_stale_sector_breadth() -> None:
    stale_sector = {
        "trend_score": 92,
        "relative_strength_score": 86,
        "sector_strength_score": 78,
        "sector_trend_continuity_score": 76,
        "sector_trend_resilience_score": 52,
        "sector_breadth_score": 32,
        "sector_avg_return_20d": 0.12,
        "sector_positive_20d_rate": 72,
        "sector_stock_count": 40,
        "return_20d": 0.14,
        "distance_to_ma20": 0.03,
    }

    assert not walk_forward._is_low_dimensional_candidate(stale_sector)


def test_low_dimensional_walk_forward_downranks_deep_stock_drawdown() -> None:
    weak_when_market_weak = {
        "trend_score": 92,
        "relative_strength_score": 86,
        "sector_strength_score": 78,
        "sector_breadth_score": 60,
        "sector_trend_continuity_score": 76,
        "sector_trend_resilience_score": 66,
        "sector_avg_return_20d": 0.12,
        "sector_positive_20d_rate": 65,
        "sector_stock_count": 40,
        "return_20d": 0.14,
        "return_5d": 0.02,
        "max_drawdown_20d": -0.18,
        "distance_to_20d_low": 0.02,
        "distance_to_ma20": 0.03,
    }

    resilient_stock = {
        **weak_when_market_weak,
        "max_drawdown_20d": -0.10,
    }

    assert walk_forward._is_low_dimensional_candidate(weak_when_market_weak)
    assert (
        walk_forward._low_dimensional_score(resilient_stock)
        > walk_forward._low_dimensional_score(weak_when_market_weak)
    )


def test_low_dimensional_walk_forward_rejects_deep_drawdown_without_repair() -> None:
    deep_drawdown_without_repair = {
        "trend_score": 88,
        "relative_strength_score": 80,
        "sector_strength_score": 78,
        "sector_breadth_score": 60,
        "sector_trend_continuity_score": 76,
        "sector_trend_resilience_score": 66,
        "sector_avg_return_20d": 0.12,
        "sector_positive_20d_rate": 65,
        "sector_stock_count": 40,
        "return_20d": 0.14,
        "return_5d": 0.01,
        "max_drawdown_20d": -0.24,
        "distance_to_20d_low": 0.08,
        "distance_to_ma20": 0.03,
    }

    assert not walk_forward._is_low_dimensional_candidate(deep_drawdown_without_repair)


def test_low_dimensional_walk_forward_allows_controlled_repair_near_low() -> None:
    strong_repair_near_low = {
        "trend_score": 92,
        "relative_strength_score": 86,
        "sector_strength_score": 78,
        "sector_breadth_score": 60,
        "sector_trend_continuity_score": 76,
        "sector_trend_resilience_score": 66,
        "sector_avg_return_20d": 0.12,
        "sector_positive_20d_rate": 65,
        "sector_stock_count": 40,
        "return_20d": 0.14,
        "return_5d": 0.04,
        "max_drawdown_20d": -0.10,
        "distance_to_20d_low": 0.02,
        "distance_to_ma20": 0.03,
    }

    assert walk_forward._is_low_dimensional_candidate(strong_repair_near_low)


def test_summarize_walk_forward_replay_compares_raw_and_guarded_returns() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-01-31",
        processed_days=2,
        days=[
            WalkForwardDay(
                signal_date="2026-01-02",
                next_trade_date="2026-01-05",
                universe_size=2,
                feature_rows=2,
                active_symbols=2,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="600001",
                        name="A",
                        sector="半导体",
                        selection_mode="low_dimensional_mainline",
                        score=80,
                        entry_date="2026-01-05",
                        forward_returns={20: -0.10},
                        guarded_forward_returns={20: -0.04},
                        guard_exit_days={20: 6},
                        guard_exit_reasons={20: "stop_loss"},
                    ),
                    WalkForwardCandidate(
                        symbol="600002",
                        name="B",
                        sector="半导体",
                        selection_mode="low_dimensional_mainline",
                        score=78,
                        entry_date="2026-01-05",
                        forward_returns={20: 0.20},
                        guarded_forward_returns={20: 0.12},
                        guard_exit_days={20: 20},
                        guard_exit_reasons={20: "horizon"},
                    ),
                ],
            )
        ],
    )

    summary = summarize_walk_forward_replay(result, horizons=(20,))

    assert summary["candidate_count"] == 2
    assert summary["horizons"][20]["raw"]["avg_return"] == 0.05
    assert summary["horizons"][20]["raw"]["total_return"] == 0.1
    assert "compounded_return" not in summary["horizons"][20]["raw"]
    assert summary["horizons"][20]["guarded"]["avg_return"] == 0.04
    assert summary["horizons"][20]["guarded"]["total_return"] == 0.08
    assert "compounded_return" not in summary["horizons"][20]["guarded"]
    assert summary["horizons"][20]["guarded"]["exit_reasons"]["stop_loss"] == 1
    assert summary["top_sectors"][0]["sector"] == "半导体"


def test_summarize_walk_forward_replay_groups_monthly_simple_returns() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-02-28",
        processed_days=3,
        days=[
            WalkForwardDay(
                signal_date="2026-01-02",
                next_trade_date="2026-01-05",
                universe_size=2,
                feature_rows=2,
                active_symbols=2,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="600001",
                        name="A",
                        sector="半导体",
                        selection_mode="low_dimensional_mainline",
                        score=80,
                        entry_date="2026-01-05",
                        forward_returns={20: 0.08},
                        guarded_forward_returns={20: 0.05},
                        guard_exit_days={20: 20},
                        guard_exit_reasons={20: "horizon"},
                    ),
                    WalkForwardCandidate(
                        symbol="600002",
                        name="B",
                        sector="半导体",
                        selection_mode="low_dimensional_mainline",
                        score=78,
                        entry_date="2026-01-06",
                        forward_returns={20: -0.02},
                        guarded_forward_returns={20: -0.04},
                        guard_exit_days={20: 7},
                        guard_exit_reasons={20: "stop_loss"},
                    ),
                ],
            ),
            WalkForwardDay(
                signal_date="2026-02-02",
                next_trade_date="2026-02-03",
                universe_size=2,
                feature_rows=2,
                active_symbols=2,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="600003",
                        name="C",
                        sector="机器人",
                        selection_mode="low_dimensional_mainline",
                        score=77,
                        entry_date="2026-02-03",
                        forward_returns={20: 0.12},
                        guarded_forward_returns={20: 0.10},
                        guard_exit_days={20: 20},
                        guard_exit_reasons={20: "horizon"},
                    )
                ],
            ),
        ],
    )

    summary = summarize_walk_forward_replay(result, horizons=(20,))

    monthly = summary["monthly_horizons"][20]
    assert monthly["2026-01"]["raw"]["sample_count"] == 2
    assert monthly["2026-01"]["raw"]["total_return"] == 0.06
    assert monthly["2026-01"]["guarded"]["total_return"] == 0.01
    assert monthly["2026-02"]["raw"]["total_return"] == 0.12
    assert "compounded_return" not in monthly["2026-02"]["raw"]


def test_summarize_walk_forward_replay_groups_selection_modes() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-02-28",
        processed_days=2,
        days=[
            WalkForwardDay(
                signal_date="2026-01-02",
                next_trade_date="2026-01-05",
                universe_size=2,
                feature_rows=2,
                active_symbols=2,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="600001",
                        name="正式",
                        sector="半导体",
                        selection_mode="formal_strategy",
                        score=80,
                        entry_date="2026-01-05",
                        forward_returns={5: -0.02},
                        guarded_forward_returns={5: -0.04},
                    ),
                    WalkForwardCandidate(
                        symbol="600002",
                        name="潜力",
                        sector="半导体",
                        selection_mode="potential_watch",
                        score=78,
                        entry_date="2026-01-05",
                        forward_returns={5: 0.08},
                        guarded_forward_returns={5: 0.06},
                    ),
                ],
            ),
            WalkForwardDay(
                signal_date="2026-02-02",
                next_trade_date="2026-02-03",
                universe_size=1,
                feature_rows=1,
                active_symbols=1,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="600003",
                        name="观察",
                        sector="机器人",
                        selection_mode="observation",
                        score=77,
                        entry_date="2026-02-03",
                        forward_returns={5: 0.12},
                        guarded_forward_returns={5: 0.10},
                    )
                ],
            ),
        ],
    )

    summary = summarize_walk_forward_replay(result, horizons=(5,))

    assert summary["selection_mode_counts"] == [
        {"selection_mode": "formal_strategy", "count": 1},
        {"selection_mode": "observation", "count": 1},
        {"selection_mode": "potential_watch", "count": 1},
    ]
    assert summary["selection_mode_horizons"][5]["formal_strategy"]["guarded"][
        "total_return"
    ] == -0.04
    assert summary["selection_mode_horizons"][5]["potential_watch"]["guarded"][
        "total_return"
    ] == 0.06
    assert summary["monthly_selection_mode_horizons"][5]["2026-02"]["observation"][
        "guarded"
    ]["total_return"] == 0.10


def test_summarize_walk_forward_replay_excludes_noise_and_attributes_strong_sectors() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-01-31",
        processed_days=1,
        days=[
            WalkForwardDay(
                signal_date="2026-01-02",
                next_trade_date="2026-01-05",
                universe_size=3,
                feature_rows=3,
                active_symbols=3,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="000001",
                        name="噪音样本",
                        sector="银行",
                        selection_mode="low_dimensional_mainline",
                        score=99,
                        entry_date="2026-01-05",
                        forward_returns={20: 0.50},
                        guarded_forward_returns={20: 0.30},
                        sector_strength_score=90,
                        sector_return_20d=0.20,
                    ),
                    WalkForwardCandidate(
                        symbol="600001",
                        name="强板块样本",
                        sector="半导体",
                        selection_mode="low_dimensional_mainline",
                        score=80,
                        entry_date="2026-01-05",
                        forward_returns={20: 0.10},
                        guarded_forward_returns={20: 0.08},
                        sector_strength_score=72,
                        sector_return_20d=0.11,
                    ),
                    WalkForwardCandidate(
                        symbol="600002",
                        name="弱板块样本",
                        sector="综合类",
                        selection_mode="low_dimensional_mainline",
                        score=78,
                        entry_date="2026-01-05",
                        forward_returns={20: 0.02},
                        guarded_forward_returns={20: 0.01},
                        sector_strength_score=54,
                        sector_return_20d=0.02,
                    ),
                ],
            )
        ],
    )

    summary = summarize_walk_forward_replay(result, horizons=(20,))

    assert summary["candidate_count"] == 2
    assert summary["excluded_symbols"] == ["000001"]
    assert summary["horizons"][20]["raw"]["total_return"] == 0.12
    monthly = summary["monthly_horizons"][20]["2026-01"]
    assert monthly["raw"]["total_return"] == 0.12
    assert monthly["sector_leadership"]["strong_sector"]["raw"]["total_return"] == 0.10
    assert monthly["sector_leadership"]["other_sector"]["raw"]["total_return"] == 0.02
    assert monthly["sector_leadership"]["strong_sector_return_share"] == 0.833333


def test_summarize_walk_forward_replay_reports_equal_weight_portfolio_returns() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-01-31",
        processed_days=2,
        days=[
            WalkForwardDay(
                signal_date="2026-01-02",
                next_trade_date="2026-01-05",
                universe_size=4,
                feature_rows=4,
                active_symbols=4,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="600001",
                        name="一号",
                        sector="半导体",
                        selection_mode="formal_strategy",
                        score=90,
                        entry_date="2026-01-05",
                        forward_returns={5: 0.09},
                        guarded_forward_returns={5: 0.06},
                    ),
                    WalkForwardCandidate(
                        symbol="600002",
                        name="二号",
                        sector="元器件",
                        selection_mode="formal_strategy",
                        score=88,
                        entry_date="2026-01-05",
                        forward_returns={5: -0.03},
                        guarded_forward_returns={5: -0.02},
                    ),
                    WalkForwardCandidate(
                        symbol="600003",
                        name="三号",
                        sector="软件服务",
                        selection_mode="formal_strategy",
                        score=86,
                        entry_date="2026-01-05",
                        forward_returns={5: 0.06},
                        guarded_forward_returns={5: 0.03},
                    ),
                    WalkForwardCandidate(
                        symbol="600004",
                        name="四号",
                        sector="电气设备",
                        selection_mode="formal_strategy",
                        score=84,
                        entry_date="2026-01-05",
                        forward_returns={5: 0.30},
                        guarded_forward_returns={5: 0.20},
                    ),
                ],
            ),
            WalkForwardDay(
                signal_date="2026-01-05",
                next_trade_date="2026-01-06",
                universe_size=2,
                feature_rows=2,
                active_symbols=2,
                feature_coverage_ratio=1.0,
                candidates=[
                    WalkForwardCandidate(
                        symbol="000001",
                        name="噪音样本",
                        sector="银行",
                        selection_mode="formal_strategy",
                        score=99,
                        entry_date="2026-01-06",
                        forward_returns={5: 0.50},
                        guarded_forward_returns={5: 0.40},
                    ),
                    WalkForwardCandidate(
                        symbol="600005",
                        name="五号",
                        sector="小金属",
                        selection_mode="formal_strategy",
                        score=82,
                        entry_date="2026-01-06",
                        forward_returns={5: -0.02},
                        guarded_forward_returns={5: -0.01},
                    ),
                ],
            ),
        ],
    )

    summary = summarize_walk_forward_replay(result, horizons=(5,))

    portfolio = summary["portfolio_horizons"][5]
    assert portfolio["max_positions"] == 3
    assert portfolio["raw"]["sample_count"] == 2
    assert portfolio["raw"]["avg_return"] == 0.01
    assert portfolio["raw"]["total_return"] == 0.02
    assert portfolio["raw"]["win_rate"] == 0.5
    assert portfolio["guarded"]["avg_return"] == 0.006666
    monthly = summary["monthly_portfolio_horizons"][5]["2026-01"]
    assert monthly["raw"]["sample_count"] == 2
    assert monthly["raw"]["total_return"] == 0.02
