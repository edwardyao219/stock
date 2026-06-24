from services.engine.fundamental.scoring import assess_fundamentals


def test_banking_fundamental_assessment_supportive() -> None:
    assessment = assess_fundamentals(
        {
            "analysis_framework": "banking_compound",
            "dividend_yield": 0.055,
            "pb": 0.58,
            "roe": 0.11,
        }
    )

    assert assessment.verdict == "supportive"
    assert assessment.score >= 80
    assert any("股息率" in reason for reason in assessment.reasons)


def test_banking_fundamental_assessment_uses_annualized_quarterly_roe() -> None:
    assessment = assess_fundamentals(
        {
            "analysis_framework": "banking_compound",
            "roe": 0.0283,
            "fundamental_extra": {"roe_annualized": "0.1132"},
        }
    )

    assert assessment.score > 50
    assert any("年化 ROE" in reason for reason in assessment.reasons)


def test_missing_fundamentals_remain_neutral() -> None:
    assessment = assess_fundamentals({"analysis_framework": "banking_compound"})

    assert assessment.verdict == "neutral"
    assert assessment.score == 50


def test_theme_growth_assessment_flags_profit_decline_hot_money_risk() -> None:
    assessment = assess_fundamentals(
        {
            "analysis_framework": "theme_momentum",
            "revenue_growth": -0.05,
            "profit_growth": -0.20,
            "roe": 0.01,
            "pe_ttm": -1,
        }
    )

    assert assessment.verdict == "weak"
    assert any("资金博弈" in reason for reason in assessment.reasons)


def test_tech_growth_assessment_rewards_real_growth() -> None:
    assessment = assess_fundamentals(
        {
            "analysis_framework": "tech_growth_cycle",
            "revenue_growth": 0.22,
            "profit_growth": 0.35,
            "roe": 0.12,
            "gross_margin": 0.32,
        }
    )

    assert assessment.verdict == "supportive"
    assert any("业绩承接" in reason for reason in assessment.reasons)
