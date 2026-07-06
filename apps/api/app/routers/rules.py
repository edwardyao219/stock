from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.engine.backtest.strategy_fit import load_strategy_fit_report
from services.engine.backtest.walk_forward import (
    build_replay_data_coverage_report,
    compare_candidate_walk_forward_scopes,
    run_low_dimensional_walk_forward_replay,
    summarize_walk_forward_replay,
)
from services.engine.rules.seed_rules import MVP_RULES
from services.shared.database import get_db
from services.shared.time import now_local

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]

_SCOPE_LABELS = {
    "all": "全候选池",
    "action": "钉钉行动池",
    "action_long": "长期行动池",
    "potential_watch": "潜力观察池",
    "startup_preheat": "启动前夜池",
}
_PRIMARY_POLICY_SCOPES = {"action_long", "action", "all"}
DEFAULT_REPLAY_START_DATE = "2024-01-01"
_STYLE_LABELS = {
    "growth_cycle": "科技成长",
    "cyclical": "周期资源",
    "consumer_quality": "消费质量",
    "property_chain": "地产链",
    "compound": "防守复利",
    "healthcare": "医药",
    "market_beta": "市场弹性",
    "theme": "题材",
    "unknown": "未分类",
}


def _empty_return_metric() -> dict[str, Any]:
    return {
        "sample_count": 0,
        "avg_return": None,
        "win_rate": None,
        "total_return": None,
    }


def _has_metric_samples(metric: dict[str, Any] | None) -> bool:
    return bool(metric and int(metric.get("sample_count") or 0) > 0)


def _guarded_metric(summary: dict[str, Any], horizon: int) -> dict[str, Any]:
    portfolio_metric = (
        ((summary.get("portfolio_horizons") or {}).get(horizon) or {}).get("guarded")
    )
    if _has_metric_samples(portfolio_metric):
        return portfolio_metric
    return (
        ((summary.get("horizons") or {}).get(horizon) or {}).get("guarded")
        or _empty_return_metric()
    )


def _metric_label(summary: dict[str, Any], horizon: int) -> str:
    portfolio_metric = (
        ((summary.get("portfolio_horizons") or {}).get(horizon) or {}).get("guarded")
    )
    return "3只等权" if _has_metric_samples(portfolio_metric) else "样本合计"


def _monthly_metric_items(summary: dict[str, Any], horizon: int) -> dict[str, Any]:
    portfolio_monthly = (summary.get("monthly_portfolio_horizons") or {}).get(horizon) or {}
    if any(
        _has_metric_samples((item or {}).get("guarded") or {})
        for item in portfolio_monthly.values()
    ):
        return portfolio_monthly
    return (summary.get("monthly_horizons") or {}).get(horizon) or {}


def _monthly_metric_label(summary: dict[str, Any], horizon: int) -> str:
    portfolio_monthly = (summary.get("monthly_portfolio_horizons") or {}).get(horizon) or {}
    if any(
        _has_metric_samples((item or {}).get("guarded") or {})
        for item in portfolio_monthly.values()
    ):
        return "3只等权"
    return "样本合计"


def _monthly_guarded_metric(
    comparison: dict[str, Any],
    *,
    scope: str,
    month: str,
    horizon: int,
) -> dict[str, Any]:
    summary = (comparison.get("scopes") or {}).get(scope) or {}
    return (_monthly_metric_items(summary, horizon).get(month, {}) or {}).get(
        "guarded"
    ) or _empty_return_metric()


def _metric_float(metric: dict[str, Any], key: str) -> float | None:
    value = metric.get(key)
    return float(value) if value is not None else None


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:+.2f}%"


def _scope_diagnosis_row(scope: str, summary: dict[str, Any], horizon: int) -> dict[str, Any]:
    metric = _guarded_metric(summary, horizon)
    return {
        "scope": scope,
        "label": _SCOPE_LABELS.get(scope, scope),
        "metric_label": _metric_label(summary, horizon),
        "candidate_count": int(summary.get("candidate_count") or 0),
        "sample_count": int(metric.get("sample_count") or 0),
        "avg_return": _metric_float(metric, "avg_return"),
        "win_rate": _metric_float(metric, "win_rate"),
        "total_return": _metric_float(metric, "total_return"),
    }


def _required_primary_samples(row: dict[str, Any], fallback: int) -> int:
    return 3 if row.get("metric_label") == "3只等权" else fallback


def _month_candidates(comparison: dict[str, Any], *, horizon: int) -> list[str]:
    months: set[str] = set()
    for summary in (comparison.get("scopes") or {}).values():
        monthly = _monthly_metric_items(summary, horizon)
        for month, item in monthly.items():
            guarded = (item or {}).get("guarded") or {}
            if int(guarded.get("sample_count") or 0) > 0:
                months.add(str(month))
    return sorted(months)


def _scope_monthly_guarded_rows(
    comparison: dict[str, Any],
    *,
    scope: str,
    horizon: int,
) -> list[dict[str, Any]]:
    summary = (comparison.get("scopes") or {}).get(scope) or {}
    monthly = _monthly_metric_items(summary, horizon)
    metric_label = _monthly_metric_label(summary, horizon)
    rows: list[dict[str, Any]] = []
    for month, item in sorted(monthly.items()):
        guarded = (item or {}).get("guarded") or {}
        sample_count = int(guarded.get("sample_count") or 0)
        if sample_count <= 0:
            continue
        rows.append(
            {
                "month": str(month),
                "metric_label": metric_label,
                "sample_count": sample_count,
                "avg_return": _metric_float(guarded, "avg_return"),
                "total_return": _metric_float(guarded, "total_return"),
            }
        )
    return rows


def _scope_monthly_style_guarded_rows(
    comparison: dict[str, Any],
    *,
    scope: str,
    horizon: int,
) -> list[dict[str, Any]]:
    summary = (comparison.get("scopes") or {}).get(scope) or {}
    monthly = (summary.get("monthly_style_horizons") or {}).get(horizon) or {}
    rows: list[dict[str, Any]] = []
    for month, styles in sorted(monthly.items()):
        for style, item in sorted((styles or {}).items()):
            guarded = (item or {}).get("guarded") or {}
            sample_count = int(guarded.get("sample_count") or 0)
            if sample_count <= 0:
                continue
            style_key = str(style)
            rows.append(
                {
                    "month": str(month),
                    "style": style_key,
                    "label": _STYLE_LABELS.get(style_key, "其他风格"),
                    "sample_count": sample_count,
                    "avg_return": _metric_float(guarded, "avg_return"),
                    "win_rate": _metric_float(guarded, "win_rate"),
                    "total_return": _metric_float(guarded, "total_return"),
                }
            )
    return rows


def diagnose_style_gate_policy(
    comparison: dict[str, Any],
    *,
    scope: str = "potential_watch",
    horizon: int = 10,
    lookback_months: int = 3,
    min_latest_samples: int = 3,
    min_recent_samples: int = 5,
    min_upgrade_avg_return: float = 0.03,
) -> dict[str, Any]:
    rows = _scope_monthly_style_guarded_rows(
        comparison,
        scope=scope,
        horizon=horizon,
    )
    scope_label = _SCOPE_LABELS.get(scope, scope)
    if not rows:
        return {
            "scope": scope,
            "horizon": horizon,
            "lookback_months": 0,
            "summary": f"{scope_label}缺少月度风格回放，暂不允许按风格升级。",
            "rows": [],
            "upgrade_styles": [],
            "observe_styles": [],
            "stand_down_styles": [],
        }

    gate_rows: list[dict[str, Any]] = []
    for style in sorted({row["style"] for row in rows}):
        style_rows = [row for row in rows if row["style"] == style]
        recent_rows = style_rows[-lookback_months:]
        latest = recent_rows[-1]
        recent_sample_count = sum(int(row["sample_count"] or 0) for row in recent_rows)
        recent_total_return = round(
            sum(float(row["total_return"] or 0.0) for row in recent_rows),
            6,
        )
        recent_avg_return = (
            round(recent_total_return / recent_sample_count, 6)
            if recent_sample_count > 0
            else None
        )
        positive_months = sum(
            1
            for row in recent_rows
            if (row["avg_return"] or 0.0) > 0.0 and (row["total_return"] or 0.0) > 0.0
        )
        negative_months = len(recent_rows) - positive_months
        latest_is_positive = (
            (latest["avg_return"] or 0.0) > 0.0
            and (latest["total_return"] or 0.0) > 0.0
        )
        sample_ready = (
            int(latest["sample_count"] or 0) >= min_latest_samples
            and recent_sample_count >= min_recent_samples
        )
        if (
            latest_is_positive
            and sample_ready
            and recent_total_return > 0.0
            and (latest["avg_return"] or 0.0) >= min_upgrade_avg_return
        ):
            status = "upgrade_allowed"
            status_label = "允许潜力升级"
            summary = (
                f"{latest['month']} {latest['label']}风格{horizon}日均值"
                f"{_format_pct(latest['avg_return'])}，样本{latest['sample_count']}；"
                f"允许从{scope_label}升级为Web重点和盘中验证，不代表买点，不自动进入钉钉核心。"
            )
        elif latest_is_positive or recent_total_return > 0.0:
            status = "observe_only"
            status_label = "只观察"
            summary = (
                f"{latest['label']}风格近期有修复，但样本或收益强度不足，"
                "只放Web观察，不作为升级门控。"
            )
        else:
            status = "stand_down"
            status_label = "休息"
            summary = (
                f"{latest['label']}风格最近{horizon}日回放不占优，"
                "潜力观察不升级，等下一轮风格回放确认。"
            )
        gate_rows.append(
            {
                "style": style,
                "label": latest["label"],
                "status": status,
                "status_label": status_label,
                "latest_month": latest["month"],
                "latest_sample_count": latest["sample_count"],
                "latest_avg_return": latest["avg_return"],
                "latest_win_rate": latest["win_rate"],
                "latest_total_return": latest["total_return"],
                "recent_months": len(recent_rows),
                "recent_sample_count": recent_sample_count,
                "recent_avg_return": recent_avg_return,
                "recent_total_return": recent_total_return,
                "positive_months": positive_months,
                "negative_months": negative_months,
                "summary": summary,
            }
        )

    status_order = {"upgrade_allowed": 0, "observe_only": 1, "stand_down": 2}
    gate_rows.sort(
        key=lambda row: (
            status_order.get(str(row["status"]), 9),
            -(row["latest_avg_return"] or -999.0),
            -(row["latest_total_return"] or -999.0),
        )
    )
    return {
        "scope": scope,
        "horizon": horizon,
        "lookback_months": lookback_months,
        "summary": (
            f"按{scope_label}最近月度风格回放做动态门控；"
            "允许升级只代表Web重点和盘中验证，不代表买点，不代表直接进入钉钉核心。"
        ),
        "rows": gate_rows,
        "upgrade_styles": [
            row["style"] for row in gate_rows if row["status"] == "upgrade_allowed"
        ],
        "observe_styles": [row["style"] for row in gate_rows if row["status"] == "observe_only"],
        "stand_down_styles": [row["style"] for row in gate_rows if row["status"] == "stand_down"],
    }


def diagnose_overfit_guardrails(
    comparison: dict[str, Any],
    *,
    horizon: int,
) -> list[str]:
    guardrails: list[str] = []
    for scope in ("potential_watch",):
        rows = _scope_monthly_guarded_rows(comparison, scope=scope, horizon=horizon)
        if len(rows) < 2:
            continue
        latest = rows[-1]
        previous_rows = rows[:-1]
        latest_total = latest["total_return"] or 0.0
        had_weak_month = any((row["total_return"] or 0.0) <= 0.0 for row in previous_rows)
        if latest_total > 0.0 and had_weak_month:
            label = _SCOPE_LABELS.get(scope, scope)
            weak_months = [
                f"{row['month']} {_format_pct(row['total_return'])}"
                for row in previous_rows
                if (row["total_return"] or 0.0) <= 0.0
            ]
            guardrails.append(
                f"{label}最近月份转强，但此前月份不稳（{', '.join(weak_months)}），"
                "只能作为Web观察和盘中确认，不升级为钉钉核心规则。"
            )
    return guardrails


def diagnose_tactical_opportunities(
    comparison: dict[str, Any],
    *,
    horizons: tuple[int, ...] = (5, 10),
    min_samples: int = 5,
) -> list[str]:
    opportunities: list[str] = []
    for horizon in horizons:
        rows = _scope_monthly_guarded_rows(
            comparison,
            scope="potential_watch",
            horizon=horizon,
        )
        if len(rows) < 2:
            continue
        latest = rows[-1]
        if latest["sample_count"] < min_samples:
            continue
        latest_total = latest["total_return"] or 0.0
        latest_avg = latest["avg_return"] or 0.0
        previous_weak_rows = [
            row for row in rows[:-1] if (row["total_return"] or 0.0) <= 0.0
        ]
        if latest_total <= 0.0 or latest_avg <= 0.0 or not previous_weak_rows:
            continue
        latest_month = latest["month"]
        previous_text = "，".join(
            f"{row['month']} {_format_pct(row['total_return'])}"
            for row in previous_weak_rows[-2:]
        )
        opportunities.append(
            f"{latest_month} 潜力观察池{horizon}日表现转强："
            f"总收益{_format_pct(latest_total)}，均值{_format_pct(latest_avg)}，"
            f"样本{latest['sample_count']}；此前弱月{previous_text}。"
            "这类机会只做Web重点观察和盘中确认，不升级为钉钉核心。"
        )
    return opportunities


def diagnose_potential_watch_policy(
    comparison: dict[str, Any],
    *,
    horizons: tuple[int, ...] = (5, 10),
    min_samples: int = 5,
) -> dict[str, Any]:
    latest_positive: list[dict[str, Any]] = []
    latest_negative: list[dict[str, Any]] = []
    for horizon in horizons:
        rows = _scope_monthly_guarded_rows(
            comparison,
            scope="potential_watch",
            horizon=horizon,
        )
        if not rows:
            continue
        latest = {**rows[-1], "horizon": horizon}
        if latest["sample_count"] < min_samples:
            continue
        if (latest["total_return"] or 0.0) > 0.0 and (latest["avg_return"] or 0.0) > 0.0:
            latest["previous_weak_rows"] = [
                row for row in rows[:-1] if (row["total_return"] or 0.0) <= 0.0
            ]
            latest_positive.append(latest)
        else:
            latest_negative.append(latest)

    if latest_positive:
        best = max(
            latest_positive,
            key=lambda item: (
                item["avg_return"] or -999.0,
                item["total_return"] or -999.0,
            ),
        )
        label = "盘中重点观察" if best["previous_weak_rows"] else "继续验证"
        status = "tactical_watch" if best["previous_weak_rows"] else "validate_watch"
        context = (
            "但此前月份不稳，"
            if best["previous_weak_rows"]
            else "但跨月稳定性还要继续验证，"
        )
        return {
            "status": status,
            "label": label,
            "month": best["month"],
            "horizon": best["horizon"],
            "sample_count": best["sample_count"],
            "avg_return": best["avg_return"],
            "total_return": best["total_return"],
            "summary": (
                f"{best['month']} 潜力观察池{best['horizon']}日收益转强，"
                f"总收益{_format_pct(best['total_return'])}，"
                f"均值{_format_pct(best['avg_return'])}，样本{best['sample_count']}；"
                f"{context}只做Web重点观察和盘中确认，不升级为钉钉核心。"
            ),
        }

    if latest_negative:
        latest = latest_negative[-1]
        return {
            "status": "stand_down",
            "label": "暂停升级",
            "month": latest["month"],
            "horizon": latest["horizon"],
            "sample_count": latest["sample_count"],
            "avg_return": latest["avg_return"],
            "total_return": latest["total_return"],
            "summary": (
                f"{latest['month']} 潜力观察池{latest['horizon']}日收益不佳，"
                "继续留在Web观察，不做盘中重点升级。"
            ),
        }

    return {
        "status": "insufficient_data",
        "label": "样本不足",
        "month": None,
        "horizon": None,
        "sample_count": 0,
        "avg_return": None,
        "total_return": None,
        "summary": "潜力观察池样本不足，先不调整盘中节奏。",
    }


def diagnose_monthly_replay_posture(
    comparison: dict[str, Any],
    *,
    horizon: int,
) -> dict[str, Any]:
    months = _month_candidates(comparison, horizon=horizon)
    if not months:
        return {
            "month": None,
            "posture": "insufficient_data",
            "posture_label": "样本不足",
            "summary": "最近完整月份样本不足，先不调整节奏。",
            "scope_rows": [],
            "reasons": ["没有足够的月度样本支持节奏判断。"],
        }

    month = months[-1]
    rows = []
    for scope in ("action_long", "action", "all"):
        metric = _monthly_guarded_metric(
            comparison,
            scope=scope,
            month=month,
            horizon=horizon,
        )
        rows.append(
            {
                "scope": scope,
                "label": _SCOPE_LABELS.get(scope, scope),
                "metric_label": _monthly_metric_label(
                    (comparison.get("scopes") or {}).get(scope) or {},
                    horizon,
                ),
                "sample_count": int(metric.get("sample_count") or 0),
                "avg_return": _metric_float(metric, "avg_return"),
                "win_rate": _metric_float(metric, "win_rate"),
                "total_return": _metric_float(metric, "total_return"),
            }
        )

    totals = {row["scope"]: row["total_return"] for row in rows}
    all_total = totals.get("all")
    action_total = totals.get("action")
    long_total = totals.get("action_long")
    if (all_total or 0.0) < 0 and (action_total or 0.0) < 0 and (long_total or 0.0) > 0:
        posture = "tighten_core"
        posture_label = "核心收敛"
        summary = (
            "扩池和普通行动池在最近完整月份拖累收益，长期行动池仍为正，"
            "盘中和钉钉都应收敛到少数核心。"
        )
    elif (all_total or 0.0) > 0 and (action_total or 0.0) <= 0:
        posture = "web_expansion_watch"
        posture_label = "扩散只看 Web"
        summary = "全候选池更强但行动池没有跟上，说明扩散机会存在，先放 Web 观察，不直接扩大钉钉。"
    elif max((all_total or 0.0), (action_total or 0.0), (long_total or 0.0)) <= 0:
        posture = "risk_off"
        posture_label = "降低频率"
        summary = "三个池子最近完整月份都没有正向收益，优先降低交易频率和仓位。"
    else:
        posture = "balanced_follow"
        posture_label = "顺势跟随"
        summary = "最近完整月份没有明显扩池拖累，继续按板块主线和趋势质量顺势筛选。"

    reasons = [
        (
            f"{month} {row['label']}：{row.get('metric_label', '样本合计')}{horizon}日总收益"
            f"{_format_pct(row['total_return'])}，均值{_format_pct(row['avg_return'])}，"
            f"样本{row['sample_count']}"
        )
        for row in rows
    ]
    return {
        "month": month,
        "posture": posture,
        "posture_label": posture_label,
        "summary": summary,
        "scope_rows": rows,
        "reasons": reasons,
    }


def diagnose_market_phase_policy(
    comparison: dict[str, Any],
    *,
    horizon: int,
    lookback_months: int = 3,
    min_month_samples: int = 20,
    min_portfolio_month_samples: int = 3,
) -> dict[str, Any]:
    rows = [
        row
        for row in _scope_monthly_guarded_rows(
            comparison,
            scope="all",
            horizon=horizon,
        )
        if int(row.get("sample_count") or 0)
        >= (
            min_portfolio_month_samples
            if row.get("metric_label") == "3只等权"
            else min_month_samples
        )
    ]
    if not rows:
        return {
            "status": "insufficient_data",
            "label": "阶段样本不足",
            "lookback_months": 0,
            "strong_months": 0,
            "weak_months": 0,
            "expansion_allowed": False,
            "max_core_positions": 1,
            "summary": "近月全候选池样本不足，阶段开关先保持防守，不据此放宽策略。",
            "reasons": ["没有足够的月度样本判断市场阶段。"],
        }

    recent_rows = rows[-lookback_months:]
    latest = recent_rows[-1]
    strong_rows = [
        row
        for row in recent_rows
        if (row["total_return"] or 0.0) > 0.0 and (row["avg_return"] or 0.0) > 0.0
    ]
    weak_rows = [row for row in recent_rows if row not in strong_rows]
    latest_is_strong = latest in strong_rows

    if latest_is_strong and len(strong_rows) >= 2:
        status = "trend_follow"
        label = "顺势阶段"
        expansion_allowed = True
        max_core_positions = 3
        summary = (
            "最近有效月份连续转强，允许顺势跟随；钉钉仍只推核心，"
            "Web 可展示扩散观察池。"
        )
    elif latest_is_strong:
        status = "rebound_watch"
        label = "反弹观察"
        expansion_allowed = False
        max_core_positions = 2
        summary = "最新月份转强但连续性不足，先观察反弹质量，不直接扩大钉钉行动池。"
    elif len(weak_rows) >= 2:
        status = "risk_off"
        label = "防守阶段"
        expansion_allowed = False
        max_core_positions = 1
        summary = "最近有效窗口出现连续弱月，优先防守，核心仓位收缩到极少数。"
    else:
        status = "selective_core"
        label = "精选阶段"
        expansion_allowed = False
        max_core_positions = 2
        summary = "阶段信号不够顺畅，只做精选核心，不扩大候选池。"

    reasons = [
        (
            f"{row['month']} 全候选池：{row.get('metric_label', '样本合计')}{horizon}日总收益"
            f"{_format_pct(row['total_return'])}，均值{_format_pct(row['avg_return'])}，"
            f"样本{row['sample_count']}"
        )
        for row in recent_rows
    ]
    return {
        "status": status,
        "label": label,
        "lookback_months": len(recent_rows),
        "strong_months": len(strong_rows),
        "weak_months": len(weak_rows),
        "expansion_allowed": expansion_allowed,
        "max_core_positions": max_core_positions,
        "summary": summary,
        "reasons": reasons,
    }


def _best_main_line_scope(comparison: dict[str, Any], *, horizon: int) -> dict[str, Any]:
    rows = [
        _scope_diagnosis_row(scope, (comparison.get("scopes") or {}).get(scope) or {}, horizon)
        for scope in ("action_long", "action")
    ]
    eligible_rows = [row for row in rows if row["sample_count"] > 0] or rows
    return max(
        eligible_rows,
        key=lambda row: (
            row["avg_return"] if row["avg_return"] is not None else -999.0,
            row["total_return"] if row["total_return"] is not None else -999.0,
        ),
    )


def diagnose_dual_line_policy(
    comparison: dict[str, Any],
    *,
    horizon: int,
    market_phase_policy: dict[str, Any],
    potential_watch_policy: dict[str, Any],
) -> dict[str, Any]:
    main_row = _best_main_line_scope(comparison, horizon=horizon)
    main_is_positive = (
        (main_row["avg_return"] or 0.0) > 0.0
        and (main_row["total_return"] or 0.0) > 0.0
        and int(main_row["sample_count"] or 0) > 0
    )
    phase_status = str(market_phase_policy.get("status") or "")
    support_status = str(potential_watch_policy.get("status") or "")
    support_is_ready = support_status in {"tactical_watch", "validate_watch"}

    if phase_status == "trend_follow" and main_is_positive:
        active_line = "main_trend"
        ding_policy = "ding_core_main_line"
        max_core_positions = int(market_phase_policy.get("max_core_positions") or 3)
        main_status = "core_enabled"
        support_line_status = "monitor_only"
        summary = (
            "主线生效：强板块趋势和行动池收益同向，钉钉只推主线核心，"
            "辅线继续在 Web 监控。"
        )
    elif phase_status in {"risk_off", "selective_core", "rebound_watch"} and support_is_ready:
        active_line = "support_preheat"
        ding_policy = "web_support_only"
        max_core_positions = 0
        main_status = "paused"
        support_line_status = "web_preheat"
        summary = (
            "主线暂停：阶段未进入顺势，辅线只做 Web 预热和盘中验证，"
            "不进入钉钉核心。"
        )
    elif main_is_positive and phase_status != "risk_off":
        active_line = "main_selective"
        ding_policy = "ding_core_selective"
        max_core_positions = min(2, int(market_phase_policy.get("max_core_positions") or 2))
        main_status = "selective_core"
        support_line_status = "monitor_only"
        summary = "主线可小仓精选，但阶段连续性不足，不扩大行动池。"
    else:
        active_line = "cash_defense"
        ding_policy = "hold"
        max_core_positions = 0
        main_status = "paused"
        support_line_status = "stand_down"
        summary = "两条线都没有足够确认，优先防守和复盘，不新增核心票。"

    return {
        "active_line": active_line,
        "ding_policy": ding_policy,
        "max_core_positions": max_core_positions,
        "summary": summary,
        "main_line": {
            "name": "强板块趋势线",
            "status": main_status,
            "scope": main_row["scope"],
            "label": main_row["label"],
            "sample_count": main_row["sample_count"],
            "avg_return": main_row["avg_return"],
            "total_return": main_row["total_return"],
            "summary": (
                f"{main_row['label']} {main_row.get('metric_label', '样本合计')}"
                f"{horizon}日均值{_format_pct(main_row['avg_return'])}，"
                f"总收益{_format_pct(main_row['total_return'])}，样本{main_row['sample_count']}。"
            ),
        },
        "support_line": {
            "name": "弱市抗跌/轮动预热线",
            "status": support_line_status,
            "month": potential_watch_policy.get("month"),
            "horizon": potential_watch_policy.get("horizon"),
            "sample_count": potential_watch_policy.get("sample_count"),
            "avg_return": potential_watch_policy.get("avg_return"),
            "total_return": potential_watch_policy.get("total_return"),
            "summary": potential_watch_policy.get("summary"),
        },
        "rules": [
            "主线只在顺势阶段承接钉钉核心。",
            "辅线只做 Web 预热和盘中确认，不自动升级为钉钉核心。",
            "阶段不确认时，宁可少做，不靠扩池弥补收益。",
        ],
    }


def diagnose_candidate_replay_effect(
    comparison: dict[str, Any],
    *,
    horizon: int = 20,
    min_primary_samples: int = 5,
) -> dict[str, Any]:
    scope_rows = [
        _scope_diagnosis_row(scope, summary, horizon)
        for scope, summary in (comparison.get("scopes") or {}).items()
    ]
    policy_rows = [row for row in scope_rows if row["scope"] in _PRIMARY_POLICY_SCOPES]
    eligible_rows = [
        row
        for row in policy_rows
        if row["sample_count"] >= _required_primary_samples(row, min_primary_samples)
    ] or policy_rows
    primary = max(
        eligible_rows,
        key=lambda row: (
            row["avg_return"] if row["avg_return"] is not None else -999.0,
            row["total_return"] if row["total_return"] is not None else -999.0,
        ),
        default={
            "scope": "none",
            "label": "暂无有效样本",
            "candidate_count": 0,
            "sample_count": 0,
            "avg_return": None,
            "win_rate": None,
            "total_return": None,
        },
    )

    scope = str(primary["scope"])
    if scope == "action_long":
        policy_label = "核心少量行动"
        ding_policy = "ding_core_only"
        summary_text = "长期行动池收益质量最好，钉钉继续只推少数核心票，扩散机会留在 Web 观察。"
    elif scope == "action":
        policy_label = "行动池跟随"
        ding_policy = "ding_action_selective"
        summary_text = "钉钉行动池仍有正向效果，但需要继续控制数量和板块集中度。"
    elif scope == "all":
        policy_label = "扩池只观察"
        ding_policy = "web_observe_only"
        summary_text = "全候选池贡献更高但噪音也更大，适合 Web 复盘，不宜直接扩大钉钉。"
    else:
        policy_label = "样本不足"
        ding_policy = "hold"
        summary_text = "当前样本不足，先保持观察，不把诊断写成硬规则。"

    ranked_rows = sorted(
        scope_rows,
        key=lambda row: (
            row["avg_return"] if row["avg_return"] is not None else -999.0,
            row["total_return"] if row["total_return"] is not None else -999.0,
        ),
        reverse=True,
    )
    reasons = [
        (
            f"{row['label']}：{row.get('metric_label', '样本合计')}{horizon}日均值"
            f"{_format_pct(row['avg_return'])}，"
            f"总收益{_format_pct(row['total_return'])}，样本{row['sample_count']}"
        )
        for row in ranked_rows[:3]
    ]
    potential_watch_policy = diagnose_potential_watch_policy(comparison)
    market_phase_policy = diagnose_market_phase_policy(
        comparison,
        horizon=horizon,
    )
    return {
        "horizon": horizon,
        "primary_scope": scope,
        "primary_scope_label": primary["label"],
        "policy_label": policy_label,
        "ding_policy": ding_policy,
        "summary": summary_text,
        "scope_rows": ranked_rows,
        "reasons": reasons,
        "overfit_guardrails": diagnose_overfit_guardrails(comparison, horizon=horizon),
        "tactical_opportunities": diagnose_tactical_opportunities(comparison),
        "potential_watch_policy": potential_watch_policy,
        "startup_preheat_policy": diagnose_style_gate_policy(
            comparison,
            scope="startup_preheat",
            horizon=5,
            min_latest_samples=3,
            min_recent_samples=5,
            min_upgrade_avg_return=0.02,
        ),
        "market_phase_policy": market_phase_policy,
        "dual_line_policy": diagnose_dual_line_policy(
            comparison,
            horizon=horizon,
            market_phase_policy=market_phase_policy,
            potential_watch_policy=potential_watch_policy,
        ),
        "style_gate_policy": diagnose_style_gate_policy(comparison),
        "monthly_posture": diagnose_monthly_replay_posture(comparison, horizon=horizon),
    }


@router.get("")
def list_rules() -> list[dict[str, object]]:
    return [rule.model_dump() for rule in MVP_RULES]


@router.get("/strategy-fit")
def get_strategy_fit(
    db: DbSession,
    report_date: str | None = None,
    rule_id: str | None = None,
    min_samples: Annotated[int, Query(ge=1, le=100)] = 1,
    per_scope_limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    return load_strategy_fit_report(
        db,
        report_date=report_date,
        rule_id=rule_id,
        min_samples=min_samples,
        per_scope_limit=per_scope_limit,
    ).to_dict()


@router.get("/low-dimensional-replay")
def get_low_dimensional_replay(
    start_date: str = DEFAULT_REPLAY_START_DATE,
    end_date: str | None = None,
    limit: Annotated[int, Query(ge=1, le=5)] = 3,
    min_coverage_ratio: Annotated[float, Query(ge=0.0, le=1.0)] = 0.70,
) -> dict:
    resolved_end_date = end_date or (now_local().date() - timedelta(days=1)).isoformat()
    horizons = (5, 10, 20)
    result = run_low_dimensional_walk_forward_replay(
        start_date=start_date,
        end_date=resolved_end_date,
        limit=limit,
        horizons=horizons,
        min_coverage_ratio=min_coverage_ratio,
    )
    return {
        **summarize_walk_forward_replay(result, horizons=horizons),
        "data_coverage": build_replay_data_coverage_report(
            start_date=start_date,
            end_date=resolved_end_date,
        ),
    }


@router.get("/candidate-replay-effect")
def get_candidate_replay_effect(
    start_date: str = DEFAULT_REPLAY_START_DATE,
    end_date: str | None = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 15,
    min_coverage_ratio: Annotated[float, Query(ge=0.0, le=1.0)] = 0.70,
    include_fundamentals: bool = False,
) -> dict:
    resolved_end_date = end_date or (now_local().date() - timedelta(days=1)).isoformat()
    horizons = (1, 5, 10, 20)
    comparison = compare_candidate_walk_forward_scopes(
        start_date=start_date,
        end_date=resolved_end_date,
        scopes=("all", "action", "action_long", "potential_watch", "startup_preheat"),
        limit=limit,
        horizons=horizons,
        min_coverage_ratio=min_coverage_ratio,
        include_fundamentals=include_fundamentals,
    )
    return {
        **comparison,
        "data_coverage": build_replay_data_coverage_report(
            start_date=start_date,
            end_date=resolved_end_date,
        ),
        "diagnosis": diagnose_candidate_replay_effect(comparison, horizon=20),
    }
