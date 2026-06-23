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
from services.shared.models import PaperPosition, Security, TradePlan


@dataclass(frozen=True)
class PaperTradeMetrics:
    scope_type: str
    scope_value: str
    trade_count: int
    win_rate: float
    avg_return: float
    profit_factor: float
    avg_mfe: float
    avg_mae: float
    avg_giveback: float
    volume_trap_rate: float
    stop_loss_rate: float
    time_exit_rate: float
    avg_holding_days: float
    status: str
    confidence: str
    summary: str
    suggestions: list[str]
    parameter_suggestions: list[ParameterSuggestion]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["parameter_suggestions"] = [
            item.to_dict() for item in self.parameter_suggestions
        ]
        return data


def _float(value: Decimal | None) -> float:
    return float(value or 0)


def _holding_days(position: PaperPosition) -> int:
    if position.exit_date is None:
        return 0
    return (position.exit_date - position.entry_date).days + 1


def _mfe_pct(position: PaperPosition) -> float:
    return float(position.highest_price / position.entry_price - Decimal("1"))


def _mae_pct(position: PaperPosition) -> float:
    return float(position.lowest_price / position.entry_price - Decimal("1"))


def _profit_factor(pnl_values: list[float]) -> float:
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return gross_profit / gross_loss if gross_loss else gross_profit


def _confidence(trade_count: int) -> str:
    if trade_count < 10:
        return "low"
    if trade_count < 40:
        return "medium"
    return "high"


def _status(
    *,
    avg_return: float,
    profit_factor: float,
    win_rate: float,
    confidence: str,
) -> str:
    if confidence == "low":
        return "collect_sample"
    if avg_return > 0.01 and profit_factor >= 1.5 and win_rate >= 0.52:
        return "promote"
    if avg_return > 0 and profit_factor >= 1.0:
        return "observe"
    return "reduce"


def _base_suggestions(
    *,
    scope_type: str,
    scope_value: str,
    trade_count: int,
    win_rate: float,
    avg_return: float,
    profit_factor: float,
    avg_mfe: float,
    avg_mae: float,
    avg_giveback: float,
    stop_loss_rate: float,
    volume_trap_rate: float,
    status: str,
    confidence: str,
) -> list[ParameterSuggestion]:
    guardrails = [
        "只使用纸面实盘样本生成建议",
        "样本外继续验证后才允许提高实盘权重",
    ]
    suggestions: list[ParameterSuggestion] = []

    if trade_count < 10:
        suggestions.append(
            ParameterSuggestion(
                target_type="research_process",
                target_name="paper_sample_collection",
                action="continue_collecting",
                priority="high",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="纸面实盘样本不足，不能根据少数交易直接调整核心参数。",
                current={"trade_count": trade_count},
                proposed={"minimum_closed_trades": 10},
                guardrails=guardrails,
            )
        )

    if avg_giveback > 0.025 and avg_mfe > 0:
        suggestions.append(
            ParameterSuggestion(
                target_type="exit_policy",
                target_name="profit_giveback",
                action="test_tighter_trailing",
                priority="medium",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="纸面实盘出现过可观浮盈但最终收益回吐，优先测试更紧的跟踪止盈。",
                current={
                    "avg_mfe": avg_mfe,
                    "avg_return": avg_return,
                    "avg_giveback": avg_giveback,
                },
                proposed={"trailing_drawdown_pct_multiplier": 0.85},
                guardrails=guardrails + ["不得只按历史最优点过拟合"],
            )
        )

    if stop_loss_rate >= 0.45 or avg_mae <= -0.045:
        suggestions.append(
            ParameterSuggestion(
                target_type="entry_filter",
                target_name="adverse_excursion_control",
                action="tighten_entry_quality",
                priority="high",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="纸面实盘止损率或不利波动偏高，问题优先在买点质量和追高过滤。",
                current={"stop_loss_rate": stop_loss_rate, "avg_mae": avg_mae},
                proposed={"require_stronger_sector_or_volume_confirmation": True},
                guardrails=guardrails,
            )
        )

    if volume_trap_rate >= 0.30:
        suggestions.append(
            ParameterSuggestion(
                target_type="entry_filter",
                target_name="high_volume_chase",
                action="test_avoid_high_position_volume_spike",
                priority="high",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="纸面实盘显示高位放量后失败比例偏高，可能存在诱多或利好兑现风险。",
                current={"volume_trap_rate": volume_trap_rate},
                proposed={
                    "avoid_if_amount_percentile_ge": 80,
                    "avoid_if_distance_to_20d_high_ge": -0.03,
                },
                guardrails=guardrails + ["分钟级数据接入后再细分早盘放量和尾盘承接"],
            )
        )

    if status == "promote" and confidence in {"medium", "high"}:
        suggestions.append(
            ParameterSuggestion(
                target_type="risk_profile",
                target_name="paper_promote_position",
                action="test_small_priority_increase",
                priority="medium",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="纸面实盘已有正期望和较好盈亏因子，可小幅提高候选优先级，不直接放大实盘仓位。",
                current={
                    "win_rate": win_rate,
                    "avg_return": avg_return,
                    "profit_factor": profit_factor,
                },
                proposed={"priority_score_delta": 3},
                guardrails=guardrails + ["若连续回撤扩大，立即回退"],
            )
        )

    if status == "reduce":
        suggestions.append(
            ParameterSuggestion(
                target_type="rule_weight",
                target_name="paper_reduce_weight",
                action="reduce_or_pause",
                priority="high",
                scope_type=scope_type,
                scope_value=scope_value,
                rationale="纸面实盘期望偏弱，继续实盘辅助前应降低规则权重或暂停该作用域。",
                current={"avg_return": avg_return, "profit_factor": profit_factor},
                proposed={"enabled_for_live_assist": False},
                guardrails=guardrails,
            )
        )

    return suggestions


def _diagnose_group(
    *,
    scope_type: str,
    scope_value: str,
    positions: list[PaperPosition],
    plan_snapshots: dict[int, dict],
) -> PaperTradeMetrics:
    pnl_values = [_float(item.pnl_pct) for item in positions]
    mfe_values = [_mfe_pct(item) for item in positions]
    mae_values = [_mae_pct(item) for item in positions]
    holding_days = [_holding_days(item) for item in positions]
    trade_count = len(positions)
    win_rate = sum(1 for value in pnl_values if value > 0) / trade_count
    avg_return = sum(pnl_values) / trade_count
    profit_factor = _profit_factor(pnl_values)
    avg_mfe = sum(mfe_values) / trade_count
    avg_mae = sum(mae_values) / trade_count
    avg_giveback = avg_mfe - avg_return
    volume_trap_rate = (
        sum(1 for item in positions if _is_high_volume_trap(item, plan_snapshots)) / trade_count
    )
    stop_loss_rate = sum(1 for item in positions if item.exit_reason == "stop_loss") / trade_count
    time_exit_rate = sum(1 for item in positions if item.exit_reason == "time_exit") / trade_count
    avg_holding_days = sum(holding_days) / trade_count
    confidence = _confidence(trade_count)
    status = _status(
        avg_return=avg_return,
        profit_factor=profit_factor,
        win_rate=win_rate,
        confidence=confidence,
    )
    suggestions: list[str] = []
    if trade_count < 10:
        suggestions.append("继续积累纸面实盘样本，暂不根据少数样本改核心参数")
    if avg_giveback > 0.025 and avg_mfe > 0:
        suggestions.append("浮盈回吐偏大，优先检查止盈和跟踪止盈")
    if stop_loss_rate >= 0.45 or avg_mae <= -0.045:
        suggestions.append("止损或不利波动偏高，优先收紧买点过滤")
    if volume_trap_rate >= 0.30:
        suggestions.append("高位放量后失败比例偏高，警惕诱多和利好兑现")
    if not suggestions:
        suggestions.append("继续滚动观察，等待更多样本确认")

    parameter_suggestions = _base_suggestions(
        scope_type=scope_type,
        scope_value=scope_value,
        trade_count=trade_count,
        win_rate=win_rate,
        avg_return=avg_return,
        profit_factor=profit_factor,
        avg_mfe=avg_mfe,
        avg_mae=avg_mae,
        avg_giveback=avg_giveback,
        stop_loss_rate=stop_loss_rate,
        volume_trap_rate=volume_trap_rate,
        status=status,
        confidence=confidence,
    )
    summary = (
        f"{scope_value}: {trade_count} 笔，胜率 {win_rate:.2%}，"
        f"平均收益 {avg_return:.2%}，盈亏因子 {profit_factor:.2f}"
    )
    return PaperTradeMetrics(
        scope_type=scope_type,
        scope_value=scope_value,
        trade_count=trade_count,
        win_rate=win_rate,
        avg_return=avg_return,
        profit_factor=profit_factor,
        avg_mfe=avg_mfe,
        avg_mae=avg_mae,
        avg_giveback=avg_giveback,
        volume_trap_rate=volume_trap_rate,
        stop_loss_rate=stop_loss_rate,
        time_exit_rate=time_exit_rate,
        avg_holding_days=avg_holding_days,
        status=status,
        confidence=confidence,
        summary=summary,
        suggestions=suggestions,
        parameter_suggestions=parameter_suggestions,
    )


def _load_closed_positions(db: Session, report_date: date) -> list[PaperPosition]:
    stmt = (
        select(PaperPosition)
        .where(PaperPosition.status == "closed")
        .where(PaperPosition.exit_date <= report_date)
        .where(PaperPosition.pnl_pct.is_not(None))
    )
    return list(db.execute(stmt).scalars())


def _trade_plan_payloads(db: Session, positions: list[PaperPosition]) -> dict[int, dict]:
    plan_ids = {item.trade_plan_id for item in positions if item.trade_plan_id is not None}
    if not plan_ids:
        return {}
    rows = db.execute(select(TradePlan).where(TradePlan.id.in_(plan_ids))).scalars()
    payloads: dict[int, dict] = {}
    for plan in rows:
        payload = plan.entry_condition_json or {}
        if isinstance(payload, dict):
            payloads[plan.id] = payload
    return payloads


def _signal_tags(position: PaperPosition, plan_payloads: dict[int, dict]) -> list[str]:
    if position.trade_plan_id is None:
        return []
    payload = plan_payloads.get(position.trade_plan_id, {})
    evidence = payload.get("evidence") or {}
    tags = evidence.get("tags") or []
    names = []
    for tag in tags:
        if isinstance(tag, dict) and tag.get("name"):
            names.append(str(tag["name"]))
    return names


def _snapshot_float(snapshot: dict, key: str) -> float | None:
    value = snapshot.get(key)
    return float(value) if value is not None else None


def _is_high_volume_trap(position: PaperPosition, plan_snapshots: dict[int, dict]) -> bool:
    if position.trade_plan_id is None:
        return False
    snapshot = plan_snapshots.get(position.trade_plan_id, {})
    amount_percentile = _snapshot_float(snapshot, "amount_percentile_60d")
    volume_score = _snapshot_float(snapshot, "volume_score")
    distance_to_high = _snapshot_float(snapshot, "distance_to_20d_high")
    return_5d = _snapshot_float(snapshot, "return_5d")
    return_20d = _snapshot_float(snapshot, "return_20d")
    high_volume = (amount_percentile or volume_score or 0) >= 80
    high_position = (
        (distance_to_high is not None and distance_to_high >= -0.03)
        or (return_5d is not None and return_5d >= 0.08)
        or (return_20d is not None and return_20d >= 0.15)
    )
    failed_after_entry = _float(position.pnl_pct) <= 0 or _mae_pct(position) <= -0.03
    return high_volume and high_position and failed_after_entry


def diagnose_paper_trading(
    db: Session,
    report_date: str,
) -> list[PaperTradeMetrics]:
    parsed_report_date = date.fromisoformat(report_date)
    positions = _load_closed_positions(db, parsed_report_date)
    plan_payloads = _trade_plan_payloads(db, positions)
    plan_snapshots = {
        plan_id: payload.get("snapshot")
        for plan_id, payload in plan_payloads.items()
        if isinstance(payload.get("snapshot"), dict)
    }
    diagnostics: list[PaperTradeMetrics] = []

    by_rule: dict[str, list[PaperPosition]] = {}
    for position in positions:
        by_rule.setdefault(position.rule_id, []).append(position)
    for rule_id, items in by_rule.items():
        diagnostics.append(
            _diagnose_group(
                scope_type="rule",
                scope_value=rule_id,
                positions=items,
                plan_snapshots=plan_snapshots,
            )
        )

    symbols = {position.symbol for position in positions}
    sectors = {}
    if symbols:
        sectors = {
            item.symbol: item.industry or "unknown"
            for item in db.execute(select(Security).where(Security.symbol.in_(symbols))).scalars()
        }
    by_sector: dict[str, list[PaperPosition]] = {}
    for position in positions:
        by_sector.setdefault(sectors.get(position.symbol, "unknown"), []).append(position)
    for sector, items in by_sector.items():
        diagnostics.append(
            _diagnose_group(
                scope_type="sector",
                scope_value=sector,
                positions=items,
                plan_snapshots=plan_snapshots,
            )
        )

    by_signal: dict[str, list[PaperPosition]] = {}
    for position in positions:
        for tag in _signal_tags(position, plan_payloads):
            by_signal.setdefault(tag, []).append(position)
    for tag, items in by_signal.items():
        diagnostics.append(
            _diagnose_group(
                scope_type="signal",
                scope_value=tag,
                positions=items,
                plan_snapshots=plan_snapshots,
            )
        )

    return sorted(diagnostics, key=lambda item: (item.scope_type, item.scope_value))


def _render_report(report_date: str, diagnostics: list[PaperTradeMetrics]) -> str:
    if not diagnostics:
        return f"# 纸面实盘诊断 {report_date}\n\n暂无已平仓纸面实盘样本。"
    lines = [f"# 纸面实盘诊断 {report_date}", ""]
    for item in diagnostics:
        lines.append(f"## {item.scope_type}:{item.scope_value}")
        lines.append(f"- 状态：{item.status} / 置信度：{item.confidence}")
        lines.append(f"- {item.summary}")
        lines.append(
            f"- MFE {item.avg_mfe:.2%} / MAE {item.avg_mae:.2%} / "
            f"回吐 {item.avg_giveback:.2%} / 止损率 {item.stop_loss_rate:.2%} / "
            f"放量诱多率 {item.volume_trap_rate:.2%}"
        )
        for suggestion in item.suggestions:
            lines.append(f"- 建议：{suggestion}")
        lines.append("")
    return "\n".join(lines)


def persist_paper_trading_review(db: Session, report_date: str) -> int:
    db.flush()
    diagnostics = diagnose_paper_trading(db, report_date)
    suggestions = [
        suggestion.to_dict()
        for item in diagnostics
        for suggestion in item.parameter_suggestions
    ]
    insert_review_report(
        db,
        report_date=report_date,
        report_type="paper_trading_review",
        scope="paper",
        generator="mechanical",
        content_md=_render_report(report_date, diagnostics),
        metrics_json={"diagnostics": [item.to_dict() for item in diagnostics]},
    )
    changed = upsert_parameter_recommendations(
        db,
        report_date=report_date,
        suggestions=suggestions,
        source_report_type="paper_trading_review",
    )
    return changed


def generate_paper_trading_review(report_date: str) -> int:
    with SessionLocal() as db:
        changed = persist_paper_trading_review(db, report_date)
        db.commit()
        return changed
