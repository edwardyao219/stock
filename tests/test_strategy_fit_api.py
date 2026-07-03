from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.main import create_app
from apps.api.app.routers import rules
from apps.api.app.routers.rules import (
    get_candidate_replay_effect,
    get_low_dimensional_replay,
    get_strategy_fit,
)
from services.shared.database import Base
from services.shared.models import BacktestTradeRecord, ParameterRecommendation, Security


def _trade(rule_id: str, symbol: str, signal_day: int, pnl: str) -> BacktestTradeRecord:
    return BacktestTradeRecord(
        run_date=date(2026, 6, 24),
        rule_id=rule_id,
        symbol=symbol,
        signal_date=date(2026, 1, signal_day),
        entry_date=date(2026, 1, signal_day + 1),
        entry_price=Decimal("10"),
        exit_date=date(2026, 1, signal_day + 2),
        exit_price=Decimal("10.5"),
        holding_days=2,
        pnl_pct=Decimal(pnl),
        mfe_pct=Decimal("0.06"),
        mae_pct=Decimal("-0.03"),
        exit_reason="time_exit",
    )


def test_strategy_fit_route_is_registered() -> None:
    schema = create_app().openapi()

    assert "/rules/strategy-fit" in schema["paths"]
    assert "/rules/low-dimensional-replay" in schema["paths"]
    assert "/rules/candidate-replay-effect" in schema["paths"]


def test_get_strategy_fit_returns_rule_sector_symbol_metrics_and_reasons() -> None:
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
                    symbol="600183",
                    name="生益科技",
                    exchange="SH",
                    list_date=None,
                    industry="PCB",
                    is_active=True,
                ),
            ]
        )
        db.add_all(
            [
                _trade("R007", "603083", 1, "-0.05"),
                _trade("R007", "603083", 2, "-0.03"),
                _trade("R007", "600183", 3, "0.04"),
                _trade("R002", "603083", 4, "0.03"),
            ]
        )
        db.add(
            ParameterRecommendation(
                report_date=date(2026, 6, 24),
                rule_id="R007",
                scope_type="sector",
                scope_value="通信设备",
                target_type="entry_filter",
                target_name="backtest_scope_quality",
                action="reduce_priority_or_require_confirmation",
                priority="high",
                rationale="R007 在通信设备历史回归偏弱",
                current_json={"sample_count": 2},
                proposed_json={"priority_score_delta": -2, "source_rule_id": "R007"},
                guardrails_json={"items": []},
                source_report_type="backtest_learning_review",
                status="pending",
            )
        )
        db.commit()

        payload = get_strategy_fit(db=db, report_date="2026-06-24", rule_id="R007")

    assert payload["report_date"] == "2026-06-24"
    assert [item["rule_id"] for item in payload["rules"]] == ["R007"]
    rule_payload = payload["rules"][0]
    assert rule_payload["overall"]["trade_count"] == 3
    sector_payload = next(
        item for item in rule_payload["sectors"] if item["scope_value"] == "通信设备"
    )
    assert sector_payload["fit_status"] == "weak"
    assert sector_payload["recommendations"][0]["rationale"] == "R007 在通信设备历史回归偏弱"
    symbol_payload = next(
        item for item in rule_payload["symbols"] if item["scope_value"] == "603083"
    )
    assert symbol_payload["trade_count"] == 2


def test_strategy_fit_prefers_stable_long_term_returns_over_win_rate() -> None:
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
                    symbol="600183",
                    name="生益科技",
                    exchange="SH",
                    list_date=None,
                    industry="PCB",
                    is_active=True,
                ),
            ]
        )
        db.add_all(
            [
                _trade("R008", "603083", 1, "0.08"),
                _trade("R008", "600183", 2, "0.07"),
                _trade("R008", "603083", 3, "0.06"),
                _trade("R008", "600183", 4, "-0.01"),
                _trade("R008", "603083", 5, "0.05"),
                _trade("R008", "600183", 6, "0.04"),
            ]
        )
        db.commit()

        payload = get_strategy_fit(db=db, report_date="2026-06-24", rule_id="R008")

    overall = payload["rules"][0]["overall"]
    assert overall["avg_return"] > 0
    assert overall["max_drawdown"] <= 0
    assert overall["return_stability"] >= 0
    assert "稳健分" in overall["summary"]


def test_get_low_dimensional_replay_uses_default_long_window_without_compounding(
    monkeypatch,
) -> None:
    captured = {}

    class _Now:
        def date(self):
            return date(2026, 7, 2)

    class _ReplayResult:
        pass

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _ReplayResult()

    def fake_summarize(result, *, horizons):
        assert isinstance(result, _ReplayResult)
        return {
            "start_date": "2025-01-01",
            "end_date": "2026-07-01",
            "processed_days": 360,
            "candidate_count": 462,
            "warning_days": 1,
            "top_sectors": [{"sector": "小金属", "count": 32}],
            "horizons": {
                20: {
                    "guarded": {
                        "sample_count": 447,
                        "avg_return": 0.023084,
                        "win_rate": 0.434004,
                        "total_return": 10.318571,
                    }
                }
            },
            "monthly_horizons": {20: {"2026-05": {"guarded": {"total_return": 0.19664}}}},
        }

    monkeypatch.setattr(rules, "now_local", lambda: _Now())
    monkeypatch.setattr(rules, "run_low_dimensional_walk_forward_replay", fake_run)
    monkeypatch.setattr(rules, "summarize_walk_forward_replay", fake_summarize)

    payload = get_low_dimensional_replay()

    assert captured == {
        "start_date": "2025-01-01",
        "end_date": "2026-07-01",
        "limit": 3,
        "horizons": (5, 10, 20),
        "min_coverage_ratio": 0.7,
    }
    assert payload["horizons"][20]["guarded"]["total_return"] == 10.318571
    assert "compounded_return" not in payload["horizons"][20]["guarded"]


def test_get_candidate_replay_effect_compares_action_scopes_without_compounding(
    monkeypatch,
) -> None:
    captured = {}

    class _Now:
        def date(self):
            return date(2026, 7, 2)

    def fake_compare(**kwargs):
        captured.update(kwargs)
        return {
            "start_date": "2025-01-01",
            "end_date": "2026-07-01",
            "scopes": {
                "all": {
                    "candidate_count": 3398,
                    "horizons": {
                        20: {
                            "guarded": {
                                "sample_count": 3200,
                                "avg_return": 0.015362,
                                "win_rate": 0.52,
                                "total_return": 49.159485,
                            }
                        }
                    },
                    "monthly_horizons": {
                        20: {
                            "2026-05": {
                                "guarded": {
                                    "sample_count": 251,
                                    "avg_return": -0.016673,
                                    "win_rate": 0.270916,
                                    "total_return": -4.184808,
                                }
                            }
                        }
                    },
                },
                "action": {
                    "candidate_count": 327,
                    "horizons": {
                        20: {
                            "guarded": {
                                "sample_count": 303,
                                "avg_return": 0.012243,
                                "win_rate": 0.48,
                                "total_return": 3.709698,
                            }
                        }
                    },
                    "monthly_horizons": {
                        20: {
                            "2026-05": {
                                "guarded": {
                                    "sample_count": 22,
                                    "avg_return": -0.007034,
                                    "win_rate": 0.272727,
                                    "total_return": -0.154757,
                                }
                            }
                        }
                    },
                },
                "action_long": {
                    "candidate_count": 19,
                    "horizons": {
                        20: {
                            "guarded": {
                                "sample_count": 18,
                                "avg_return": 0.057108,
                                "win_rate": 0.61,
                                "total_return": 1.027945,
                            }
                        }
                    },
                    "monthly_horizons": {
                        20: {
                            "2026-05": {
                                "guarded": {
                                    "sample_count": 5,
                                    "avg_return": 0.165327,
                                    "win_rate": 0.6,
                                    "total_return": 0.826633,
                                }
                            }
                        }
                    },
                },
            },
            "discovery_cache_dir": ".tmp/candidate-replay-discovery-cache",
        }

    monkeypatch.setattr(rules, "now_local", lambda: _Now())
    monkeypatch.setattr(rules, "compare_candidate_walk_forward_scopes", fake_compare)

    payload = get_candidate_replay_effect()

    assert captured == {
        "start_date": "2025-01-01",
        "end_date": "2026-07-01",
        "scopes": ("all", "action", "action_long"),
        "limit": 15,
        "horizons": (5, 10, 20),
        "min_coverage_ratio": 0.7,
        "include_fundamentals": True,
    }
    assert payload["scopes"]["action_long"]["horizons"][20]["guarded"]["total_return"] == 1.027945
    assert (
        "compounded_return"
        not in payload["scopes"]["action_long"]["horizons"][20]["guarded"]
    )
    diagnosis = payload["diagnosis"]
    assert diagnosis["horizon"] == 20
    assert diagnosis["primary_scope"] == "action_long"
    assert diagnosis["policy_label"] == "核心少量行动"
    assert diagnosis["ding_policy"] == "ding_core_only"
    assert any("长期行动池" in reason for reason in diagnosis["reasons"])
    monthly_posture = diagnosis["monthly_posture"]
    assert monthly_posture["month"] == "2026-05"
    assert monthly_posture["posture"] == "tighten_core"
    assert monthly_posture["posture_label"] == "核心收敛"
    assert any("全候选池" in reason for reason in monthly_posture["reasons"])
