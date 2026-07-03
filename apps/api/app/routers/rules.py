from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.engine.backtest.strategy_fit import load_strategy_fit_report
from services.engine.backtest.walk_forward import (
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
}


def _guarded_metric(summary: dict[str, Any], horizon: int) -> dict[str, Any]:
    return (
        ((summary.get("horizons") or {}).get(horizon) or {}).get("guarded")
        or {
            "sample_count": 0,
            "avg_return": None,
            "win_rate": None,
            "total_return": None,
        }
    )


def _monthly_guarded_metric(
    comparison: dict[str, Any],
    *,
    scope: str,
    month: str,
    horizon: int,
) -> dict[str, Any]:
    summary = (comparison.get("scopes") or {}).get(scope) or {}
    return (
        ((summary.get("monthly_horizons") or {}).get(horizon) or {})
        .get(month, {})
        .get("guarded")
        or {
            "sample_count": 0,
            "avg_return": None,
            "win_rate": None,
            "total_return": None,
        }
    )


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
        "candidate_count": int(summary.get("candidate_count") or 0),
        "sample_count": int(metric.get("sample_count") or 0),
        "avg_return": _metric_float(metric, "avg_return"),
        "win_rate": _metric_float(metric, "win_rate"),
        "total_return": _metric_float(metric, "total_return"),
    }


def _month_candidates(comparison: dict[str, Any], *, horizon: int) -> list[str]:
    months: set[str] = set()
    for summary in (comparison.get("scopes") or {}).values():
        monthly = (summary.get("monthly_horizons") or {}).get(horizon) or {}
        for month, item in monthly.items():
            guarded = (item or {}).get("guarded") or {}
            if int(guarded.get("sample_count") or 0) > 0:
                months.add(str(month))
    return sorted(months)


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
            f"{month} {row['label']}：{horizon}日总收益"
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
    eligible_rows = [
        row for row in scope_rows if row["sample_count"] >= min_primary_samples
    ] or scope_rows
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
            f"{row['label']}：{horizon}日均值{_format_pct(row['avg_return'])}，"
            f"总收益{_format_pct(row['total_return'])}，样本{row['sample_count']}"
        )
        for row in ranked_rows[:3]
    ]
    return {
        "horizon": horizon,
        "primary_scope": scope,
        "primary_scope_label": primary["label"],
        "policy_label": policy_label,
        "ding_policy": ding_policy,
        "summary": summary_text,
        "scope_rows": ranked_rows,
        "reasons": reasons,
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
    start_date: str = "2025-01-01",
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
    return summarize_walk_forward_replay(result, horizons=horizons)


@router.get("/candidate-replay-effect")
def get_candidate_replay_effect(
    start_date: str = "2025-01-01",
    end_date: str | None = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 15,
    min_coverage_ratio: Annotated[float, Query(ge=0.0, le=1.0)] = 0.70,
    include_fundamentals: bool = True,
) -> dict:
    resolved_end_date = end_date or (now_local().date() - timedelta(days=1)).isoformat()
    horizons = (5, 10, 20)
    comparison = compare_candidate_walk_forward_scopes(
        start_date=start_date,
        end_date=resolved_end_date,
        scopes=("all", "action", "action_long"),
        limit=limit,
        horizons=horizons,
        min_coverage_ratio=min_coverage_ratio,
        include_fundamentals=include_fundamentals,
    )
    return {
        **comparison,
        "diagnosis": diagnose_candidate_replay_effect(comparison, horizon=20),
    }
