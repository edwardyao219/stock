from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FundamentalAssessment:
    score: float
    verdict: str
    reasons: list[str]


def _value(context: dict[str, Any], key: str) -> float | None:
    value = context.get(key)
    if value is None:
        return None
    return float(value)


def _extra_value(context: dict[str, Any], key: str) -> float | None:
    extra = context.get("fundamental_extra") or {}
    if not isinstance(extra, dict):
        return None
    value = extra.get(key)
    if value is None:
        return None
    return float(value)


def _score_growth_quality(context: dict[str, Any], reasons: list[str]) -> float:
    score_delta = 0.0
    revenue_growth = _value(context, "revenue_growth")
    profit_growth = _value(context, "profit_growth")
    roe = _extra_value(context, "roe_annualized") or _value(context, "roe")
    gross_margin = _value(context, "gross_margin")
    debt_ratio = _value(context, "debt_ratio")
    pe_ttm = _value(context, "pe_ttm")

    if revenue_growth is not None:
        if revenue_growth >= 0.15:
            score_delta += 8
            reasons.append("营收增速较强，题材有业绩承接")
        elif revenue_growth < 0:
            score_delta -= 8
            reasons.append("营收下滑，题材兑现风险更高")
    if profit_growth is not None:
        if profit_growth >= 0.20:
            score_delta += 10
            reasons.append("利润增速较强，趋势延续更有基本面支撑")
        elif profit_growth < 0:
            score_delta -= 15
            reasons.append("利润增速为负，短线更偏资金博弈")
    if roe is not None:
        if roe >= 0.10:
            score_delta += 6
            reasons.append("ROE 尚可，质量不拖累交易")
        elif roe < 0.03:
            score_delta -= 8
            reasons.append("ROE 偏低，质量支撑不足")
    if gross_margin is not None and gross_margin >= 0.25:
        score_delta += 4
        reasons.append("毛利率具备一定产品/周期弹性")
    if debt_ratio is not None and debt_ratio >= 0.75:
        score_delta -= 8
        reasons.append("负债率偏高，回撤时风险放大")
    if pe_ttm is not None:
        if pe_ttm <= 0:
            score_delta -= 8
            reasons.append("PE 为负或不可用，盈利质量需警惕")
        elif pe_ttm > 100:
            score_delta -= 6
            reasons.append("PE 极高，业绩兑现压力较大")
    return score_delta


def assess_fundamentals(context: dict[str, Any]) -> FundamentalAssessment:
    framework = context.get("analysis_framework")
    reasons: list[str] = []
    score = 50.0

    if framework == "banking_compound":
        dividend_yield = _value(context, "dividend_yield")
        pb = _value(context, "pb")
        roe = _extra_value(context, "roe_annualized") or _value(context, "roe")

        if dividend_yield is not None:
            if dividend_yield >= 0.04:
                score += 15
                reasons.append("股息率较高，适合复利框架")
            else:
                score -= 10
                reasons.append("股息率偏低，复利吸引力不足")
        if pb is not None:
            if pb <= 0.8:
                score += 15
                reasons.append("PB 处于较低估值区间")
            elif pb > 1.2:
                score -= 15
                reasons.append("PB 偏高，安全边际下降")
        if roe is not None:
            if roe >= 0.10:
                score += 10
                reasons.append("年化 ROE 支撑长期持有逻辑")
            else:
                score -= 10
                reasons.append("年化 ROE 偏弱，长期持有质量不足")

    elif framework == "consumer_quality":
        profit_growth = _value(context, "profit_growth")
        gross_margin = _value(context, "gross_margin")
        pe_ttm = _value(context, "pe_ttm")

        if profit_growth is not None:
            score += 10 if profit_growth > 0 else -15
            reasons.append("利润增速为正" if profit_growth > 0 else "利润增速为负")
        if gross_margin is not None and gross_margin >= 0.40:
            score += 10
            reasons.append("毛利率较高，具备消费质量属性")
        if pe_ttm is not None and pe_ttm > 35:
            score -= 10
            reasons.append("PE 偏高，估值修复空间受限")

    elif framework in {"tech_growth_cycle", "theme_momentum"}:
        score += _score_growth_quality(context, reasons)

    else:
        for key in ["profit_growth", "revenue_growth", "roe"]:
            value = _value(context, key)
            if value is not None and value > 0:
                score += 5
                reasons.append(f"{key} 为正")

    score = max(0.0, min(100.0, score))
    if score >= 70:
        verdict = "supportive"
    elif score <= 40:
        verdict = "weak"
    else:
        verdict = "neutral"
    if not reasons:
        reasons.append("暂无足够基本面数据，保持中性")
    return FundamentalAssessment(score=score, verdict=verdict, reasons=reasons)
