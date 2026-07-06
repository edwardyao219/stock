from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.main import create_app
from apps.api.app.routers import rules
from apps.api.app.routers.rules import (
    diagnose_candidate_replay_effect,
    diagnose_strategy_pk,
    get_candidate_replay_effect,
    get_low_dimensional_replay,
    get_strategy_fit,
)
from services.shared.database import Base
from services.shared.models import (
    BacktestTradeRecord,
    ParameterRecommendation,
    ReviewReport,
    Security,
)


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


def test_strategy_fit_surfaces_out_of_sample_learning_audit() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(
            Security(
                symbol="603083",
                name="剑桥科技",
                exchange="SH",
                list_date=None,
                industry="通信设备",
                is_active=True,
            )
        )
        db.add_all(
            [
                _trade("R007", "603083", 1, "0.05"),
                _trade("R007", "603083", 2, "0.04"),
                _trade("R007", "603083", 3, "-0.03"),
            ]
        )
        db.add(
            ReviewReport(
                report_date=date(2026, 6, 24),
                report_type="backtest_learning_review",
                scope="backtest",
                generator="mechanical",
                content_md="# 回归学习报告",
                metrics_json={
                    "insights": [
                        {
                            "rule_id": "R007",
                            "scope_type": "sector",
                            "scope_value": "通信设备",
                            "positive_learning_allowed": False,
                            "evidence_quality": "broad",
                            "train_sample_count": 8,
                            "validation_sample_count": 4,
                            "train_avg_return": 0.035,
                            "validation_avg_return": -0.02,
                            "train_win_rate": 0.75,
                            "validation_win_rate": 0.25,
                            "train_profit_factor": 3.2,
                            "validation_profit_factor": 0.0,
                            "train_total_return": 0.28,
                            "validation_total_return": -0.08,
                            "out_of_sample_passed": False,
                            "out_of_sample_status": "failed",
                            "summary": "训练段表现尚可，但样本外验证转弱",
                        }
                    ]
                },
            )
        )
        db.commit()

        payload = get_strategy_fit(db=db, report_date="2026-06-24", rule_id="R007")

    sector = payload["rules"][0]["sectors"][0]

    assert sector["fit_status"] == "validation_failed"
    assert sector["out_of_sample_status"] == "failed"
    assert sector["out_of_sample_passed"] is False
    assert sector["train_sample_count"] == 8
    assert sector["validation_sample_count"] == 4
    assert sector["train_avg_return"] == 0.035
    assert sector["validation_avg_return"] == -0.02
    assert "样本外" in sector["summary"]


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
            "start_date": "2024-01-01",
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

    def fake_coverage(**kwargs):
        return {
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "overall": {"grade": "partial", "warning_months": 1},
            "months": [{"month": "2024-01", "grade": "partial"}],
            "warnings": ["2024-01 样本偏窄，只作压力测试。"],
        }

    monkeypatch.setattr(rules, "now_local", lambda: _Now())
    monkeypatch.setattr(rules, "run_low_dimensional_walk_forward_replay", fake_run)
    monkeypatch.setattr(rules, "summarize_walk_forward_replay", fake_summarize)
    monkeypatch.setattr(rules, "build_replay_data_coverage_report", fake_coverage)

    payload = get_low_dimensional_replay()

    assert captured == {
        "start_date": "2024-01-01",
        "end_date": "2026-07-01",
        "limit": 3,
        "horizons": (5, 10, 20),
        "min_coverage_ratio": 0.7,
    }
    assert payload["horizons"][20]["guarded"]["total_return"] == 10.318571
    assert "compounded_return" not in payload["horizons"][20]["guarded"]
    assert payload["data_coverage"]["overall"]["grade"] == "partial"
    assert "样本偏窄" in payload["data_coverage"]["warnings"][0]


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
            "start_date": "2024-01-01",
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
                "potential_watch": {
                    "candidate_count": 41,
                    "horizons": {
                        20: {
                            "guarded": {
                                "sample_count": 30,
                                "avg_return": 0.2,
                                "win_rate": 0.5,
                                "total_return": 6.0,
                            }
                        }
                    },
                    "monthly_horizons": {
                        20: {
                            "2026-04": {
                                "guarded": {
                                    "sample_count": 12,
                                    "avg_return": -0.04,
                                    "win_rate": 0.25,
                                    "total_return": -0.48,
                                }
                            },
                            "2026-05": {
                                "guarded": {
                                    "sample_count": 10,
                                    "avg_return": 0.12,
                                    "win_rate": 0.5,
                                    "total_return": 1.2,
                                }
                            }
                        }
                    },
                },
                "startup_preheat": {
                    "candidate_count": 8,
                    "horizons": {
                        1: {
                            "guarded": {
                                "sample_count": 8,
                                "avg_return": 0.018,
                                "win_rate": 0.625,
                                "total_return": 0.144,
                            }
                        },
                        5: {
                            "guarded": {
                                "sample_count": 8,
                                "avg_return": 0.035,
                                "win_rate": 0.625,
                                "total_return": 0.28,
                            }
                        },
                        10: {
                            "guarded": {
                                "sample_count": 8,
                                "avg_return": 0.052,
                                "win_rate": 0.625,
                                "total_return": 0.416,
                            }
                        },
                        20: {
                            "guarded": {
                                "sample_count": 8,
                                "avg_return": 0.04,
                                "win_rate": 0.5,
                                "total_return": 0.32,
                            }
                        },
                    },
                    "monthly_horizons": {},
                },
            },
            "discovery_cache_dir": ".tmp/candidate-replay-discovery-cache",
        }

    def fake_coverage(**kwargs):
        return {
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "overall": {"grade": "usable", "warning_months": 0},
            "months": [{"month": "2024-01", "grade": "usable"}],
            "warnings": [],
        }

    monkeypatch.setattr(rules, "now_local", lambda: _Now())
    monkeypatch.setattr(rules, "compare_candidate_walk_forward_scopes", fake_compare)
    monkeypatch.setattr(rules, "build_replay_data_coverage_report", fake_coverage)

    payload = get_candidate_replay_effect()

    assert captured == {
        "start_date": "2024-01-01",
        "end_date": "2026-07-01",
        "scopes": (
            "all",
            "action",
            "action_long",
            "potential_watch",
            "startup_preheat",
            "startup_confirmed",
        ),
        "limit": 15,
        "horizons": (1, 5, 10, 20),
        "min_coverage_ratio": 0.7,
        "include_fundamentals": False,
    }
    assert payload["scopes"]["action_long"]["horizons"][20]["guarded"]["total_return"] == 1.027945
    assert payload["scopes"]["startup_preheat"]["horizons"][1]["guarded"]["total_return"] == 0.144
    assert payload["scopes"]["startup_preheat"]["horizons"][10]["guarded"]["total_return"] == 0.416
    assert (
        "compounded_return"
        not in payload["scopes"]["action_long"]["horizons"][20]["guarded"]
    )
    diagnosis = payload["diagnosis"]
    assert payload["data_coverage"]["overall"]["grade"] == "usable"
    assert diagnosis["horizon"] == 20
    assert diagnosis["primary_scope"] == "action_long"
    assert diagnosis["policy_label"] == "核心少量行动"
    assert diagnosis["ding_policy"] == "ding_core_only"
    assert any("长期行动池" in reason for reason in diagnosis["reasons"])
    assert any("潜力观察池" in item for item in diagnosis["overfit_guardrails"])
    monthly_posture = diagnosis["monthly_posture"]
    assert monthly_posture["month"] == "2026-05"
    assert monthly_posture["posture"] == "tighten_core"
    assert monthly_posture["posture_label"] == "核心收敛"
    assert any("全候选池" in reason for reason in monthly_posture["reasons"])
    strategy_pk = diagnosis["strategy_pk"]
    assert strategy_pk["return_mode"] == "simple_sum_no_compounding"
    assert strategy_pk["primary_horizon"] == 20
    assert strategy_pk["rows"][0]["scope"] == "potential_watch"
    assert strategy_pk["rows"][0]["policy"] == "tactical_observe"
    assert strategy_pk["rows"][0]["metrics_by_horizon"][20]["total_return"] == 6.0
    assert "compounded_return" not in strategy_pk["rows"][0]["metrics_by_horizon"][20]
    core_row = next(row for row in strategy_pk["rows"] if row["scope"] == "action_long")
    assert core_row["policy"] == "core_candidate"


def test_strategy_pk_keeps_tactical_lines_out_of_core_even_when_strong() -> None:
    comparison = {
        "scopes": {
            "action_long": {
                "candidate_count": 7,
                "horizons": {
                    5: {"guarded": {"sample_count": 7, "avg_return": 0.03, "total_return": 0.21}},
                    10: {"guarded": {"sample_count": 7, "avg_return": 0.04, "total_return": 0.28}},
                    20: {"guarded": {"sample_count": 7, "avg_return": 0.05, "total_return": 0.35}},
                },
                "monthly_horizons": {
                    20: {
                        "2026-05": {
                            "guarded": {
                                "sample_count": 3,
                                "avg_return": 0.04,
                                "total_return": 0.12,
                            }
                        },
                        "2026-06": {
                            "guarded": {
                                "sample_count": 4,
                                "avg_return": 0.06,
                                "total_return": 0.24,
                            }
                        },
                    }
                },
            },
            "potential_watch": {
                "candidate_count": 18,
                "horizons": {
                    5: {"guarded": {"sample_count": 18, "avg_return": 0.09, "total_return": 1.62}},
                    10: {"guarded": {"sample_count": 18, "avg_return": 0.10, "total_return": 1.80}},
                    20: {"guarded": {"sample_count": 18, "avg_return": 0.08, "total_return": 1.44}},
                },
                "monthly_horizons": {
                    20: {
                        "2026-05": {
                            "guarded": {
                                "sample_count": 8,
                                "avg_return": -0.02,
                                "total_return": -0.16,
                            }
                        },
                        "2026-06": {
                            "guarded": {
                                "sample_count": 10,
                                "avg_return": 0.16,
                                "total_return": 1.60,
                            }
                        },
                    }
                },
            },
            "startup_preheat": {
                "candidate_count": 5,
                "horizons": {
                    5: {"guarded": {"sample_count": 5, "avg_return": 0.11, "total_return": 0.55}},
                    10: {"guarded": {"sample_count": 5, "avg_return": 0.13, "total_return": 0.65}},
                    20: {"guarded": {"sample_count": 5, "avg_return": 0.06, "total_return": 0.30}},
                },
                "monthly_horizons": {
                    20: {
                        "2026-06": {
                            "guarded": {
                                "sample_count": 5,
                                "avg_return": 0.06,
                                "total_return": 0.30,
                            }
                        },
                    }
                },
            },
            "all": {
                "candidate_count": 40,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 40,
                            "avg_return": -0.01,
                            "total_return": -0.40,
                        }
                    },
                },
                "monthly_horizons": {
                    20: {
                        "2026-06": {
                            "guarded": {
                                "sample_count": 40,
                                "avg_return": -0.01,
                                "total_return": -0.40,
                            }
                        },
                    }
                },
            },
        }
    }

    pk = diagnose_strategy_pk(comparison, horizons=(5, 10, 20), primary_horizon=20)

    assert pk["return_mode"] == "simple_sum_no_compounding"
    assert pk["summary"].startswith("策略PK：")
    assert pk["rows"][0]["scope"] == "potential_watch"
    assert pk["rows"][0]["policy"] == "tactical_observe"
    assert pk["rows"][0]["latest_month"] == "2026-06"
    assert pk["rows"][0]["latest_month_total_return"] == 1.6
    assert pk["rows"][0]["worst_month_total_return"] == -0.16
    assert pk["rows"][0]["positive_months"] == 1
    assert pk["rows"][0]["metrics_by_horizon"][10]["avg_return"] == 0.10
    assert "compounded_return" not in pk["rows"][0]["metrics_by_horizon"][20]
    core_row = next(row for row in pk["rows"] if row["scope"] == "action_long")
    assert core_row["policy"] == "core_candidate"
    preheat_row = next(row for row in pk["rows"] if row["scope"] == "startup_preheat")
    assert preheat_row["policy"] == "tactical_observe"


def test_strategy_pk_summary_stands_down_when_best_line_is_negative() -> None:
    comparison = {
        "scopes": {
            "action": {
                "candidate_count": 4,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 4,
                            "avg_return": -0.04,
                            "total_return": -0.16,
                        }
                    }
                },
                "monthly_horizons": {
                    20: {
                        "2026-05": {
                            "guarded": {
                                "sample_count": 4,
                                "avg_return": -0.04,
                                "total_return": -0.16,
                            }
                        }
                    }
                },
            },
            "startup_preheat": {
                "candidate_count": 3,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 3,
                            "avg_return": -0.02,
                            "total_return": -0.06,
                        }
                    }
                },
                "monthly_horizons": {
                    20: {
                        "2026-05": {
                            "guarded": {
                                "sample_count": 3,
                                "avg_return": -0.02,
                                "total_return": -0.06,
                            }
                        }
                    }
                },
            },
        }
    }

    pk = diagnose_strategy_pk(comparison, horizons=(20,), primary_horizon=20)

    assert "暂未转正" in pk["summary"]
    assert pk["rows"][0]["scope"] == "startup_preheat"
    assert pk["rows"][0]["policy"] == "stand_down"


def test_candidate_replay_diagnosis_marks_potential_watch_as_tactical_only() -> None:
    comparison = {
        "scopes": {
            "action_long": {
                "candidate_count": 7,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 7,
                            "avg_return": 0.16,
                            "total_return": 1.12,
                            "win_rate": 0.6,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "action": {
                "candidate_count": 11,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 10,
                            "avg_return": 0.01,
                            "total_return": 0.1,
                            "win_rate": 0.5,
                        }
                    }
                },
                "monthly_horizons": {
                    10: {
                        "2026-06": {
                            "guarded": {
                                "sample_count": 6,
                                "avg_return": 0.04,
                                "total_return": 0.25,
                            }
                        }
                    }
                },
            },
            "all": {
                "candidate_count": 123,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 100,
                            "avg_return": -0.01,
                            "total_return": -1.0,
                            "win_rate": 0.4,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "potential_watch": {
                "candidate_count": 55,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 20,
                            "avg_return": 0.01,
                            "total_return": 0.2,
                            "win_rate": 0.5,
                        }
                    }
                },
                "monthly_horizons": {
                    10: {
                        "2026-05": {
                            "guarded": {
                                "sample_count": 40,
                                "avg_return": -0.01,
                                "total_return": -0.4,
                            }
                        },
                        "2026-06": {
                            "guarded": {
                                "sample_count": 37,
                                "avg_return": 0.07,
                                "total_return": 2.65,
                            }
                        },
                    }
                },
            },
        }
    }

    diagnosis = diagnose_candidate_replay_effect(comparison, horizon=20)

    assert diagnosis["primary_scope"] == "action_long"
    assert any(
        "潜力观察池" in item and "10日" in item for item in diagnosis["tactical_opportunities"]
    )
    assert all("不升级为钉钉核心" in item for item in diagnosis["tactical_opportunities"])
    assert diagnosis["potential_watch_policy"]["status"] == "tactical_watch"
    assert diagnosis["potential_watch_policy"]["label"] == "盘中重点观察"
    assert "不升级为钉钉核心" in diagnosis["potential_watch_policy"]["summary"]


def test_candidate_replay_diagnosis_uses_equal_weight_portfolio_metrics() -> None:
    def scope(
        *,
        candidate_count: int,
        sample_total: float,
        portfolio_total: float,
        portfolio_avg: float,
        monthly_portfolio_total: float,
        monthly_portfolio_avg: float,
    ) -> dict:
        return {
            "candidate_count": candidate_count,
            "horizons": {
                20: {
                    "guarded": {
                        "sample_count": candidate_count,
                        "avg_return": sample_total / max(candidate_count, 1),
                        "total_return": sample_total,
                        "win_rate": 0.6,
                    }
                }
            },
            "portfolio_horizons": {
                20: {
                    "guarded": {
                        "sample_count": 4,
                        "avg_return": portfolio_avg,
                        "total_return": portfolio_total,
                        "win_rate": 0.5,
                    }
                }
            },
            "monthly_horizons": {
                20: {
                    "2026-04": {
                        "guarded": {
                            "sample_count": candidate_count,
                            "avg_return": 0.04,
                            "total_return": 4.0,
                            "win_rate": 0.6,
                        }
                    },
                    "2026-05": {
                        "guarded": {
                            "sample_count": candidate_count,
                            "avg_return": 0.04,
                            "total_return": 4.0,
                            "win_rate": 0.6,
                        }
                    },
                    "2026-06": {
                        "guarded": {
                            "sample_count": candidate_count,
                            "avg_return": 0.04,
                            "total_return": 4.0,
                            "win_rate": 0.6,
                        }
                    },
                }
            },
            "monthly_portfolio_horizons": {
                20: {
                    "2026-04": {
                        "guarded": {
                            "sample_count": 4,
                            "avg_return": -0.02,
                            "total_return": -0.08,
                            "win_rate": 0.25,
                        }
                    },
                    "2026-05": {
                        "guarded": {
                            "sample_count": 4,
                            "avg_return": -0.03,
                            "total_return": -0.12,
                            "win_rate": 0.25,
                        }
                    },
                    "2026-06": {
                        "guarded": {
                            "sample_count": 4,
                            "avg_return": monthly_portfolio_avg,
                            "total_return": monthly_portfolio_total,
                            "win_rate": 0.5,
                        }
                    },
                }
            },
        }

    comparison = {
        "scopes": {
            "all": scope(
                candidate_count=100,
                sample_total=8.0,
                portfolio_total=-0.4,
                portfolio_avg=-0.10,
                monthly_portfolio_total=-0.16,
                monthly_portfolio_avg=-0.04,
            ),
            "action": scope(
                candidate_count=20,
                sample_total=2.0,
                portfolio_total=-0.2,
                portfolio_avg=-0.05,
                monthly_portfolio_total=-0.08,
                monthly_portfolio_avg=-0.02,
            ),
            "action_long": scope(
                candidate_count=6,
                sample_total=0.3,
                portfolio_total=0.24,
                portfolio_avg=0.06,
                monthly_portfolio_total=0.16,
                monthly_portfolio_avg=0.04,
            ),
        }
    }

    diagnosis = diagnose_candidate_replay_effect(comparison, horizon=20)

    assert diagnosis["primary_scope"] == "action_long"
    assert diagnosis["policy_label"] == "核心少量行动"
    assert diagnosis["scope_rows"][0]["total_return"] == 0.24
    assert diagnosis["monthly_posture"]["posture"] == "tighten_core"
    assert diagnosis["market_phase_policy"]["status"] == "risk_off"
    assert any("3只等权" in reason for reason in diagnosis["reasons"])


def test_candidate_replay_style_gate_uses_recent_style_replay_without_sector_names() -> None:
    comparison = {
        "scopes": {
            "all": {
                "candidate_count": 120,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 100,
                            "avg_return": 0.02,
                            "total_return": 2.0,
                            "win_rate": 0.55,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "action": {"candidate_count": 0, "horizons": {}, "monthly_horizons": {}},
            "action_long": {"candidate_count": 0, "horizons": {}, "monthly_horizons": {}},
            "potential_watch": {
                "candidate_count": 40,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 30,
                            "avg_return": 0.01,
                            "total_return": 0.3,
                            "win_rate": 0.45,
                        }
                    }
                },
                "monthly_horizons": {},
                "monthly_style_horizons": {
                    10: {
                        "2026-05": {
                            "growth_cycle": {
                                "guarded": {
                                    "sample_count": 5,
                                    "avg_return": -0.02,
                                    "total_return": -0.1,
                                    "win_rate": 0.2,
                                }
                            },
                            "cyclical": {
                                "guarded": {
                                    "sample_count": 5,
                                    "avg_return": 0.01,
                                    "total_return": 0.05,
                                    "win_rate": 0.6,
                                }
                            },
                        },
                        "2026-06": {
                            "growth_cycle": {
                                "guarded": {
                                    "sample_count": 6,
                                    "avg_return": 0.12,
                                    "total_return": 0.72,
                                    "win_rate": 0.67,
                                }
                            },
                            "cyclical": {
                                "guarded": {
                                    "sample_count": 4,
                                    "avg_return": -0.03,
                                    "total_return": -0.12,
                                    "win_rate": 0.25,
                                }
                            },
                            "unknown": {
                                "guarded": {
                                    "sample_count": 2,
                                    "avg_return": 0.1,
                                    "total_return": 0.2,
                                    "win_rate": 1.0,
                                }
                            },
                        },
                    }
                },
            },
        }
    }

    diagnosis = diagnose_candidate_replay_effect(comparison, horizon=20)

    style_gate = diagnosis["style_gate_policy"]
    assert style_gate["horizon"] == 10
    assert style_gate["scope"] == "potential_watch"
    rows = {row["style"]: row for row in style_gate["rows"]}
    assert rows["growth_cycle"]["status"] == "upgrade_allowed"
    assert rows["growth_cycle"]["status_label"] == "允许潜力升级"
    assert rows["cyclical"]["status"] == "stand_down"
    assert rows["unknown"]["status"] == "observe_only"
    assert style_gate["upgrade_styles"] == ["growth_cycle"]
    rendered = str(style_gate)
    assert "半导体" not in rendered
    assert "证券" not in rendered


def test_candidate_replay_startup_preheat_policy_uses_style_gate_replay() -> None:
    comparison = {
        "scopes": {
            "all": {
                "candidate_count": 120,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 100,
                            "avg_return": 0.02,
                            "total_return": 2.0,
                            "win_rate": 0.55,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "action": {"candidate_count": 0, "horizons": {}, "monthly_horizons": {}},
            "action_long": {"candidate_count": 0, "horizons": {}, "monthly_horizons": {}},
            "potential_watch": {"candidate_count": 0, "horizons": {}, "monthly_horizons": {}},
            "startup_preheat": {
                "candidate_count": 18,
                "horizons": {
                    5: {
                        "guarded": {
                            "sample_count": 14,
                            "avg_return": 0.04,
                            "total_return": 0.56,
                            "win_rate": 0.57,
                        }
                    },
                    20: {
                        "guarded": {
                            "sample_count": 14,
                            "avg_return": 0.01,
                            "total_return": 0.14,
                            "win_rate": 0.5,
                        }
                    },
                },
                "monthly_horizons": {},
                "monthly_style_horizons": {
                    5: {
                        "2026-05": {
                            "growth_cycle": {
                                "guarded": {
                                    "sample_count": 3,
                                    "avg_return": 0.01,
                                    "total_return": 0.03,
                                    "win_rate": 0.67,
                                }
                            },
                            "consumer_quality": {
                                "guarded": {
                                    "sample_count": 3,
                                    "avg_return": -0.02,
                                    "total_return": -0.06,
                                    "win_rate": 0.33,
                                }
                            },
                        },
                        "2026-06": {
                            "growth_cycle": {
                                "guarded": {
                                    "sample_count": 5,
                                    "avg_return": 0.05,
                                    "total_return": 0.25,
                                    "win_rate": 0.6,
                                }
                            },
                            "consumer_quality": {
                                "guarded": {
                                    "sample_count": 4,
                                    "avg_return": -0.01,
                                    "total_return": -0.04,
                                    "win_rate": 0.25,
                                }
                            },
                        },
                    }
                },
            },
        }
    }

    diagnosis = diagnose_candidate_replay_effect(comparison, horizon=20)

    startup_policy = diagnosis["startup_preheat_policy"]
    assert startup_policy["scope"] == "startup_preheat"
    assert startup_policy["horizon"] == 5
    assert startup_policy["upgrade_styles"] == ["growth_cycle"]
    rows = {row["style"]: row for row in startup_policy["rows"]}
    assert rows["growth_cycle"]["status"] == "upgrade_allowed"
    assert rows["consumer_quality"]["status"] == "stand_down"
    rendered = str(startup_policy)
    assert "启动前夜池" in rendered
    assert "不代表买点" in rendered
    assert "半导体" not in rendered
    assert "证券" not in rendered


def test_candidate_replay_market_phase_switch_turns_defensive_after_weak_months() -> None:
    comparison = {
        "scopes": {
            "all": {
                "candidate_count": 400,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 300,
                            "avg_return": -0.01,
                            "total_return": -3.0,
                            "win_rate": 0.35,
                        }
                    }
                },
                "monthly_horizons": {
                    20: {
                        "2024-04": {
                            "guarded": {
                                "sample_count": 80,
                                "avg_return": -0.03,
                                "total_return": -2.4,
                                "win_rate": 0.2,
                            }
                        },
                        "2024-05": {
                            "guarded": {
                                "sample_count": 75,
                                "avg_return": -0.02,
                                "total_return": -1.5,
                                "win_rate": 0.25,
                            }
                        },
                        "2024-06": {
                            "guarded": {
                                "sample_count": 60,
                                "avg_return": -0.01,
                                "total_return": -0.6,
                                "win_rate": 0.3,
                            }
                        },
                    }
                },
            },
            "action": {
                "candidate_count": 30,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 28,
                            "avg_return": -0.02,
                            "total_return": -0.56,
                            "win_rate": 0.25,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "action_long": {
                "candidate_count": 0,
                "horizons": {},
                "monthly_horizons": {},
            },
        }
    }

    diagnosis = diagnose_candidate_replay_effect(comparison, horizon=20)

    phase = diagnosis["market_phase_policy"]
    assert phase["status"] == "risk_off"
    assert phase["label"] == "防守阶段"
    assert phase["expansion_allowed"] is False
    assert phase["max_core_positions"] == 1
    assert "连续弱月" in phase["summary"]


def test_candidate_replay_market_phase_switch_allows_following_strong_phase() -> None:
    comparison = {
        "scopes": {
            "all": {
                "candidate_count": 600,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 500,
                            "avg_return": 0.02,
                            "total_return": 10.0,
                            "win_rate": 0.55,
                        }
                    }
                },
                "monthly_horizons": {
                    20: {
                        "2024-09": {
                            "guarded": {
                                "sample_count": 120,
                                "avg_return": 0.12,
                                "total_return": 14.4,
                                "win_rate": 0.8,
                            }
                        },
                        "2024-10": {
                            "guarded": {
                                "sample_count": 140,
                                "avg_return": 0.06,
                                "total_return": 8.4,
                                "win_rate": 0.65,
                            }
                        },
                    }
                },
            },
            "action": {
                "candidate_count": 30,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 25,
                            "avg_return": 0.02,
                            "total_return": 0.5,
                            "win_rate": 0.56,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "action_long": {
                "candidate_count": 5,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 5,
                            "avg_return": 0.04,
                            "total_return": 0.2,
                            "win_rate": 0.6,
                        }
                    }
                },
                "monthly_horizons": {},
            },
        }
    }

    diagnosis = diagnose_candidate_replay_effect(comparison, horizon=20)

    phase = diagnosis["market_phase_policy"]
    assert phase["status"] == "trend_follow"
    assert phase["label"] == "顺势阶段"
    assert phase["expansion_allowed"] is True
    assert phase["max_core_positions"] == 3
    assert any("2024-09" in reason for reason in phase["reasons"])


def test_candidate_replay_dual_line_prefers_main_trend_in_strong_phase() -> None:
    comparison = {
        "scopes": {
            "all": {
                "candidate_count": 500,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 400,
                            "avg_return": 0.03,
                            "total_return": 12.0,
                            "win_rate": 0.58,
                        }
                    }
                },
                "monthly_horizons": {
                    20: {
                        "2024-09": {
                            "guarded": {
                                "sample_count": 120,
                                "avg_return": 0.12,
                                "total_return": 14.4,
                            }
                        },
                        "2024-10": {
                            "guarded": {
                                "sample_count": 130,
                                "avg_return": 0.06,
                                "total_return": 7.8,
                            }
                        },
                    }
                },
            },
            "action": {
                "candidate_count": 30,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 25,
                            "avg_return": 0.02,
                            "total_return": 0.5,
                            "win_rate": 0.56,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "action_long": {
                "candidate_count": 8,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 8,
                            "avg_return": 0.05,
                            "total_return": 0.4,
                            "win_rate": 0.625,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "potential_watch": {
                "candidate_count": 20,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 20,
                            "avg_return": -0.01,
                            "total_return": -0.2,
                            "win_rate": 0.3,
                        }
                    }
                },
                "monthly_horizons": {},
            },
        }
    }

    diagnosis = diagnose_candidate_replay_effect(comparison, horizon=20)

    dual_line = diagnosis["dual_line_policy"]
    assert dual_line["active_line"] == "main_trend"
    assert dual_line["main_line"]["status"] == "core_enabled"
    assert dual_line["support_line"]["status"] == "monitor_only"
    assert dual_line["ding_policy"] == "ding_core_main_line"
    assert dual_line["max_core_positions"] == 3


def test_candidate_replay_dual_line_uses_support_preheat_when_weak_but_watch_repairs() -> None:
    comparison = {
        "scopes": {
            "all": {
                "candidate_count": 500,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 400,
                            "avg_return": -0.02,
                            "total_return": -8.0,
                            "win_rate": 0.25,
                        }
                    }
                },
                "monthly_horizons": {
                    20: {
                        "2024-10": {
                            "guarded": {
                                "sample_count": 150,
                                "avg_return": 0.04,
                                "total_return": 6.0,
                            }
                        },
                        "2024-11": {
                            "guarded": {
                                "sample_count": 130,
                                "avg_return": -0.01,
                                "total_return": -1.3,
                            }
                        },
                        "2024-12": {
                            "guarded": {
                                "sample_count": 120,
                                "avg_return": -0.04,
                                "total_return": -4.8,
                            }
                        },
                    }
                },
            },
            "action": {
                "candidate_count": 30,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 25,
                            "avg_return": -0.02,
                            "total_return": -0.5,
                            "win_rate": 0.24,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "action_long": {
                "candidate_count": 2,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 2,
                            "avg_return": -0.04,
                            "total_return": -0.08,
                            "win_rate": 0.0,
                        }
                    }
                },
                "monthly_horizons": {},
            },
            "potential_watch": {
                "candidate_count": 80,
                "horizons": {
                    20: {
                        "guarded": {
                            "sample_count": 70,
                            "avg_return": -0.03,
                            "total_return": -2.1,
                            "win_rate": 0.25,
                        }
                    }
                },
                "monthly_horizons": {
                    10: {
                        "2024-11": {
                            "guarded": {
                                "sample_count": 30,
                                "avg_return": -0.02,
                                "total_return": -0.6,
                            }
                        },
                        "2024-12": {
                            "guarded": {
                                "sample_count": 35,
                                "avg_return": 0.05,
                                "total_return": 1.75,
                            }
                        },
                    }
                },
            },
        }
    }

    diagnosis = diagnose_candidate_replay_effect(comparison, horizon=20)

    dual_line = diagnosis["dual_line_policy"]
    assert dual_line["active_line"] == "support_preheat"
    assert dual_line["main_line"]["status"] == "paused"
    assert dual_line["support_line"]["status"] == "web_preheat"
    assert dual_line["ding_policy"] == "web_support_only"
    assert dual_line["max_core_positions"] == 0
    assert "辅线" in dual_line["summary"]
