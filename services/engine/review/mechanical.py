from dataclasses import dataclass
from typing import Any

from services.engine.review.rule_diagnostics import diagnose_rule_performances

NOISE_REVIEW_SYMBOLS = {"000001"}


@dataclass(frozen=True)
class MechanicalReview:
    report_date: str
    title: str
    content_md: str


def _pct(value: object) -> str:
    return f"{float(value) * 100:.2f}%"


def _amount(value: object) -> str:
    if value is None:
        return "-"
    amount = float(value)
    if abs(amount) >= 100_000_000:
        return f"{amount / 100_000_000:.1f}亿"
    if abs(amount) >= 10_000:
        return f"{amount / 10_000:.1f}万"
    return f"{amount:.0f}"


def _bar_change_pct(bar: Any) -> float | None:
    if bar is None or bar.pre_close is None or float(bar.pre_close) <= 0:
        return None
    return float(bar.close) / float(bar.pre_close) - 1


def _short_text(value: str | None, limit: int = 96) -> str | None:
    if not value:
        return None
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _tag_number(tags: list[str], prefix: str, cast: Any) -> int | float | None:
    for tag in tags:
        if str(tag).startswith(prefix):
            try:
                return cast(str(tag).removeprefix(prefix))
            except ValueError:
                return None
    return None


def generate_daily_mechanical_review(report_date: str) -> MechanicalReview:
    try:
        from sqlalchemy import select

        from services.engine.review.repository import (
            insert_review_report,
            load_candidate_pool_items_for_review,
            load_daily_bars_for_symbols,
            load_market_summary_for_report_date,
            load_rule_performance_for_date,
            load_trade_plans_for_date,
            upsert_parameter_recommendations,
        )
        from services.shared.database import SessionLocal
        from services.shared.models import Security

        with SessionLocal() as db:
            market_summary = load_market_summary_for_report_date(db, report_date)
            candidate_items = load_candidate_pool_items_for_review(db, report_date)
            candidate_items = [
                item for item in candidate_items if str(item.get("symbol") or "").strip() not in NOISE_REVIEW_SYMBOLS
            ]
            candidate_items = sorted(
                candidate_items,
                key=lambda item: (
                    _tag_number(item.get("tags") or [], "rank:", int) or 999,
                    item["symbol"],
                ),
            )
            candidate_symbols = [item["symbol"] for item in candidate_items]
            candidate_bars = load_daily_bars_for_symbols(db, report_date, candidate_symbols)
            securities = {}
            if candidate_symbols:
                securities = {
                    item.symbol: item
                    for item in db.execute(
                        select(Security).where(Security.symbol.in_(candidate_symbols))
                    ).scalars()
                }

            performances = load_rule_performance_for_date(db, report_date)
            plans = load_trade_plans_for_date(db, report_date)
            diagnostics = diagnose_rule_performances(performances)

            lines = [
                "# 每日机械复盘",
                "",
                f"报告日期: {report_date}",
                "",
                "## 市场概况",
                "",
            ]

            trade_date = market_summary.get("trade_date") or report_date
            stale_suffix = "（已过期）" if market_summary.get("stale") else ""
            lines.append(
                "- "
                f"请求日期 {market_summary.get('requested_date') or report_date} / "
                f"数据日期 {trade_date}{stale_suffix}"
            )
            lines.append(
                "- "
                f"样本 {market_summary.get('stock_count', 0)} / "
                f"{market_summary.get('active_security_count', 0)}，"
                f"覆盖率 {_pct(market_summary['coverage_ratio']) if market_summary.get('coverage_ratio') is not None else '-'}，"
                f"是否全市场 {'是' if market_summary.get('is_full_market') else '否'}"
            )
            lines.append(
                "- "
                f"上涨 {market_summary.get('up_count', 0)} / "
                f"下跌 {market_summary.get('down_count', 0)} / "
                f"平盘 {market_summary.get('flat_count', 0)}，"
                f"上涨占比 {_pct(market_summary['up_ratio']) if market_summary.get('up_ratio') is not None else '-'}，"
                f"平均涨跌 {_pct(market_summary['avg_change_pct']) if market_summary.get('avg_change_pct') is not None else '-'}，"
                f"成交额 {_amount(market_summary.get('total_amount'))}"
            )
            if market_summary.get("amount_change_pct") is not None:
                lines.append(f"- 较前日成交额 {_pct(market_summary['amount_change_pct'])}")

            lines.extend(["", "## 规则表现", ""])
            if performances:
                diagnostics_by_rule = {item.rule_id: item for item in diagnostics}
                for item in performances:
                    diagnostic = diagnostics_by_rule[item.rule_id]
                    lines.append(
                        "- "
                        f"{item.rule_id}: 交易 {item.trade_count} 笔, "
                        f"胜率 {_pct(item.win_rate)}, "
                        f"平均收益 {_pct(item.avg_return)}, "
                        f"盈亏因子 {float(item.profit_factor):.2f}, "
                        f"评分 {float(item.score):.2f}, "
                        f"诊断 {diagnostic.status}/{diagnostic.confidence}"
                    )
                    lines.append(f"  - 结论: {diagnostic.summary}")
                    for suggestion in diagnostic.suggestions:
                        lines.append(f"  - 建议: {suggestion}")
            else:
                lines.append("- 暂无规则表现数据")

            parameter_suggestions = [
                suggestion
                for diagnostic in diagnostics
                for suggestion in diagnostic.parameter_suggestions
            ]
            lines.extend(["", "## 候选参数调整", ""])
            if parameter_suggestions:
                for suggestion in parameter_suggestions:
                    lines.append(
                        "- "
                        f"{suggestion.scope_value or suggestion.scope_type} / "
                        f"{suggestion.target_type}.{suggestion.target_name}: "
                        f"{suggestion.action} "
                        f"({suggestion.priority})"
                    )
                    lines.append(f"  - 理由: {suggestion.rationale}")
            else:
                lines.append("- 暂无候选参数调整")

            lines.extend(["", "## 昨日候选今日回看", ""])
            if candidate_items:
                active_count = sum(1 for item in candidate_items if item.get("status") == "active")
                retired_count = sum(1 for item in candidate_items if item.get("status") == "retired")
                lines.append(
                    f"- 昨日候选 {len(candidate_items)} 只，活跃 {active_count} 只，已退休 {retired_count} 只"
                )
                for item in candidate_items[:8]:
                    symbol = item["symbol"]
                    security = securities.get(symbol)
                    bar = candidate_bars.get(symbol)
                    name = security.name if security else ""
                    industry = security.industry if security else ""
                    display_name = " ".join(part for part in [name, industry] if part)
                    candidate_label = f"{symbol}{f' {display_name}' if display_name else ''}"
                    status = item.get("status") or "-"
                    rank = _tag_number(item.get("tags") or [], "rank:", int)
                    score = _tag_number(item.get("tags") or [], "score:", float)
                    meta_bits = []
                    if rank is not None:
                        meta_bits.append(f"第{rank}名")
                    if score is not None:
                        meta_bits.append(f"{float(score):.1f}分")
                    meta_text = " / ".join(meta_bits)
                    if bar is None:
                        lines.append(
                            f"- {candidate_label}"
                            f"{f' / {meta_text}' if meta_text else ''}: 今日无日线数据，状态 {status}".strip()
                        )
                        continue
                    change_pct = _bar_change_pct(bar)
                    lines.append(
                        f"- {candidate_label}"
                        f"{f' / {meta_text}' if meta_text else ''}: 今日 "
                        f"{_pct(change_pct) if change_pct is not None else '-'}，"
                        f"K线 O{float(bar.open):.2f} H{float(bar.high):.2f} "
                        f"L{float(bar.low):.2f} C{float(bar.close):.2f}，"
                        f"成交额 {_amount(bar.amount)}，状态 {status}"
                    )
                    note = _short_text(item.get("note"))
                    if note:
                        lines.append(f"  - 备注: {note}")
            else:
                lines.append("- 暂无可回看的盘后候选")

            lines.extend(["", "## 风险提示", ""])
            weak_rules = [item for item in performances if float(item.avg_return) < 0]
            if weak_rules:
                lines.append("- 存在平均收益为负的规则，建议降低对应规则仓位或继续观察。")
            else:
                lines.append("- 暂未发现规则平均收益为负的机械信号。")
            low_sample_rules = [item for item in diagnostics if item.confidence == "low"]
            if low_sample_rules:
                ids = ", ".join(item.rule_id for item in low_sample_rules)
                lines.append(f"- 样本不足规则: {ids}，不要据此快速放大仓位。")

            content = "\n".join(lines)
            parameter_suggestions_json = [item.to_dict() for item in parameter_suggestions]
            insert_review_report(
                db,
                report_date=report_date,
                report_type="daily_mechanical",
                content_md=content,
                metrics_json={
                    "rule_diagnostics": [item.to_dict() for item in diagnostics],
                    "parameter_suggestions": parameter_suggestions_json,
                    "trade_plan_count": len(plans),
                },
            )
            upsert_parameter_recommendations(
                db,
                report_date=report_date,
                suggestions=parameter_suggestions_json,
                source_report_type="daily_mechanical",
            )
            db.commit()

            return MechanicalReview(
                report_date=report_date,
                title=f"{report_date} 每日机械复盘",
                content_md=content,
            )
    except Exception:
        pass

    content = "\n".join(
        [
            "# 每日机械复盘",
            "",
            "数据采集、特征计算、规则回归和候选回看模块仍在开发中。",
            "",
            "## 今日状态",
            "",
            "- 市场状态: unknown",
            "- 强势板块: 暂无",
            "- 规则表现: 暂无",
            "- 昨日候选回看: 暂无",
        ]
    )
    return MechanicalReview(
        report_date=report_date,
        title=f"{report_date} 每日机械复盘",
        content_md=content,
    )
