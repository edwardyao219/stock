from dataclasses import dataclass
from datetime import date
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


def _pct_or_dash(value: object) -> str:
    return _pct(value) if value is not None else "-"


def _amount(value: object) -> str:
    if value is None:
        return "-"
    amount = float(value)
    if abs(amount) >= 100_000_000:
        return f"{amount / 100_000_000:.1f}亿"
    if abs(amount) >= 10_000:
        return f"{amount / 10_000:.1f}万"
    return f"{amount:.0f}"


def _flow_rate(value: object) -> str:
    return f"{float(value):.2f}%" if value is not None else "-"


def _status_label(value: object) -> str:
    return {
        "ok": "正常",
        "warning": "警告",
        "critical": "严重",
    }.get(str(value), str(value or "-"))


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


def _tag_text(tags: list[str], prefix: str) -> str | None:
    for tag in tags:
        if str(tag).startswith(prefix):
            value = str(tag).removeprefix(prefix).strip()
            return value or None
    return None


def _candidate_tier_label(tags: list[str]) -> str | None:
    tier = _tag_text(tags, "tier:")
    return {
        "core_action": "核心行动",
        "sector_watch": "板块观察",
        "watch_wait": "观察等待",
        "risk_reject": "淘汰/风险",
    }.get(str(tier or ""), None)


def _sector_line(item: dict[str, object]) -> str:
    net_amount = item.get("fund_flow_net_amount")
    flow_label = "资金净流入"
    flow_amount = _amount(net_amount)
    if net_amount is not None and float(net_amount) < 0:
        flow_label = "资金净流出"
        flow_amount = _amount(abs(float(net_amount)))
    flow_text = f"{flow_label} {flow_amount} / 净流入率 {_flow_rate(item.get('fund_flow_rate'))}"
    flow_date = str(item.get("fund_flow_trade_date") or "")
    source_count = int(item.get("fund_flow_source_count") or 0)
    flow_notes = []
    if flow_date:
        flow_notes.append(f"资金日期 {flow_date}")
    if flow_date and item.get("fund_flow_stale"):
        flow_notes.append("非当日")
    if source_count > 1:
        flow_notes.append(f"细分合计 {source_count} 个")
    if flow_notes:
        flow_text += f"（{'，'.join(flow_notes)}）"
    if not flow_date and net_amount is None and item.get("fund_flow_rate") is None:
        flow_text = "资金流 -"
    return (
        f"{item.get('sector') or '-'} "
        f"均涨 {_pct(item.get('avg_change_pct') or 0)} / "
        f"上涨占比 {_pct(item.get('up_ratio') or 0)} / "
        f"{int(item.get('stock_count') or 0)}只 / "
        f"成交额 {_amount(item.get('total_amount'))} / "
        f"{flow_text}"
    )


def _mover_line(item: dict[str, object]) -> str:
    name = str(item.get("name") or "").strip()
    sector = str(item.get("sector") or "-").strip()
    label = f"{item.get('symbol')}{f' {name}' if name else ''}"
    return (
        f"{label} / {sector} / "
        f"{_pct(item.get('change_pct') or 0)} / "
        f"成交额 {_amount(item.get('amount'))}"
    )


def _index_line(item: dict[str, object]) -> str:
    close = item.get("close")
    change_pct = item.get("change_pct")
    stale_suffix = "（非当日）" if item.get("stale") else ""
    close_text = f"{float(close):.2f}" if close is not None else "-"
    change_text = _pct(change_pct) if change_pct is not None else "-"
    return f"{item.get('name') or item.get('symbol')} {close_text} / {change_text}{stale_suffix}"


def _breadth_label(up_ratio: object) -> str:
    if up_ratio is None:
        return "市场宽度未知"
    value = float(up_ratio)
    if value >= 0.62:
        return "市场宽度偏强"
    if value >= 0.55:
        return "市场宽度温和修复"
    if value <= 0.38:
        return "市场宽度偏弱"
    if value <= 0.45:
        return "市场宽度承压"
    return "市场宽度均衡偏分歧"


def _sector_names(items: list[dict[str, object]], limit: int = 2) -> str:
    names = [str(item.get("sector") or "").strip() for item in items[:limit]]
    return "、".join(name for name in names if name)


def _candidate_change_values(
    candidate_items: list[dict[str, object]],
    candidate_bars: dict[str, Any],
) -> list[float]:
    values: list[float] = []
    for item in candidate_items:
        change_pct = _bar_change_pct(candidate_bars.get(item["symbol"]))
        if change_pct is not None:
            values.append(change_pct)
    return values


def _sector_matches(industry: str | None, sector_names: set[str]) -> bool:
    text = str(industry or "").strip()
    return any(name and (name == text or name in text or text in name) for name in sector_names)


def _candidate_recap_hint(
    *,
    change_pct: float,
    market_avg_change_pct: object,
    up_ratio: object,
    industry: str | None,
    strong_sector_names: set[str],
    weak_sector_names: set[str],
) -> str:
    parts: list[str] = []
    delta: float | None = None
    if market_avg_change_pct is not None:
        delta = change_pct - float(market_avg_change_pct)
        if delta >= 0:
            parts.append(f"跑赢市场 {delta * 100:.2f} 个百分点")
        else:
            parts.append(f"跑输市场 {abs(delta) * 100:.2f} 个百分点")
    if _sector_matches(industry, strong_sector_names):
        parts.append("处在当日相对强板块")
    elif _sector_matches(industry, weak_sector_names):
        parts.append("处在当日承压板块")
    if up_ratio is not None and float(up_ratio) <= 0.18:
        if delta is not None and delta >= 0:
            parts.append("极端宽度日先记为抗跌样本，次日仍看承接")
        else:
            parts.append("极端宽度日先控制仓位，等市场宽度修复")
    return "；".join(parts)


def _candidate_line_label(tags: list[str]) -> str:
    if any(
        tag == "candidate_pool:startup_preheat" or tag.startswith("startup_signal_")
        for tag in tags
    ):
        return "启动观察"
    if "strategy:long_term" in tags or any(tag.startswith("hold_style:") for tag in tags):
        return "长期主线"
    if "strategy:swing" in tags:
        return "波段跟踪"
    if "tier:sector_watch" in tags:
        return "板块观察"
    return "其他观察"


def _candidate_line_recap(
    *,
    candidate_items: list[dict[str, object]],
    candidate_bars: dict[str, Any],
) -> str | None:
    grouped: dict[str, list[float]] = {}
    for item in candidate_items:
        change_pct = _bar_change_pct(candidate_bars.get(item["symbol"]))
        if change_pct is None:
            continue
        label = _candidate_line_label([str(tag) for tag in item.get("tags") or []])
        grouped.setdefault(label, []).append(change_pct)
    parts = []
    for label in ("长期主线", "启动观察", "波段跟踪", "板块观察", "其他观察"):
        values = grouped.get(label)
        if values:
            parts.append(f"{label} {len(values)}只，平均 {_pct(sum(values) / len(values))}")
    return f"策略线回看: {'；'.join(parts)}" if parts else None


def _candidate_divergence_lines(
    *,
    market_summary: dict[str, object],
    market_cross_section: dict[str, object],
    candidate_items: list[dict[str, object]],
    candidate_bars: dict[str, Any],
) -> list[str]:
    lines = ["", "## 盘面与候选分化", ""]
    up_ratio = market_summary.get("up_ratio")
    avg_change_pct = market_summary.get("avg_change_pct")
    down_count = int(market_summary.get("down_count") or 0)
    lines.append(
        "- "
        f"{_breadth_label(up_ratio)}："
        f"上涨 {market_summary.get('up_count', 0)} / "
        f"下跌 {down_count}，"
        f"上涨占比 {_pct_or_dash(up_ratio)}，"
        f"市场平均 {_pct_or_dash(avg_change_pct)}。"
    )
    if down_count >= 4500 or (up_ratio is not None and float(up_ratio) <= 0.18):
        pressure_text = (
            f"下跌 {down_count} 家" if down_count else f"上涨占比 {_pct_or_dash(up_ratio)}"
        )
        lines.append(
            f"- 极端防守：{pressure_text}，次日少推核心，多数候选先降级观察；"
            "优先等指数止跌、板块资金回流和个股承接确认。"
        )

    strong_sectors = list(market_cross_section.get("strong_sectors") or [])
    weak_sectors = list(market_cross_section.get("weak_sectors") or [])
    strong_names = _sector_names(strong_sectors)
    weak_names = _sector_names(weak_sectors)
    if strong_names and weak_names:
        if up_ratio is not None and float(up_ratio) <= 0.38:
            lines.append(
                f"- 弱市里相对抗跌先看 {strong_names}，承压集中在 {weak_names}；"
                "这不等于主线确认，只说明今天这些方向更抗跌。"
            )
        else:
            lines.append(
                f"- 主线先看 {strong_names}，承压集中在 {weak_names}；"
                "今天不是只看个股涨跌，更要看它站在哪个板块风口里。"
            )
    elif strong_names:
        lines.append(f"- 主线先看 {strong_names}；弱势端不明显，继续观察扩散能否延续。")
    elif weak_names:
        lines.append(f"- 暂无清晰强势板块，承压集中在 {weak_names}；防守阶段先少动。")
    else:
        lines.append("- 板块强弱分化暂不清晰，今天先把个股表现当作局部样本。")

    changes = _candidate_change_values(candidate_items, candidate_bars)
    if not candidate_items:
        lines.append("- 昨日没有可回看的候选，今天只复盘市场和板块。")
        return lines
    if not changes:
        lines.append(
            f"- 昨日候选有日线 0/{len(candidate_items)} 只，"
            "数据不足，暂不判断候选是否跑赢市场。"
        )
        return lines

    red_count = sum(1 for value in changes if value > 0)
    green_count = sum(1 for value in changes if value < 0)
    avg_candidate = sum(changes) / len(changes)
    lines.append(
        "- "
        f"昨日候选有日线 {len(changes)}/{len(candidate_items)} 只，"
        f"红盘 {red_count} 只，绿盘 {green_count} 只，"
        f"平均 {_pct(avg_candidate)}。"
    )
    if avg_change_pct is None:
        lines.append("- 市场平均涨跌缺失，暂不比较候选和大盘。")
    else:
        delta = avg_candidate - float(avg_change_pct)
        direction = "跑赢" if delta >= 0 else "跑输"
        lines.append(f"- 候选整体{direction}市场平均 {abs(delta) * 100:.2f} 个百分点。")

    lines.append(
        "- 如果候选表现好于市场，优先看板块顺风和个股自身承接；"
        "如果候选表现弱于市场，先查是否处在弱板块、缩量无承接或冲高回落。"
    )
    return lines


def _data_health_metrics(report: Any) -> dict[str, object]:
    if report is None:
        return {}
    return {
        "status": getattr(report, "status", ""),
        "trade_date": getattr(getattr(report, "trade_date", None), "isoformat", lambda: "")(),
        "daily_bar_count": getattr(report, "daily_bar_count", 0),
        "feature_count": getattr(report, "feature_count", 0),
        "amount_missing_ratio": getattr(report, "amount_missing_ratio", None),
        "issues": [
            {
                "code": getattr(issue, "code", ""),
                "severity": getattr(issue, "severity", ""),
                "message": getattr(issue, "message", ""),
            }
            for issue in getattr(report, "issues", [])[:10]
        ],
    }


def generate_daily_mechanical_review(report_date: str) -> MechanicalReview:
    try:
        from sqlalchemy import select

        from services.engine.features.health import inspect_daily_data_health
        from services.engine.review.repository import (
            insert_review_report,
            load_candidate_pool_items_for_review,
            load_daily_bars_for_symbols,
            load_market_cross_section_for_report_date,
            load_market_indexes_for_report_date,
            load_market_summary_for_report_date,
            load_rule_performance_for_date,
            load_trade_plans_for_date,
            upsert_parameter_recommendations,
        )
        from services.shared.database import SessionLocal
        from services.shared.models import Security

        with SessionLocal() as db:
            market_summary = load_market_summary_for_report_date(db, report_date)
            market_indexes = load_market_indexes_for_report_date(db, report_date)
            market_cross_section = load_market_cross_section_for_report_date(db, report_date)
            trade_date = str(market_summary.get("trade_date") or report_date)
            try:
                health_trade_date = date.fromisoformat(trade_date) if trade_date else None
            except ValueError:
                health_trade_date = date.fromisoformat(report_date)
            try:
                data_health = inspect_daily_data_health(db, trade_date=health_trade_date)
            except Exception:
                data_health = None
            candidate_items = load_candidate_pool_items_for_review(db, report_date)
            candidate_items = [
                item
                for item in candidate_items
                if str(item.get("symbol") or "").strip() not in NOISE_REVIEW_SYMBOLS
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
                "# 收盘总体复盘",
                "",
                f"报告日期: {report_date}",
                "",
                "## 市场概况",
                "",
            ]

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
                f"覆盖率 {_pct_or_dash(market_summary.get('coverage_ratio'))}，"
                f"是否全市场 {'是' if market_summary.get('is_full_market') else '否'}"
            )
            lines.append(
                "- "
                f"上涨 {market_summary.get('up_count', 0)} / "
                f"下跌 {market_summary.get('down_count', 0)} / "
                f"平盘 {market_summary.get('flat_count', 0)}，"
                f"上涨占比 {_pct_or_dash(market_summary.get('up_ratio'))}，"
                f"平均涨跌 {_pct_or_dash(market_summary.get('avg_change_pct'))}，"
                f"成交额 {_amount(market_summary.get('total_amount'))}"
            )
            if market_summary.get("amount_change_pct") is not None:
                lines.append(f"- 较前日成交额 {_pct(market_summary['amount_change_pct'])}")
            elif market_summary.get("amount_change_note"):
                lines.append(f"- {market_summary['amount_change_note']}")
            if market_indexes:
                lines.append(
                    "- 主要指数: "
                    + "；".join(_index_line(item) for item in market_indexes)
                )

            lines.extend(["", "## 数据健康", ""])
            if data_health is None:
                lines.append("- 数据健康检查未完成，本次复盘只能按已入库样本观察。")
            else:
                lines.append(
                    "- "
                    f"状态 {_status_label(getattr(data_health, 'status', ''))}，"
                    f"日线 {getattr(data_health, 'daily_bar_count', 0)} 条，"
                    f"特征 {getattr(data_health, 'feature_count', 0)} 条，"
                    f"前一交易日日线 {getattr(data_health, 'previous_daily_bar_count', 0)} 条"
                )
                amount_missing_ratio = getattr(data_health, "amount_missing_ratio", None)
                if amount_missing_ratio is not None:
                    lines.append(f"- 成交额缺失占比 {_pct(amount_missing_ratio)}")
                issues = list(getattr(data_health, "issues", []) or [])
                if issues:
                    for issue in issues[:4]:
                        lines.append(
                            "- "
                            f"{_status_label(getattr(issue, 'severity', ''))}: "
                            f"{getattr(issue, 'message', '')}"
                        )
                else:
                    lines.append("- 暂未发现日线和特征覆盖异常。")

            lines.extend(["", "## 大盘强弱分化", ""])
            strong_sectors = list(market_cross_section.get("strong_sectors") or [])
            weak_sectors = list(market_cross_section.get("weak_sectors") or [])
            top_gainers = list(market_cross_section.get("top_gainers") or [])
            top_losers = list(market_cross_section.get("top_losers") or [])
            if not market_summary.get("is_full_market"):
                lines.append(
                    "- 全市场覆盖不足，暂不输出强弱板块排行；"
                    "当前只能看作局部样本，不能据此判断今天市场主线。"
                )
            else:
                moneyflow_date = str(
                    market_cross_section.get("sector_moneyflow_trade_date") or ""
                )
                moneyflow_missing_count = int(
                    market_cross_section.get("sector_moneyflow_missing_count") or 0
                )
                if moneyflow_date:
                    stale_text = (
                        "（非当日）" if market_cross_section.get("sector_moneyflow_stale") else ""
                    )
                    matched_count = int(
                        market_cross_section.get("sector_moneyflow_matched_count") or 0
                    )
                    total_count = int(
                        market_cross_section.get("sector_moneyflow_total_count") or 0
                    )
                    coverage_ratio = market_cross_section.get(
                        "sector_moneyflow_coverage_ratio"
                    )
                    coverage_text = (
                        f"，覆盖 {matched_count} / {total_count}，"
                        f"覆盖率 {_pct_or_dash(coverage_ratio)}"
                        if total_count
                        else ""
                    )
                    missing_text = (
                        f"，缺失 {moneyflow_missing_count} 个板块"
                        if moneyflow_missing_count
                        else "，当前板块均有资金流"
                    )
                    lines.append(
                        f"- 行业资金流日期 {moneyflow_date}{stale_text}"
                        f"{coverage_text}{missing_text}"
                    )
                    if coverage_ratio is not None and float(coverage_ratio) < 0.8:
                        lines.append(
                            "- 行业资金流覆盖不足，只作为板块趋势的辅助确认，不单独判断主线。"
                        )
                elif moneyflow_missing_count:
                    lines.append(f"- 行业资金流未入库，缺失 {moneyflow_missing_count} 个板块")
                if strong_sectors:
                    lines.append(
                        "- 强势板块: "
                        + "；".join(_sector_line(item) for item in strong_sectors[:3])
                    )
                else:
                    lines.append("- 强势板块: 暂无足够样本")
                if weak_sectors:
                    lines.append(
                        "- 弱势板块: "
                        + "；".join(_sector_line(item) for item in weak_sectors[:3])
                    )
                if top_gainers:
                    lines.append(
                        "- 当日强势个股: "
                        + "；".join(_mover_line(item) for item in top_gainers[:5])
                    )
                if top_losers:
                    lines.append(
                        "- 当日承压个股: "
                        + "；".join(_mover_line(item) for item in top_losers[:5])
                    )
                lines.append(
                    "- 归因口径: 强股通常来自当日更强的板块、放量承接或逆势抗跌；"
                    "弱股通常来自板块补跌、缩量无承接或冲高回落。"
                )

            lines.extend(
                _candidate_divergence_lines(
                    market_summary=market_summary,
                    market_cross_section=market_cross_section,
                    candidate_items=candidate_items,
                    candidate_bars=candidate_bars,
                )
            )

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
                retired_count = sum(
                    1 for item in candidate_items if item.get("status") == "retired"
                )
                strong_sector_names = {
                    str(item.get("sector") or "").strip()
                    for item in strong_sectors
                    if str(item.get("sector") or "").strip()
                }
                weak_sector_names = {
                    str(item.get("sector") or "").strip()
                    for item in weak_sectors
                    if str(item.get("sector") or "").strip()
                }
                lines.append(
                    f"- 昨日候选 {len(candidate_items)} 只，活跃 {active_count} 只，"
                    f"已退休 {retired_count} 只"
                )
                line_recap = _candidate_line_recap(
                    candidate_items=candidate_items,
                    candidate_bars=candidate_bars,
                )
                if line_recap:
                    lines.append(f"- {line_recap}")
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
                            f"{f' / {meta_text}' if meta_text else ''}: "
                            f"今日无日线数据，状态 {status}".strip()
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
                    if change_pct is not None:
                        recap_hint = _candidate_recap_hint(
                            change_pct=change_pct,
                            market_avg_change_pct=market_summary.get("avg_change_pct"),
                            up_ratio=market_summary.get("up_ratio"),
                            industry=industry,
                            strong_sector_names=strong_sector_names,
                            weak_sector_names=weak_sector_names,
                        )
                        if recap_hint:
                            lines.append(f"  - 复盘判断: {recap_hint}")
                    note = _short_text(item.get("note"))
                    if note:
                        lines.append(f"  - 备注: {note}")
                    tags = [str(tag) for tag in item.get("tags") or []]
                    tier_label = _candidate_tier_label(tags)
                    tier_reason = _short_text(_tag_text(tags, "tier_reason:"), limit=140)
                    candidate_summary = _short_text(
                        _tag_text(tags, "candidate_summary:"),
                        limit=140,
                    )
                    if tier_label:
                        lines.append(f"  - 分层: {tier_label}")
                    if tier_reason:
                        lines.append(f"  - 分层原因: {tier_reason}")
                    if candidate_summary:
                        lines.append(f"  - 候选池提示: {candidate_summary}")
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
                    "data_health": _data_health_metrics(data_health),
                    "market_indexes": market_indexes,
                    "market_cross_section": market_cross_section,
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
                title=f"{report_date} 收盘总体复盘",
                content_md=content,
            )
    except Exception:
        pass

    content = "\n".join(
        [
            "# 收盘总体复盘",
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
        title=f"{report_date} 收盘总体复盘",
        content_md=content,
    )
