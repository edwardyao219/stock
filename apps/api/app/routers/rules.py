import hashlib
import json
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
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
    "startup_confirmed": "启动确认池",
}
_PRIMARY_POLICY_SCOPES = {"action_long", "action", "all"}
_CORE_POLICY_SCOPES = {"action_long", "action"}
_TACTICAL_POLICY_SCOPES = {"potential_watch", "startup_preheat", "startup_confirmed"}
DEFAULT_REPLAY_START_DATE = "2024-01-01"
DEFAULT_INTERACTIVE_REPLAY_MONTHS = 3
CANDIDATE_REPLAY_EFFECT_CACHE_VERSION = "candidate-replay-effect-v2"
CANDIDATE_REPLAY_EFFECT_CACHE_DIR = Path(".tmp/candidate-replay-effect-cache")
CANDIDATE_REPLAY_EFFECT_HORIZONS = (1, 5, 10, 20)
CANDIDATE_REPLAY_EFFECT_SCOPES = (
    "all",
    "action",
    "action_long",
    "potential_watch",
    "startup_preheat",
    "startup_confirmed",
)
_CANDIDATE_REPLAY_NUMERIC_KEY_MAPS = {
    "horizons",
    "monthly_horizons",
    "portfolio_horizons",
    "monthly_portfolio_horizons",
    "startup_signal_style_horizons",
    "metrics_by_horizon",
}
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


def _month_start_shift(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _default_interactive_replay_start_date(end_date: str) -> str:
    return _month_start_shift(
        date.fromisoformat(end_date),
        -DEFAULT_INTERACTIVE_REPLAY_MONTHS,
    ).isoformat()


def _candidate_replay_effect_cache_key(
    *,
    start_date: str,
    end_date: str,
    limit: int,
    min_coverage_ratio: float,
    include_fundamentals: bool,
) -> str:
    payload = {
        "version": CANDIDATE_REPLAY_EFFECT_CACHE_VERSION,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
        "min_coverage_ratio": round(float(min_coverage_ratio), 6),
        "include_fundamentals": include_fundamentals,
        "horizons": CANDIDATE_REPLAY_EFFECT_HORIZONS,
        "scopes": CANDIDATE_REPLAY_EFFECT_SCOPES,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _candidate_replay_effect_cache_path(cache_key: str) -> Path:
    return (
        Path(CANDIDATE_REPLAY_EFFECT_CACHE_DIR)
        / f"{CANDIDATE_REPLAY_EFFECT_CACHE_VERSION}_{cache_key}.json"
    )


def _restore_candidate_replay_key_types(value: Any, *, parent_key: str | None = None) -> Any:
    if isinstance(value, list):
        return [_restore_candidate_replay_key_types(item, parent_key=parent_key) for item in value]
    if not isinstance(value, dict):
        return value

    restored: dict[Any, Any] = {}
    for key, item in value.items():
        restored_key: Any = key
        if (
            parent_key in _CANDIDATE_REPLAY_NUMERIC_KEY_MAPS
            and isinstance(key, str)
            and key.isdigit()
        ):
            restored_key = int(key)
        restored[restored_key] = _restore_candidate_replay_key_types(
            item,
            parent_key=str(restored_key),
        )
    return restored


def _load_candidate_replay_effect_cache(path: Path, *, cache_key: str) -> dict[str, Any] | None:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if envelope.get("version") != CANDIDATE_REPLAY_EFFECT_CACHE_VERSION:
        return None
    if envelope.get("cache_key") != cache_key:
        return None
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None
    restored = _restore_candidate_replay_key_types(payload)
    return restored if isinstance(restored, dict) else None


def _store_candidate_replay_effect_cache(
    path: Path,
    *,
    cache_key: str,
    payload: dict[str, Any],
) -> None:
    envelope = {
        "version": CANDIDATE_REPLAY_EFFECT_CACHE_VERSION,
        "cache_key": cache_key,
        "payload": payload,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(envelope, ensure_ascii=False, sort_keys=True, default=str),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        return


def _with_candidate_replay_cache_meta(
    payload: dict[str, Any],
    *,
    cache_key: str,
    hit: bool,
    mode: str = "range_cache",
    shard_count: int | None = None,
    shard_hits: int | None = None,
    shard_misses: int | None = None,
) -> dict[str, Any]:
    replay_cache = {
        "hit": hit,
        "cache_key": cache_key,
        "version": CANDIDATE_REPLAY_EFFECT_CACHE_VERSION,
        "mode": mode,
    }
    if shard_count is not None:
        replay_cache["shard_count"] = shard_count
    if shard_hits is not None:
        replay_cache["shard_hits"] = shard_hits
    if shard_misses is not None:
        replay_cache["shard_misses"] = shard_misses
    return {
        **payload,
        "replay_cache": replay_cache,
    }


def _candidate_replay_month_ranges(start_date: str, end_date: str) -> list[tuple[str, str]]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    ranges: list[tuple[str, str]] = []
    current = date(start.year, start.month, 1)
    while current <= end:
        month_end = date(current.year, current.month, monthrange(current.year, current.month)[1])
        ranges.append((max(start, current).isoformat(), min(end, month_end).isoformat()))
        current = _month_start_shift(current, 1)
    return ranges


def _horizon_item(payload: dict[str, Any], key: str, horizon: int) -> dict[str, Any]:
    values = payload.get(key) or {}
    item = values.get(horizon)
    if item is None:
        item = values.get(str(horizon))
    return item if isinstance(item, dict) else {}


def _merge_return_metrics(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    sample_count = 0
    total_return = 0.0
    win_count = 0.0
    exit_reasons: dict[str, int] = {}
    for metric in metrics:
        count = int(metric.get("sample_count") or 0)
        if count <= 0:
            continue
        sample_count += count
        if metric.get("total_return") is not None:
            total_return += float(metric["total_return"])
        elif metric.get("avg_return") is not None:
            total_return += float(metric["avg_return"]) * count
        if metric.get("win_rate") is not None:
            win_count += float(metric["win_rate"]) * count
        for reason, reason_count in (metric.get("exit_reasons") or {}).items():
            exit_reasons[str(reason)] = exit_reasons.get(str(reason), 0) + int(reason_count or 0)
    if sample_count <= 0:
        merged: dict[str, Any] = {
            "sample_count": 0,
            "avg_return": None,
            "win_rate": None,
            "total_return": None,
        }
    else:
        merged = {
            "sample_count": sample_count,
            "avg_return": round(total_return / sample_count, 6),
            "win_rate": round(win_count / sample_count, 6),
            "total_return": round(total_return, 6),
        }
    if exit_reasons:
        merged["exit_reasons"] = dict(sorted(exit_reasons.items()))
    return merged


def _merge_metric_pair(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "raw": _merge_return_metrics([item.get("raw") or {} for item in items]),
        "guarded": _merge_return_metrics([item.get("guarded") or {} for item in items]),
    }


def _merge_portfolio_metric(items: list[dict[str, Any]]) -> dict[str, Any]:
    first = next((item for item in items if item), {})
    return {
        "max_positions": first.get("max_positions", 3),
        "weighting": first.get("weighting", "equal_weight_by_signal_day"),
        **_merge_metric_pair(items),
    }


def _merge_count_rows(
    summaries: list[dict[str, Any]],
    key: str,
    label_key: str,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    labels: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        for item in summary.get(key) or []:
            label = str(item.get(label_key) or "")
            if not label:
                continue
            counts[label] = counts.get(label, 0) + int(item.get("count") or 0)
            labels.setdefault(
                label,
                {extra_key: extra_value for extra_key, extra_value in item.items()},
            )
    rows = []
    for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        row = {**labels.get(label, {}), label_key: label, "count": count}
        rows.append(row)
    return rows


def _merge_category_horizons(
    summaries: list[dict[str, Any]],
    key: str,
    *,
    horizons: tuple[int, ...],
) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for horizon in horizons:
        categories = sorted(
            {
                str(category)
                for summary in summaries
                for category in _horizon_item(summary, key, horizon)
            }
        )
        merged[horizon] = {}
        for category in categories:
            category_items = [
                _horizon_item(summary, key, horizon).get(category) or {}
                for summary in summaries
            ]
            row = _merge_metric_pair(category_items)
            label = next(
                (
                    item.get("label")
                    for item in category_items
                    if isinstance(item, dict) and item.get("label")
                ),
                None,
            )
            if label:
                row["label"] = label
            merged[horizon][category] = row
    return merged


def _merge_monthly_horizons(
    summaries: list[dict[str, Any]],
    key: str,
    *,
    horizons: tuple[int, ...],
) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {horizon: {} for horizon in horizons}
    for horizon in horizons:
        for summary in summaries:
            for month, item in _horizon_item(summary, key, horizon).items():
                merged[horizon][str(month)] = item
    return merged


def _merge_nested_category_horizons(
    summaries: list[dict[str, Any]],
    key: str,
    *,
    horizons: tuple[int, ...],
) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for horizon in horizons:
        outer_keys = sorted(
            {
                str(outer_key)
                for summary in summaries
                for outer_key in _horizon_item(summary, key, horizon)
            }
        )
        merged[horizon] = {}
        for outer_key in outer_keys:
            inner_keys = sorted(
                {
                    str(inner_key)
                    for summary in summaries
                    for inner_key in (_horizon_item(summary, key, horizon).get(outer_key) or {})
                }
            )
            merged[horizon][outer_key] = {}
            for inner_key in inner_keys:
                inner_items = [
                    (
                        (_horizon_item(summary, key, horizon).get(outer_key) or {}).get(
                            inner_key
                        )
                        or {}
                    )
                    for summary in summaries
                ]
                row = _merge_metric_pair(inner_items)
                label = next(
                    (
                        item.get("label")
                        for item in inner_items
                        if isinstance(item, dict) and item.get("label")
                    ),
                    None,
                )
                if label:
                    row["label"] = label
                merged[horizon][outer_key][inner_key] = row
    return merged


def _style_horizon_preferences_from_summary(
    style_horizons: dict[int, dict[str, Any]],
    *,
    min_actionable_samples: int = 10,
) -> dict[str, dict[str, Any]]:
    preferences: dict[str, dict[str, Any]] = {}
    styles = sorted(
        {style for horizon_summary in style_horizons.values() for style in horizon_summary}
    )
    for style in styles:
        best: tuple[int, dict[str, Any]] | None = None
        for horizon in sorted(style_horizons):
            guarded = (style_horizons[horizon].get(style) or {}).get("guarded") or {}
            avg_return = guarded.get("avg_return")
            if avg_return is None:
                continue
            if best is None or float(avg_return) > float(best[1]["avg_return"]):
                best = (
                    horizon,
                    {
                        "avg_return": avg_return,
                        "sample_count": int(guarded.get("sample_count") or 0),
                        "total_return": guarded.get("total_return"),
                    },
                )
        if best is None:
            continue
        horizon, metrics = best
        actionable = (
            int(metrics.get("sample_count") or 0) >= min_actionable_samples
            and float(metrics.get("avg_return") or 0.0) > 0
        )
        preferences[style] = {
            "preferred_horizon": horizon,
            "preferred_metric": "guarded_avg_return",
            **metrics,
            "actionable": actionable,
            "reason": (
                "样本足够且风控后平均收益为正"
                if actionable
                else "样本不足或收益不正，只作观察"
            ),
        }
    return preferences


def _merge_candidate_replay_scope_summaries(
    summaries: list[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
    horizons: tuple[int, ...],
) -> dict[str, Any]:
    horizon_summaries: dict[int, dict[str, Any]] = {}
    portfolio_horizons: dict[int, dict[str, Any]] = {}
    for horizon in horizons:
        horizon_summaries[horizon] = _merge_metric_pair(
            [_horizon_item(summary, "horizons", horizon) for summary in summaries]
        )
        portfolio_horizons[horizon] = _merge_portfolio_metric(
            [_horizon_item(summary, "portfolio_horizons", horizon) for summary in summaries]
        )
    style_horizons = _merge_category_horizons(
        summaries,
        "style_horizons",
        horizons=horizons,
    )
    return {
        "start_date": start_date,
        "end_date": end_date,
        "processed_days": sum(int(summary.get("processed_days") or 0) for summary in summaries),
        "candidate_count": sum(int(summary.get("candidate_count") or 0) for summary in summaries),
        "excluded_symbols": sorted(
            {
                str(symbol)
                for summary in summaries
                for symbol in (summary.get("excluded_symbols") or [])
            }
        ),
        "warning_days": sum(int(summary.get("warning_days") or 0) for summary in summaries),
        "top_sectors": _merge_count_rows(summaries, "top_sectors", "sector")[:10],
        "style_counts": _merge_count_rows(summaries, "style_counts", "style"),
        "selection_mode_counts": _merge_count_rows(
            summaries,
            "selection_mode_counts",
            "selection_mode",
        ),
        "startup_signal_counts": _merge_count_rows(
            summaries,
            "startup_signal_counts",
            "bucket",
        ),
        "horizons": horizon_summaries,
        "portfolio_horizons": portfolio_horizons,
        "style_horizons": style_horizons,
        "selection_mode_horizons": _merge_category_horizons(
            summaries,
            "selection_mode_horizons",
            horizons=horizons,
        ),
        "startup_signal_horizons": _merge_category_horizons(
            summaries,
            "startup_signal_horizons",
            horizons=horizons,
        ),
        "startup_signal_style_horizons": _merge_nested_category_horizons(
            summaries,
            "startup_signal_style_horizons",
            horizons=horizons,
        ),
        "style_horizon_preferences": _style_horizon_preferences_from_summary(style_horizons),
        "monthly_horizons": _merge_monthly_horizons(
            summaries,
            "monthly_horizons",
            horizons=horizons,
        ),
        "monthly_portfolio_horizons": _merge_monthly_horizons(
            summaries,
            "monthly_portfolio_horizons",
            horizons=horizons,
        ),
        "monthly_style_horizons": _merge_monthly_horizons(
            summaries,
            "monthly_style_horizons",
            horizons=horizons,
        ),
        "monthly_selection_mode_horizons": _merge_monthly_horizons(
            summaries,
            "monthly_selection_mode_horizons",
            horizons=horizons,
        ),
        "monthly_startup_signal_horizons": _merge_monthly_horizons(
            summaries,
            "monthly_startup_signal_horizons",
            horizons=horizons,
        ),
    }


def _merge_candidate_replay_comparisons(
    *,
    start_date: str,
    end_date: str,
    shards: list[dict[str, Any]],
    scopes: tuple[str, ...],
    horizons: tuple[int, ...],
) -> dict[str, Any]:
    scope_summaries: dict[str, Any] = {}
    for scope in scopes:
        summaries = [
            (shard.get("scopes") or {}).get(scope)
            for shard in shards
            if isinstance((shard.get("scopes") or {}).get(scope), dict)
        ]
        if summaries:
            scope_summaries[scope] = _merge_candidate_replay_scope_summaries(
                summaries,
                start_date=start_date,
                end_date=end_date,
                horizons=horizons,
            )
    return {
        "start_date": start_date,
        "end_date": end_date,
        "scopes": scope_summaries,
        "discovery_cache_dir": next(
            (
                shard.get("discovery_cache_dir")
                for shard in shards
                if shard.get("discovery_cache_dir") is not None
            ),
            None,
        ),
    }


def _build_candidate_replay_effect_payload(
    *,
    start_date: str,
    end_date: str,
    limit: int,
    horizons: tuple[int, ...],
    min_coverage_ratio: float,
    include_fundamentals: bool,
) -> dict[str, Any]:
    comparison = compare_candidate_walk_forward_scopes(
        start_date=start_date,
        end_date=end_date,
        scopes=CANDIDATE_REPLAY_EFFECT_SCOPES,
        limit=limit,
        horizons=horizons,
        min_coverage_ratio=min_coverage_ratio,
        include_fundamentals=include_fundamentals,
    )
    return {
        **comparison,
        "data_coverage": build_replay_data_coverage_report(
            start_date=start_date,
            end_date=end_date,
        ),
        "diagnosis": diagnose_candidate_replay_effect(comparison, horizon=20),
    }


def _load_or_build_candidate_replay_effect_payload(
    *,
    start_date: str,
    end_date: str,
    limit: int,
    horizons: tuple[int, ...],
    min_coverage_ratio: float,
    include_fundamentals: bool,
    force_refresh: bool,
) -> tuple[dict[str, Any], bool]:
    cache_key = _candidate_replay_effect_cache_key(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        min_coverage_ratio=min_coverage_ratio,
        include_fundamentals=include_fundamentals,
    )
    cache_path = _candidate_replay_effect_cache_path(cache_key)
    if not force_refresh:
        cached_payload = _load_candidate_replay_effect_cache(cache_path, cache_key=cache_key)
        if cached_payload is not None:
            return cached_payload, True
    payload = _build_candidate_replay_effect_payload(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        horizons=horizons,
        min_coverage_ratio=min_coverage_ratio,
        include_fundamentals=include_fundamentals,
    )
    _store_candidate_replay_effect_cache(cache_path, cache_key=cache_key, payload=payload)
    return payload, False


def _build_candidate_replay_effect_from_monthly_shards(
    *,
    start_date: str,
    end_date: str,
    limit: int,
    horizons: tuple[int, ...],
    min_coverage_ratio: float,
    include_fundamentals: bool,
    force_refresh: bool,
) -> tuple[dict[str, Any], int, int]:
    shards: list[dict[str, Any]] = []
    shard_hits = 0
    shard_misses = 0
    for shard_start, shard_end in _candidate_replay_month_ranges(start_date, end_date):
        shard_payload, shard_hit = _load_or_build_candidate_replay_effect_payload(
            start_date=shard_start,
            end_date=shard_end,
            limit=limit,
            horizons=horizons,
            min_coverage_ratio=min_coverage_ratio,
            include_fundamentals=include_fundamentals,
            force_refresh=force_refresh,
        )
        shards.append(shard_payload)
        if shard_hit:
            shard_hits += 1
        else:
            shard_misses += 1
    comparison = _merge_candidate_replay_comparisons(
        start_date=start_date,
        end_date=end_date,
        shards=shards,
        scopes=CANDIDATE_REPLAY_EFFECT_SCOPES,
        horizons=horizons,
    )
    return (
        {
            **comparison,
            "data_coverage": build_replay_data_coverage_report(
                start_date=start_date,
                end_date=end_date,
            ),
            "diagnosis": diagnose_candidate_replay_effect(comparison, horizon=20),
        },
        shard_hits,
        shard_misses,
    )


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


def _strategy_pk_policy(
    *,
    scope: str,
    sample_count: int,
    avg_return: float | None,
    latest_month_total_return: float | None,
    min_samples: int,
) -> tuple[str, str]:
    if sample_count < min_samples:
        return "low_sample", "样本不足"
    if avg_return is None or avg_return <= 0.0:
        return "stand_down", "休息"
    if latest_month_total_return is not None and latest_month_total_return < 0.0:
        return "stand_down", "休息"
    if scope in _CORE_POLICY_SCOPES:
        return "core_candidate", "核心候选"
    if scope in _TACTICAL_POLICY_SCOPES:
        return "tactical_observe", "战术观察"
    return "observe_only", "只观察"


def diagnose_strategy_pk(
    comparison: dict[str, Any],
    *,
    horizons: tuple[int, ...] = (5, 10, 20),
    primary_horizon: int = 20,
    min_samples: int = 3,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for scope, summary in (comparison.get("scopes") or {}).items():
        metrics_by_horizon: dict[int, dict[str, Any]] = {}
        for horizon in horizons:
            metric = _guarded_metric(summary, horizon)
            metrics_by_horizon[horizon] = {
                "metric_label": _metric_label(summary, horizon),
                "sample_count": int(metric.get("sample_count") or 0),
                "avg_return": _metric_float(metric, "avg_return"),
                "win_rate": _metric_float(metric, "win_rate"),
                "total_return": _metric_float(metric, "total_return"),
            }

        monthly_rows = _scope_monthly_guarded_rows(
            comparison,
            scope=scope,
            horizon=primary_horizon,
        )
        latest_month = monthly_rows[-1] if monthly_rows else {}
        month_total_returns = [
            float(row["total_return"])
            for row in monthly_rows
            if row.get("total_return") is not None
        ]
        month_sample_counts = [
            int(row.get("sample_count") or 0)
            for row in monthly_rows
            if row.get("sample_count") is not None
        ]
        positive_months = sum(1 for value in month_total_returns if value > 0.0)
        negative_months = sum(1 for value in month_total_returns if value < 0.0)
        monthly_positive_ratio = (
            round(positive_months / len(month_total_returns), 4)
            if month_total_returns
            else None
        )
        monthly_max_drawdown = (
            round(min(0.0, min(month_total_returns)), 6) if month_total_returns else None
        )
        avg_monthly_sample_count = (
            round(sum(month_sample_counts) / len(month_sample_counts), 2)
            if month_sample_counts
            else None
        )
        primary_metric = metrics_by_horizon.get(primary_horizon, {})
        primary_total_return = primary_metric.get("total_return")
        return_drawdown_ratio = (
            round(float(primary_total_return) / abs(monthly_max_drawdown), 4)
            if primary_total_return is not None
            and monthly_max_drawdown is not None
            and monthly_max_drawdown < 0.0
            else None
        )
        policy, policy_label = _strategy_pk_policy(
            scope=str(scope),
            sample_count=int(primary_metric.get("sample_count") or 0),
            avg_return=primary_metric.get("avg_return"),
            latest_month_total_return=latest_month.get("total_return"),
            min_samples=min_samples,
        )
        latest_total = latest_month.get("total_return")
        reason = (
            f"{_SCOPE_LABELS.get(scope, scope)}：{primary_horizon}日均值"
            f"{_format_pct(primary_metric.get('avg_return'))}，"
            f"总收益{_format_pct(primary_metric.get('total_return'))}，"
            f"最近月{_format_pct(latest_total)}"
        )
        rows.append(
            {
                "scope": str(scope),
                "label": _SCOPE_LABELS.get(str(scope), str(scope)),
                "policy": policy,
                "policy_label": policy_label,
                "candidate_count": int(summary.get("candidate_count") or 0),
                "primary_horizon": primary_horizon,
                "sample_count": int(primary_metric.get("sample_count") or 0),
                "avg_return": primary_metric.get("avg_return"),
                "win_rate": primary_metric.get("win_rate"),
                "total_return": primary_metric.get("total_return"),
                "metrics_by_horizon": metrics_by_horizon,
                "latest_month": latest_month.get("month"),
                "latest_month_sample_count": latest_month.get("sample_count", 0),
                "latest_month_avg_return": latest_month.get("avg_return"),
                "latest_month_total_return": latest_total,
                "month_count": len(monthly_rows),
                "positive_months": positive_months,
                "negative_months": negative_months,
                "monthly_positive_ratio": monthly_positive_ratio,
                "monthly_max_drawdown": monthly_max_drawdown,
                "return_drawdown_ratio": return_drawdown_ratio,
                "avg_monthly_sample_count": avg_monthly_sample_count,
                "worst_month_total_return": (
                    round(min(month_total_returns), 6) if month_total_returns else None
                ),
                "best_month_total_return": (
                    round(max(month_total_returns), 6) if month_total_returns else None
                ),
                "rank_reason": reason,
            }
        )

    rows.sort(
        key=lambda row: (
            row["avg_return"] if row["avg_return"] is not None else -999.0,
            row["total_return"] if row["total_return"] is not None else -999.0,
            row["latest_month_total_return"]
            if row["latest_month_total_return"] is not None
            else -999.0,
        ),
        reverse=True,
    )
    best = rows[0] if rows else None
    core = next((row for row in rows if row["policy"] == "core_candidate"), None)
    if best is None:
        summary = "策略PK：暂无足够回放样本。"
    elif best["avg_return"] is None or best["avg_return"] <= 0.0:
        summary = (
            f"策略PK：各线{primary_horizon}日回放暂未转正，"
            "先休息或只做复盘观察。"
        )
    else:
        summary = (
            f"策略PK：{best['label']}暂时领先，"
            f"{primary_horizon}日均值{_format_pct(best['avg_return'])}；"
            f"核心线{core['label'] if core else '暂无'}。"
        )
    return {
        "return_mode": "simple_sum_no_compounding",
        "horizons": list(horizons),
        "primary_horizon": primary_horizon,
        "summary": summary,
        "rows": rows,
        "rules": [
            "收益用简单相加，不计算复利。",
            "潜力观察和启动线即使阶段领先，也默认只做Web/盘中观察，不自动进入钉钉核心。",
            "核心行动优先看长期行动池和钉钉行动池，样本不足时保持克制。",
        ],
    }


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


def _monthly_sector_leadership_items(
    summary: dict[str, Any],
    *,
    horizon: int,
) -> list[tuple[str, dict[str, Any]]]:
    monthly_horizons = summary.get("monthly_horizons") or {}
    items = monthly_horizons.get(horizon)
    if items is None:
        items = monthly_horizons.get(str(horizon))
    return [
        (str(month), item)
        for month, item in sorted((items or {}).items())
        if isinstance(item, dict)
    ]


def _sector_leadership_month_row(month: str, item: dict[str, Any]) -> dict[str, Any]:
    strong = (
        ((item.get("sector_leadership") or {}).get("strong_sector") or {}).get("guarded")
    ) or {}
    other = (((item.get("sector_leadership") or {}).get("other_sector") or {}).get("guarded")) or {}
    strong_avg = _metric_float(strong, "avg_return")
    other_avg = _metric_float(other, "avg_return")
    strong_total = _metric_float(strong, "total_return")
    other_total = _metric_float(other, "total_return")
    avg_lift = (
        round(strong_avg - other_avg, 6)
        if strong_avg is not None and other_avg is not None
        else None
    )
    total_lift = (
        round(strong_total - other_total, 6)
        if strong_total is not None and other_total is not None
        else None
    )
    status = (
        "effective"
        if (avg_lift or 0.0) > 0.0 and (strong_total or 0.0) > 0.0
        else "weak"
    )
    return {
        "month": month,
        "status": status,
        "strong_sample_count": int(strong.get("sample_count") or 0),
        "strong_avg_return": strong_avg,
        "strong_total_return": strong_total,
        "other_sample_count": int(other.get("sample_count") or 0),
        "other_avg_return": other_avg,
        "other_total_return": other_total,
        "avg_return_lift": avg_lift,
        "total_return_lift": total_lift,
    }


def _sector_leadership_rhythm(
    *,
    status: str,
    best: dict[str, Any] | None,
    horizon: int,
) -> dict[str, Any]:
    if best is None:
        return {
            "rhythm_status": "observe_only",
            "rhythm_label": "样本不足",
            "rhythm_summary": "强板块拆分样本不足，先观察策略池整体表现。",
            "latest_month_status": None,
            "warnings": [],
        }

    monthly_rows = best.get("monthly_rows") or []
    latest_row = monthly_rows[-1] if monthly_rows else None
    latest_month_status = latest_row.get("status") if isinstance(latest_row, dict) else None
    if status != "supported":
        return {
            "rhythm_status": "observe_only",
            "rhythm_label": "只观察",
            "rhythm_summary": "板块顺势贡献还不稳定，暂不升级为行动节奏。",
            "latest_month_status": latest_month_status,
            "warnings": [],
        }

    if isinstance(latest_row, dict) and latest_row.get("status") == "weak":
        latest_month = latest_row.get("month") or best.get("latest_month") or "最近月份"
        return {
            "rhythm_status": "tighten_core",
            "rhythm_label": "最近弱月，收敛核心",
            "rhythm_summary": (
                f"{latest_month}强板块{horizon}日表现转弱，"
                "先收敛核心，不把潜力观察升级为行动。"
            ),
            "latest_month_status": latest_month_status,
            "warnings": ["最近月份板块顺势转弱，暂停潜力观察升级。"],
        }

    if int(best.get("negative_months") or 0) > 0:
        return {
            "rhythm_status": "selective_follow",
            "rhythm_label": "顺势有效但有弱月",
            "rhythm_summary": (
                "板块顺势不是全月有效，强月顺势跟随，弱月先收敛核心，"
                "不扩大行动池。"
            ),
            "latest_month_status": latest_month_status,
            "warnings": ["板块顺势不是全月有效，弱月先收敛核心。"],
        }

    return {
        "rhythm_status": "follow_with_confirmation",
        "rhythm_label": "顺势跟随",
        "rhythm_summary": "强板块连续有效时允许顺势跟随，但仍要确认个股趋势、量能和风险位。",
        "latest_month_status": latest_month_status,
        "warnings": [],
    }


def diagnose_sector_leadership_policy(
    comparison: dict[str, Any],
    *,
    horizon: int = 20,
    scopes: tuple[str, ...] = ("action_long", "action", "potential_watch", "all"),
    min_strong_samples: int = 5,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for scope in scopes:
        summary = (comparison.get("scopes") or {}).get(scope) or {}
        monthly_items = _monthly_sector_leadership_items(summary, horizon=horizon)
        monthly_rows = [
            _sector_leadership_month_row(month, item) for month, item in monthly_items
        ]
        strong_metrics = [
            (((item.get("sector_leadership") or {}).get("strong_sector") or {}).get("guarded"))
            or {}
            for _month, item in monthly_items
        ]
        other_metrics = [
            (((item.get("sector_leadership") or {}).get("other_sector") or {}).get("guarded"))
            or {}
            for _month, item in monthly_items
        ]
        strong = _merge_return_metrics(strong_metrics)
        other = _merge_return_metrics(other_metrics)
        strong_samples = int(strong.get("sample_count") or 0)
        other_samples = int(other.get("sample_count") or 0)
        if strong_samples <= 0 and other_samples <= 0:
            continue
        strong_avg = _metric_float(strong, "avg_return")
        other_avg = _metric_float(other, "avg_return")
        strong_total = _metric_float(strong, "total_return")
        other_total = _metric_float(other, "total_return")
        avg_lift = (
            round(strong_avg - other_avg, 6)
            if strong_avg is not None and other_avg is not None
            else None
        )
        total_lift = (
            round(strong_total - other_total, 6)
            if strong_total is not None and other_total is not None
            else None
        )
        rows.append(
            {
                "scope": scope,
                "label": _SCOPE_LABELS.get(scope, scope),
                "horizon": horizon,
                "month_count": len(monthly_items),
                "strong_sample_count": strong_samples,
                "strong_avg_return": strong_avg,
                "strong_total_return": strong_total,
                "other_sample_count": other_samples,
                "other_avg_return": other_avg,
                "other_total_return": other_total,
                "avg_return_lift": avg_lift,
                "total_return_lift": total_lift,
                "positive_months": sum(
                    1 for row in monthly_rows if row["status"] == "effective"
                ),
                "negative_months": sum(1 for row in monthly_rows if row["status"] == "weak"),
                "latest_month": monthly_rows[-1]["month"] if monthly_rows else None,
                "monthly_rows": monthly_rows,
            }
        )

    rows.sort(
        key=lambda row: (
            row["strong_sample_count"],
            row["avg_return_lift"] if row["avg_return_lift"] is not None else -999.0,
            row["strong_total_return"] if row["strong_total_return"] is not None else -999.0,
        ),
        reverse=True,
    )
    best = rows[0] if rows else None
    if best is None:
        status = "insufficient"
        label = "板块样本不足"
        summary = "当前回放缺少强板块拆分样本，只能先看策略池整体表现。"
    elif (
        int(best["strong_sample_count"] or 0) >= min_strong_samples
        and (best["avg_return_lift"] or 0.0) > 0.0
        and (best["strong_total_return"] or 0.0) > 0.0
    ):
        status = "supported"
        label = "板块顺势有效"
        summary = (
            f"{best['label']}里强板块候选{horizon}日均值"
            f"{_format_pct(best['strong_avg_return'])}，"
            f"比其他候选高{_format_pct(best['avg_return_lift'])}。"
            f"近{best['month_count']}个月有效{best['positive_months']}个月。"
            "这只作门控验证，不直接当买点。"
        )
    else:
        status = "mixed"
        label = "板块贡献待确认"
        summary = (
            "强板块候选尚未稳定跑赢其他候选，先保留观察，"
            "不把板块门控升级成硬性买入条件。"
        )
    rhythm = _sector_leadership_rhythm(status=status, best=best, horizon=horizon)
    return {
        "status": status,
        "label": label,
        "horizon": horizon,
        "summary": summary,
        **rhythm,
        "rows": rows,
        "rules": [
            "板块顺势只作门控验证，不直接当买点。",
            "强板块有效也需要个股趋势、量能和风险位确认。",
            "样本不足时宁可观察，不因单月表现过拟合。",
        ],
    }


def _sector_leadership_policy_needs_enrichment(diagnosis: dict[str, Any]) -> bool:
    policy = diagnosis.get("sector_leadership_policy")
    if not isinstance(policy, dict):
        return True
    required_keys = {
        "rhythm_status",
        "rhythm_label",
        "rhythm_summary",
        "latest_month_status",
        "warnings",
    }
    return not required_keys.issubset(policy)


def _strategy_pk_needs_enrichment(diagnosis: dict[str, Any]) -> bool:
    strategy_pk = diagnosis.get("strategy_pk")
    if not isinstance(strategy_pk, dict):
        return True
    rows = strategy_pk.get("rows")
    if not isinstance(rows, list):
        return True
    required_row_keys = {
        "monthly_max_drawdown",
        "avg_monthly_sample_count",
        "monthly_positive_ratio",
        "return_drawdown_ratio",
    }
    return any(
        isinstance(row, dict) and not required_row_keys.issubset(row)
        for row in rows
    )


def _market_stress_gate_policy_needs_enrichment(diagnosis: dict[str, Any]) -> bool:
    policy = diagnosis.get("market_stress_gate_policy")
    if not isinstance(policy, dict):
        return True
    required_keys = {
        "status",
        "label",
        "max_core_positions",
        "avoided_total_loss",
        "summary",
        "rows",
        "reasons",
    }
    return not required_keys.issubset(policy)


def _enrich_candidate_replay_effect_payload(payload: dict[str, Any]) -> dict[str, Any]:
    diagnosis = payload.get("diagnosis") if isinstance(payload.get("diagnosis"), dict) else {}
    needs_sector_policy = _sector_leadership_policy_needs_enrichment(diagnosis)
    needs_strategy_pk = _strategy_pk_needs_enrichment(diagnosis)
    needs_market_stress_gate = _market_stress_gate_policy_needs_enrichment(diagnosis)
    if not needs_sector_policy and not needs_strategy_pk and not needs_market_stress_gate:
        return payload
    comparison = {
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "scopes": payload.get("scopes") or {},
        "discovery_cache_dir": payload.get("discovery_cache_dir"),
    }
    horizon = int(diagnosis.get("horizon") or 20)
    enriched_diagnosis = {**diagnosis}
    if needs_sector_policy:
        enriched_diagnosis["sector_leadership_policy"] = diagnose_sector_leadership_policy(
            comparison,
            horizon=horizon,
        )
    if needs_strategy_pk:
        enriched_diagnosis["strategy_pk"] = diagnose_strategy_pk(comparison)
    if needs_market_stress_gate:
        enriched_diagnosis["market_stress_gate_policy"] = diagnose_market_stress_gate_policy(
            comparison,
            horizon=horizon,
        )
    return {
        **payload,
        "diagnosis": enriched_diagnosis,
    }


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


def _best_core_month_metric(
    comparison: dict[str, Any],
    *,
    month: str,
    horizon: int,
) -> tuple[str | None, dict[str, Any]]:
    best_scope: str | None = None
    best_metric: dict[str, Any] = _empty_return_metric()
    for scope in ("action_long", "action"):
        metric = _monthly_guarded_metric(
            comparison,
            scope=scope,
            month=month,
            horizon=horizon,
        )
        if int(metric.get("sample_count") or 0) <= 0:
            continue
        total_return = metric.get("total_return")
        best_total = best_metric.get("total_return")
        if best_scope is None or (
            total_return is not None
            and (best_total is None or float(total_return) > float(best_total))
        ):
            best_scope = scope
            best_metric = metric
    return best_scope, best_metric


def _best_core_metric(
    comparison: dict[str, Any],
    *,
    horizon: int,
) -> tuple[str | None, dict[str, Any]]:
    best_scope: str | None = None
    best_metric: dict[str, Any] = _empty_return_metric()
    for scope in ("action_long", "action"):
        summary = (comparison.get("scopes") or {}).get(scope) or {}
        metric = _guarded_metric(summary, horizon)
        if int(metric.get("sample_count") or 0) <= 0:
            continue
        total_return = metric.get("total_return")
        best_total = best_metric.get("total_return")
        if best_scope is None or (
            total_return is not None
            and (best_total is None or float(total_return) > float(best_total))
        ):
            best_scope = scope
            best_metric = metric
    return best_scope, best_metric


def diagnose_market_stress_gate_policy(
    comparison: dict[str, Any],
    *,
    horizon: int,
    lookback_months: int = 3,
    min_all_month_samples: int = 20,
) -> dict[str, Any]:
    months = _month_candidates(comparison, horizon=horizon)
    all_summary = (comparison.get("scopes") or {}).get("all") or {}
    min_required_samples = (
        3
        if _monthly_metric_label(all_summary, horizon) == "3只等权"
        else min_all_month_samples
    )
    rows: list[dict[str, Any]] = []
    for month in months[-lookback_months:]:
        all_metric = _monthly_guarded_metric(
            comparison,
            scope="all",
            month=month,
            horizon=horizon,
        )
        all_sample_count = int(all_metric.get("sample_count") or 0)
        if all_sample_count < min_required_samples:
            continue
        core_scope, core_metric = _best_core_month_metric(
            comparison,
            month=month,
            horizon=horizon,
        )
        all_total = _metric_float(all_metric, "total_return")
        core_total = _metric_float(core_metric, "total_return")
        rows.append(
            {
                "month": month,
                "all_sample_count": all_sample_count,
                "all_total_return": all_total,
                "core_scope": core_scope,
                "core_label": _SCOPE_LABELS.get(core_scope or "", core_scope),
                "core_sample_count": int(core_metric.get("sample_count") or 0),
                "core_total_return": core_total,
                "avoided_loss": (
                    round(core_total - all_total, 6)
                    if all_total is not None and all_total < 0 and core_total is not None
                    else None
                ),
            }
        )

    if not rows:
        return {
            "status": "insufficient_data",
            "label": "压力样本不足",
            "horizon": horizon,
            "lookback_months": 0,
            "weak_months": 0,
            "defended_months": 0,
            "best_core_scope": None,
            "max_core_positions": 1,
            "avoided_total_loss": None,
            "summary": "弱市月份样本不足，暂不评价市场压力门控效果。",
            "rows": [],
            "reasons": ["没有足够的弱市月度样本。"],
        }

    all_metric = _guarded_metric(all_summary, horizon)
    best_core_scope, best_core_metric = _best_core_metric(comparison, horizon=horizon)
    all_total = _metric_float(all_metric, "total_return")
    best_core_total = _metric_float(best_core_metric, "total_return")
    avoided_total_loss = (
        round(best_core_total - all_total, 6)
        if all_total is not None and all_total < 0 and best_core_total is not None
        else None
    )
    weak_rows = [row for row in rows if (row.get("all_total_return") or 0.0) < 0.0]
    defended_rows = [
        row for row in weak_rows if (row.get("avoided_loss") or 0.0) > 0.0
    ]

    if weak_rows and len(defended_rows) == len(weak_rows) and (avoided_total_loss or 0.0) > 0:
        status = "effective_defense"
        label = "压力门控有效"
        max_core_positions = 1
        summary = "弱月收缩有效：核心行动池相对全候选池明显少亏或转正，压力大时继续少做。"
    elif weak_rows and defended_rows:
        status = "selective_defense"
        label = "压力门控部分有效"
        max_core_positions = 1
        summary = "部分弱月收缩有效，但稳定性还不够，压力大时只保留极少数核心。"
    elif weak_rows:
        status = "cash_defense"
        label = "现金防守优先"
        max_core_positions = 0
        summary = "弱月里核心池也没有明显改善，压力大时应优先空仓观察。"
    else:
        status = "normal_follow"
        label = "正常跟随"
        max_core_positions = 3
        summary = "最近月度没有明显全候选池承压，不需要额外压力门控。"

    reasons = [
        (
            f"{row['month']} 全候选{horizon}日总收益"
            f"{_format_pct(row['all_total_return'])}，"
            f"{row.get('core_label') or '核心池'}"
            f"{_format_pct(row['core_total_return'])}，"
            f"改善{_format_pct(row.get('avoided_loss'))}"
        )
        for row in rows
    ]
    return {
        "status": status,
        "label": label,
        "horizon": horizon,
        "lookback_months": len(rows),
        "weak_months": len(weak_rows),
        "defended_months": len(defended_rows),
        "best_core_scope": best_core_scope,
        "best_core_label": _SCOPE_LABELS.get(best_core_scope or "", best_core_scope),
        "max_core_positions": max_core_positions,
        "avoided_total_loss": avoided_total_loss,
        "summary": summary,
        "rows": rows,
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
        "strategy_pk": diagnose_strategy_pk(
            comparison,
            horizons=(5, 10, 20),
            primary_horizon=horizon,
        ),
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
        "market_stress_gate_policy": diagnose_market_stress_gate_policy(
            comparison,
            horizon=horizon,
        ),
        "dual_line_policy": diagnose_dual_line_policy(
            comparison,
            horizon=horizon,
            market_phase_policy=market_phase_policy,
            potential_watch_policy=potential_watch_policy,
        ),
        "sector_leadership_policy": diagnose_sector_leadership_policy(
            comparison,
            horizon=horizon,
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
    start_date: str | None = None,
    end_date: str | None = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 15,
    min_coverage_ratio: Annotated[float, Query(ge=0.0, le=1.0)] = 0.70,
    include_fundamentals: bool = False,
    force_refresh: bool = False,
    use_monthly_shards: bool = True,
) -> dict:
    resolved_end_date = end_date or (now_local().date() - timedelta(days=1)).isoformat()
    resolved_start_date = start_date or _default_interactive_replay_start_date(resolved_end_date)
    horizons = CANDIDATE_REPLAY_EFFECT_HORIZONS
    cache_key = _candidate_replay_effect_cache_key(
        start_date=resolved_start_date,
        end_date=resolved_end_date,
        limit=limit,
        min_coverage_ratio=min_coverage_ratio,
        include_fundamentals=include_fundamentals,
    )
    cache_path = _candidate_replay_effect_cache_path(cache_key)
    if not force_refresh:
        cached_payload = _load_candidate_replay_effect_cache(cache_path, cache_key=cache_key)
        if cached_payload is not None:
            cached_payload = _enrich_candidate_replay_effect_payload(cached_payload)
            _store_candidate_replay_effect_cache(
                cache_path,
                cache_key=cache_key,
                payload=cached_payload,
            )
            return _with_candidate_replay_cache_meta(
                cached_payload,
                cache_key=cache_key,
                hit=True,
            )

    month_ranges = _candidate_replay_month_ranges(resolved_start_date, resolved_end_date)
    if use_monthly_shards and len(month_ranges) > 1:
        payload, shard_hits, shard_misses = _build_candidate_replay_effect_from_monthly_shards(
            start_date=resolved_start_date,
            end_date=resolved_end_date,
            limit=limit,
            horizons=horizons,
            min_coverage_ratio=min_coverage_ratio,
            include_fundamentals=include_fundamentals,
            force_refresh=force_refresh,
        )
        _store_candidate_replay_effect_cache(cache_path, cache_key=cache_key, payload=payload)
        return _with_candidate_replay_cache_meta(
            payload,
            cache_key=cache_key,
            hit=False,
            mode="monthly_shards",
            shard_count=len(month_ranges),
            shard_hits=shard_hits,
            shard_misses=shard_misses,
        )

    payload = _build_candidate_replay_effect_payload(
        start_date=resolved_start_date,
        end_date=resolved_end_date,
        limit=limit,
        horizons=horizons,
        min_coverage_ratio=min_coverage_ratio,
        include_fundamentals=include_fundamentals,
    )
    _store_candidate_replay_effect_cache(cache_path, cache_key=cache_key, payload=payload)
    return _with_candidate_replay_cache_meta(payload, cache_key=cache_key, hit=False)


def prewarm_candidate_replay_effect_cache(
    *,
    end_date: str | None = None,
    limit: int = 15,
    min_coverage_ratio: float = 0.70,
    include_fundamentals: bool = False,
) -> dict[str, Any]:
    resolved_end_date = end_date or (now_local().date() - timedelta(days=1)).isoformat()
    resolved_start_date = _default_interactive_replay_start_date(resolved_end_date)
    payload = get_candidate_replay_effect(
        start_date=resolved_start_date,
        end_date=resolved_end_date,
        limit=limit,
        min_coverage_ratio=min_coverage_ratio,
        include_fundamentals=include_fundamentals,
        force_refresh=False,
        use_monthly_shards=True,
    )
    replay_cache = payload.get("replay_cache") or {}
    return {
        "status": "ok",
        "start_date": resolved_start_date,
        "end_date": resolved_end_date,
        "cache_hit": bool(replay_cache.get("hit")),
        "cache_mode": replay_cache.get("mode"),
        "shard_count": replay_cache.get("shard_count"),
        "shard_hits": replay_cache.get("shard_hits"),
        "shard_misses": replay_cache.get("shard_misses"),
    }
