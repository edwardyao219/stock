import pytest

from services.engine.plans.generator import generate_trade_plans
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
