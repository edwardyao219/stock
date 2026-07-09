from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.shared.models import (
    BacktestTradeRecord,
    ParameterRecommendation,
    ReviewReport,
    Security,
)


@dataclass(frozen=True)
class StrategyFitMetrics:
    rule_id: str
    scope_type: str
    scope_value: str
    trade_count: int
    win_rate: float
    avg_return: float
    profit_factor: float
    max_drawdown: float
    return_stability: float
    avg_mfe: float
    avg_mae: float
    evidence_quality: str | None
    positive_learning_allowed: bool | None
    train_sample_count: int | None
    validation_sample_count: int | None
    train_avg_return: float | None
    validation_avg_return: float | None
    train_win_rate: float | None
    validation_win_rate: float | None
    train_profit_factor: float | None
    validation_profit_factor: float | None
    train_total_return: float | None
    validation_total_return: float | None
    out_of_sample_passed: bool | None
    out_of_sample_status: str | None
    fit_status: str
    summary: str
    recommendations: list[dict]

    def to_dict(self, *, include_recommendations: bool = True) -> dict:
        payload = asdict(self)
        if not include_recommendations:
            payload["recommendations"] = []
        return payload


@dataclass(frozen=True)
class StrategyFitReport:
    report_date: str | None
    rules: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


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


def _latest_backtest_run_date(db: Session) -> date | None:
    return db.execute(select(func.max(BacktestTradeRecord.run_date))).scalar_one_or_none()


def _load_security_map(db: Session, symbols: set[str]) -> dict[str, Security]:
    if not symbols:
        return {}
    rows = db.execute(select(Security).where(Security.symbol.in_(symbols))).scalars()
    return {item.symbol: item for item in rows}


def _recommendation_payload(item: ParameterRecommendation) -> dict:
    return {
        "id": item.id,
        "priority": item.priority,
        "target_type": item.target_type,
        "target_name": item.target_name,
        "action": item.action,
        "rationale": item.rationale,
        "proposed": item.proposed_json or {},
        "status": item.status,
    }


def _recommendation_status(recommendations: list[ParameterRecommendation]) -> str:
    actions = {item.action for item in recommendations}
    target_names = {item.target_name for item in recommendations}
    if "backtest_validation_quality" in target_names:
        return "validation_failed"
    if "reduce_priority_or_require_confirmation" in actions:
        return "weak"
    if "keep_or_test_small_priority_increase" in actions:
        return "fit"
    if "backtest_profit_giveback" in target_names:
        return "profit_giveback"
    return "neutral"


def _learning_status(insight: dict | None) -> str:
    if not insight:
        return "neutral"
    if insight.get("out_of_sample_status") == "failed":
        return "validation_failed"
    if insight.get("out_of_sample_status") == "insufficient":
        return "low_sample"
    if insight.get("positive_learning_allowed") is True:
        return "fit"
    return "neutral"


def _status_label(value: str | None) -> str:
    labels = {
        "passed": "通过",
        "failed": "失败",
        "insufficient": "不足",
    }
    return labels.get(value or "", "暂无")


def _insight_float(insight: dict | None, key: str) -> float | None:
    if insight is None or insight.get(key) is None:
        return None
    return float(insight[key])


def _insight_int(insight: dict | None, key: str) -> int | None:
    if insight is None or insight.get(key) is None:
        return None
    return int(insight[key])


def _load_learning_insights(
    db: Session,
    report_date: date,
    rule_ids: set[str] | None,
) -> dict[tuple[str, str, str], dict]:
    stmt = (
        select(ReviewReport)
        .where(ReviewReport.report_date == report_date)
        .where(ReviewReport.report_type == "backtest_learning_review")
        .order_by(ReviewReport.id.desc())
        .limit(1)
    )
    report = db.execute(stmt).scalar_one_or_none()
    if report is None:
        return {}

    insights = report.metrics_json.get("insights", [])
    mapped: dict[tuple[str, str, str], dict] = {}
    for insight in insights:
        rule_id = str(insight.get("rule_id") or "")
        scope_type = str(insight.get("scope_type") or "")
        scope_value = str(insight.get("scope_value") or "")
        if not rule_id or not scope_type or not scope_value:
            continue
        if rule_ids and rule_id not in rule_ids:
            continue
        mapped[(rule_id, scope_type, scope_value)] = insight
    return mapped


def _metric_status(
    *,
    trade_count: int,
    win_rate: float,
    avg_return: float,
    profit_factor: float,
    max_drawdown: float,
    return_stability: float,
) -> str:
    if trade_count < 5:
        return "low_sample"
    if avg_return <= 0 or win_rate < 0.4:
        return "weak"
    if (
        avg_return >= 0.008
        and profit_factor >= 1.15
        and max_drawdown >= -0.18
        and return_stability >= 0.45
    ):
        return "fit"
    return "neutral"


def _robustness_score(
    *,
    avg_return: float,
    profit_factor: float,
    max_drawdown: float,
    return_stability: float,
    trade_count: int,
) -> float:
    return (
        avg_return * 240.0
        + profit_factor * 10.0
        + return_stability * 8.0
        + max(0.0, trade_count - 5) * 0.15
        + (1.0 + max_drawdown) * 18.0
    )


def _build_metrics(
    *,
    rule_id: str,
    scope_type: str,
    scope_value: str,
    trades: list[BacktestTradeRecord],
    recommendations: list[ParameterRecommendation],
    learning_insight: dict | None,
) -> StrategyFitMetrics:
    returns = [_float(item.pnl_pct) for item in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    trade_count = len(trades)
    win_rate = len(wins) / trade_count if trade_count else 0.0
    avg_return = _avg(returns)
    profit_factor = gross_profit / gross_loss if gross_loss else gross_profit
    max_drawdown = _max_drawdown(returns)
    return_stability = _return_stability(returns)
    avg_mfe = _avg([_float(item.mfe_pct) for item in trades])
    avg_mae = _avg([_float(item.mae_pct) for item in trades])
    fit_status = _recommendation_status(recommendations)
    if fit_status == "neutral":
        fit_status = _learning_status(learning_insight)
    if fit_status == "neutral":
        fit_status = _metric_status(
            trade_count=trade_count,
            win_rate=win_rate,
            avg_return=avg_return,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            return_stability=return_stability,
        )
    robustness_score = _robustness_score(
        avg_return=avg_return,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        return_stability=return_stability,
        trade_count=trade_count,
    )
    summary = (
        f"{rule_id} {scope_type}:{scope_value} 样本{trade_count}笔，"
        f"胜率{win_rate:.2%}，平均收益{avg_return:.2%}，盈亏因子{profit_factor:.2f}，"
        f"最大回撤{max_drawdown:.2%}，稳定度{return_stability:.2f}，稳健分{robustness_score:.1f}"
    )
    if learning_insight:
        summary += (
            f"，样本外{_status_label(str(learning_insight.get('out_of_sample_status') or ''))}"
            f"，训练均值{_insight_float(learning_insight, 'train_avg_return') or 0:.2%}"
            f"，验证均值{_insight_float(learning_insight, 'validation_avg_return') or 0:.2%}"
        )
    return StrategyFitMetrics(
        rule_id=rule_id,
        scope_type=scope_type,
        scope_value=scope_value,
        trade_count=trade_count,
        win_rate=win_rate,
        avg_return=avg_return,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        return_stability=return_stability,
        avg_mfe=avg_mfe,
        avg_mae=avg_mae,
        evidence_quality=str(learning_insight.get("evidence_quality"))
        if learning_insight and learning_insight.get("evidence_quality") is not None
        else None,
        positive_learning_allowed=bool(learning_insight["positive_learning_allowed"])
        if learning_insight and learning_insight.get("positive_learning_allowed") is not None
        else None,
        train_sample_count=_insight_int(learning_insight, "train_sample_count"),
        validation_sample_count=_insight_int(learning_insight, "validation_sample_count"),
        train_avg_return=_insight_float(learning_insight, "train_avg_return"),
        validation_avg_return=_insight_float(learning_insight, "validation_avg_return"),
        train_win_rate=_insight_float(learning_insight, "train_win_rate"),
        validation_win_rate=_insight_float(learning_insight, "validation_win_rate"),
        train_profit_factor=_insight_float(learning_insight, "train_profit_factor"),
        validation_profit_factor=_insight_float(learning_insight, "validation_profit_factor"),
        train_total_return=_insight_float(learning_insight, "train_total_return"),
        validation_total_return=_insight_float(learning_insight, "validation_total_return"),
        out_of_sample_passed=bool(learning_insight["out_of_sample_passed"])
        if learning_insight and learning_insight.get("out_of_sample_passed") is not None
        else None,
        out_of_sample_status=str(learning_insight.get("out_of_sample_status"))
        if learning_insight and learning_insight.get("out_of_sample_status") is not None
        else None,
        fit_status=fit_status,
        summary=summary,
        recommendations=[_recommendation_payload(item) for item in recommendations],
    )


def _load_recommendations(
    db: Session,
    report_date: date,
    rule_ids: set[str] | None,
) -> dict[tuple[str, str, str], list[ParameterRecommendation]]:
    stmt = (
        select(ParameterRecommendation)
        .where(ParameterRecommendation.report_date == report_date)
        .where(ParameterRecommendation.source_report_type == "backtest_learning_review")
        .where(ParameterRecommendation.status.in_(("pending", "approved", "applied")))
        .order_by(ParameterRecommendation.priority.desc(), ParameterRecommendation.id)
    )
    if rule_ids:
        stmt = stmt.where(ParameterRecommendation.rule_id.in_(rule_ids))
    recommendations: dict[tuple[str, str, str], list[ParameterRecommendation]] = defaultdict(list)
    for item in db.execute(stmt).scalars():
        if item.rule_id and item.scope_value:
            recommendations[(item.rule_id, item.scope_type, item.scope_value)].append(item)
    return recommendations


def load_strategy_fit_report(
    db: Session,
    *,
    report_date: str | None = None,
    rule_id: str | None = None,
    min_samples: int = 1,
    per_scope_limit: int = 20,
    include_symbols: bool = True,
    symbol: str | None = None,
    include_recommendations: bool = True,
) -> StrategyFitReport:
    parsed_date = date.fromisoformat(report_date) if report_date else _latest_backtest_run_date(db)
    if parsed_date is None:
        return StrategyFitReport(report_date=None, rules=[])

    stmt = select(BacktestTradeRecord).where(BacktestTradeRecord.run_date == parsed_date)
    if rule_id:
        stmt = stmt.where(BacktestTradeRecord.rule_id == rule_id)
    trades = list(
        db.execute(
            stmt.order_by(BacktestTradeRecord.rule_id, BacktestTradeRecord.symbol)
        ).scalars()
    )
    if not trades:
        return StrategyFitReport(report_date=parsed_date.isoformat(), rules=[])

    securities = _load_security_map(db, {item.symbol for item in trades})
    rule_ids = {item.rule_id for item in trades}
    recommendations = _load_recommendations(db, parsed_date, rule_ids)
    learning_insights = _load_learning_insights(db, parsed_date, rule_ids)

    overall: dict[str, list[BacktestTradeRecord]] = defaultdict(list)
    by_sector: dict[tuple[str, str], list[BacktestTradeRecord]] = defaultdict(list)
    by_symbol: dict[tuple[str, str], list[BacktestTradeRecord]] = defaultdict(list)
    selected_symbol = symbol.strip() if symbol else None
    should_include_symbols = include_symbols or selected_symbol is not None
    for trade in trades:
        sector = securities.get(trade.symbol).industry if securities.get(trade.symbol) else None
        sector = sector or "unknown"
        overall[trade.rule_id].append(trade)
        by_sector[(trade.rule_id, sector)].append(trade)
        if should_include_symbols and (selected_symbol is None or trade.symbol == selected_symbol):
            by_symbol[(trade.rule_id, trade.symbol)].append(trade)

    rules = []
    for current_rule_id in sorted(overall):
        overall_metric = _build_metrics(
            rule_id=current_rule_id,
            scope_type="rule",
            scope_value=current_rule_id,
            trades=overall[current_rule_id],
            recommendations=recommendations.get((current_rule_id, "rule", current_rule_id), []),
            learning_insight=learning_insights.get((current_rule_id, "rule", current_rule_id)),
        )
        sector_metrics = [
            _build_metrics(
                rule_id=current_rule_id,
                scope_type="sector",
                scope_value=scope_value,
                trades=items,
                recommendations=recommendations.get((current_rule_id, "sector", scope_value), []),
                learning_insight=learning_insights.get((current_rule_id, "sector", scope_value)),
            )
            for (group_rule_id, scope_value), items in by_sector.items()
            if group_rule_id == current_rule_id and len(items) >= min_samples
        ]
        symbol_metrics = [
            _build_metrics(
                rule_id=current_rule_id,
                scope_type="symbol",
                scope_value=scope_value,
                trades=items,
                recommendations=recommendations.get((current_rule_id, "symbol", scope_value), []),
                learning_insight=learning_insights.get((current_rule_id, "symbol", scope_value)),
            )
            for (group_rule_id, scope_value), items in by_symbol.items()
            if group_rule_id == current_rule_id and len(items) >= min_samples
        ]
        rules.append(
            {
                "rule_id": current_rule_id,
                "overall": overall_metric.to_dict(
                    include_recommendations=include_recommendations
                ),
                "sectors": [
                    item.to_dict(include_recommendations=include_recommendations)
                    for item in sorted(
                        sector_metrics,
                        key=lambda item: (item.fit_status != "weak", -item.trade_count),
                    )[:per_scope_limit]
                ],
                "symbols": [
                    item.to_dict(include_recommendations=include_recommendations)
                    for item in sorted(
                        symbol_metrics,
                        key=lambda item: (item.fit_status != "weak", -item.trade_count),
                    )[:per_scope_limit]
                ],
            }
        )

    return StrategyFitReport(report_date=parsed_date.isoformat(), rules=rules)
