import pytest

from services.engine.plans.generator import generate_trade_plans
from services.engine.risk.profiles import RiskProfile
from services.engine.rules.seed_rules import MVP_RULES


def test_generate_trade_plans_from_feature_context() -> None:
    contexts = [
        {
            "symbol": "000001",
            "trade_date": "2026-06-23",
            "close": 10.0,
            "atr_14": 0.3,
            "breakout_level": 10.2,
            "support_level": 9.4,
            "sector_strength_score": 80,
            "fundamental_score": 70,
            "fundamental_verdict": "supportive",
            "relative_strength_score": 75,
            "amount_percentile_60d": 90,
            "distance_to_20d_high": -0.01,
            "trend_score": 80,
            "volume_score": 90,
            "risk_score": 20,
            "is_st": False,
            "is_suspended": False,
        }
    ]

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=MVP_RULES,
        feature_contexts=contexts,
    )

    assert len(plans) == 1
    assert plans[0].symbol == "000001"
    assert plans[0].rule_id == "R001"
    assert plans[0].entry_trigger_price == pytest.approx(10.2)
    assert plans[0].initial_stop == pytest.approx(9.75)
    assert plans[0].take_profit_1 == pytest.approx(10.65)
    assert plans[0].take_profit_2 == pytest.approx(11.1)
    assert plans[0].position_size == pytest.approx(0.10)
    assert "trade_parameters" in plans[0].entry_condition
    evidence = plans[0].entry_condition["evidence"]
    assert "high_position_volume_spike" in evidence["risk_flags"]
    assert "trend_alignment" in evidence["support_flags"]
    assert plans[0].confidence_score > 75


def test_compound_rule_requires_banking_fundamental_context() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R004")
    contexts = [
        {
            "symbol": "600519",
            "trade_date": "2026-06-23",
            "close": 1500.0,
            "ma20": 1480.0,
            "atr_14": 30.0,
            "support_level": 1450.0,
            "trend_score": 100,
            "volatility_score": 40,
            "risk_score": 0,
            "max_drawdown_20d": -0.03,
            "distance_to_ma20": 0.01,
            "distance_to_20d_low": 0.08,
            "analysis_framework": "consumer_quality",
            "fundamental_verdict": "supportive",
            "pb": 3.5,
            "dividend_yield": 0.04,
            "sector_sample_confidence": 0.5,
            "is_st": False,
            "is_suspended": False,
        }
    ]

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=[rule],
        feature_contexts=contexts,
    )

    assert plans == []


def test_trade_evidence_uses_profile_thresholds() -> None:
    contexts = [
        {
            "symbol": "000001",
            "trade_date": "2026-06-23",
            "close": 10.0,
            "atr_14": 0.3,
            "breakout_level": 10.2,
            "support_level": 9.4,
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
    ]
    profile = RiskProfile(
        evidence_thresholds={
            "high_volume_percentile": 95.0,
            "near_high_distance_pct": -0.03,
        }
    )

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=MVP_RULES,
        feature_contexts=contexts,
        risk_profile=profile,
    )

    evidence = plans[0].entry_condition["evidence"]
    assert "high_position_volume_spike" not in evidence["risk_flags"]
    assert evidence["thresholds"]["high_volume_percentile"] == 95.0


def test_contraction_breakout_rule_requires_dry_up_before_confirmation() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R005")
    context = {
        "symbol": "002837",
        "trade_date": "2026-06-23",
        "close": 82.0,
        "high": 84.0,
        "ma5": 80.0,
        "atr_14": 4.0,
        "breakout_level": 85.0,
        "support_level": 76.0,
        "sector_strength_score": 78,
        "sector_style": "theme",
        "trend_score": 100,
        "relative_strength_score": 65,
        "amount_percentile_60d": 55,
        "amount_ratio_5d": 0.82,
        "recent_amount_ratio_20d": 0.9,
        "return_20d": 0.12,
        "distance_to_20d_high": -0.03,
        "distance_to_ma20": 0.04,
        "close_position_in_range": 0.62,
        "upper_shadow_pct": 0.025,
        "volume_trap_risk_score": 40,
        "risk_score": 0,
        "is_st": False,
        "is_suspended": False,
    }

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=[rule],
        feature_contexts=[context],
    )

    assert len(plans) == 1
    assert plans[0].rule_id == "R005"
    assert plans[0].entry_trigger_price == pytest.approx(84.0)


def test_contraction_breakout_rule_rejects_hot_volume_trap() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R005")
    context = {
        "symbol": "600183",
        "trade_date": "2026-06-23",
        "close": 120.0,
        "high": 124.0,
        "atr_14": 6.0,
        "support_level": 112.0,
        "sector_style": "theme",
        "sector_strength_score": 80,
        "trend_score": 100,
        "relative_strength_score": 75,
        "return_20d": 0.42,
        "distance_to_20d_high": -0.02,
        "distance_to_ma20": 0.18,
        "amount_ratio_5d": 1.4,
        "close_position_in_range": 0.35,
        "upper_shadow_pct": 0.06,
        "volume_trap_risk_score": 70,
        "risk_score": 0,
        "is_st": False,
        "is_suspended": False,
    }

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=[rule],
        feature_contexts=[context],
    )

    assert plans == []


def test_trend_continuation_rule_uses_theme_context() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R006")
    context = {
        "symbol": "603083",
        "trade_date": "2026-06-23",
        "close": 238.0,
        "ma10": 220.0,
        "atr_14": 16.0,
        "support_level": 200.0,
        "sector_style": "theme",
        "sector_strength_score": 75,
        "trend_score": 100,
        "relative_strength_score": 68,
        "return_20d": 0.18,
        "distance_to_ma10": 0.08,
        "distance_to_ma20": 0.12,
        "amount_ratio_5d": 1.0,
        "volume_trap_risk_score": 60,
        "risk_score": 0,
        "is_st": False,
        "is_suspended": False,
    }

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=[rule],
        feature_contexts=[context],
    )

    assert len(plans) == 1
    assert plans[0].rule_id == "R006"
    assert plans[0].entry_trigger_price == pytest.approx(238.0)
