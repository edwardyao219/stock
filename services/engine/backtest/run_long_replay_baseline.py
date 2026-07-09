from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import case, func, select

from services.engine.backtest.walk_forward import (
    NOISE_WALK_FORWARD_SYMBOLS,
    WalkForwardCandidate,
    WalkForwardReplayResult,
    run_candidate_walk_forward_replay,
)
from services.shared.database import SessionLocal, require_primary_database
from services.shared.models import LowDimensionalFeatureSnapshot

ADAPTIVE_GUARD_PARAMETERS = {
    "action": (0.04, 0.06),
    "action_long": (0.04, 0.06),
    "sector_watch": (0.06, 0.08),
    "potential_watch": (0.06, 0.08),
    "startup_preheat": (0.06, 0.08),
    "startup_confirmed": (0.04, 0.06),
}

DRAWDOWN15_GUARD_PARAMETERS = {
    "action": (0.04, 0.05),
    "action_long": (0.04, 0.06),
    "sector_watch": (0.05, 0.05),
    "potential_watch": (0.06, 0.08),
    "startup_preheat": (0.04, 0.06),
    "startup_confirmed": (0.03, 0.06),
}

DEFAULT_RANK_SCOPES = (
    "action",
    "action_long",
    "sector_watch",
    "potential_watch",
    "startup_preheat",
    "startup_confirmed",
)
DEFAULT_RANK_PRESETS = ("adaptive", "drawdown15")
MARKET_STATE_GATE_PRESETS: tuple[tuple[str, set[str] | None], ...] = (
    ("全部", None),
    ("排除risk_off", {"risk_on", "neutral", "缺数据"}),
    ("risk_on+neutral", {"risk_on", "neutral"}),
    ("仅risk_on", {"risk_on"}),
)
MARKET_STATE_ORDER = {"risk_on": 0, "neutral": 1, "risk_off": 2, "缺数据": 3}


def resolve_guard_parameters(
    *,
    candidate_scope: str,
    guard_preset: str,
    stop_loss_pct: float,
    trailing_drawdown_pct: float,
) -> tuple[float, float]:
    if guard_preset == "fixed":
        return stop_loss_pct, trailing_drawdown_pct
    if guard_preset == "adaptive":
        return ADAPTIVE_GUARD_PARAMETERS.get(
            candidate_scope,
            (stop_loss_pct, trailing_drawdown_pct),
        )
    if guard_preset == "drawdown15":
        return DRAWDOWN15_GUARD_PARAMETERS.get(
            candidate_scope,
            (stop_loss_pct, trailing_drawdown_pct),
        )
    raise ValueError(f"Unsupported guard_preset: {guard_preset}")


def _candidate_return(
    candidate: WalkForwardCandidate,
    *,
    horizon: int,
    guarded: bool,
) -> float | None:
    values = candidate.guarded_forward_returns if guarded else candidate.forward_returns
    value = values.get(horizon)
    return float(value) if value is not None else None


def _max_drawdown(month_returns: list[float]) -> float:
    peak = 0.0
    cumulative = 0.0
    worst = 0.0
    for value in month_returns:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return round(worst, 6)


def summarize_replay_baseline(
    result: WalkForwardReplayResult,
    *,
    horizon: int,
    guarded: bool = False,
) -> dict[str, Any]:
    month_returns: dict[str, list[float]] = defaultdict(list)
    month_signal_days: dict[str, set[str]] = defaultdict(set)
    candidate_returns: list[dict[str, Any]] = []

    for day in result.days:
        month = day.signal_date[:7]
        for candidate in day.candidates:
            if candidate.symbol in NOISE_WALK_FORWARD_SYMBOLS:
                continue
            value = _candidate_return(candidate, horizon=horizon, guarded=guarded)
            if value is None:
                continue
            month_returns[month].append(value)
            month_signal_days[month].add(day.signal_date)
            candidate_returns.append(
                {
                    "signal_date": day.signal_date,
                    "month": month,
                    "return": value,
                }
            )

    months: list[dict[str, Any]] = []
    monthly_values: list[float] = []
    for month in sorted(month_returns):
        values = month_returns[month]
        month_return = round(sum(values) / len(values), 6)
        monthly_values.append(month_return)
        months.append(
            {
                "month": month,
                "signal_days": len(month_signal_days[month]),
                "candidate_count": len(values),
                "win_rate": round(sum(1 for value in values if value > 0) / len(values), 6),
                "month_return": month_return,
                "signal_dates": sorted(month_signal_days[month]),
            }
        )

    return {
        "start_date": result.start_date,
        "end_date": result.end_date,
        "horizon": horizon,
        "return_type": "guarded" if guarded else "raw",
        "processed_days": result.processed_days,
        "month_count": len(months),
        "candidate_count": sum(item["candidate_count"] for item in months),
        "total_return": round(sum(monthly_values), 6) if monthly_values else 0.0,
        "max_drawdown": _max_drawdown(monthly_values),
        "months": months,
        "candidate_returns": candidate_returns,
    }


def annotate_drawdown_limit(
    summary: dict[str, Any],
    *,
    max_drawdown_limit_pct: float,
) -> dict[str, Any]:
    limit = abs(max_drawdown_limit_pct)
    max_drawdown = float(summary["max_drawdown"])
    return {
        **summary,
        "max_drawdown_limit_pct": limit,
        "max_drawdown_passed": max_drawdown >= -limit,
    }


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def format_replay_baseline(summary: dict[str, Any]) -> str:
    lines = [
        (
            f"长回归基线 {summary['start_date']} -> {summary['end_date']} "
            f"H{summary['horizon']} {summary['return_type']} "
            f"止损{_pct(float(summary.get('stop_loss_pct') or 0.0))} "
            f"回撤{_pct(float(summary.get('trailing_drawdown_pct') or 0.0))}"
        ),
        (
            f"总收益(不复利) {_pct(float(summary['total_return']))} | "
            f"最大回撤 {_pct(float(summary['max_drawdown']))} "
            f"(目标≤{_pct(float(summary.get('max_drawdown_limit_pct') or 0.15))} "
            f"{'达标' if summary.get('max_drawdown_passed') else '超标'}) | "
            f"候选 {summary['candidate_count']} | 月份 {summary['month_count']}"
        ),
        "月份 | 信号日 | 候选 | 胜率 | 月收益",
    ]
    for item in summary["months"]:
        lines.append(
            " | ".join(
                [
                    str(item["month"]),
                    str(item["signal_days"]),
                    str(item["candidate_count"]),
                    _pct(float(item["win_rate"])),
                    _pct(float(item["month_return"])),
                ]
            )
        )
    return "\n".join(lines)


def run_replay_baseline(
    *,
    start_date: str,
    end_date: str,
    horizon: int,
    limit: int,
    candidate_scope: str,
    guarded: bool,
    min_coverage_ratio: float,
    include_fundamentals: bool,
    stop_loss_pct: float,
    trailing_drawdown_pct: float,
    guard_preset: str = "fixed",
    max_drawdown_limit_pct: float = 0.15,
) -> dict[str, Any]:
    effective_stop_loss_pct, effective_trailing_drawdown_pct = resolve_guard_parameters(
        candidate_scope=candidate_scope,
        guard_preset=guard_preset,
        stop_loss_pct=stop_loss_pct,
        trailing_drawdown_pct=trailing_drawdown_pct,
    )
    result = run_candidate_walk_forward_replay(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        horizons=(horizon,),
        min_coverage_ratio=min_coverage_ratio,
        include_fundamentals=include_fundamentals,
        candidate_scope=candidate_scope,
        stop_loss_pct=effective_stop_loss_pct,
        trailing_drawdown_pct=effective_trailing_drawdown_pct,
    )
    summary = {
        **summarize_replay_baseline(result, horizon=horizon, guarded=guarded),
        "guard_preset": guard_preset,
        "stop_loss_pct": effective_stop_loss_pct,
        "trailing_drawdown_pct": effective_trailing_drawdown_pct,
    }
    return annotate_drawdown_limit(
        summary,
        max_drawdown_limit_pct=max_drawdown_limit_pct,
    )


def rank_replay_baselines(
    *,
    start_date: str,
    end_date: str,
    horizon: int,
    limit: int,
    candidate_scopes: list[str],
    guard_presets: list[str],
    guarded: bool,
    min_coverage_ratio: float,
    include_fundamentals: bool,
    stop_loss_pct: float,
    trailing_drawdown_pct: float,
    max_drawdown_limit_pct: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate_scope in candidate_scopes:
        for guard_preset in guard_presets:
            summary = run_replay_baseline(
                start_date=start_date,
                end_date=end_date,
                horizon=horizon,
                limit=limit,
                candidate_scope=candidate_scope,
                guarded=guarded,
                min_coverage_ratio=min_coverage_ratio,
                include_fundamentals=include_fundamentals,
                stop_loss_pct=stop_loss_pct,
                trailing_drawdown_pct=trailing_drawdown_pct,
                guard_preset=guard_preset,
                max_drawdown_limit_pct=max_drawdown_limit_pct,
            )
            rows.append(
                {
                    **summary,
                    "candidate_scope": candidate_scope,
                    "guard_preset": guard_preset,
                }
            )
    return sorted(
        rows,
        key=lambda item: (
            not bool(item["max_drawdown_passed"]),
            -float(item["total_return"]),
            float(item["max_drawdown"]),
        ),
    )


def format_ranked_replay_baselines(rows: list[dict[str, Any]]) -> str:
    lines = [
        "回撤约束排名",
        "范围 | 预设 | 回撤目标 | 总收益 | 最大回撤 | 止损/回撤 | 候选 | 月份",
    ]
    for item in rows:
        lines.append(
            " | ".join(
                [
                    str(item["candidate_scope"]),
                    str(item["guard_preset"]),
                    "达标" if item.get("max_drawdown_passed") else "超标",
                    _pct(float(item["total_return"])),
                    _pct(float(item["max_drawdown"])),
                    (
                        f"{_pct(float(item.get('stop_loss_pct') or 0.0))}/"
                        f"{_pct(float(item.get('trailing_drawdown_pct') or 0.0))}"
                    ),
                    str(item["candidate_count"]),
                    str(item["month_count"]),
                ]
            )
        )
    return "\n".join(lines)


def format_ranked_replay_months(
    rows: list[dict[str, Any]],
    *,
    top_n: int,
) -> str:
    lines = [f"月度拆解 Top {top_n}"]
    for item in rows[: max(0, top_n)]:
        lines.append(
            f"{item['candidate_scope']}/{item['guard_preset']} "
            f"总收益{_pct(float(item['total_return']))} "
            f"最大回撤{_pct(float(item['max_drawdown']))}"
        )
        lines.append("月份 | 信号日 | 候选 | 胜率 | 月收益")
        for month in item.get("months") or []:
            lines.append(
                " | ".join(
                    [
                        str(month["month"]),
                        str(month["signal_days"]),
                        str(month["candidate_count"]),
                        _pct(float(month["win_rate"])),
                        _pct(float(month["month_return"])),
                    ]
                )
            )
    return "\n".join(lines)


def _max_loss_streak(months: list[dict[str, Any]]) -> int:
    longest = 0
    current = 0
    for month in months:
        if float(month.get("month_return") or 0.0) < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def diagnose_ranked_replay_losses(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for item in rows:
        months = list(item.get("months") or [])
        negative_months = [
            month for month in months if float(month.get("month_return") or 0.0) < 0
        ]
        worst = min(months, key=lambda month: float(month.get("month_return") or 0.0), default={})
        max_loss_streak = _max_loss_streak(months)
        if not item.get("max_drawdown_passed"):
            recommendation = "降级观察"
        elif max_loss_streak >= 3:
            recommendation = "需要行情门控"
        else:
            recommendation = "继续跟踪"
        diagnostics.append(
            {
                "candidate_scope": item["candidate_scope"],
                "guard_preset": item["guard_preset"],
                "negative_month_count": len(negative_months),
                "worst_month": worst.get("month"),
                "worst_month_return": float(worst.get("month_return") or 0.0),
                "max_loss_streak": max_loss_streak,
                "recommendation": recommendation,
            }
        )
    return diagnostics


def format_replay_loss_diagnostics(rows: list[dict[str, Any]]) -> str:
    lines = [
        "亏损月诊断",
        "范围 | 预设 | 负收益月 | 最差月 | 连续亏损月 | 建议",
    ]
    for item in rows:
        lines.append(
            " | ".join(
                [
                    str(item["candidate_scope"]),
                    str(item["guard_preset"]),
                    str(item["negative_month_count"]),
                    f"{item['worst_month']} {_pct(float(item['worst_month_return']))}",
                    str(item["max_loss_streak"]),
                    str(item["recommendation"]),
                ]
            )
        )
    return "\n".join(lines)


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 50.0


def _market_state(*, trend_score: float, breadth_score: float, emotion_score: float) -> str:
    if (trend_score <= 45.0 and breadth_score <= 45.0) or emotion_score <= 40.0:
        return "risk_off"
    if trend_score >= 55.0 and breadth_score >= 50.0 and emotion_score >= 50.0:
        return "risk_on"
    return "neutral"


def summarize_market_context_by_month(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"trend": [], "breadth": [], "emotion": []}
    )
    for row in rows:
        month = str(row["trade_date"])[:7]
        grouped[month]["trend"].append(float(row.get("trend_score") or 50.0))
        grouped[month]["breadth"].append(float(row.get("breadth_score") or 50.0))
        grouped[month]["emotion"].append(float(row.get("emotion_score") or 50.0))

    summary: dict[str, dict[str, Any]] = {}
    for month, values in grouped.items():
        trend_score = _average(values["trend"])
        breadth_score = _average(values["breadth"])
        emotion_score = _average(values["emotion"])
        summary[month] = {
            "trend_score": trend_score,
            "breadth_score": breadth_score,
            "emotion_score": emotion_score,
            "market_state": _market_state(
                trend_score=trend_score,
                breadth_score=breadth_score,
                emotion_score=emotion_score,
            ),
        }
    return summary


def _ranked_signal_dates(rows: list[dict[str, Any]]) -> list[str]:
    dates: set[str] = set()
    for item in rows:
        for month in item.get("months") or []:
            dates.update(str(value) for value in month.get("signal_dates") or [])
    return sorted(dates)


def load_market_context_by_signal_date(signal_dates: list[str]) -> dict[str, dict[str, Any]]:
    parsed_dates = sorted({date.fromisoformat(value) for value in signal_dates})
    if not parsed_dates:
        return {}

    emotion_expr = case(
        (LowDimensionalFeatureSnapshot.return_5d > 0, 1.0),
        (LowDimensionalFeatureSnapshot.return_5d <= 0, 0.0),
        else_=None,
    )
    with SessionLocal() as db:
        rows = db.execute(
            select(
                LowDimensionalFeatureSnapshot.trade_date,
                func.avg(LowDimensionalFeatureSnapshot.trend_score),
                func.avg(LowDimensionalFeatureSnapshot.sector_breadth_score),
                func.avg(emotion_expr) * 100.0,
            )
            .where(LowDimensionalFeatureSnapshot.trade_date.in_(parsed_dates))
            .group_by(LowDimensionalFeatureSnapshot.trade_date)
            .order_by(LowDimensionalFeatureSnapshot.trade_date)
        ).all()
    context_by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        trend_score = float(row[1] or 50.0)
        breadth_score = float(row[2] or 50.0)
        emotion_score = float(row[3] or 50.0)
        context_by_date[row[0].isoformat()] = {
            "trend_score": round(trend_score, 4),
            "breadth_score": round(breadth_score, 4),
            "emotion_score": round(emotion_score, 4),
            "market_state": _market_state(
                trend_score=trend_score,
                breadth_score=breadth_score,
                emotion_score=emotion_score,
            ),
        }
    return context_by_date


def load_market_context_by_signal_dates(signal_dates: list[str]) -> dict[str, dict[str, Any]]:
    return summarize_market_context_by_month(
        [
            {
                "trade_date": trade_date,
                "trend_score": context.get("trend_score"),
                "breadth_score": context.get("breadth_score"),
                "emotion_score": context.get("emotion_score"),
            }
            for trade_date, context in load_market_context_by_signal_date(signal_dates).items()
        ]
    )


def format_ranked_replay_market_context(
    rows: list[dict[str, Any]],
    market_context_by_month: dict[str, dict[str, Any]],
    *,
    top_n: int,
) -> str:
    lines = [f"行情状态诊断 Top {top_n}", "月份 | 月收益 | 状态 | 趋势 | 宽度 | 情绪"]
    for item in rows[: max(0, top_n)]:
        lines.append(f"{item['candidate_scope']}/{item['guard_preset']}")
        for month in item.get("months") or []:
            month_return = float(month.get("month_return") or 0.0)
            if month_return >= 0:
                continue
            context = market_context_by_month.get(str(month.get("month"))) or {}
            if not context:
                lines.append(
                    " | ".join(
                        [
                            str(month["month"]),
                            _pct(month_return),
                            "缺数据",
                            "趋势-",
                            "宽度-",
                            "情绪-",
                        ]
                    )
                )
                continue
            lines.append(
                " | ".join(
                    [
                        str(month["month"]),
                        _pct(month_return),
                        str(context.get("market_state") or "unknown"),
                        f"趋势{float(context.get('trend_score') or 0.0):.1f}",
                        f"宽度{float(context.get('breadth_score') or 0.0):.1f}",
                        f"情绪{float(context.get('emotion_score') or 0.0):.1f}",
                    ]
                )
            )
    return "\n".join(lines)


def summarize_ranked_replay_market_state_returns(
    rows: list[dict[str, Any]],
    market_context_by_month: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in rows:
        month_state_values: dict[tuple[str, str], list[float]] = defaultdict(list)
        candidate_returns = list(item.get("candidate_returns") or [])
        if candidate_returns:
            for candidate_return in candidate_returns:
                signal_date = str(candidate_return.get("signal_date"))
                month_key = str(candidate_return.get("month") or signal_date[:7])
                context = (
                    market_context_by_month.get(signal_date)
                    or market_context_by_month.get(month_key)
                    or {}
                )
                state = str(context.get("market_state") or "缺数据")
                month_state_values[(state, month_key)].append(
                    float(candidate_return.get("return") or 0.0)
                )
        else:
            for month in item.get("months") or []:
                month_key = str(month.get("month"))
                context = market_context_by_month.get(month_key) or {}
                state = str(context.get("market_state") or "缺数据")
                month_state_values[(state, month_key)].append(
                    float(month.get("month_return") or 0.0)
                )

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (state, month_key), values in month_state_values.items():
            grouped[state].append(
                {
                    "month": month_key,
                    "month_return": round(sum(values) / len(values), 6),
                }
            )

        states: list[dict[str, Any]] = []
        for state, months in sorted(
            grouped.items(),
            key=lambda pair: MARKET_STATE_ORDER.get(pair[0], 99),
        ):
            returns = [float(month.get("month_return") or 0.0) for month in months]
            worst = min(months, key=lambda month: float(month.get("month_return") or 0.0))
            states.append(
                {
                    "market_state": state,
                    "month_count": len(months),
                    "total_return": round(sum(returns), 6),
                    "average_return": round(sum(returns) / len(returns), 6),
                    "win_rate": round(sum(1 for value in returns if value > 0) / len(returns), 6),
                    "worst_month": worst.get("month"),
                    "worst_month_return": float(worst.get("month_return") or 0.0),
                }
            )
        summaries.append(
            {
                "candidate_scope": item["candidate_scope"],
                "guard_preset": item["guard_preset"],
                "states": states,
            }
        )
    return summaries


def summarize_ranked_replay_market_state_scope_matrix(
    rows: list[dict[str, Any]],
    market_context_by_period: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in rows:
        candidate_returns = list(item.get("candidate_returns") or [])
        states = sorted(
            {
                _candidate_market_state(candidate_return, market_context_by_period)
                for candidate_return in candidate_returns
            },
            key=lambda state: MARKET_STATE_ORDER.get(state, 99),
        )
        for state in states:
            filtered = [
                candidate_return
                for candidate_return in candidate_returns
                if _candidate_market_state(candidate_return, market_context_by_period) == state
            ]
            if not filtered:
                continue
            summary = _summarize_candidate_return_rows(filtered)
            grouped[state].append(
                {
                    "candidate_scope": item["candidate_scope"],
                    "guard_preset": item["guard_preset"],
                    **summary,
                }
            )

    matrix: list[dict[str, Any]] = []
    for state, state_rows in sorted(
        grouped.items(),
        key=lambda pair: MARKET_STATE_ORDER.get(pair[0], 99),
    ):
        matrix.append(
            {
                "market_state": state,
                "rows": sorted(
                    state_rows,
                    key=lambda row: (
                        -float(row["total_return"]),
                        -float(row["max_drawdown"]),
                        str(row["candidate_scope"]),
                    ),
                ),
            }
        )
    return matrix


def _candidate_market_state(
    candidate_return: dict[str, Any],
    market_context_by_period: dict[str, dict[str, Any]],
) -> str:
    signal_date = str(candidate_return.get("signal_date"))
    month_key = str(candidate_return.get("month") or signal_date[:7])
    context = (
        market_context_by_period.get(signal_date)
        or market_context_by_period.get(month_key)
        or {}
    )
    return str(context.get("market_state") or "缺数据")


def _filter_candidate_returns_by_allowed_states(
    candidate_returns: list[dict[str, Any]],
    market_context_by_period: dict[str, dict[str, Any]],
    allowed_states: set[str] | None,
) -> list[dict[str, Any]]:
    if allowed_states is None:
        return candidate_returns
    return [
        candidate_return
        for candidate_return in candidate_returns
        if _candidate_market_state(candidate_return, market_context_by_period) in allowed_states
    ]


def _summarize_candidate_return_rows(candidate_returns: list[dict[str, Any]]) -> dict[str, Any]:
    month_returns: dict[str, list[float]] = defaultdict(list)
    for candidate_return in candidate_returns:
        month = str(candidate_return.get("month") or str(candidate_return.get("signal_date"))[:7])
        month_returns[month].append(float(candidate_return.get("return") or 0.0))

    monthly_values = [
        round(sum(values) / len(values), 6)
        for month, values in sorted(month_returns.items())
        if values
    ]
    return {
        "candidate_count": len(candidate_returns),
        "month_count": len(monthly_values),
        "total_return": round(sum(monthly_values), 6) if monthly_values else 0.0,
        "max_drawdown": _max_drawdown(monthly_values),
    }


def simulate_ranked_replay_market_state_gates(
    rows: list[dict[str, Any]],
    market_context_by_period: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    simulations: list[dict[str, Any]] = []
    for item in rows:
        candidate_returns = list(item.get("candidate_returns") or [])
        gates: list[dict[str, Any]] = []
        for gate_name, allowed_states in MARKET_STATE_GATE_PRESETS:
            filtered = _filter_candidate_returns_by_allowed_states(
                candidate_returns,
                market_context_by_period,
                allowed_states,
            )
            gates.append({"gate": gate_name, **_summarize_candidate_return_rows(filtered)})
        simulations.append(
            {
                "candidate_scope": item["candidate_scope"],
                "guard_preset": item["guard_preset"],
                "gates": gates,
            }
        )
    return simulations


def _candidate_return_year(candidate_return: dict[str, Any]) -> int:
    signal_date = str(candidate_return.get("signal_date"))
    if signal_date:
        return int(signal_date[:4])
    return int(str(candidate_return.get("month"))[:4])


def _year_span(years: list[int]) -> str:
    if not years:
        return "-"
    return str(years[0]) if years[0] == years[-1] else f"{years[0]}-{years[-1]}"


def _select_best_gate(
    gate_summaries: list[dict[str, Any]],
    *,
    max_drawdown_limit_pct: float,
) -> dict[str, Any]:
    indexed = list(enumerate(gate_summaries))
    return max(
        indexed,
        key=lambda pair: (
            float(pair[1]["max_drawdown"]) >= -abs(max_drawdown_limit_pct),
            float(pair[1]["total_return"]),
            float(pair[1]["max_drawdown"]),
            -pair[0],
        ),
    )[1]


def validate_ranked_replay_market_state_gates(
    rows: list[dict[str, Any]],
    market_context_by_period: dict[str, dict[str, Any]],
    *,
    max_drawdown_limit_pct: float = 0.15,
) -> list[dict[str, Any]]:
    validations: list[dict[str, Any]] = []
    gate_lookup = dict(MARKET_STATE_GATE_PRESETS)
    for item in rows:
        candidate_returns = list(item.get("candidate_returns") or [])
        years = sorted(
            {_candidate_return_year(candidate_return) for candidate_return in candidate_returns}
        )
        windows: list[dict[str, Any]] = []
        for split_year in years[1:]:
            train_years = [year for year in years if year < split_year]
            test_years = [year for year in years if year >= split_year]
            train_rows = [
                candidate_return
                for candidate_return in candidate_returns
                if _candidate_return_year(candidate_return) < split_year
            ]
            test_rows = [
                candidate_return
                for candidate_return in candidate_returns
                if _candidate_return_year(candidate_return) >= split_year
            ]
            if not train_rows or not test_rows:
                continue

            train_gates = []
            for gate_name, allowed_states in MARKET_STATE_GATE_PRESETS:
                filtered = _filter_candidate_returns_by_allowed_states(
                    train_rows,
                    market_context_by_period,
                    allowed_states,
                )
                train_gates.append(
                    {"gate": gate_name, **_summarize_candidate_return_rows(filtered)}
                )
            selected_train = _select_best_gate(
                train_gates,
                max_drawdown_limit_pct=max_drawdown_limit_pct,
            )
            selected_test_rows = _filter_candidate_returns_by_allowed_states(
                test_rows,
                market_context_by_period,
                gate_lookup.get(str(selected_train["gate"])),
            )
            selected_test = _summarize_candidate_return_rows(selected_test_rows)
            baseline_test = _summarize_candidate_return_rows(test_rows)
            windows.append(
                {
                    "train": _year_span(train_years),
                    "test": _year_span(test_years),
                    "selected_gate": selected_train["gate"],
                    "train_total_return": selected_train["total_return"],
                    "train_max_drawdown": selected_train["max_drawdown"],
                    "test_total_return": selected_test["total_return"],
                    "test_max_drawdown": selected_test["max_drawdown"],
                    "baseline_test_total_return": baseline_test["total_return"],
                    "baseline_test_max_drawdown": baseline_test["max_drawdown"],
                    "test_delta_return": round(
                        float(selected_test["total_return"])
                        - float(baseline_test["total_return"]),
                        6,
                    ),
                    "test_drawdown_delta": round(
                        float(selected_test["max_drawdown"])
                        - float(baseline_test["max_drawdown"]),
                        6,
                    ),
                    "test_candidate_count": selected_test["candidate_count"],
                    "baseline_test_candidate_count": baseline_test["candidate_count"],
                }
            )
        validations.append(
            {
                "candidate_scope": item["candidate_scope"],
                "guard_preset": item["guard_preset"],
                "windows": windows,
            }
        )
    return validations


def validate_ranked_replay_fixed_market_state_gates(
    rows: list[dict[str, Any]],
    market_context_by_period: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    validations: list[dict[str, Any]] = []
    for item in rows:
        candidate_returns = list(item.get("candidate_returns") or [])
        years = sorted(
            {_candidate_return_year(candidate_return) for candidate_return in candidate_returns}
        )
        windows: list[dict[str, Any]] = []
        for split_year in years[1:]:
            train_years = [year for year in years if year < split_year]
            test_years = [year for year in years if year >= split_year]
            train_rows = [
                candidate_return
                for candidate_return in candidate_returns
                if _candidate_return_year(candidate_return) < split_year
            ]
            test_rows = [
                candidate_return
                for candidate_return in candidate_returns
                if _candidate_return_year(candidate_return) >= split_year
            ]
            if not train_rows or not test_rows:
                continue

            baseline_test = _summarize_candidate_return_rows(test_rows)
            gates: list[dict[str, Any]] = []
            for gate_name, allowed_states in MARKET_STATE_GATE_PRESETS[1:]:
                train_gate = _summarize_candidate_return_rows(
                    _filter_candidate_returns_by_allowed_states(
                        train_rows,
                        market_context_by_period,
                        allowed_states,
                    )
                )
                test_gate = _summarize_candidate_return_rows(
                    _filter_candidate_returns_by_allowed_states(
                        test_rows,
                        market_context_by_period,
                        allowed_states,
                    )
                )
                gates.append(
                    {
                        "gate": gate_name,
                        "train_total_return": train_gate["total_return"],
                        "train_max_drawdown": train_gate["max_drawdown"],
                        "test_total_return": test_gate["total_return"],
                        "test_max_drawdown": test_gate["max_drawdown"],
                        "baseline_test_total_return": baseline_test["total_return"],
                        "baseline_test_max_drawdown": baseline_test["max_drawdown"],
                        "test_delta_return": round(
                            float(test_gate["total_return"])
                            - float(baseline_test["total_return"]),
                            6,
                        ),
                        "test_drawdown_delta": round(
                            float(test_gate["max_drawdown"])
                            - float(baseline_test["max_drawdown"]),
                            6,
                        ),
                        "test_candidate_count": test_gate["candidate_count"],
                        "baseline_test_candidate_count": baseline_test["candidate_count"],
                    }
                )
            windows.append(
                {
                    "train": _year_span(train_years),
                    "test": _year_span(test_years),
                    "gates": gates,
                }
            )
        validations.append(
            {
                "candidate_scope": item["candidate_scope"],
                "guard_preset": item["guard_preset"],
                "windows": windows,
            }
        )
    return validations


def _signed_pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _format_gate_validation_line(
    *,
    train: str,
    test: str,
    gate: str,
    row: dict[str, Any],
) -> str:
    return " | ".join(
        [
            train,
            test,
            gate,
            (
                f"{_pct(float(row['train_total_return']))}/"
                f"{_pct(float(row['train_max_drawdown']))}"
            ),
            (
                f"{_pct(float(row['test_total_return']))}/"
                f"{_pct(float(row['test_max_drawdown']))}"
            ),
            (
                f"{_signed_pct(float(row['test_delta_return']))}/"
                f"{_signed_pct(float(row['test_drawdown_delta']))}"
            ),
        ]
    )


def format_ranked_replay_market_state_gate_validation(
    rows: list[dict[str, Any]],
    market_context_by_period: dict[str, dict[str, Any]],
    *,
    top_n: int,
    max_drawdown_limit_pct: float = 0.15,
) -> str:
    lines = [
        f"行情状态门控滚动验证 Top {top_n}",
        "训练 | 测试 | 选中门控 | 训练收益/回撤 | 测试收益/回撤 | 相对全部",
    ]
    for item in validate_ranked_replay_market_state_gates(
        rows[: max(0, top_n)],
        market_context_by_period,
        max_drawdown_limit_pct=max_drawdown_limit_pct,
    ):
        lines.append(f"{item['candidate_scope']}/{item['guard_preset']}")
        for window in item["windows"]:
            lines.append(
                _format_gate_validation_line(
                    train=str(window["train"]),
                    test=str(window["test"]),
                    gate=str(window["selected_gate"]),
                    row=window,
                )
            )
    return "\n".join(lines)


def format_ranked_replay_fixed_market_state_gate_validation(
    rows: list[dict[str, Any]],
    market_context_by_period: dict[str, dict[str, Any]],
    *,
    top_n: int,
) -> str:
    lines = [
        f"固定门控样本外对比 Top {top_n}",
        "训练 | 测试 | 门控 | 训练收益/回撤 | 测试收益/回撤 | 相对全部",
    ]
    for item in validate_ranked_replay_fixed_market_state_gates(
        rows[: max(0, top_n)],
        market_context_by_period,
    ):
        lines.append(f"{item['candidate_scope']}/{item['guard_preset']}")
        for window in item["windows"]:
            for gate in window["gates"]:
                lines.append(
                    _format_gate_validation_line(
                        train=str(window["train"]),
                        test=str(window["test"]),
                        gate=str(gate["gate"]),
                        row=gate,
                    )
                )
    return "\n".join(lines)


def format_ranked_replay_market_state_gate_simulation(
    rows: list[dict[str, Any]],
    market_context_by_period: dict[str, dict[str, Any]],
    *,
    top_n: int,
) -> str:
    lines = [
        f"行情状态门控模拟 Top {top_n}",
        "门控 | 总收益 | 最大回撤 | 候选 | 月份",
    ]
    for item in simulate_ranked_replay_market_state_gates(
        rows[: max(0, top_n)],
        market_context_by_period,
    ):
        lines.append(f"{item['candidate_scope']}/{item['guard_preset']}")
        for gate in item["gates"]:
            lines.append(
                " | ".join(
                    [
                        str(gate["gate"]),
                        _pct(float(gate["total_return"])),
                        _pct(float(gate["max_drawdown"])),
                        str(gate["candidate_count"]),
                        str(gate["month_count"]),
                    ]
                )
            )
    return "\n".join(lines)


def format_ranked_replay_market_state_returns(
    rows: list[dict[str, Any]],
    market_context_by_month: dict[str, dict[str, Any]],
    *,
    top_n: int,
) -> str:
    lines = [
        f"行情状态收益拆解 Top {top_n}",
        "状态 | 月份桶 | 总收益 | 月均 | 月胜率 | 最差月",
    ]
    for item in summarize_ranked_replay_market_state_returns(
        rows[: max(0, top_n)],
        market_context_by_month,
    ):
        lines.append(f"{item['candidate_scope']}/{item['guard_preset']}")
        for state in item["states"]:
            lines.append(
                " | ".join(
                    [
                        str(state["market_state"]),
                        str(state["month_count"]),
                        _pct(float(state["total_return"])),
                        _pct(float(state["average_return"])),
                        _pct(float(state["win_rate"])),
                        f"{state['worst_month']} {_pct(float(state['worst_month_return']))}",
                    ]
                )
            )
    return "\n".join(lines)


def format_ranked_replay_market_state_scope_matrix(
    rows: list[dict[str, Any]],
    market_context_by_period: dict[str, dict[str, Any]],
    *,
    top_n: int,
) -> str:
    lines = [
        f"行情状态候选线对比 Top {top_n}",
        "状态 | 范围/预设 | 总收益 | 最大回撤 | 候选 | 月份",
    ]
    for state_group in summarize_ranked_replay_market_state_scope_matrix(
        rows[: max(0, top_n)],
        market_context_by_period,
    ):
        for row in state_group["rows"]:
            lines.append(
                " | ".join(
                    [
                        str(state_group["market_state"]),
                        f"{row['candidate_scope']}/{row['guard_preset']}",
                        _pct(float(row["total_return"])),
                        _pct(float(row["max_drawdown"])),
                        str(row["candidate_count"]),
                        str(row["month_count"]),
                    ]
                )
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run long walk-forward baseline.")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument(
        "--candidate-scope",
        default="all",
        choices=[
            "all",
            "action",
            "action_long",
            "sector_watch",
            "potential_watch",
            "startup_preheat",
            "startup_confirmed",
        ],
    )
    parser.add_argument("--guarded", action="store_true")
    parser.add_argument("--min-coverage-ratio", type=float, default=0.70)
    parser.add_argument("--disable-fundamentals", action="store_true")
    parser.add_argument(
        "--guard-preset",
        choices=["fixed", "adaptive", "drawdown15"],
        default="fixed",
    )
    parser.add_argument("--stop-loss-pct", type=float, default=0.06)
    parser.add_argument("--trailing-drawdown-pct", type=float, default=0.08)
    parser.add_argument("--max-drawdown-limit-pct", type=float, default=0.15)
    parser.add_argument("--rank-presets", action="store_true")
    parser.add_argument("--rank-months", action="store_true")
    parser.add_argument("--rank-months-top", type=int, default=3)
    parser.add_argument("--loss-diagnostics", action="store_true")
    parser.add_argument("--market-context", action="store_true")
    parser.add_argument("--gate-validation", action="store_true")
    args = parser.parse_args()

    require_primary_database("long_replay_baseline")
    if args.rank_presets:
        ranked = rank_replay_baselines(
            start_date=args.start_date,
            end_date=args.end_date,
            horizon=args.horizon,
            limit=args.limit,
            candidate_scopes=list(DEFAULT_RANK_SCOPES),
            guard_presets=list(DEFAULT_RANK_PRESETS),
            guarded=True,
            min_coverage_ratio=args.min_coverage_ratio,
            include_fundamentals=not args.disable_fundamentals,
            stop_loss_pct=args.stop_loss_pct,
            trailing_drawdown_pct=args.trailing_drawdown_pct,
            max_drawdown_limit_pct=args.max_drawdown_limit_pct,
        )
        print(
            format_ranked_replay_baselines(ranked)
        )
        if args.rank_months:
            print()
            print(format_ranked_replay_months(ranked, top_n=args.rank_months_top))
        if args.loss_diagnostics:
            print()
            print(format_replay_loss_diagnostics(diagnose_ranked_replay_losses(ranked)))
        if args.market_context or args.gate_validation:
            signal_dates = _ranked_signal_dates(ranked)
            market_context_by_signal_date = load_market_context_by_signal_date(signal_dates)
        if args.market_context:
            market_context_by_month = summarize_market_context_by_month(
                [
                    {
                        "trade_date": trade_date,
                        "trend_score": context.get("trend_score"),
                        "breadth_score": context.get("breadth_score"),
                        "emotion_score": context.get("emotion_score"),
                    }
                    for trade_date, context in market_context_by_signal_date.items()
                ]
            )
            print()
            print(
                format_ranked_replay_market_context(
                    ranked,
                    market_context_by_month,
                    top_n=args.rank_months_top,
                )
            )
            print()
            print(
                format_ranked_replay_market_state_returns(
                    ranked,
                    market_context_by_signal_date,
                    top_n=args.rank_months_top,
                )
            )
            print()
            print(
                format_ranked_replay_market_state_scope_matrix(
                    ranked,
                    market_context_by_signal_date,
                    top_n=args.rank_months_top,
                )
            )
            print()
            print(
                format_ranked_replay_market_state_gate_simulation(
                    ranked,
                    market_context_by_signal_date,
                    top_n=args.rank_months_top,
                )
            )
        if args.gate_validation:
            print()
            print(
                format_ranked_replay_market_state_gate_validation(
                    ranked,
                    market_context_by_signal_date,
                    top_n=args.rank_months_top,
                    max_drawdown_limit_pct=args.max_drawdown_limit_pct,
                )
            )
            print()
            print(
                format_ranked_replay_fixed_market_state_gate_validation(
                    ranked,
                    market_context_by_signal_date,
                    top_n=args.rank_months_top,
                )
            )
        return
    print(
        format_replay_baseline(
            run_replay_baseline(
                start_date=args.start_date,
                end_date=args.end_date,
                horizon=args.horizon,
                limit=args.limit,
                candidate_scope=args.candidate_scope,
                guarded=args.guarded,
                min_coverage_ratio=args.min_coverage_ratio,
                include_fundamentals=not args.disable_fundamentals,
                stop_loss_pct=args.stop_loss_pct,
                trailing_drawdown_pct=args.trailing_drawdown_pct,
                guard_preset=args.guard_preset,
                max_drawdown_limit_pct=args.max_drawdown_limit_pct,
            )
        )
    )


if __name__ == "__main__":
    main()
