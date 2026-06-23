from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RuleDiagnostic:
    rule_id: str
    status: str
    confidence: str
    summary: str
    reasons: list[str]
    suggestions: list[str]
    metrics: dict[str, float | int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _float(value: Any) -> float:
    return float(value or 0)


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


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
        metrics=metrics,
    )


def diagnose_rule_performances(items: list[Any]) -> list[RuleDiagnostic]:
    return [diagnose_rule_performance(item) for item in items]
