from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any

from services.engine.backtest.walk_forward import (
    NOISE_WALK_FORWARD_SYMBOLS,
    WalkForwardCandidate,
    WalkForwardReplayResult,
    run_candidate_walk_forward_replay,
)
from services.shared.database import require_primary_database

ADAPTIVE_GUARD_PARAMETERS = {
    "action": (0.04, 0.06),
    "action_long": (0.04, 0.06),
    "sector_watch": (0.06, 0.08),
    "potential_watch": (0.06, 0.08),
    "startup_preheat": (0.06, 0.08),
    "startup_confirmed": (0.04, 0.06),
}


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
            f"最大回撤 {_pct(float(summary['max_drawdown']))} | "
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
    return {
        **summarize_replay_baseline(result, horizon=horizon, guarded=guarded),
        "guard_preset": guard_preset,
        "stop_loss_pct": effective_stop_loss_pct,
        "trailing_drawdown_pct": effective_trailing_drawdown_pct,
    }


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
    parser.add_argument("--guard-preset", choices=["fixed", "adaptive"], default="fixed")
    parser.add_argument("--stop-loss-pct", type=float, default=0.06)
    parser.add_argument("--trailing-drawdown-pct", type=float, default=0.08)
    args = parser.parse_args()

    require_primary_database("long_replay_baseline")
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
            )
        )
    )


if __name__ == "__main__":
    main()
