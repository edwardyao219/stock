from types import SimpleNamespace

from services.engine.review.rule_diagnostics import diagnose_rule_performance


def test_diagnose_rule_performance_promotes_strong_rule() -> None:
    diagnostic = diagnose_rule_performance(
        SimpleNamespace(
            rule_id="R001",
            trade_count=45,
            win_rate=0.62,
            avg_return=0.018,
            profit_factor=1.8,
            avg_mfe=0.03,
            avg_mae=-0.02,
            score=8.0,
        )
    )

    assert diagnostic.status == "promote"
    assert diagnostic.confidence == "medium"
    assert any("保持当前参数" in item for item in diagnostic.suggestions)
    assert any(
        item.target_name == "position_sizing" and item.action == "test_small_increase"
        for item in diagnostic.parameter_suggestions
    )
    assert any(
        item.target_name == "breakout_confirmation"
        for item in diagnostic.parameter_suggestions
    )


def test_diagnose_rule_performance_reduces_weak_rule() -> None:
    diagnostic = diagnose_rule_performance(
        SimpleNamespace(
            rule_id="R004",
            trade_count=90,
            win_rate=0.38,
            avg_return=-0.004,
            profit_factor=0.8,
            avg_mfe=0.04,
            avg_mae=-0.05,
            score=1.0,
        )
    )

    assert diagnostic.status == "reduce"
    assert diagnostic.confidence == "high"
    assert any("收紧止损" in item for item in diagnostic.suggestions)
    assert any(
        item.target_name == "monthly_sector_trend_quality"
        and item.proposed["candidate_sector_strength_score_min"] == 72
        for item in diagnostic.parameter_suggestions
    )


def test_diagnose_rule_performance_marks_low_sample_observation() -> None:
    diagnostic = diagnose_rule_performance(
        SimpleNamespace(
            rule_id="R002",
            trade_count=5,
            win_rate=0.8,
            avg_return=0.02,
            profit_factor=2.0,
            avg_mfe=0.03,
            avg_mae=-0.01,
            score=10.0,
        )
    )

    assert diagnostic.confidence == "low"
    assert any("样本数不足" in item for item in diagnostic.reasons)
    assert any(
        item.target_name == "out_of_sample_collection"
        and "低样本规则禁止放大仓位" in item.guardrails
        for item in diagnostic.parameter_suggestions
    )


def test_diagnose_rule_performance_preserves_payoff_ratio() -> None:
    diagnostic = diagnose_rule_performance(
        SimpleNamespace(
            rule_id="R004",
            trade_count=60,
            win_rate=0.42,
            avg_return=0.006,
            profit_factor=1.2,
            avg_mfe=0.05,
            avg_mae=-0.03,
            score=4.0,
        )
    )

    assert diagnostic.status == "observe"
    assert any(
        item.target_name == "monthly_sector_trend_take_profit"
        and item.proposed["prefer_position_rebalance"] is True
        for item in diagnostic.parameter_suggestions
    )
