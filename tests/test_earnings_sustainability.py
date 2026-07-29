from copy import deepcopy

import pytest

from services.engine.fundamental.sustainability import (
    assess_earnings_sustainability,
    estimate_value_reversion_range,
)


def giant_network_like_history() -> list[dict[str, object]]:
    return [
        {
            "report_date": "2026-03-31",
            "revenue_growth": 0.22,
            "profit_growth": 0.31,
            "roe": 0.04,
            "gross_margin": 0.75,
            "parent_net_profit": 300,
            "deducted_parent_net_profit": 270,
            "operating_cash_flow": -20,
        },
        {
            "report_date": "2025-12-31",
            "revenue_growth": 0.18,
            "profit_growth": 0.25,
            "roe": 0.17,
            "gross_margin": 0.76,
            "parent_net_profit": 1000,
            "deducted_parent_net_profit": 900,
            "operating_cash_flow": 1100,
        },
        {
            "report_date": "2025-09-30",
            "revenue_growth": 0.15,
            "profit_growth": 0.20,
            "roe": 0.12,
            "gross_margin": 0.74,
            "parent_net_profit": 700,
            "deducted_parent_net_profit": 630,
            "operating_cash_flow": 650,
        },
        {
            "report_date": "2025-06-30",
            "revenue_growth": 0.12,
            "profit_growth": 0.16,
            "roe": 0.08,
            "gross_margin": 0.73,
            "parent_net_profit": 450,
            "deducted_parent_net_profit": 405,
            "operating_cash_flow": 430,
        },
        {
            "report_date": "2025-03-31",
            "revenue_growth": 0.10,
            "profit_growth": 0.14,
            "roe": 0.038,
            "gross_margin": 0.72,
            "parent_net_profit": 220,
            "deducted_parent_net_profit": 198,
            "operating_cash_flow": 210,
        },
        {
            "report_date": "2024-12-31",
            "revenue_growth": 0.08,
            "profit_growth": 0.12,
            "roe": 0.16,
            "gross_margin": 0.72,
            "parent_net_profit": 800,
            "deducted_parent_net_profit": 720,
            "operating_cash_flow": 800,
        },
    ]


def test_sustained_operating_earnings_grade_as_sustainable() -> None:
    result = assess_earnings_sustainability(
        giant_network_like_history(), analysis_framework="tech_growth_cycle"
    )
    assert result.grade == "sustainable"
    assert result.score >= 70
    assert result.earnings_quality_ratio == pytest.approx(0.9)


def test_positive_reported_profit_with_negative_deducted_profit_is_unsustainable() -> None:
    history = giant_network_like_history()
    history[0]["deducted_parent_net_profit"] = -1
    assert assess_earnings_sustainability(history).grade == "unsustainable"


def test_two_weak_deducted_profit_ratios_are_unsustainable() -> None:
    history = giant_network_like_history()
    history[0]["deducted_parent_net_profit"] = 120
    history[1]["deducted_parent_net_profit"] = 400
    assert assess_earnings_sustainability(history).grade == "unsustainable"


def test_two_unsupported_severe_profit_declines_are_unsustainable() -> None:
    history = giant_network_like_history()
    for row in history[:2]:
        row["profit_growth"] = -0.30
        row["revenue_growth"] = 0.0
    assert assess_earnings_sustainability(history).grade == "unsustainable"


def test_two_weak_annual_cash_ratios_are_unsustainable_except_for_banks() -> None:
    history = giant_network_like_history()
    history[1]["operating_cash_flow"] = 200
    history[5]["operating_cash_flow"] = 100
    assert assess_earnings_sustainability(history).grade == "unsustainable"
    assert (
        assess_earnings_sustainability(
            history, analysis_framework="banking_compound"
        ).grade
        != "unsustainable"
    )


def test_negative_interim_cash_flow_does_not_hard_block() -> None:
    history = giant_network_like_history()
    history[0]["operating_cash_flow"] = -999
    assert assess_earnings_sustainability(history).grade == "sustainable"


def test_missing_deducted_or_annual_cash_evidence_stays_pending() -> None:
    no_deducted = giant_network_like_history()[:3]
    for row in no_deducted:
        row["deducted_parent_net_profit"] = None
    assert assess_earnings_sustainability(no_deducted).grade == "pending"

    no_annual_cash = deepcopy(giant_network_like_history())
    for row in no_annual_cash:
        if str(row["report_date"])[5:7] == "12":
            row["operating_cash_flow"] = None
    assert assess_earnings_sustainability(no_annual_cash).grade == "pending"


def test_exact_seventy_point_boundary_is_sustainable() -> None:
    history = giant_network_like_history()
    for row in history:
        row["deducted_parent_net_profit"] = float(row["parent_net_profit"]) * 0.5
        row["roe"] = 0.15 if str(row["report_date"])[5:7] == "12" else 0.075
        row["gross_margin"] = 0.40 if len(str(row["report_date"])) % 2 else 0.48
    history[0]["gross_margin"] = 0.40
    history[1]["gross_margin"] = 0.48
    history[2]["gross_margin"] = 0.44
    history[3]["gross_margin"] = 0.46
    history[1]["operating_cash_flow"] = float(history[1]["parent_net_profit"]) * 0.3
    history[5]["operating_cash_flow"] = float(history[5]["parent_net_profit"]) * 0.3

    result = assess_earnings_sustainability(history)

    assert result.score == pytest.approx(70.0)
    assert result.grade == "sustainable"


def test_conservative_value_range_caps_historical_pe() -> None:
    result = estimate_value_reversion_range(
        current_close=10,
        current_pe=10,
        earnings_quality_ratio=0.9,
        historical_pe=[*range(10, 40)] * 3 + [999],
    )
    assert result is not None
    assert result.fair_pe_low <= 25
    assert result.fair_pe_high <= 30
    assert result.fair_value_low == pytest.approx(22.5)
    assert result.conservative_upside_pct == pytest.approx(1.25)
    assert result.label == "near_double_valuation_space"


def test_value_range_requires_sixty_positive_observations() -> None:
    assert (
        estimate_value_reversion_range(
            current_close=10,
            current_pe=10,
            earnings_quality_ratio=0.9,
            historical_pe=[10] * 59,
        )
        is None
    )
