from services.engine.plans.generator import generate_trade_plans
from services.engine.rules.seed_rules import MVP_RULES


def test_generate_trade_plans_from_feature_context() -> None:
    contexts = [
        {
            "symbol": "000001",
            "trade_date": "2026-06-23",
            "close": 10.0,
            "atr_14": 0.3,
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

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=MVP_RULES,
        feature_contexts=contexts,
    )

    assert len(plans) == 1
    assert plans[0].symbol == "000001"
    assert plans[0].rule_id == "R001"
    assert plans[0].initial_stop == 9.55
    assert plans[0].take_profit_1 == 10.6
    assert plans[0].take_profit_2 == 11.2
    assert plans[0].confidence_score > 70
