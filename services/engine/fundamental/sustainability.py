from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median
from typing import Any


@dataclass(frozen=True)
class EarningsSustainabilityAssessment:
    score: float
    grade: str
    reasons: list[str]
    earnings_quality_ratio: float | None

    def to_context(self) -> dict[str, Any]:
        return {
            "earnings_sustainability_score": self.score,
            "earnings_sustainability_grade": self.grade,
            "earnings_sustainability_reasons": self.reasons,
            "earnings_quality_ratio": self.earnings_quality_ratio,
        }


@dataclass(frozen=True)
class ValueReversionRange:
    fair_pe_low: float
    fair_pe_high: float
    fair_value_low: float
    fair_value_high: float
    conservative_upside_pct: float
    upper_upside_pct: float
    label: str
    reason: str

    def to_context(self) -> dict[str, Any]:
        return {
            "fair_pe_low": self.fair_pe_low,
            "fair_pe_high": self.fair_pe_high,
            "fair_value_low": self.fair_value_low,
            "fair_value_high": self.fair_value_high,
            "valuation_upside_low": self.conservative_upside_pct,
            "valuation_upside_high": self.upper_upside_pct,
            "valuation_space_label": self.label,
            "valuation_space_reason": self.reason,
        }


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sorted_history(history: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(history, key=lambda row: str(row.get("report_date") or ""), reverse=True)


def _annualized_roe(row: dict[str, Any]) -> float | None:
    roe = _number(row.get("roe"))
    report_date = str(row.get("report_date") or "")
    if roe is None or len(report_date) < 7:
        return None
    multiplier = {"03": 4.0, "06": 2.0, "09": 4.0 / 3.0, "12": 1.0}.get(
        report_date[5:7]
    )
    return roe * multiplier if multiplier is not None else None


def _growth_score(rows: list[dict[str, Any]], reasons: list[str]) -> float:
    latest = rows[:4]
    revenue = [_number(row.get("revenue_growth")) for row in latest]
    profit = [_number(row.get("profit_growth")) for row in latest]
    usable_revenue = [value for value in revenue if value is not None]
    usable_profit = [value for value in profit if value is not None]
    revenue_score = (
        15.0 * sum(value > 0 for value in usable_revenue) / len(usable_revenue)
        if len(usable_revenue) >= 3
        else 7.5
    )
    profit_score = (
        20.0 * sum(value > 0 for value in usable_profit) / len(usable_profit)
        if len(usable_profit) >= 3
        else 10.0
    )
    if len(usable_profit) >= 3 and usable_profit[0] < usable_profit[1] < usable_profit[2]:
        profit_score -= 5.0
        reasons.append("最近三期利润增速连续走弱")
    if len(usable_revenue) < 3 or len(usable_profit) < 3:
        reasons.append("增长连续性证据不足，按中性计分")
    else:
        reasons.append("最近四期营收与利润增长连续性已评估")
    return max(0.0, min(35.0, revenue_score + profit_score))


def _deducted_ratios(rows: list[dict[str, Any]]) -> list[float]:
    ratios = []
    for row in rows:
        parent = _number(row.get("parent_net_profit"))
        deducted = _number(row.get("deducted_parent_net_profit"))
        if parent is not None and parent > 0 and deducted is not None:
            ratios.append(deducted / parent)
    return ratios


def _deducted_score(ratios: list[float], reasons: list[str]) -> tuple[float, bool]:
    if len(ratios) < 2:
        reasons.append("扣非利润覆盖证据不足，按中性计分")
        return 15.0, False
    ratio = median(ratios[:2])
    score = 30.0 if ratio >= 0.9 else 24.0 if ratio >= 0.7 else 15.0 if ratio >= 0.5 else 0.0
    reasons.append(f"最近两期扣非利润覆盖率中位数 {ratio:.1%}")
    return score, True


def _annual_cash_ratios(rows: list[dict[str, Any]]) -> list[float]:
    ratios = []
    for row in rows:
        if str(row.get("report_date") or "")[5:7] != "12":
            continue
        parent = _number(row.get("parent_net_profit"))
        cash = _number(row.get("operating_cash_flow"))
        if parent is not None and parent > 0 and cash is not None:
            ratios.append(cash / parent)
    return ratios


def _cash_score(
    ratios: list[float], reasons: list[str], *, banking: bool
) -> tuple[float, bool]:
    if banking:
        reasons.append("银行复利框架不使用普通企业现金转化硬门槛")
        return 10.0, True
    if len(ratios) < 2:
        reasons.append("年度经营现金转化证据不足，按中性计分")
        return 10.0, False
    ratio = median(ratios[:2])
    score = 20.0 if ratio >= 1.0 else 15.0 if ratio >= 0.7 else 8.0 if ratio >= 0.3 else 0.0
    reasons.append(f"最近两年经营现金转化率中位数 {ratio:.1%}")
    return score, True


def _stability_score(rows: list[dict[str, Any]], reasons: list[str]) -> float:
    latest = rows[:4]
    roes = [value for row in latest if (value := _annualized_roe(row)) is not None]
    margins = [
        value
        for row in latest
        if (value := _number(row.get("gross_margin"))) is not None
    ]
    if len(roes) < 3:
        roe_score = 4.0
        reasons.append("年化 ROE 稳定性证据不足")
    else:
        roe_median = median(roes)
        roe_score = (
            8.0
            if roe_median >= 0.15
            else 6.0
            if roe_median >= 0.10
            else 3.0
            if roe_median >= 0.05
            else 0.0
        )
    if len(margins) < 3:
        margin_score = 3.5
        reasons.append("毛利率稳定性证据不足")
    else:
        spread = max(margins) - min(margins)
        margin_score = 7.0 if spread <= 0.05 else 4.0 if spread <= 0.10 else 0.0
    return max(0.0, min(15.0, roe_score + margin_score))


def assess_earnings_sustainability(
    history: Iterable[dict[str, Any]],
    *,
    analysis_framework: str | None = None,
) -> EarningsSustainabilityAssessment:
    rows = _sorted_history(history)
    reasons: list[str] = []
    deducted_ratios = _deducted_ratios(rows)
    annual_cash_ratios = _annual_cash_ratios(rows)
    banking = analysis_framework == "banking_compound"

    score = _growth_score(rows, reasons)
    deducted_score, deducted_available = _deducted_score(deducted_ratios, reasons)
    cash_score, cash_available = _cash_score(annual_cash_ratios, reasons, banking=banking)
    score += deducted_score + cash_score + _stability_score(rows, reasons)
    score = round(max(0.0, min(100.0, score)), 4)

    hard_reason = None
    if rows:
        latest_parent = _number(rows[0].get("parent_net_profit"))
        latest_deducted = _number(rows[0].get("deducted_parent_net_profit"))
        if (
            latest_parent is not None
            and latest_parent > 0
            and latest_deducted is not None
            and latest_deducted <= 0
        ):
            hard_reason = "最新一期归母利润为正但扣非利润非正"
    if hard_reason is None and len(deducted_ratios) >= 2 and all(
        ratio < 0.5 for ratio in deducted_ratios[:2]
    ):
        hard_reason = "最近两期扣非利润均低于归母利润的 50%"
    if hard_reason is None and len(rows) >= 2:
        latest_two = rows[:2]
        if all(
            (profit := _number(row.get("profit_growth"))) is not None
            and profit <= -0.30
            and (revenue := _number(row.get("revenue_growth"))) is not None
            and revenue <= 0
            for row in latest_two
        ):
            hard_reason = "连续两期利润大幅下滑且营收没有增长"
    if (
        hard_reason is None
        and not banking
        and len(annual_cash_ratios) >= 2
        and all(ratio < 0.30 for ratio in annual_cash_ratios[:2])
    ):
        hard_reason = "最近两年经营现金转化率均低于 30%"

    quality_ratio = median(deducted_ratios[:2]) if deducted_ratios else None
    if hard_reason is not None:
        reasons.insert(0, hard_reason)
        grade = "unsustainable"
    elif len(rows) < 4 or not deducted_available or not cash_available:
        grade = "pending"
    else:
        grade = "sustainable" if score >= 70 else "general"
    return EarningsSustainabilityAssessment(score, grade, reasons, quality_ratio)


def _percentile(values: list[float], percentile: float) -> float:
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def estimate_value_reversion_range(
    *,
    current_close: Any,
    current_pe: Any,
    earnings_quality_ratio: Any,
    historical_pe: Iterable[Any],
) -> ValueReversionRange | None:
    close = _number(current_close)
    current_multiple = _number(current_pe)
    quality = _number(earnings_quality_ratio)
    values = sorted(
        value
        for raw in historical_pe
        if (value := _number(raw)) is not None and value > 0
    )
    if (
        close is None
        or close <= 0
        or current_multiple is None
        or current_multiple <= 0
        or quality is None
        or quality <= 0
        or len(values) < 60
    ):
        return None
    trim = int(len(values) * 0.05)
    trimmed = values[trim : len(values) - trim] if trim else values
    if not trimmed:
        return None
    normalized_eps = close / current_multiple * min(1.0, quality)
    fair_pe_low = min(25.0, median(trimmed))
    fair_pe_high = max(fair_pe_low, min(30.0, _percentile(trimmed, 0.75)))
    fair_value_low = normalized_eps * fair_pe_low
    fair_value_high = normalized_eps * fair_pe_high
    conservative_upside = fair_value_low / close - 1.0
    upper_upside = fair_value_high / close - 1.0
    label = (
        "near_double_valuation_space"
        if conservative_upside >= 0.80
        else "valuation_reversion_space"
    )
    reason = (
        f"保守估值回归空间 {conservative_upside:+.1%}，"
        "基于盈利质量与历史估值回归测算，不是价格预测"
    )
    return ValueReversionRange(
        fair_pe_low=fair_pe_low,
        fair_pe_high=fair_pe_high,
        fair_value_low=fair_value_low,
        fair_value_high=fair_value_high,
        conservative_upside_pct=conservative_upside,
        upper_upside_pct=upper_upside,
        label=label,
        reason=reason,
    )
