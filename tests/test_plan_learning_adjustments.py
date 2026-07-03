from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.engine.plans.generator import generate_trade_plans
from services.engine.plans.learning_adjustments import load_plan_learning_adjustments
from services.engine.rules.seed_rules import MVP_RULES
from services.shared.database import Base
from services.shared.models import ParameterRecommendation


def _context(**overrides) -> dict:
    context = {
        "symbol": "000001",
        "trade_date": "2026-06-23",
        "close": 10.0,
        "atr_14": 0.3,
        "breakout_level": 10.2,
        "support_level": 9.4,
        "sector_code": "银行",
        "sector_strength_score": 80,
        "relative_strength_score": 75,
        "amount_percentile_60d": 90,
        "distance_to_20d_high": -0.01,
        "trend_score": 80,
        "volume_score": 90,
        "risk_score": 20,
        "is_st": False,
        "is_suspended": False,
    }
    context.update(overrides)
    return context


def _add_recommendation(db, **overrides) -> ParameterRecommendation:
    payload = {
        "report_date": date(2026, 6, 23),
        "rule_id": "R001",
        "scope_type": "rule",
        "scope_value": "R001",
        "target_type": "exit_policy",
        "target_name": "learned_profit_protection",
        "action": "test_tighter_trailing_from_reviews",
        "priority": "high",
        "rationale": "sample",
        "current_json": {},
        "proposed_json": {"trailing_drawdown_pct_multiplier": 0.5},
        "guardrails_json": {"items": []},
        "source_report_type": "paper_learning_review",
        "status": "pending",
        **overrides,
    }
    row = ParameterRecommendation(**payload)
    db.add(row)
    db.commit()
    return row


def test_learning_adjustments_change_plan_parameters_and_evidence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_recommendation(db)

        plans = generate_trade_plans(
            plan_date="2026-06-23",
            trade_date="2026-06-24",
            rules=MVP_RULES,
            feature_contexts=[_context()],
            learning_adjustment_loader=lambda rule, context, tags: load_plan_learning_adjustments(
                db,
                rule_id=rule.id,
                sector_code=context.get("sector_code"),
                signal_tags=tags,
            ),
        )

    plan = plans[0]
    assert plan.trailing_drawdown_pct == pytest.approx(0.03)
    assert plan.entry_condition["learning_adjustments"][0]["target_name"] == (
        "learned_profit_protection"
    )
    assert plan.entry_condition["trade_parameters"]["evidence"]["learning_adjustments"]


def test_learning_adjustments_can_reduce_position_and_require_confirmation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_recommendation(
            db,
            target_type="entry_filter",
            target_name="learned_entry_quality",
            action="tighten_entry_or_reduce_priority",
            proposed_json={
                "position_size_pct_multiplier": 0.5,
                "priority_score_delta": -3,
                "require_extra_confirmation": True,
            },
        )

        plans = generate_trade_plans(
            plan_date="2026-06-23",
            trade_date="2026-06-24",
            rules=MVP_RULES,
            feature_contexts=[_context()],
            learning_adjustment_loader=lambda rule, context, tags: load_plan_learning_adjustments(
                db,
                rule_id=rule.id,
                sector_code=context.get("sector_code"),
                signal_tags=tags,
            ),
        )

    plan = plans[0]
    assert plan.position_size == pytest.approx(0.05)
    assert plan.confidence_score < 80
    assert "learned extra confirmation required before entry" in plan.risk_notes


def test_backtest_learning_adjustments_match_symbol_scope() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_recommendation(
            db,
            source_report_type="backtest_learning_review",
            scope_type="symbol",
            scope_value="000001",
            target_type="entry_filter",
            target_name="backtest_scope_quality",
            action="reduce_priority_or_require_confirmation",
            proposed_json={
                "position_size_pct_multiplier": 0.5,
                "priority_score_delta": -4,
                "require_extra_confirmation": True,
                "source_rule_id": "R001",
            },
        )

        recommendations = load_plan_learning_adjustments(
            db,
            rule_id="R001",
            symbol="000001",
            sector_code="银行",
            signal_tags=[],
        )

    assert len(recommendations) == 1
    assert recommendations[0].scope_type == "symbol"


def test_backtest_learning_adjustments_do_not_cross_rule_scope() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_recommendation(
            db,
            source_report_type="backtest_learning_review",
            scope_type="sector",
            scope_value="银行",
            target_type="entry_filter",
            target_name="backtest_scope_quality",
            action="reduce_priority_or_require_confirmation",
            proposed_json={
                "priority_score_delta": -4,
                "source_rule_id": "R007",
            },
        )

        recommendations = load_plan_learning_adjustments(
            db,
            rule_id="R001",
            symbol="000001",
            sector_code="银行",
            signal_tags=[],
        )

    assert recommendations == []


def test_backtest_learning_rule_filter_runs_before_limit() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_recommendation(
            db,
            report_date=date(2026, 1, 9),
            source_report_type="backtest_learning_review",
            scope_type="sector",
            scope_value="银行",
            target_type="entry_filter",
            target_name="backtest_scope_quality",
            action="reduce_priority_or_require_confirmation",
            proposed_json={
                "priority_score_delta": -4,
                "source_rule_id": "R001",
            },
        )
        for index in range(25):
            _add_recommendation(
                db,
                rule_id="R007",
                report_date=date(2026, 1, 10),
                source_report_type="backtest_learning_review",
                scope_type="sector",
                scope_value="银行",
                target_type="entry_filter",
                target_name=f"other_rule_{index}",
                action="reduce_priority_or_require_confirmation",
                proposed_json={
                    "priority_score_delta": -4,
                    "source_rule_id": "R007",
                },
            )

        recommendations = load_plan_learning_adjustments(
            db,
            rule_id="R001",
            symbol="000001",
            sector_code="银行",
            signal_tags=[],
            limit=20,
        )

    assert len(recommendations) == 1
    assert recommendations[0].proposed_json["source_rule_id"] == "R001"


def test_learning_adjustments_decay_with_feature_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_recommendation(
            db,
            report_date=date(2026, 6, 23),
            scope_type="symbol",
            scope_value="000001",
            proposed_json={
                "trailing_drawdown_pct_multiplier": 0.5,
                "priority_score_delta": 4,
                "source_rule_id": "R001",
            },
        )
        _add_recommendation(
            db,
            report_date=date(2026, 5, 10),
            scope_type="symbol",
            scope_value="000002",
            proposed_json={
                "trailing_drawdown_pct_multiplier": 0.5,
                "priority_score_delta": 4,
                "source_rule_id": "R001",
            },
        )

        plans = generate_trade_plans(
            plan_date="2026-06-24",
            trade_date="2026-06-25",
            rules=MVP_RULES,
            feature_contexts=[_context(symbol="000001"), _context(symbol="000002")],
            learning_adjustment_loader=lambda rule, context, tags: load_plan_learning_adjustments(
                db,
                rule_id=rule.id,
                symbol=context.get("symbol"),
                sector_code=context.get("sector_code"),
                signal_tags=tags,
                feature_date=date(2026, 6, 23),
            ),
        )

    recent_plan = next(item for item in plans if item.symbol == "000001")
    old_plan = next(item for item in plans if item.symbol == "000002")

    assert recent_plan.trailing_drawdown_pct == pytest.approx(0.03)
    assert old_plan.trailing_drawdown_pct > recent_plan.trailing_drawdown_pct
    assert recent_plan.confidence_score > old_plan.confidence_score
    assert recent_plan.entry_condition["learning_adjustments"][0]["recency_weight"] == pytest.approx(1.0)
    assert old_plan.entry_condition["learning_adjustments"][0]["recency_weight"] == pytest.approx(0.25)


def test_learning_adjustments_skip_stale_items_with_feature_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        _add_recommendation(
            db,
            report_date=date(2026, 1, 10),
            scope_type="symbol",
            scope_value="000001",
            proposed_json={
                "trailing_drawdown_pct_multiplier": 0.5,
                "source_rule_id": "R001",
            },
        )

        recommendations = load_plan_learning_adjustments(
            db,
            rule_id="R001",
            symbol="000001",
            sector_code="银行",
            signal_tags=[],
            feature_date=date(2026, 6, 24),
        )

    assert recommendations == []
