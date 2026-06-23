from dataclasses import dataclass

from services.engine.review.rule_diagnostics import diagnose_rule_performances


@dataclass(frozen=True)
class MechanicalReview:
    report_date: str
    title: str
    content_md: str


def _pct(value: object) -> str:
    return f"{float(value) * 100:.2f}%"


def generate_daily_mechanical_review(report_date: str) -> MechanicalReview:
    try:
        from services.engine.review.repository import (
            insert_review_report,
            load_rule_performance_for_date,
            load_trade_plans_for_date,
        )
        from services.shared.database import SessionLocal

        with SessionLocal() as db:
            performances = load_rule_performance_for_date(db, report_date)
            plans = load_trade_plans_for_date(db, report_date)
            diagnostics = diagnose_rule_performances(performances)

            lines = [
                "# 每日机械复盘",
                "",
                f"报告日期: {report_date}",
                "",
                "## 规则表现",
                "",
            ]
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

            lines.extend(["", "## 明日候选计划", ""])
            if plans:
                for item in plans:
                    lines.append(
                        "- "
                        f"{item.symbol} / {item.rule_id}: "
                        f"仓位 {float(item.position_size) * 100:.1f}%, "
                        f"止损 {item.initial_stop}, "
                        f"止盈1 {item.take_profit_1}, "
                        f"置信分 {float(item.confidence_score or 0):.2f}"
                    )
            else:
                lines.append("- 暂无交易计划")

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
            insert_review_report(
                db,
                report_date=report_date,
                report_type="daily_mechanical",
                content_md=content,
                metrics_json={
                    "rule_diagnostics": [item.to_dict() for item in diagnostics],
                    "parameter_suggestions": [item.to_dict() for item in parameter_suggestions],
                    "trade_plan_count": len(plans),
                },
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
            "数据采集、特征计算、规则回归和交易计划模块仍在开发中。",
            "",
            "## 今日状态",
            "",
            "- 市场状态: unknown",
            "- 强势板块: 暂无",
            "- 规则表现: 暂无",
            "- 明日计划: 暂无",
        ]
    )
    return MechanicalReview(
        report_date=report_date,
        title=f"{report_date} 每日机械复盘",
        content_md=content,
    )
