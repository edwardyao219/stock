from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.review.repository import (
    insert_review_report,
    upsert_parameter_recommendations,
)
from services.engine.review.rule_diagnostics import ParameterSuggestion
from services.shared.database import SessionLocal
from services.shared.models import PaperTradeReview


@dataclass(frozen=True)
class LearningInsight:
    scope_type: str
    scope_value: str
    sample_count: int
    avg_return: float
    avg_giveback: float
    verdict_counts: dict[str, int]
    summary: str
    suggestions: list[ParameterSuggestion]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["suggestions"] = [item.to_dict() for item in self.suggestions]
        return data


def _float(value: Decimal | None) -> float:
    return float(value or 0)


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _confidence_guardrail(sample_count: int) -> list[str]:
    guardrails = ["只基于纸面实盘复盘样本，不直接应用到实盘"]
    if sample_count < 10:
        guardrails.append("样本不足10笔，只允许作为观察假设")
    return guardrails


def _build_insight(
    *,
    scope_type: str,
    scope_value: str,
    reviews: list[PaperTradeReview],
) -> LearningInsight:
    sample_count = len(reviews)
    returns = [_float(item.pnl_pct) for item in reviews]
    givebacks = [_float(item.giveback_pct) for item in reviews]
    verdict_counts: dict[str, int] = {}
    for review in reviews:
        verdict_counts[review.verdict] = verdict_counts.get(review.verdict, 0) + 1
    avg_return = _avg(returns)
    avg_giveback = _avg(givebacks)
    avg_mfe = _avg([_float(item.mfe_pct) for item in reviews])
    avg_mae = _avg([_float(item.mae_pct) for item in reviews])
    avg_holding_days = _avg([float(item.holding_days or 0) for item in reviews])
    suggestions = _suggestions(
        scope_type=scope_type,
        scope_value=scope_value,
        sample_count=sample_count,
        avg_return=avg_return,
        avg_giveback=avg_giveback,
        avg_mfe=avg_mfe,
        avg_mae=avg_mae,
        avg_holding_days=avg_holding_days,
        verdict_counts=verdict_counts,
    )
    summary = (
        f"{scope_type}:{scope_value} 样本{sample_count}笔，"
        f"平均收益{avg_return:.2%}，平均回吐{avg_giveback:.2%}，"
        f"结论分布{verdict_counts}"
    )
    return LearningInsight(
        scope_type=scope_type,
        scope_value=scope_value,
        sample_count=sample_count,
        avg_return=avg_return,
        avg_giveback=avg_giveback,
        verdict_counts=verdict_counts,
        summary=summary,
        suggestions=suggestions,
    )


def _suggestions(
    *,
    scope_type: str,
    scope_value: str,
    sample_count: int,
    avg_return: float,
    avg_giveback: float,
    avg_mfe: float,
    avg_mae: float,
    avg_holding_days: float,
    verdict_counts: dict[str, int],
) -> list[ParameterSuggestion]:
    guardrails = _confidence_guardrail(sample_count)
    suggestions: list[ParameterSuggestion] = []
    if sample_count < 3:
        return suggestions

    missed_exit_rate = verdict_counts.get("missed_exit", 0) / sample_count
    giveback_rate = verdict_counts.get("profit_giveback", 0) / sample_count
    bad_entry_rate = verdict_counts.get("bad_entry_or_stop", 0) / sample_count
    healthy_rate = verdict_counts.get("healthy_trade", 0) / sample_count

    if avg_giveback >= 0.03 or missed_exit_rate >= 0.25 or giveback_rate >= 0.35:
        suggestions.append(
            ParameterSuggestion(
                target_type="exit_policy",
                target_name="learned_profit_protection",
                action="test_tighter_trailing_from_reviews",
                priority="high" if sample_count >= 10 else "medium",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="复盘样本显示浮盈回吐或错过卖点偏多，应优先测试更紧的跟踪止盈。",
                current={
                    "sample_count": sample_count,
                    "avg_giveback": avg_giveback,
                    "missed_exit_rate": missed_exit_rate,
                    "giveback_rate": giveback_rate,
                },
                proposed={
                    "trailing_drawdown_pct_multiplier": 0.85,
                    "take_profit_1_r_multiplier": 0.9,
                },
                guardrails=guardrails + ["必须观察盈亏比是否被过度压低"],
            )
        )

    if avg_return <= 0 and bad_entry_rate >= 0.25:
        suggestions.append(
            ParameterSuggestion(
                target_type="entry_filter",
                target_name="learned_entry_quality",
                action="tighten_entry_or_reduce_priority",
                priority="high",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="复盘样本显示亏损主要来自买点质量或止损触发，应先收紧入场过滤。",
                current={
                    "sample_count": sample_count,
                    "avg_return": avg_return,
                    "bad_entry_rate": bad_entry_rate,
                    "avg_mae": avg_mae,
                },
                proposed={
                    "priority_score_delta": -3,
                    "require_extra_confirmation": True,
                    "position_size_pct_multiplier": 0.8,
                    "candidate_gap_up_pct_max": 0.04 if scope_type in {"rule", "signal"} else None,
                },
                guardrails=guardrails + ["优先验证是否为高位放量追涨失败，不要简单扩大止损"],
            )
        )

    if avg_return < 0 and avg_mae <= -0.03:
        suggestions.append(
            ParameterSuggestion(
                target_type="exit_policy",
                target_name="learned_initial_stop",
                action="test_tighter_stop_from_reviews",
                priority="high" if sample_count >= 10 else "medium",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="复盘显示亏损样本的不利波动偏大，应测试更紧的初始止损和更低仓位版本。",
                current={
                    "sample_count": sample_count,
                    "avg_return": avg_return,
                    "avg_mae": avg_mae,
                },
                proposed={
                    "max_stop_loss_pct_multiplier": 0.85,
                    "position_size_pct_multiplier": 0.85,
                },
                guardrails=guardrails + ["若被频繁洗出，说明入场触发而不是止损距离需要重做"],
            )
        )

    if avg_mfe >= 0.05 and avg_return <= avg_mfe * 0.25:
        suggestions.append(
            ParameterSuggestion(
                target_type="exit_policy",
                target_name="learned_profit_capture",
                action="test_stage_profit_and_trailing",
                priority="medium",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="复盘显示出现过较好浮盈但最终留存不足，应测试分段止盈和更主动的回撤保护。",
                current={
                    "sample_count": sample_count,
                    "avg_return": avg_return,
                    "avg_mfe": avg_mfe,
                    "avg_giveback": avg_giveback,
                },
                proposed={
                    "take_profit_1_r_multiplier": 0.85,
                    "trailing_drawdown_pct_multiplier": 0.9,
                },
                guardrails=guardrails + ["不能为了提高胜率牺牲所有大赚样本"],
            )
        )

    if avg_return > 0 and healthy_rate >= 0.6 and sample_count >= 10:
        suggestions.append(
            ParameterSuggestion(
                target_type="risk_profile",
                target_name="learned_position_sizing",
                action="test_small_increase_after_stable_reviews",
                priority="medium",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="复盘样本表现稳定且健康交易占比较高，可在纸面环境小幅提高候选优先级和仓位。",
                current={
                    "sample_count": sample_count,
                    "avg_return": avg_return,
                    "healthy_rate": healthy_rate,
                    "avg_holding_days": avg_holding_days,
                },
                proposed={
                    "priority_score_delta": 2,
                    "position_size_pct_multiplier": 1.05,
                },
                guardrails=guardrails + ["只允许纸面验证小步放大，不能直接进入实盘放大"],
            )
        )

    return suggestions


def _load_reviews(db: Session, report_date: date) -> list[PaperTradeReview]:
    stmt = (
        select(PaperTradeReview)
        .where(PaperTradeReview.exit_date <= report_date)
        .order_by(PaperTradeReview.exit_date, PaperTradeReview.id)
    )
    return list(db.execute(stmt).scalars())


def learn_from_paper_trade_reviews(db: Session, report_date: str) -> list[LearningInsight]:
    parsed_date = date.fromisoformat(report_date)
    reviews = _load_reviews(db, parsed_date)
    insights: list[LearningInsight] = []

    by_rule: dict[str, list[PaperTradeReview]] = {}
    by_sector: dict[str, list[PaperTradeReview]] = {}
    by_signal: dict[str, list[PaperTradeReview]] = {}
    by_exit: dict[str, list[PaperTradeReview]] = {}

    for review in reviews:
        by_rule.setdefault(review.rule_id, []).append(review)
        by_sector.setdefault(review.sector_code or "unknown", []).append(review)
        by_exit.setdefault(review.exit_reason, []).append(review)
        for tag in (review.signal_tags_json or {}).get("items", []):
            by_signal.setdefault(str(tag), []).append(review)

    for scope_type, groups in [
        ("rule", by_rule),
        ("sector", by_sector),
        ("signal", by_signal),
        ("exit_reason", by_exit),
    ]:
        for scope_value, items in groups.items():
            insights.append(
                _build_insight(
                    scope_type=scope_type,
                    scope_value=scope_value,
                    reviews=items,
                )
            )

    return sorted(insights, key=lambda item: (item.scope_type, item.scope_value))


def _render_report(report_date: str, insights: list[LearningInsight]) -> str:
    if not insights:
        return f"# 纸面交易学习报告 {report_date}\n\n暂无复盘样本。"
    lines = [f"# 纸面交易学习报告 {report_date}", ""]
    for insight in insights:
        lines.append(f"## {insight.scope_type}:{insight.scope_value}")
        lines.append(f"- {insight.summary}")
        for suggestion in insight.suggestions:
            lines.append(f"- 参数建议：{suggestion.rationale}")
        lines.append("")
    return "\n".join(lines)


def persist_paper_learning_report(db: Session, report_date: str) -> int:
    db.flush()
    insights = learn_from_paper_trade_reviews(db, report_date)
    suggestions = [item.to_dict() for insight in insights for item in insight.suggestions]
    insert_review_report(
        db,
        report_date=report_date,
        report_type="paper_learning_review",
        scope="paper",
        generator="mechanical",
        content_md=_render_report(report_date, insights),
        metrics_json={"insights": [item.to_dict() for item in insights]},
    )
    return upsert_parameter_recommendations(
        db,
        report_date=report_date,
        suggestions=suggestions,
        source_report_type="paper_learning_review",
    )


def generate_paper_learning_report(report_date: str) -> int:
    with SessionLocal() as db:
        changed = persist_paper_learning_report(db, report_date)
        db.commit()
        return changed
