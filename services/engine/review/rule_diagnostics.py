from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParameterSuggestion:
    target_type: str
    target_name: str
    action: str
    rationale: str
    priority: str = "medium"
    scope_type: str = "rule"
    scope_value: str | None = None
    current: dict[str, Any] = field(default_factory=dict)
    proposed: dict[str, Any] = field(default_factory=dict)
    guardrails: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuleDiagnostic:
    rule_id: str
    status: str
    confidence: str
    summary: str
    reasons: list[str]
    suggestions: list[str]
    parameter_suggestions: list[ParameterSuggestion]
    metrics: dict[str, float | int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _float(value: Any) -> float:
    return float(value or 0)


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _sample_guardrails(confidence: str) -> list[str]:
    guardrails = [
        "只作为候选参数，不自动应用",
        "必须用后续交易日做样本外验证",
    ]
    if confidence == "low":
        guardrails.append("低样本规则禁止放大仓位")
    return guardrails


def _base_parameter_suggestions(
    *,
    rule_id: str,
    status: str,
    confidence: str,
    trade_count: int,
    win_rate: float,
    avg_return: float,
    profit_factor: float,
    avg_mfe: float,
    avg_mae: float,
) -> list[ParameterSuggestion]:
    suggestions: list[ParameterSuggestion] = []
    guardrails = _sample_guardrails(confidence)

    if trade_count == 0:
        return [
            ParameterSuggestion(
                target_type="research_process",
                target_name="sample_collection",
                action="expand_or_inspect",
                priority="high",
                scope_value=rule_id,
                rationale="规则没有触发样本，暂时无法判断参数优劣，优先确认条件是否过严或样本池是否覆盖不足。",
                proposed={"next_step": "review_entry_filters_and_universe"},
                guardrails=guardrails,
            )
        ]

    if confidence == "low":
        suggestions.append(
            ParameterSuggestion(
                target_type="research_process",
                target_name="out_of_sample_collection",
                action="expand_sample",
                priority="high",
                scope_value=rule_id,
                rationale="样本数不足，当前表现容易被少数行情扭曲，应先扩大股票池和时间窗，再决定是否调整交易参数。",
                current={"trade_count": trade_count},
                proposed={"minimum_trade_count_before_position_change": 20},
                guardrails=guardrails,
            )
        )

    if status == "promote" and confidence in {"medium", "high"}:
        suggestions.append(
            ParameterSuggestion(
                target_type="risk_profile",
                target_name="position_sizing",
                action="test_small_increase",
                priority="medium",
                scope_value=rule_id,
                rationale="规则有正期望且盈亏因子较好，可小步测试仓位上限，不直接重仓。",
                current={
                    "win_rate": win_rate,
                    "avg_return": avg_return,
                    "profit_factor": profit_factor,
                },
                proposed={"max_position_pct_delta": 0.01, "max_total_delta": 0.02},
                guardrails=guardrails + ["若连续样本外回撤扩大，立即回退"],
            )
        )

    if status == "reduce":
        suggestions.extend(
            [
                ParameterSuggestion(
                    target_type="risk_profile",
                    target_name="position_sizing",
                    action="test_reduce",
                    priority="high",
                    scope_value=rule_id,
                    rationale="规则期望偏弱，应先降低单笔暴露，避免把亏损样本继续放大。",
                    current={"avg_return": avg_return, "profit_factor": profit_factor},
                    proposed={"max_position_pct_multiplier": 0.8},
                    guardrails=guardrails,
                ),
                ParameterSuggestion(
                    target_type="exit_policy",
                    target_name="initial_stop",
                    action="test_tighten",
                    priority="medium",
                    scope_value=rule_id,
                    rationale="规则不利波动或亏损特征偏弱，适合回测更紧的初始止损版本。",
                    current={"avg_mae": avg_mae},
                    proposed={"max_stop_loss_pct_multiplier": 0.85},
                    guardrails=guardrails + ["不要只用历史最优止损点，需检查交易成本和滑点"],
                ),
            ]
        )

    if avg_mfe > abs(avg_mae) * 1.5 and avg_return <= 0:
        suggestions.append(
            ParameterSuggestion(
                target_type="exit_policy",
                target_name="take_profit_or_trailing",
                action="test_earlier_profit_capture",
                priority="medium",
                scope_value=rule_id,
                rationale="平均浮盈明显出现过但最终收益不佳，说明卖点可能把利润还回去。",
                current={"avg_mfe": avg_mfe, "avg_mae": avg_mae, "avg_return": avg_return},
                proposed={"trailing_drawdown_pct_multiplier": 0.85},
                guardrails=guardrails + ["如果盈亏比被明显压低，则撤销该版本"],
            )
        )

    if win_rate < 0.45 and avg_return > 0:
        suggestions.append(
            ParameterSuggestion(
                target_type="exit_policy",
                target_name="take_profit",
                action="preserve_payoff_ratio",
                priority="medium",
                scope_value=rule_id,
                rationale="胜率低但期望为正，优势可能来自少数大赚样本，不能机械提前止盈。",
                current={"win_rate": win_rate, "avg_return": avg_return},
                proposed={
                    "avoid_tightening_take_profit": True,
                    "focus": "entry_quality_or_position_control",
                },
                guardrails=guardrails,
            )
        )

    return suggestions


def _rule_specific_parameter_suggestions(
    *,
    rule_id: str,
    status: str,
    confidence: str,
    trade_count: int,
    win_rate: float,
    avg_return: float,
    profit_factor: float,
) -> list[ParameterSuggestion]:
    guardrails = _sample_guardrails(confidence)

    if rule_id == "R001":
        if status == "promote":
            return [
                ParameterSuggestion(
                    target_type="rule_condition",
                    target_name="breakout_confirmation",
                    action="hold_or_test_stricter_liquidity",
                    priority="medium",
                    scope_value=rule_id,
                    rationale="强势板块突破规则表现较好时，优先保持核心逻辑，下一步只小范围测试量能确认，避免追涨规则被过拟合。",
                    current={"amount_percentile_60d_min": 80, "intraday_amount_ratio_min": 1.2},
                    proposed={"candidate_intraday_amount_ratio_min": 1.3},
                    guardrails=guardrails + ["高开限制和弱市过滤不可放宽"],
                )
            ]
        if status == "reduce":
            return [
                ParameterSuggestion(
                    target_type="rule_condition",
                    target_name="breakout_entry",
                    action="test_tighten",
                    priority="high",
                    scope_value=rule_id,
                    rationale="短线突破规则一旦失效，通常先来自情绪退潮或追高失败，应优先收紧板块强度和高开限制。",
                    current={"sector_strength_score_min": 75, "gap_up_pct_max": 0.06},
                    proposed={
                        "candidate_sector_strength_score_min": 80,
                        "candidate_gap_up_pct_max": 0.04,
                    },
                    guardrails=guardrails,
                )
            ]

    if rule_id == "R004":
        suggestions: list[ParameterSuggestion] = []
        if status in {"observe", "reduce"}:
            suggestions.append(
                ParameterSuggestion(
                    target_type="rule_condition",
                    target_name="banking_compound_valuation",
                    action="test_tighten",
                    priority="high" if status == "reduce" else "medium",
                    scope_value=rule_id,
                    rationale="稳定复利类资产不能用短线强度硬追，正期望偏弱时应先测试更便宜和更高股息的入场版本。",
                    current={"pb_max": 1.0, "dividend_yield_min": 0.03},
                    proposed={"candidate_pb_max": 0.8, "candidate_dividend_yield_min": 0.04},
                    guardrails=guardrails + ["不要因为短期涨幅好而放宽估值约束"],
                )
            )
        if status == "promote" and confidence == "high":
            suggestions.append(
                ParameterSuggestion(
                    target_type="risk_profile",
                    target_name="banking_compound_position",
                    action="test_pyramid_slowly",
                    priority="medium",
                    scope_value=rule_id,
                    rationale="银行复利类如果长期样本稳定，仓位优化应偏慢，采用分批加仓而非突破追入。",
                    current={"max_position_pct": 0.18},
                    proposed={
                        "candidate_max_position_pct": 0.20,
                        "add_only_after_new_high_or_pullback_hold": True,
                    },
                    guardrails=guardrails + ["单股集中度仍需受组合上限约束"],
                )
            )
        if win_rate < 0.45 and avg_return > 0:
            suggestions.append(
                ParameterSuggestion(
                    target_type="exit_policy",
                    target_name="banking_compound_take_profit",
                    action="avoid_short_term_take_profit",
                    priority="medium",
                    scope_value=rule_id,
                    rationale="复利类资产胜率不高但期望为正时，过早止盈可能破坏少数趋势段贡献。",
                    current={
                        "win_rate": win_rate,
                        "avg_return": avg_return,
                        "profit_factor": profit_factor,
                    },
                    proposed={
                        "keep_trailing_drawdown_pct": 0.10,
                        "prefer_position_rebalance": True,
                    },
                    guardrails=guardrails,
                )
            )
        return suggestions

    return []


def diagnose_rule_performance(item: Any) -> RuleDiagnostic:
    trade_count = int(item.trade_count or 0)
    win_rate = _float(item.win_rate)
    avg_return = _float(item.avg_return)
    profit_factor = _float(item.profit_factor)
    avg_mfe = _float(item.avg_mfe)
    avg_mae = _float(item.avg_mae)
    score = _float(item.score)

    reasons: list[str] = []
    suggestions: list[str] = []

    if trade_count < 20:
        confidence = "low"
        reasons.append("样本数不足，结论只能作为观察")
    elif trade_count < 80:
        confidence = "medium"
        reasons.append("样本数中等，需要继续滚动验证")
    else:
        confidence = "high"
        reasons.append("样本数较充足，可作为参数调整依据")

    if trade_count == 0:
        status = "inactive"
        summary = "规则当前没有触发样本"
        suggestions.append("检查入场条件是否过严，或等待更多市场样本")
    elif avg_return > 0.01 and profit_factor >= 1.5 and win_rate >= 0.55:
        status = "promote"
        summary = "规则表现较好，可考虑小幅提高优先级"
        suggestions.append("保持当前参数，扩大样本后再评估是否提高仓位")
    elif avg_return > 0 and profit_factor >= 1.0:
        status = "observe"
        summary = "规则有正期望，但优势不强"
        suggestions.append("继续观察，优先优化入场过滤而不是放大仓位")
    elif avg_return <= 0 or profit_factor < 1.0:
        status = "reduce"
        summary = "规则期望偏弱，需要收紧或降权"
        suggestions.append("降低规则优先级或仓位，复盘亏损样本的共同特征")
    else:
        status = "observe"
        summary = "规则表现中性，暂不调整"
        suggestions.append("维持测试状态，等待更多样本")

    if trade_count > 0:
        if avg_mfe > abs(avg_mae) * 1.5 and avg_return <= 0:
            suggestions.append("MFE 明显高于收益，考虑更早止盈或更紧跟踪止盈")
        if abs(avg_mae) > 0.04:
            suggestions.append("平均不利波动偏大，考虑收紧止损或降低单笔仓位")
        if win_rate < 0.45 and avg_return > 0:
            suggestions.append("胜率偏低但期望为正，保留盈亏比优势，避免过早止盈")
        if win_rate >= 0.6 and avg_return <= 0.005:
            suggestions.append("胜率尚可但收益偏薄，检查止盈空间和交易成本")

    metrics = {
        "trade_count": trade_count,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "profit_factor": profit_factor,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "score": score,
    }
    parameter_suggestions = _base_parameter_suggestions(
        rule_id=item.rule_id,
        status=status,
        confidence=confidence,
        trade_count=trade_count,
        win_rate=win_rate,
        avg_return=avg_return,
        profit_factor=profit_factor,
        avg_mfe=avg_mfe,
        avg_mae=avg_mae,
    )
    parameter_suggestions.extend(
        _rule_specific_parameter_suggestions(
            rule_id=item.rule_id,
            status=status,
            confidence=confidence,
            trade_count=trade_count,
            win_rate=win_rate,
            avg_return=avg_return,
            profit_factor=profit_factor,
        )
    )
    reason_text = (
        f"{trade_count} 笔，胜率 {_pct(win_rate)}，平均收益 {_pct(avg_return)}，"
        f"盈亏因子 {profit_factor:.2f}"
    )
    reasons.insert(0, reason_text)

    return RuleDiagnostic(
        rule_id=item.rule_id,
        status=status,
        confidence=confidence,
        summary=summary,
        reasons=reasons,
        suggestions=suggestions,
        parameter_suggestions=parameter_suggestions,
        metrics=metrics,
    )


def diagnose_rule_performances(items: list[Any]) -> list[RuleDiagnostic]:
    return [diagnose_rule_performance(item) for item in items]
