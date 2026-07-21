import pytest

from services.engine.plans.evidence import build_trade_evidence
from services.engine.plans.generator import generate_trade_plans
from services.engine.risk.profiles import RiskProfile
from services.engine.rules.seed_rules import MVP_RULES


def _valid_long_term_context() -> dict[str, float | str | bool]:
    return {
        "symbol": "603083",
        "trade_date": "2026-06-23",
        "close": 58.0,
        "ma20": 56.5,
        "atr_14": 2.0,
        "support_level": 52.0,
        "sector_strength_score": 76.0,
        "sector_breadth_score": 60.0,
        "sector_momentum_score": 62.0,
        "relative_strength_score": 70.0,
        "trend_score": 78.0,
        "ma_alignment_score": 74.0,
        "trend_quality_score": 72.0,
        "volume_confirmation_score": 55.0,
        "risk_score": 32.0,
        "overheat_score": 58.0,
        "volume_trap_risk_score": 40.0,
        "return_20d": 0.14,
        "distance_to_ma20": 0.026,
        "max_drawdown_20d": -0.08,
        "analysis_framework": "tech_growth_cycle",
        "fundamental_verdict": "supportive",
        "is_st": False,
        "is_suspended": False,
    }


def test_trade_evidence_reports_tushare_5000_matrix() -> None:
    supportive = build_trade_evidence(
        {"moneyflow_support_score": 54, "dc_net_amount_rate": 1.0}
    )
    outflow = build_trade_evidence(
        {"moneyflow_support_score": 45, "dc_net_amount_rate": -1.0}
    )
    divergent = build_trade_evidence(
        {"moneyflow_support_score": 54, "dc_net_amount_rate": -1.0}
    )
    limit_down = build_trade_evidence({"limit_event": "D"})
    opened_twice = build_trade_evidence({"limit_open_times": 2})
    below_cost = build_trade_evidence({"close": 10.0, "chip_cost_85pct": 11.0})
    overheated = build_trade_evidence(
        {"close": 11.0, "chip_cost_85pct": 11.0, "chip_winner_rate": 90.0}
    )

    assert "dual_source_moneyflow_confirmation" in supportive["support_flags"]
    assert "dual_source_moneyflow_outflow" in outflow["risk_flags"]
    assert "moneyflow_source_divergence" in divergent["risk_flags"]
    assert "limit_down_risk" in limit_down["risk_flags"]
    assert "repeated_limit_open" in opened_twice["risk_flags"]
    assert "chip_overhead_pressure" in below_cost["risk_flags"]
    assert "chip_overheat" in overheated["risk_flags"]
    assert overheated["scores"]["chip_winner_rate"] == 90.0


@pytest.mark.parametrize(
    "risk_context",
    [
        {"moneyflow_support_score": 45, "dc_net_amount_rate": -1.0},
        {"limit_event": "D"},
        {"limit_open_times": 2},
        {"chip_cost_85pct": 58.0, "chip_winner_rate": 90.0},
    ],
)
def test_generate_trade_plans_blocks_action_on_tushare_high_risks(risk_context) -> None:
    rule = next(item for item in MVP_RULES if item.id == "R004")

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=[rule],
        feature_contexts=[{**_valid_long_term_context(), **risk_context}],
    )

    assert plans == []


def test_generate_trade_plans_blocks_action_when_data_evidence_is_incomplete() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R004")

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=[rule],
        feature_contexts=[
            {
                **_valid_long_term_context(),
                "data_evidence_risk": {
                    "status": "blocked",
                    "reasons": ["筹码分布：数据覆盖不完整"],
                },
            }
        ],
    )

    assert plans == []


def test_nonblocking_tushare_evidence_remains_explanatory() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R004")

    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=[rule],
        feature_contexts=[
            {
                **_valid_long_term_context(),
                "moneyflow_support_score": 54,
                "dc_net_amount_rate": -1.0,
                "chip_cost_85pct": 60.0,
            }
        ],
    )

    assert len(plans) == 1
    evidence = plans[0].entry_condition["evidence"]
    assert "moneyflow_source_divergence" in evidence["risk_flags"]
    assert "chip_overhead_pressure" in evidence["risk_flags"]


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
    assert plans[0].entry_condition["snapshot"]["route_score"] is not None
    evidence = plans[0].entry_condition["evidence"]
    assert "high_position_volume_spike" in evidence["risk_flags"]
    assert "trend_alignment" in evidence["support_flags"]
    assert plans[0].confidence_score > 75


def test_generate_trade_plans_can_filter_short_term_from_main_book() -> None:
    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=MVP_RULES,
        feature_contexts=[
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
        ],
        allowed_strategy_types={"long_term", "swing"},
    )

    assert plans == []


def test_monthly_trend_rule_accepts_sector_trend_context_without_dividend_filter() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R004")
    contexts = [
        {
            "symbol": "603083",
            "trade_date": "2026-06-23",
            "close": 58.0,
            "ma20": 56.5,
            "atr_14": 2.0,
            "support_level": 52.0,
            "sector_strength_score": 76,
            "sector_breadth_score": 60,
            "sector_momentum_score": 62,
            "relative_strength_score": 70,
            "trend_score": 78,
            "ma_alignment_score": 74,
            "trend_quality_score": 72,
            "volume_confirmation_score": 55,
            "risk_score": 32,
            "overheat_score": 58,
            "volume_trap_risk_score": 40,
            "return_20d": 0.14,
            "distance_to_ma20": 0.026,
            "max_drawdown_20d": -0.08,
            "analysis_framework": "tech_growth_cycle",
            "fundamental_verdict": "supportive",
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

    assert len(plans) == 1
    assert plans[0].rule_id == "R004"
    assert plans[0].strategy_type == "long_term"
    assert plans[0].max_holding_days == 60


def test_monthly_trend_rule_accepts_top_ranked_sector_when_absolute_score_is_moderate() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R004")
    plans = generate_trade_plans(
        plan_date="2026-07-07",
        trade_date="2026-07-08",
        rules=[rule],
        feature_contexts=[
            {
                "symbol": "688130",
                "trade_date": "2026-07-07",
                "close": 87.0,
                "ma20": 83.0,
                "atr_14": 3.0,
                "support_level": 78.0,
                "sector_strength_score": 58.1,
                "sector_strength_rank_score": 100.0,
                "sector_breadth_score": 54.0,
                "sector_momentum_score": 45.0,
                "relative_strength_score": 95,
                "trend_score": 100,
                "ma_alignment_score": 100,
                "trend_quality_score": 76,
                "volume_confirmation_score": 62,
                "risk_score": 20,
                "overheat_score": 35,
                "volume_trap_risk_score": 40,
                "return_20d": 0.276,
                "distance_to_ma20": 0.048,
                "max_drawdown_20d": -0.08,
                "analysis_framework": "tech_growth_cycle",
                "fundamental_verdict": "neutral",
                "is_st": False,
                "is_suspended": False,
            }
        ],
    )

    assert len(plans) == 1
    assert plans[0].rule_id == "R004"


def test_monthly_trend_rule_requires_sector_breadth_confirmation() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R004")
    plans = generate_trade_plans(
        plan_date="2026-06-23",
        trade_date="2026-06-24",
        rules=[rule],
        feature_contexts=[
            {
                "symbol": "603083",
                "trade_date": "2026-06-23",
                "close": 58.0,
                "ma20": 56.5,
                "atr_14": 2.0,
                "support_level": 52.0,
                "sector_strength_score": 76,
                "sector_breadth_score": 48,
                "sector_momentum_score": 62,
                "relative_strength_score": 70,
                "trend_score": 78,
                "ma_alignment_score": 74,
                "trend_quality_score": 72,
                "volume_confirmation_score": 55,
                "risk_score": 32,
                "overheat_score": 58,
                "volume_trap_risk_score": 40,
                "return_20d": 0.14,
                "distance_to_ma20": 0.026,
                "max_drawdown_20d": -0.08,
                "analysis_framework": "tech_growth_cycle",
                "fundamental_verdict": "supportive",
                "is_st": False,
                "is_suspended": False,
            }
        ],
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
        "volume_confirmation_score": 60,
        "ma_alignment_score": 100,
        "trend_quality_score": 80,
        "close_position_in_range": 0.6,
        "volume_score": 60,
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


def test_trend_volume_confirmation_rule_accepts_orderly_trend() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R007")
    context = {
        "symbol": "600183",
        "trade_date": "2026-06-23",
        "close": 168.0,
        "high": 171.0,
        "ma10": 160.0,
        "ma20": 154.0,
        "atr_14": 7.0,
        "support_level": 150.0,
        "sector_strength_score": 72,
        "ma_alignment_score": 100,
        "trend_quality_score": 78,
        "volume_confirmation_score": 68,
        "relative_strength_score": 66,
        "return_20d": 0.16,
        "distance_to_ma20": 0.09,
        "amount_ratio_5d": 1.15,
        "amount_percentile_60d": 70,
        "close_position_in_range": 0.72,
        "upper_shadow_pct": 0.018,
        "overheat_score": 55,
        "volume_trap_risk_score": 42,
        "fundamental_verdict": "neutral",
        "fundamental_score": 62,
        "trend_score": 100,
        "volume_score": 70,
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
    assert plans[0].rule_id == "R007"
    assert plans[0].entry_trigger_price == pytest.approx(168.0)
    assert plans[0].entry_condition["trade_parameters"]["evidence"]["entry_reason"] == (
        "trend_volume_confirmation_reference"
    )


def test_trend_volume_confirmation_rule_rejects_overheated_volume_trap() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R007")
    context = {
        "symbol": "002837",
        "trade_date": "2026-06-23",
        "close": 82.0,
        "high": 88.0,
        "ma10": 70.0,
        "ma20": 62.0,
        "atr_14": 5.0,
        "support_level": 68.0,
        "sector_strength_score": 82,
        "ma_alignment_score": 100,
        "trend_quality_score": 82,
        "volume_confirmation_score": 74,
        "relative_strength_score": 78,
        "return_20d": 0.42,
        "distance_to_ma20": 0.32,
        "amount_ratio_5d": 2.1,
        "amount_percentile_60d": 96,
        "close_position_in_range": 0.35,
        "upper_shadow_pct": 0.07,
        "overheat_score": 91,
        "volume_trap_risk_score": 79,
        "fundamental_verdict": "weak",
        "trend_score": 100,
        "volume_score": 96,
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
