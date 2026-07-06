from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.review.repository import insert_review_report, upsert_parameter_recommendations
from services.engine.review.rule_diagnostics import ParameterSuggestion
from services.shared.database import SessionLocal
from services.shared.models import BacktestTradeRecord, Security


@dataclass(frozen=True)
class BacktestLearningInsight:
    scope_type: str
    scope_value: str
    rule_id: str
    sample_count: int
    distinct_symbols: int
    distinct_signal_months: int
    signal_span_days: int
    top_symbol_share: float
    evidence_quality: str
    positive_learning_allowed: bool
    train_sample_count: int
    validation_sample_count: int
    train_avg_return: float
    validation_avg_return: float
    train_win_rate: float
    validation_win_rate: float
    train_profit_factor: float
    validation_profit_factor: float
    train_total_return: float
    validation_total_return: float
    out_of_sample_passed: bool
    out_of_sample_status: str
    win_rate: float
    avg_return: float
    profit_factor: float
    max_drawdown: float
    return_stability: float
    avg_mfe: float
    avg_mae: float
    summary: str
    suggestions: list[ParameterSuggestion]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["suggestions"] = [item.to_dict() for item in self.suggestions]
        return data


@dataclass(frozen=True)
class ReturnMetrics:
    sample_count: int
    avg_return: float
    win_rate: float
    profit_factor: float
    total_return: float


@dataclass(frozen=True)
class OutOfSampleAudit:
    train: ReturnMetrics
    validation: ReturnMetrics
    passed: bool
    status: str
    guardrails: list[str]


def _float(value: Decimal | None) -> float:
    return float(value or 0)


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            worst = min(worst, equity / peak - 1.0)
    return worst


def _profit_factor(values: list[float]) -> float:
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return gross_profit / gross_loss if gross_loss else gross_profit


def _return_stability(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _avg(values)
    if mean == 0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = variance ** 0.5
    if std == 0:
        return abs(mean)
    return abs(mean) / std


def _return_metrics(values: list[float]) -> ReturnMetrics:
    sample_count = len(values)
    return ReturnMetrics(
        sample_count=sample_count,
        avg_return=_avg(values),
        win_rate=sum(1 for value in values if value > 0) / sample_count
        if sample_count
        else 0.0,
        profit_factor=_profit_factor(values),
        total_return=sum(values),
    )


def _split_train_validation(
    trades: list[BacktestTradeRecord],
) -> tuple[list[BacktestTradeRecord], list[BacktestTradeRecord]]:
    if len(trades) < 10:
        return trades, []

    ordered = sorted(
        trades,
        key=lambda item: (
            item.signal_date or date.min,
            item.symbol,
            item.id or 0,
        ),
    )
    validation_count = max(3, ceil(len(ordered) * 0.3))
    validation_count = min(validation_count, len(ordered) - 1)
    return ordered[:-validation_count], ordered[-validation_count:]


def _profit_factor_passes(metrics: ReturnMetrics, threshold: float) -> bool:
    if metrics.sample_count == 0:
        return False
    if metrics.win_rate == 1.0 and metrics.avg_return > 0:
        return True
    return metrics.profit_factor >= threshold


def _out_of_sample_audit(trades: list[BacktestTradeRecord]) -> OutOfSampleAudit:
    train_trades, validation_trades = _split_train_validation(trades)
    train = _return_metrics([_float(item.pnl_pct) for item in train_trades])
    validation = _return_metrics([_float(item.pnl_pct) for item in validation_trades])

    guardrails: list[str] = []
    if validation.sample_count < 3:
        return OutOfSampleAudit(
            train=train,
            validation=validation,
            passed=False,
            status="insufficient",
            guardrails=["样本外验证不足3笔，正向学习只允许观察"],
        )
    if train.sample_count < 7:
        return OutOfSampleAudit(
            train=train,
            validation=validation,
            passed=False,
            status="insufficient",
            guardrails=["训练段样本不足7笔，不能用少量历史样本拟合阈值"],
        )

    if train.avg_return <= 0:
        guardrails.append("训练段平均收益未转正")
    if validation.avg_return <= 0:
        guardrails.append("样本外验证平均收益未转正")
    if validation.win_rate < 0.45:
        guardrails.append("样本外验证胜率低于45%")
    if not _profit_factor_passes(validation, 1.05):
        guardrails.append("样本外验证盈亏因子不足1.05")

    return OutOfSampleAudit(
        train=train,
        validation=validation,
        passed=not guardrails,
        status="passed" if not guardrails else "failed",
        guardrails=guardrails,
    )


def _breadth_metrics(trades: list[BacktestTradeRecord]) -> dict[str, float | int]:
    symbol_counts = Counter(item.symbol for item in trades)
    signal_dates = sorted(
        item.signal_date for item in trades if item.signal_date is not None
    )
    distinct_signal_months = len({(item.year, item.month) for item in signal_dates})
    signal_span_days = (signal_dates[-1] - signal_dates[0]).days if len(signal_dates) > 1 else 0
    top_symbol_share = (
        max(symbol_counts.values()) / len(trades) if trades and symbol_counts else 0.0
    )
    return {
        "distinct_symbols": len(symbol_counts),
        "distinct_signal_months": distinct_signal_months,
        "signal_span_days": signal_span_days,
        "top_symbol_share": round(top_symbol_share, 4),
    }


def _guardrails(sample_count: int) -> list[str]:
    guardrails = [
        "只来自历史回归，不直接代表实盘可执行优势",
        "必须结合纸面实盘样本继续验证",
    ]
    if sample_count < 10:
        guardrails.append("样本不足10笔，只允许降权或观察，不允许放大仓位")
    return guardrails


def _breadth_guardrails(
    *,
    scope_type: str,
    sample_count: int,
    distinct_symbols: int,
    distinct_signal_months: int,
    signal_span_days: int,
    top_symbol_share: float,
) -> list[str]:
    guardrails: list[str] = []
    if sample_count < 8:
        guardrails.append("样本少于8笔，正向结论容易漂移")
    if scope_type == "symbol":
        if distinct_signal_months < 3:
            guardrails.append("单票样本跨月不足3个月")
        if signal_span_days < 90:
            guardrails.append("单票样本时间跨度不足90天")
    elif scope_type == "sector":
        if distinct_symbols < 3:
            guardrails.append("行业样本股票覆盖不足3只")
        if distinct_signal_months < 3:
            guardrails.append("行业样本跨月不足3个月")
        if signal_span_days < 90:
            guardrails.append("行业样本时间跨度不足90天")
        if top_symbol_share > 0.55:
            guardrails.append("样本被少数股票主导")
    elif scope_type == "rule":
        if distinct_symbols < 5:
            guardrails.append("规则样本股票覆盖不足5只")
        if distinct_signal_months < 4:
            guardrails.append("规则样本跨月不足4个月")
        if signal_span_days < 120:
            guardrails.append("规则样本时间跨度不足120天")
        if top_symbol_share > 0.4:
            guardrails.append("规则样本集中度过高")
    return guardrails


def _positive_learning_allowed(
    *,
    scope_type: str,
    sample_count: int,
    distinct_symbols: int,
    distinct_signal_months: int,
    signal_span_days: int,
    top_symbol_share: float,
) -> bool:
    if sample_count < 10:
        return False
    if scope_type == "symbol":
        return distinct_signal_months >= 4 and signal_span_days >= 120
    if scope_type == "sector":
        return (
            distinct_symbols >= 3
            and distinct_signal_months >= 4
            and signal_span_days >= 120
            and top_symbol_share <= 0.55
        )
    if scope_type == "rule":
        return (
            distinct_symbols >= 5
            and distinct_signal_months >= 4
            and signal_span_days >= 120
            and top_symbol_share <= 0.4
        )
    return False


def _evidence_quality(
    *,
    scope_type: str,
    sample_count: int,
    distinct_symbols: int,
    distinct_signal_months: int,
    signal_span_days: int,
    top_symbol_share: float,
) -> str:
    if sample_count < 5:
        return "too_small"
    if _positive_learning_allowed(
        scope_type=scope_type,
        sample_count=sample_count,
        distinct_symbols=distinct_symbols,
        distinct_signal_months=distinct_signal_months,
        signal_span_days=signal_span_days,
        top_symbol_share=top_symbol_share,
    ):
        return "broad"
    if (
        sample_count >= 8
        and distinct_signal_months >= 2
        and signal_span_days >= 45
        and top_symbol_share <= 0.75
    ):
        return "mixed"
    return "concentrated"


def _robustness_score(
    *,
    avg_return: float,
    profit_factor: float,
    max_drawdown: float,
    return_stability: float,
    distinct_signal_months: int,
    top_symbol_share: float,
) -> float:
    return (
        avg_return * 220.0
        + profit_factor * 12.0
        + return_stability * 8.0
        + distinct_signal_months * 2.5
        + (1.0 + max_drawdown) * 20.0
        - top_symbol_share * 12.0
    )


def _sample_breadth_notes(
    *,
    scope_type: str,
    sample_count: int,
    distinct_symbols: int,
    distinct_signal_months: int,
    signal_span_days: int,
    top_symbol_share: float,
) -> list[str]:
    notes = _breadth_guardrails(
        scope_type=scope_type,
        sample_count=sample_count,
        distinct_symbols=distinct_symbols,
        distinct_signal_months=distinct_signal_months,
        signal_span_days=signal_span_days,
        top_symbol_share=top_symbol_share,
    )
    if not notes:
        return []
    if scope_type == "symbol":
        return ["单票样本集中，只能做观察学习"] + notes
    if scope_type == "sector":
        return ["行业样本分布偏窄，只能小步验证"] + notes
    if scope_type == "rule":
        return ["规则样本覆盖不够广，只能作为假设"] + notes
    return notes


def _suggestions(
    *,
    rule_id: str,
    scope_type: str,
    scope_value: str,
    positive_learning_allowed: bool,
    out_of_sample_status: str,
    out_of_sample_guardrails: list[str],
    train_sample_count: int,
    validation_sample_count: int,
    train_avg_return: float,
    validation_avg_return: float,
    validation_win_rate: float,
    validation_profit_factor: float,
    sample_count: int,
    distinct_symbols: int,
    distinct_signal_months: int,
    signal_span_days: int,
    top_symbol_share: float,
    win_rate: float,
    avg_return: float,
    profit_factor: float,
    avg_mfe: float,
    avg_mae: float,
) -> list[ParameterSuggestion]:
    if sample_count < 5:
        return []

    guardrails = _guardrails(sample_count) + _sample_breadth_notes(
        scope_type=scope_type,
        sample_count=sample_count,
        distinct_symbols=distinct_symbols,
        distinct_signal_months=distinct_signal_months,
        signal_span_days=signal_span_days,
        top_symbol_share=top_symbol_share,
    )
    guardrails += out_of_sample_guardrails
    suggestions: list[ParameterSuggestion] = []
    learned_scope_type = scope_type
    learned_scope_value = scope_value

    if out_of_sample_status == "failed":
        suggestions.append(
            ParameterSuggestion(
                target_type="entry_filter",
                target_name="backtest_validation_quality",
                action="observe_or_require_fresh_confirmation",
                priority="high",
                scope_type=learned_scope_type,
                scope_value=learned_scope_value,
                rationale=(
                    f"{rule_id} 在 {scope_type}:{scope_value} 的训练段表现尚可，"
                    "但最近样本外验证转弱，不能把旧样本收益直接学成正向规则。"
                ),
                current={
                    "rule_id": rule_id,
                    "sample_count": sample_count,
                    "train_sample_count": train_sample_count,
                    "validation_sample_count": validation_sample_count,
                    "train_avg_return": train_avg_return,
                    "validation_avg_return": validation_avg_return,
                    "validation_win_rate": validation_win_rate,
                    "validation_profit_factor": validation_profit_factor,
                },
                proposed={
                    "priority_score_delta": -3,
                    "require_extra_confirmation": True,
                    "source_rule_id": rule_id,
                },
                guardrails=guardrails + ["不能用训练段收益抵消最近样本外失败"],
            )
        )

    if avg_return <= 0 or win_rate < 0.4:
        suggestions.append(
            ParameterSuggestion(
                target_type="entry_filter",
                target_name="backtest_scope_quality",
                action="reduce_priority_or_require_confirmation",
                priority="high" if sample_count >= 10 else "medium",
                scope_type=learned_scope_type,
                scope_value=learned_scope_value,
                rationale=(
                    f"{rule_id} 在 {scope_type}:{scope_value} 的历史回归偏弱，"
                    "后续同类计划应降权并要求额外确认，避免把不适配板块的策略硬套。"
                ),
                current={
                    "rule_id": rule_id,
                    "sample_count": sample_count,
                    "win_rate": win_rate,
                    "avg_return": avg_return,
                    "avg_mae": avg_mae,
                },
                proposed={
                    "priority_score_delta": -4 if sample_count >= 10 else -2,
                    "position_size_pct_multiplier": 0.75 if sample_count >= 10 else 0.85,
                    "require_extra_confirmation": True,
                    "source_rule_id": rule_id,
                },
                guardrails=guardrails + ["优先检查是否高位放量、上影线或题材兑现导致失效"],
            )
        )

    if profit_factor < 1.0 and avg_return > 0:
        suggestions.append(
            ParameterSuggestion(
                target_type="risk_profile",
                target_name="backtest_edge_quality",
                action="reduce_priority_or_require_confirmation",
                priority="medium",
                scope_type=learned_scope_type,
                scope_value=learned_scope_value,
                rationale=(
                    f"{rule_id} 在 {scope_type}:{scope_value} 的盈亏因子不足，"
                    "说明少数盈利样本还不够覆盖亏损回撤，先降权而不是加仓。"
                ),
                current={
                    "rule_id": rule_id,
                    "sample_count": sample_count,
                    "profit_factor": profit_factor,
                    "avg_return": avg_return,
                },
                proposed={
                    "priority_score_delta": -2,
                    "position_size_pct_multiplier": 0.9,
                    "require_extra_confirmation": True,
                    "source_rule_id": rule_id,
                },
                guardrails=guardrails + ["不能因为平均收益为正就忽略盈亏因子"],
            )
        )

    if avg_mfe >= 0.06 and avg_return <= avg_mfe * 0.25:
        suggestions.append(
            ParameterSuggestion(
                target_type="exit_policy",
                target_name="backtest_profit_giveback",
                action="test_earlier_profit_capture",
                priority="medium",
                scope_type=learned_scope_type,
                scope_value=learned_scope_value,
                rationale=(
                    f"{rule_id} 在 {scope_type}:{scope_value} 出现过较高浮盈，"
                    "但最终收益留存不足，应测试更主动的分段止盈或跟踪止盈。"
                ),
                current={
                    "rule_id": rule_id,
                    "sample_count": sample_count,
                    "avg_return": avg_return,
                    "avg_mfe": avg_mfe,
                    "avg_mae": avg_mae,
                },
                proposed={
                    "take_profit_1_r_multiplier": 0.9,
                    "trailing_drawdown_pct_multiplier": 0.9,
                    "source_rule_id": rule_id,
                },
                guardrails=guardrails + ["不能为了提高胜率牺牲所有大赚样本"],
            )
        )

    if (
        positive_learning_allowed
        and avg_return >= 0.015
        and win_rate >= 0.58
        and profit_factor >= 1.2
    ):
        suggestions.append(
            ParameterSuggestion(
                target_type="entry_filter",
                target_name="backtest_scope_fit",
                action="keep_or_test_small_priority_increase",
                priority="medium",
                scope_type=learned_scope_type,
                scope_value=learned_scope_value,
                rationale=(
                    f"{rule_id} 在 {scope_type}:{scope_value} 的历史回归相对适配，"
                    "可保留为同类环境下的候选，但仍需纸面实盘继续验证。"
                ),
                current={
                    "rule_id": rule_id,
                    "sample_count": sample_count,
                    "win_rate": win_rate,
                    "avg_return": avg_return,
                },
                proposed={
                    "priority_score_delta": 1,
                    "position_size_pct_multiplier": 1.0,
                    "source_rule_id": rule_id,
                },
                guardrails=guardrails + ["只提升排序信心，不自动放大仓位"],
            )
        )

    if (
        positive_learning_allowed
        and avg_return >= 0.012
        and win_rate >= 0.55
        and profit_factor >= 1.15
    ):
        suggestions.append(
            ParameterSuggestion(
                target_type="time_exit",
                target_name="learned_long_horizon_hold",
                action="keep_or_test_small_priority_increase",
                priority="medium",
                scope_type=learned_scope_type,
                scope_value=learned_scope_value,
                rationale=(
                    f"{rule_id} 在 {scope_type}:{scope_value} 的历史回归显示，"
                    "这类样本往往不是一两天就结束的短线结构，更适合作为可长期跟踪的候选。"
                ),
                current={
                    "rule_id": rule_id,
                    "sample_count": sample_count,
                    "win_rate": win_rate,
                    "avg_return": avg_return,
                    "profit_factor": profit_factor,
                    "avg_mfe": avg_mfe,
                    "avg_mae": avg_mae,
                },
                proposed={
                    "max_holding_days_multiplier": 1.5,
                    "trailing_drawdown_pct_multiplier": 1.05,
                    "priority_score_delta": 1,
                    "source_rule_id": rule_id,
                },
                guardrails=guardrails + ["样本不足时只允许小步验证，不要直接把短线票当长线重仓"],
            )
        )

    return suggestions


def _candidate_label(
    scope_type: str,
    avg_return: float,
    profit_factor: float,
    max_drawdown: float,
) -> str:
    if avg_return > 0 and profit_factor >= 1.2 and max_drawdown >= -0.12:
        if scope_type == "rule":
            return "稳健规则"
        if scope_type == "sector":
            return "稳健板块"
        return "稳健单票"
    return "观察候选"


def _build_insight(
    *,
    rule_id: str,
    scope_type: str,
    scope_value: str,
    trades: list[BacktestTradeRecord],
) -> BacktestLearningInsight:
    returns = [_float(item.pnl_pct) for item in trades]
    mfe_values = [_float(item.mfe_pct) for item in trades]
    mae_values = [_float(item.mae_pct) for item in trades]
    sample_count = len(trades)
    breadth = _breadth_metrics(trades)
    distinct_symbols = int(breadth["distinct_symbols"])
    distinct_signal_months = int(breadth["distinct_signal_months"])
    signal_span_days = int(breadth["signal_span_days"])
    top_symbol_share = float(breadth["top_symbol_share"])
    evidence_quality = _evidence_quality(
        scope_type=scope_type,
        sample_count=sample_count,
        distinct_symbols=distinct_symbols,
        distinct_signal_months=distinct_signal_months,
        signal_span_days=signal_span_days,
        top_symbol_share=top_symbol_share,
    )
    breadth_learning_allowed = _positive_learning_allowed(
        scope_type=scope_type,
        sample_count=sample_count,
        distinct_symbols=distinct_symbols,
        distinct_signal_months=distinct_signal_months,
        signal_span_days=signal_span_days,
        top_symbol_share=top_symbol_share,
    )
    out_of_sample = _out_of_sample_audit(trades)
    positive_learning_allowed = breadth_learning_allowed and out_of_sample.passed
    win_rate = sum(1 for value in returns if value > 0) / sample_count if sample_count else 0.0
    avg_return = _avg(returns)
    profit_factor = _profit_factor(returns)
    max_drawdown = _max_drawdown(returns)
    return_stability = _return_stability(returns)
    avg_mfe = _avg(mfe_values)
    avg_mae = _avg(mae_values)
    suggestions = _suggestions(
        rule_id=rule_id,
        scope_type=scope_type,
        scope_value=scope_value,
        positive_learning_allowed=positive_learning_allowed,
        out_of_sample_status=out_of_sample.status,
        out_of_sample_guardrails=out_of_sample.guardrails,
        train_sample_count=out_of_sample.train.sample_count,
        validation_sample_count=out_of_sample.validation.sample_count,
        train_avg_return=out_of_sample.train.avg_return,
        validation_avg_return=out_of_sample.validation.avg_return,
        validation_win_rate=out_of_sample.validation.win_rate,
        validation_profit_factor=out_of_sample.validation.profit_factor,
        sample_count=sample_count,
        distinct_symbols=distinct_symbols,
        distinct_signal_months=distinct_signal_months,
        signal_span_days=signal_span_days,
        top_symbol_share=top_symbol_share,
        win_rate=win_rate,
        avg_return=avg_return,
        profit_factor=profit_factor,
        avg_mfe=avg_mfe,
        avg_mae=avg_mae,
    )
    robustness_score = _robustness_score(
        avg_return=avg_return,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        return_stability=return_stability,
        distinct_signal_months=distinct_signal_months,
        top_symbol_share=top_symbol_share,
    )
    candidate_label = _candidate_label(
        scope_type=scope_type,
        avg_return=avg_return,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
    )
    summary = (
        f"{rule_id} {scope_type}:{scope_value} 样本{sample_count}笔，"
        f"覆盖{distinct_symbols}只票，跨{distinct_signal_months}个月，"
        f"跨度{signal_span_days}天，集中度{top_symbol_share:.0%}，"
        f"证据{evidence_quality}，正向可学习{'是' if positive_learning_allowed else '否'}，"
        f"样本外{out_of_sample.status}，训练{out_of_sample.train.sample_count}笔"
        f"均值{out_of_sample.train.avg_return:.2%}，"
        f"验证{out_of_sample.validation.sample_count}笔"
        f"均值{out_of_sample.validation.avg_return:.2%}，"
        f"胜率{win_rate:.2%}，平均收益{avg_return:.2%}，盈亏因子{profit_factor:.2f}，"
        f"最大回撤{max_drawdown:.2%}，稳定度{return_stability:.2f}，"
        f"平均浮盈{avg_mfe:.2%}，平均不利波动{avg_mae:.2%}，"
        f"{candidate_label}分{robustness_score:.1f}"
    )
    return BacktestLearningInsight(
        scope_type=scope_type,
        scope_value=scope_value,
        rule_id=rule_id,
        sample_count=sample_count,
        distinct_symbols=distinct_symbols,
        distinct_signal_months=distinct_signal_months,
        signal_span_days=signal_span_days,
        top_symbol_share=top_symbol_share,
        evidence_quality=evidence_quality,
        positive_learning_allowed=positive_learning_allowed,
        train_sample_count=out_of_sample.train.sample_count,
        validation_sample_count=out_of_sample.validation.sample_count,
        train_avg_return=out_of_sample.train.avg_return,
        validation_avg_return=out_of_sample.validation.avg_return,
        train_win_rate=out_of_sample.train.win_rate,
        validation_win_rate=out_of_sample.validation.win_rate,
        train_profit_factor=out_of_sample.train.profit_factor,
        validation_profit_factor=out_of_sample.validation.profit_factor,
        train_total_return=out_of_sample.train.total_return,
        validation_total_return=out_of_sample.validation.total_return,
        out_of_sample_passed=out_of_sample.passed,
        out_of_sample_status=out_of_sample.status,
        win_rate=win_rate,
        avg_return=avg_return,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        return_stability=return_stability,
        avg_mfe=avg_mfe,
        avg_mae=avg_mae,
        summary=summary,
        suggestions=suggestions,
    )


def _load_security_map(db: Session, symbols: Iterable[str]) -> dict[str, Security]:
    stmt = select(Security).where(Security.symbol.in_(set(symbols)))
    return {item.symbol: item for item in db.execute(stmt).scalars()}


def learn_from_backtest_trades(
    db: Session,
    report_date: str,
    *,
    min_samples: int = 5,
) -> list[BacktestLearningInsight]:
    parsed_date = date.fromisoformat(report_date)
    trades = list(
        db.execute(
            select(BacktestTradeRecord)
            .where(BacktestTradeRecord.run_date == parsed_date)
            .order_by(BacktestTradeRecord.rule_id, BacktestTradeRecord.symbol)
        ).scalars()
    )
    if not trades:
        return []

    securities = _load_security_map(db, [item.symbol for item in trades])
    grouped: dict[tuple[str, str, str], list[BacktestTradeRecord]] = defaultdict(list)
    for trade in trades:
        security = securities.get(trade.symbol)
        sector = security.industry if security and security.industry else "unknown"
        grouped[(trade.rule_id, "sector", sector)].append(trade)
        grouped[(trade.rule_id, "symbol", trade.symbol)].append(trade)

    insights = [
        _build_insight(
            rule_id=rule_id,
            scope_type=scope_type,
            scope_value=scope_value,
            trades=items,
        )
        for (rule_id, scope_type, scope_value), items in grouped.items()
        if len(items) >= min_samples
    ]
    return sorted(
        insights,
        key=lambda item: (item.rule_id, item.scope_type, item.scope_value),
    )


def _render_report(report_date: str, insights: list[BacktestLearningInsight]) -> str:
    if not insights:
        return f"# 回归学习报告 {report_date}\n\n暂无可学习回归样本。"
    lines = [f"# 回归学习报告 {report_date}", ""]
    ranked_insights = sorted(
        insights,
        key=lambda item: (
            item.avg_return <= 0,
            -(item.avg_return or 0),
            -(item.profit_factor or 0),
            item.max_drawdown,
        ),
    )
    for insight in ranked_insights[:2]:
        lines.append(f"## {insight.rule_id} {insight.scope_type}:{insight.scope_value}")
        lines.append(f"- {insight.summary}")
        if not insight.positive_learning_allowed:
            if insight.out_of_sample_status != "passed":
                lines.append(
                    "- 说明：样本外验证未通过或样本不足，正向结论只做观察，不放大权重。"
                )
            else:
                lines.append("- 说明：样本分散度不够，正向结论只做观察，不放大权重。")
        for suggestion in insight.suggestions:
            lines.append(f"- 参数建议：{suggestion.rationale}")
        lines.append("")
    if len(ranked_insights) > 2:
        lines.append("## 其余样本")
        lines.append(f"- 已省略 {len(ranked_insights) - 2} 个次级候选，避免学习目标过散。")
    return "\n".join(lines)


def persist_backtest_learning_report(db: Session, report_date: str) -> int:
    db.flush()
    insights = learn_from_backtest_trades(db, report_date)
    suggestions = [item.to_dict() for insight in insights for item in insight.suggestions]
    insert_review_report(
        db,
        report_date=report_date,
        report_type="backtest_learning_review",
        scope="backtest",
        generator="mechanical",
        content_md=_render_report(report_date, insights),
        metrics_json={"insights": [item.to_dict() for item in insights]},
    )
    return upsert_parameter_recommendations(
        db,
        report_date=report_date,
        suggestions=suggestions,
        source_report_type="backtest_learning_review",
    )


def generate_backtest_learning_report(report_date: str) -> int:
    with SessionLocal() as db:
        changed = persist_backtest_learning_report(db, report_date)
        db.commit()
        return changed
