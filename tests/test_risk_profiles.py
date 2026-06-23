from services.engine.risk.profiles import BANKING_COMPOUND_PROFILE
from services.engine.risk.trade_parameters import build_trade_parameters
from services.engine.rules.seed_rules import MVP_RULES


def test_banking_profile_uses_wider_longer_parameters() -> None:
    params = build_trade_parameters(
        rule=MVP_RULES[0],
        profile=BANKING_COMPOUND_PROFILE,
        context={
            "symbol": "000001",
            "close": 10.0,
            "atr_14": 0.3,
            "breakout_level": 10.2,
            "support_level": 9.4,
        },
    )

    assert params.max_holding_days == 5  # Rule-specific short-term holding still wins for R001.
    assert params.trailing_drawdown_pct == 0.10
    assert params.take_profit_1 > 11
    assert params.take_profit_2 > 12
    assert params.position_size_pct <= BANKING_COMPOUND_PROFILE.max_position_pct


def test_compound_rule_uses_profile_holding_period() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R004")
    params = build_trade_parameters(
        rule=rule,
        profile=BANKING_COMPOUND_PROFILE,
        context={
            "symbol": "000001",
            "close": 10.0,
            "ma20": 9.9,
            "atr_14": 0.2,
            "support_level": 9.2,
        },
    )

    assert params.max_holding_days == 60
    assert params.entry_reference_price == 10.0
    assert params.trailing_drawdown_pct == 0.10
