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
            (
                f"{item['candidate_scope']}/{item['guard_preset']} "
                f"总收益{_pct(float(item['total_return']))} "
                f"最大回撤{_pct(float(item['max_drawdown']))}"
            )
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


def load_market_context_by_signal_dates(signal_dates: list[str]) -> dict[str, dict[str, Any]]:
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
    return summarize_market_context_by_month(
        [
            {
                "trade_date": row[0].isoformat(),
                "trend_score": row[1],
                "breadth_score": row[2],
                "emotion_score": row[3],
            }
            for row in rows
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
        if args.market_context:
            print()
            print(
                format_ranked_replay_market_context(
                    ranked,
                    load_market_context_by_signal_dates(_ranked_signal_dates(ranked)),
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
