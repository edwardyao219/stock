from __future__ import annotations

import json
import re
from calendar import monthrange
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Numeric, Text, and_, cast, delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from services.engine.research_pool.candidates import discover_next_session_candidates
from services.engine.risk.trend_guard import (
    guard_parameters_for_features as _guard_parameters_for_features,
)
from services.notifications.dispatcher import (
    build_candidate_tiers,
    select_action_candidates,
    select_long_action_candidates,
)
from services.shared.database import SessionLocal
from services.shared.models import (
    CandidateDiscoverySnapshot,
    DailyBar,
    LowDimensionalFeatureSnapshot,
    SectorFeatureDaily,
    Security,
    StockFeatureDaily,
)

MAINLINE_RETURN_20D_MIN = 0.08
MAINLINE_RETURN_20D_MAX = 0.18
OVEREXTENDED_RETURN_20D_MIN = 0.24
OVEREXTENDED_POSITIVE_20D_MIN = 85.0
LONG_HORIZON_STRENGTH_REASON = "中期强者：相对强度或板块扩散足够强"
CANDIDATE_DISCOVERY_CACHE_VERSION = "candidate-v5-startup-signal"
DEFAULT_CANDIDATE_DISCOVERY_CACHE_DIR = Path(".tmp/candidate-replay-discovery-cache")
NOISE_WALK_FORWARD_SYMBOLS = {"000001"}
PORTFOLIO_SUMMARY_MAX_POSITIONS = 3
PORTFOLIO_MAX_DRAWDOWN_LIMIT_PCT = 0.15
LOW_DIMENSIONAL_TEXT_PREFILTER_KEYS = (
    "trend_score",
    "relative_strength_score",
    "return_20d",
    "distance_to_ma20",
)
FEATURE_TEXT_NUMBER_PATTERNS = {
    key: re.compile(rf'"{re.escape(key)}"\s*:\s*(-?\d+(?:\.\d+)?)')
    for key in LOW_DIMENSIONAL_TEXT_PREFILTER_KEYS
}
LOW_DIMENSIONAL_CACHE_FEATURE_KEYS = (
    "trend_score",
    "trend_quality_score",
    "relative_strength_score",
    "volume_confirmation_score",
    "price_volume_trend_score",
    "sector_strength_score",
    "sector_avg_return_20d",
    "sector_positive_20d_rate",
    "sector_breadth_score",
    "sector_trend_continuity_score",
    "sector_trend_resilience_score",
    "sector_stock_count",
    "return_5d",
    "return_20d",
    "distance_to_ma20",
    "distance_to_20d_low",
    "max_drawdown_20d",
    "overheat_score",
    "volume_trap_risk_score",
)
SECTOR_STYLE_KEYWORDS = {
    "growth_cycle": (
        "半导体",
        "元器件",
        "通信设备",
        "光学光电子",
        "软件服务",
        "互联网",
        "IT设备",
        "电子化学品",
        "电器仪表",
        "专用机械",
        "机器人",
        "PCB",
    ),
    "cyclical": (
        "铜",
        "铝",
        "小金属",
        "有色",
        "矿物制品",
        "化工原料",
        "化纤",
        "钢铁",
        "煤炭",
        "石油",
        "黄金",
        "稀土",
    ),
    "consumer_quality": (
        "白酒",
        "食品饮料",
        "食品",
        "饮料",
        "旅游",
        "酒店餐饮",
        "家用电器",
        "日用化工",
        "商贸代理",
    ),
    "market_beta": ("证券", "保险", "多元金融"),
    "compound": ("银行", "水力发电", "火力发电", "电力", "公路", "铁路"),
    "healthcare": ("生物制药", "化学制药", "医药", "医疗保健"),
    "property_chain": ("区域地产", "全国地产", "装修装饰", "其他建材", "水泥"),
}


@dataclass(frozen=True)
class WalkForwardCandidate:
    symbol: str
    name: str | None
    sector: str | None
    selection_mode: str
    score: float
    entry_date: str | None
    forward_returns: dict[int, float | None]
    guarded_forward_returns: dict[int, float | None] = field(default_factory=dict)
    guard_exit_days: dict[int, int | None] = field(default_factory=dict)
    guard_exit_reasons: dict[int, str | None] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    sector_strength_score: float | None = None
    sector_return_20d: float | None = None
    sector_style: str | None = None
    startup_signal_score: float | None = None
    startup_signal_label: str | None = None
    startup_signal_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    trade_date: date
    features: dict[str, Any]


@dataclass(frozen=True)
class WalkForwardDay:
    signal_date: str
    next_trade_date: str | None
    universe_size: int
    feature_rows: int
    active_symbols: int
    feature_coverage_ratio: float
    candidates: list[WalkForwardCandidate]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "candidates": [item.to_dict() for item in self.candidates],
        }


@dataclass(frozen=True)
class WalkForwardReplayResult:
    start_date: str
    end_date: str
    processed_days: int
    days: list[WalkForwardDay]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "processed_days": self.processed_days,
            "days": [item.to_dict() for item in self.days],
        }


ForwardReturnBundle = tuple[
    dict[int, float | None],
    dict[int, float | None],
    dict[int, int | None],
    dict[int, str | None],
]
ForwardReturnCacheKey = tuple[str, date, tuple[int, ...], float, float]


def _return_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "sample_count": 0,
            "avg_return": None,
            "win_rate": None,
            "total_return": None,
        }
    return {
        "sample_count": len(values),
        "avg_return": round(sum(values) / len(values), 6),
        "win_rate": round(sum(1 for value in values if value > 0) / len(values), 6),
        "total_return": round(sum(values), 6),
    }


def _month_key(value: str | None) -> str:
    if not value:
        return "unknown"
    return value[:7]


def _optional_float(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return float(value)
    return None


def _safe_metric_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _historical_market_stress_from_discovery(discovery: dict[str, Any]) -> dict[str, Any]:
    existing = discovery.get("market_stress")
    if isinstance(existing, dict):
        return existing

    regime_snapshot = discovery.get("market_regime_snapshot") or {}
    participation_snapshot = discovery.get("market_participation_snapshot") or {}
    emotion_gate = discovery.get("emotion_gate") or {}
    regime = str(discovery.get("market_regime") or regime_snapshot.get("regime") or "")
    gate_state = str(regime_snapshot.get("emotion_gate") or "")
    if not gate_state and isinstance(emotion_gate, dict):
        gate_state = str(emotion_gate.get("state") or "")
    breadth_score = _safe_metric_float(regime_snapshot.get("breadth_score"), 50.0)
    participation_score = _safe_metric_float(
        participation_snapshot.get("participation_score"),
        50.0,
    )
    liquidity_score = _safe_metric_float(
        participation_snapshot.get("liquidity_score"),
        50.0,
    )

    score = 0.0
    reasons: list[str] = []
    if regime == "panic" or gate_state == "risk_off":
        score += 45.0
        reasons.append("历史情绪阀门risk_off，按弱市处理")
    if breadth_score <= 35.0:
        score += 35.0
        reasons.append(f"历史市场宽度{breadth_score:.1f}，多数股票承压")
    elif breadth_score <= 45.0:
        score += 20.0
        reasons.append(f"历史市场宽度{breadth_score:.1f}，赚钱效应偏弱")
    if participation_score < 45.0 or liquidity_score < 35.0:
        score += 15.0
        reasons.append("历史参与度或流动性不足，候选需要二次确认")

    if score >= 70.0:
        status = "risk_off"
        label = "压力大"
        action = "停止扩散，只做观察和风控"
    elif score >= 40.0:
        status = "caution"
        label = "谨慎"
        action = "降低频率，等盘中确认"
    else:
        status = "neutral"
        label = "中性"
        action = "按原计划精选"

    return {
        "stress_status": status,
        "stress_label": label,
        "stress_score": round(score, 2),
        "stress_reasons": reasons or ["历史候选发现阶段没有明显市场压力"],
        "risk_action_label": action,
    }


def _sector_style(security_or_style: Any, sector: str | None = None) -> str | None:
    explicit_style = None
    if isinstance(security_or_style, str):
        explicit_style = security_or_style
    elif security_or_style is not None:
        explicit_style = getattr(security_or_style, "sector_style", None)
        sector = sector or getattr(security_or_style, "industry", None)
    if explicit_style:
        return str(explicit_style)
    sector_name = str(sector or "")
    for style, keywords in SECTOR_STYLE_KEYWORDS.items():
        if any(keyword in sector_name for keyword in keywords):
            return style
    return None


def _is_noise_candidate(candidate: WalkForwardCandidate) -> bool:
    return candidate.symbol in NOISE_WALK_FORWARD_SYMBOLS


def _is_strong_sector_candidate(candidate: WalkForwardCandidate) -> bool:
    sector_strength = candidate.sector_strength_score
    sector_return_20d = candidate.sector_return_20d
    if sector_strength is None or sector_return_20d is None:
        return False
    return sector_strength >= 60.0 and sector_return_20d >= MAINLINE_RETURN_20D_MIN


def _sector_leadership_summary(
    candidates: list[WalkForwardCandidate],
    *,
    horizon: int,
    raw_summary: dict[str, Any],
) -> dict[str, Any]:
    strong_candidates = [
        candidate for candidate in candidates if _is_strong_sector_candidate(candidate)
    ]
    other_candidates = [
        candidate for candidate in candidates if not _is_strong_sector_candidate(candidate)
    ]

    def returns_for(
        selected_candidates: list[WalkForwardCandidate],
        field_name: str,
    ) -> list[float]:
        return [
            value
            for candidate in selected_candidates
            if (value := getattr(candidate, field_name).get(horizon)) is not None
        ]

    strong_raw = _return_summary(returns_for(strong_candidates, "forward_returns"))
    raw_total = raw_summary.get("total_return")
    strong_raw_total = strong_raw.get("total_return")
    return {
        "strong_sector": {
            "raw": strong_raw,
            "guarded": _return_summary(
                returns_for(strong_candidates, "guarded_forward_returns")
            ),
        },
        "other_sector": {
            "raw": _return_summary(returns_for(other_candidates, "forward_returns")),
            "guarded": _return_summary(
                returns_for(other_candidates, "guarded_forward_returns")
            ),
        },
        "strong_sector_sample_share": (
            round(len(strong_candidates) / len(candidates), 6) if candidates else None
        ),
        "strong_sector_return_share": (
            round(float(strong_raw_total) / float(raw_total), 6)
            if raw_total and raw_total > 0 and strong_raw_total is not None
            else None
        ),
    }


def _style_return_summaries(
    candidates: list[WalkForwardCandidate],
    *,
    horizon: int,
) -> dict[str, dict[str, Any]]:
    styles = sorted({str(candidate.sector_style or "unknown") for candidate in candidates})
    summaries: dict[str, dict[str, Any]] = {}
    for style in styles:
        style_candidates = [
            candidate
            for candidate in candidates
            if str(candidate.sector_style or "unknown") == style
        ]
        raw_values = [
            value
            for candidate in style_candidates
            if (value := candidate.forward_returns.get(horizon)) is not None
        ]
        guarded_values = [
            value
            for candidate in style_candidates
            if (value := candidate.guarded_forward_returns.get(horizon)) is not None
        ]
        summaries[style] = {
            "raw": _return_summary(raw_values),
            "guarded": _return_summary(guarded_values),
        }
    return summaries


def _selection_mode_return_summaries(
    candidates: list[WalkForwardCandidate],
    *,
    horizon: int,
) -> dict[str, dict[str, Any]]:
    modes = sorted({str(candidate.selection_mode or "unknown") for candidate in candidates})
    summaries: dict[str, dict[str, Any]] = {}
    for mode in modes:
        mode_candidates = [
            candidate
            for candidate in candidates
            if str(candidate.selection_mode or "unknown") == mode
        ]
        raw_values = [
            value
            for candidate in mode_candidates
            if (value := candidate.forward_returns.get(horizon)) is not None
        ]
        guarded_values = [
            value
            for candidate in mode_candidates
            if (value := candidate.guarded_forward_returns.get(horizon)) is not None
        ]
        summaries[mode] = {
            "raw": _return_summary(raw_values),
            "guarded": _return_summary(guarded_values),
        }
    return summaries


STARTUP_SIGNAL_BUCKET_LABELS = {
    "high": "高分启动观察",
    "medium": "中分启动观察",
    "low": "低分预热观察",
}


def _startup_signal_bucket(candidate: WalkForwardCandidate) -> str | None:
    score = candidate.startup_signal_score
    if score is None:
        return None
    if score >= 80.0:
        return "high"
    if score >= 70.0:
        return "medium"
    return "low"


def _startup_signal_return_summaries(
    candidates: list[WalkForwardCandidate],
    *,
    horizon: int,
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for bucket in ("high", "medium", "low"):
        bucket_candidates = [
            candidate for candidate in candidates if _startup_signal_bucket(candidate) == bucket
        ]
        if not bucket_candidates:
            continue
        raw_values = [
            value
            for candidate in bucket_candidates
            if (value := candidate.forward_returns.get(horizon)) is not None
        ]
        guarded_values = [
            value
            for candidate in bucket_candidates
            if (value := candidate.guarded_forward_returns.get(horizon)) is not None
        ]
        summaries[bucket] = {
            "label": STARTUP_SIGNAL_BUCKET_LABELS[bucket],
            "raw": _return_summary(raw_values),
            "guarded": _return_summary(guarded_values),
        }
    return summaries


def _startup_signal_style_return_summaries(
    candidates: list[WalkForwardCandidate],
    *,
    horizon: int,
) -> dict[str, dict[str, Any]]:
    styles = sorted(
        {
            str(candidate.sector_style or "unknown")
            for candidate in candidates
            if _startup_signal_bucket(candidate) is not None
        }
    )
    return {
        style: _startup_signal_return_summaries(
            [
                candidate
                for candidate in candidates
                if str(candidate.sector_style or "unknown") == style
            ],
            horizon=horizon,
        )
        for style in styles
    }


def _monthly_return_summaries(
    candidates: list[WalkForwardCandidate],
    *,
    horizon: int,
) -> dict[str, dict[str, Any]]:
    months = sorted({_month_key(candidate.entry_date) for candidate in candidates})
    summaries: dict[str, dict[str, Any]] = {}
    for month in months:
        monthly_candidates = [
            candidate
            for candidate in candidates
            if _month_key(candidate.entry_date) == month
        ]
        raw_values = [
            value
            for candidate in monthly_candidates
            if (value := candidate.forward_returns.get(horizon)) is not None
        ]
        guarded_values = [
            value
            for candidate in monthly_candidates
            if (value := candidate.guarded_forward_returns.get(horizon)) is not None
        ]
        raw_summary = _return_summary(raw_values)
        summaries[month] = {
            "raw": raw_summary,
            "guarded": _return_summary(guarded_values),
            "sector_leadership": _sector_leadership_summary(
                monthly_candidates,
                horizon=horizon,
                raw_summary=raw_summary,
            ),
        }
    return summaries


def _monthly_style_return_summaries(
    candidates: list[WalkForwardCandidate],
    *,
    horizon: int,
) -> dict[str, dict[str, Any]]:
    months = sorted({_month_key(candidate.entry_date) for candidate in candidates})
    return {
        month: _style_return_summaries(
            [
                candidate
                for candidate in candidates
                if _month_key(candidate.entry_date) == month
            ],
            horizon=horizon,
        )
        for month in months
    }


def _monthly_selection_mode_return_summaries(
    candidates: list[WalkForwardCandidate],
    *,
    horizon: int,
) -> dict[str, dict[str, Any]]:
    months = sorted({_month_key(candidate.entry_date) for candidate in candidates})
    return {
        month: _selection_mode_return_summaries(
            [
                candidate
                for candidate in candidates
                if _month_key(candidate.entry_date) == month
            ],
            horizon=horizon,
        )
        for month in months
    }


def _monthly_startup_signal_return_summaries(
    candidates: list[WalkForwardCandidate],
    *,
    horizon: int,
) -> dict[str, dict[str, Any]]:
    months = sorted(
        {
            _month_key(candidate.entry_date)
            for candidate in candidates
            if _startup_signal_bucket(candidate) is not None
        }
    )
    return {
        month: _startup_signal_return_summaries(
            [
                candidate
                for candidate in candidates
                if _month_key(candidate.entry_date) == month
            ],
            horizon=horizon,
        )
        for month in months
    }


def _portfolio_return_points(
    days: list[WalkForwardDay],
    *,
    horizon: int,
    field_name: str,
    max_positions: int = PORTFOLIO_SUMMARY_MAX_POSITIONS,
) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    for day in days:
        selected_candidates = [
            candidate for candidate in day.candidates if not _is_noise_candidate(candidate)
        ][:max_positions]
        values = [
            value
            for candidate in selected_candidates
            if (value := getattr(candidate, field_name).get(horizon)) is not None
        ]
        if not values:
            continue
        entry_month = _month_key(selected_candidates[0].entry_date)
        points.append((entry_month, round(sum(values) / len(values), 6)))
    return points


def _portfolio_return_summary(
    days: list[WalkForwardDay],
    *,
    horizon: int,
    max_positions: int = PORTFOLIO_SUMMARY_MAX_POSITIONS,
) -> dict[str, Any]:
    raw_points = _portfolio_return_points(
        days,
        horizon=horizon,
        field_name="forward_returns",
        max_positions=max_positions,
    )
    guarded_points = _portfolio_return_points(
        days,
        horizon=horizon,
        field_name="guarded_forward_returns",
        max_positions=max_positions,
    )
    return {
        "max_positions": max_positions,
        "weighting": "equal_weight_by_signal_day",
        "raw": _return_summary([value for _month, value in raw_points]),
        "guarded": _return_summary([value for _month, value in guarded_points]),
    }


def _non_overlapping_portfolio_return_points(
    days: list[WalkForwardDay],
    *,
    horizon: int,
    field_name: str,
    max_positions: int = PORTFOLIO_SUMMARY_MAX_POSITIONS,
    distinct_sectors: bool = False,
    min_positions: int = 1,
) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    index = 0
    while index < len(days):
        candidates = [
            candidate for candidate in days[index].candidates if not _is_noise_candidate(candidate)
        ]
        values: list[tuple[WalkForwardCandidate, float]] = []
        sectors: set[str] = set()
        for candidate in candidates:
            if not distinct_sectors and len(values) >= max_positions:
                break
            sector = str(candidate.sector or "unknown")
            if distinct_sectors and sector in sectors:
                continue
            value = getattr(candidate, field_name).get(horizon)
            if value is None:
                continue
            sectors.add(sector)
            values.append((candidate, float(value)))
            if len(values) >= max_positions:
                break
        if len(values) < min_positions:
            index += 1
            continue
        points.append(
            (
                str(values[0][0].entry_date or days[index].next_trade_date or ""),
                round(sum(value for _candidate, value in values) / len(values), 6),
            )
        )
        index += max(1, horizon)
    return points


def _non_compound_capital_summary(
    points: list[tuple[str, float]],
    *,
    max_drawdown_limit_pct: float = PORTFOLIO_MAX_DRAWDOWN_LIMIT_PCT,
) -> dict[str, Any]:
    cumulative = 0.0
    peak = 0.0
    worst_drawdown = 0.0
    curve: list[dict[str, Any]] = []
    for entry_date, value in points:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = cumulative - peak
        worst_drawdown = min(worst_drawdown, drawdown)
        curve.append(
            {
                "entry_date": entry_date,
                "period_return": round(value, 6),
                "cumulative_return": round(cumulative, 6),
                "drawdown": round(drawdown, 6),
            }
        )
    limit = abs(max_drawdown_limit_pct)
    return {
        **_return_summary([value for _entry_date, value in points]),
        "max_drawdown": round(worst_drawdown, 6),
        "max_drawdown_limit_pct": limit,
        "max_drawdown_passed": worst_drawdown >= -limit,
        "curve": curve,
    }


def _capital_validation_summary(
    points: list[tuple[str, float]],
    *,
    min_samples: int = 5,
) -> dict[str, Any]:
    points_by_year: dict[str, list[tuple[str, float]]] = {}
    for entry_date, value in points:
        points_by_year.setdefault(entry_date[:4], []).append((entry_date, value))

    windows: list[dict[str, Any]] = []
    for year, year_points in sorted(points_by_year.items()):
        metric = _non_compound_capital_summary(year_points)
        enough_samples = int(metric["sample_count"]) >= min_samples
        status = (
            "insufficient"
            if not enough_samples
            else "passed"
            if float(metric["total_return"] or 0.0) > 0
            and bool(metric["max_drawdown_passed"])
            else "failed"
        )
        windows.append(
            {
                "window": year,
                "status": status,
                **{key: value for key, value in metric.items() if key != "curve"},
            }
        )

    valid_windows = [item for item in windows if item["status"] != "insufficient"]
    passed_windows = [item for item in windows if item["status"] == "passed"]
    status = (
        "failed"
        if any(item["status"] == "failed" for item in valid_windows)
        else "passed"
        if len(valid_windows) >= 3
        else "insufficient"
    )
    return {
        "status": status,
        "min_samples_per_window": min_samples,
        "valid_window_count": len(valid_windows),
        "passed_window_count": len(passed_windows),
        "windows": windows,
    }


def _capital_curve_summary(
    days: list[WalkForwardDay],
    *,
    horizon: int,
    max_positions: int = PORTFOLIO_SUMMARY_MAX_POSITIONS,
) -> dict[str, Any]:
    defensive_points = _non_overlapping_portfolio_return_points(
        days,
        horizon=horizon,
        field_name="guarded_forward_returns",
        max_positions=max_positions,
        distinct_sectors=True,
        min_positions=max_positions,
    )
    return {
        "max_positions": max_positions,
        "weighting": "equal_weight_fixed_notional",
        "holding_period_days": horizon,
        "return_calculation": "simple_sum_no_compounding",
        "defensive_policy": "three_distinct_sectors",
        "raw": _non_compound_capital_summary(
            _non_overlapping_portfolio_return_points(
                days,
                horizon=horizon,
                field_name="forward_returns",
                max_positions=max_positions,
            )
        ),
        "guarded": _non_compound_capital_summary(
            _non_overlapping_portfolio_return_points(
                days,
                horizon=horizon,
                field_name="guarded_forward_returns",
                max_positions=max_positions,
            )
        ),
        "defensive_breadth": _non_compound_capital_summary(defensive_points),
        "defensive_validation": _capital_validation_summary(defensive_points),
    }


def _monthly_portfolio_return_summaries(
    days: list[WalkForwardDay],
    *,
    horizon: int,
    max_positions: int = PORTFOLIO_SUMMARY_MAX_POSITIONS,
) -> dict[str, Any]:
    raw_points = _portfolio_return_points(
        days,
        horizon=horizon,
        field_name="forward_returns",
        max_positions=max_positions,
    )
    guarded_points = _portfolio_return_points(
        days,
        horizon=horizon,
        field_name="guarded_forward_returns",
        max_positions=max_positions,
    )
    months = sorted({month for month, _value in raw_points + guarded_points})
    return {
        month: {
            "max_positions": max_positions,
            "weighting": "equal_weight_by_signal_day",
            "raw": _return_summary(
                [value for point_month, value in raw_points if point_month == month]
            ),
            "guarded": _return_summary(
                [value for point_month, value in guarded_points if point_month == month]
            ),
        }
        for month in months
    }


def _style_horizon_preferences(
    style_horizon_summaries: dict[int, dict[str, Any]],
    *,
    min_actionable_samples: int = 10,
) -> dict[str, dict[str, Any]]:
    styles = sorted(
        {
            style
            for horizon_summary in style_horizon_summaries.values()
            for style in horizon_summary
        }
    )
    preferences: dict[str, dict[str, Any]] = {}
    for style in styles:
        best: tuple[int, dict[str, Any]] | None = None
        for horizon in sorted(style_horizon_summaries):
            summary = style_horizon_summaries[horizon].get(style, {})
            guarded = summary.get("guarded") or {}
            avg_return = guarded.get("avg_return")
            if avg_return is None:
                continue
            if best is None or float(avg_return) > float(best[1]["avg_return"]):
                best = (
                    horizon,
                    {
                        "avg_return": avg_return,
                        "sample_count": guarded.get("sample_count", 0),
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


def summarize_walk_forward_replay(
    result: WalkForwardReplayResult,
    *,
    horizons: tuple[int, ...] = (1, 5, 10, 20),
) -> dict[str, Any]:
    all_candidates = [candidate for day in result.days for candidate in day.candidates]
    excluded_symbols = sorted(
        {candidate.symbol for candidate in all_candidates if _is_noise_candidate(candidate)}
    )
    candidates = [
        candidate for candidate in all_candidates if not _is_noise_candidate(candidate)
    ]
    sector_counts = Counter(str(candidate.sector or "unknown") for candidate in candidates)
    style_counts = Counter(str(candidate.sector_style or "unknown") for candidate in candidates)
    selection_mode_counts = Counter(
        str(candidate.selection_mode or "unknown") for candidate in candidates
    )
    startup_signal_counts = Counter(
        bucket for candidate in candidates if (bucket := _startup_signal_bucket(candidate))
    )
    horizon_summaries: dict[int, dict[str, Any]] = {}
    style_horizon_summaries: dict[int, dict[str, Any]] = {}
    selection_mode_horizon_summaries: dict[int, dict[str, Any]] = {}
    startup_signal_horizon_summaries: dict[int, dict[str, Any]] = {}
    startup_signal_style_horizon_summaries: dict[int, dict[str, Any]] = {}
    for horizon in horizons:
        raw_values = [
            value
            for candidate in candidates
            if (value := candidate.forward_returns.get(horizon)) is not None
        ]
        guarded_values = [
            value
            for candidate in candidates
            if (value := candidate.guarded_forward_returns.get(horizon)) is not None
        ]
        exit_reasons = Counter(
            str(reason)
            for candidate in candidates
            if (reason := candidate.guard_exit_reasons.get(horizon)) is not None
        )
        horizon_summaries[horizon] = {
            "raw": _return_summary(raw_values),
            "guarded": {
                **_return_summary(guarded_values),
                "exit_reasons": dict(exit_reasons),
            },
        }
        style_horizon_summaries[horizon] = _style_return_summaries(
            candidates,
            horizon=horizon,
        )
        selection_mode_horizon_summaries[horizon] = _selection_mode_return_summaries(
            candidates,
            horizon=horizon,
        )
        startup_signal_horizon_summaries[horizon] = _startup_signal_return_summaries(
            candidates,
            horizon=horizon,
        )
        startup_signal_style_horizon_summaries[horizon] = (
            _startup_signal_style_return_summaries(
                candidates,
                horizon=horizon,
            )
        )
    return {
        "start_date": result.start_date,
        "end_date": result.end_date,
        "processed_days": result.processed_days,
        "candidate_count": len(candidates),
        "excluded_symbols": excluded_symbols,
        "warning_days": sum(1 for day in result.days if day.warnings),
        "top_sectors": [
            {"sector": sector, "count": count}
            for sector, count in sector_counts.most_common(10)
        ],
        "style_counts": [
            {"style": style, "count": count}
            for style, count in sorted(style_counts.items())
        ],
        "selection_mode_counts": [
            {"selection_mode": mode, "count": count}
            for mode, count in sorted(selection_mode_counts.items())
        ],
        "startup_signal_counts": [
            {
                "bucket": bucket,
                "label": STARTUP_SIGNAL_BUCKET_LABELS[bucket],
                "count": startup_signal_counts[bucket],
            }
            for bucket in ("high", "medium", "low")
            if startup_signal_counts[bucket]
        ],
        "horizons": horizon_summaries,
        "portfolio_horizons": {
            horizon: _portfolio_return_summary(result.days, horizon=horizon)
            for horizon in horizons
        },
        "capital_curve_horizons": {
            horizon: _capital_curve_summary(result.days, horizon=horizon)
            for horizon in horizons
        },
        "style_horizons": style_horizon_summaries,
        "selection_mode_horizons": selection_mode_horizon_summaries,
        "startup_signal_horizons": startup_signal_horizon_summaries,
        "startup_signal_style_horizons": startup_signal_style_horizon_summaries,
        "style_horizon_preferences": _style_horizon_preferences(
            style_horizon_summaries,
        ),
        "monthly_horizons": {
            horizon: _monthly_return_summaries(candidates, horizon=horizon)
            for horizon in horizons
        },
        "monthly_portfolio_horizons": {
            horizon: _monthly_portfolio_return_summaries(result.days, horizon=horizon)
            for horizon in horizons
        },
        "monthly_style_horizons": {
            horizon: _monthly_style_return_summaries(candidates, horizon=horizon)
            for horizon in horizons
        },
        "monthly_selection_mode_horizons": {
            horizon: _monthly_selection_mode_return_summaries(candidates, horizon=horizon)
            for horizon in horizons
        },
        "monthly_startup_signal_horizons": {
            horizon: _monthly_startup_signal_return_summaries(candidates, horizon=horizon)
            for horizon in horizons
        },
    }


def _has_long_horizon_strength_reason(item: dict[str, Any]) -> bool:
    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    return LONG_HORIZON_STRENGTH_REASON in reasons_text


def _is_startup_preheat_candidate_item(item: dict[str, Any]) -> bool:
    if str(item.get("selection_mode") or "").strip() != "potential_watch":
        return False
    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    return "启动前夜：T-1量价修复" in reasons_text


def _is_startup_confirmed_candidate_item(item: dict[str, Any]) -> bool:
    if not _is_startup_preheat_candidate_item(item):
        return False
    startup_score = _optional_float(item, "startup_signal_score") or 0.0
    sector_strength = _optional_float(item, "sector_strength_score") or 0.0
    sector_return = _optional_float(item, "sector_avg_return_20d", "sector_return_20d")
    volume = _optional_float(item, "volume_confirmation_score", "volume_score") or 0.0
    price_volume = _optional_float(item, "price_volume_trend_score") or volume
    return_20d = _optional_float(item, "return_20d") or 0.0
    distance_to_ma20 = _optional_float(item, "distance_to_ma20") or 0.0
    risk_flags_text = " ".join(str(flag) for flag in item.get("risk_flags") or [])
    return (
        startup_score >= 80.0
        and sector_strength >= 58.0
        and sector_return is not None
        and sector_return >= 0.0
        and (volume >= 80.0 or price_volume >= 78.0)
        and 0.0 <= return_20d <= 0.16
        and 0.0 <= distance_to_ma20 <= 0.08
        and "拥挤" not in risk_flags_text
    )


def _candidate_discovery_cache_path(
    cache_dir: str | Path,
    *,
    signal_date: date,
    next_date: date,
    limit: int,
    include_fundamentals: bool,
) -> Path:
    return Path(cache_dir) / (
        f"{CANDIDATE_DISCOVERY_CACHE_VERSION}_"
        f"{signal_date.isoformat()}_{next_date.isoformat()}_"
        f"limit{limit}_fund{int(include_fundamentals)}.json"
    )


def _load_candidate_discovery_cache(
    cache_dir: str | Path | None,
    *,
    signal_date: date,
    next_date: date,
    limit: int,
    include_fundamentals: bool,
) -> dict[str, Any] | None:
    if cache_dir is None:
        return None
    path = _candidate_discovery_cache_path(
        cache_dir,
        signal_date=signal_date,
        next_date=next_date,
        limit=limit,
        include_fundamentals=include_fundamentals,
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("version") != CANDIDATE_DISCOVERY_CACHE_VERSION:
        return None
    discovery = payload.get("discovery")
    if not isinstance(discovery, dict):
        return None
    if not _candidate_discovery_passes_no_future_guard(discovery, signal_date):
        return None
    return discovery


def _normalized_candidate_discovery(discovery: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(discovery, ensure_ascii=False, sort_keys=True, default=str))


def _parse_discovery_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).split("T", maxsplit=1)[0])
    except ValueError:
        return None


def _candidate_discovery_passes_no_future_guard(
    discovery: dict[str, Any],
    signal_date: date,
) -> bool:
    for key in ("feature_date", "requested_feature_date"):
        discovered_date = _parse_discovery_date(discovery.get(key))
        if discovered_date is not None and discovered_date > signal_date:
            return False
    return True


def _ensure_candidate_discovery_has_no_future_features(
    discovery: dict[str, Any],
    signal_date: date,
) -> None:
    if not _candidate_discovery_passes_no_future_guard(discovery, signal_date):
        raise ValueError(
            "candidate discovery contains future feature dates "
            f"for signal_date {signal_date.isoformat()}"
        )


def _load_candidate_discovery_db_cache(
    db: Any,
    *,
    signal_date: date,
    next_date: date,
    limit: int,
    include_fundamentals: bool,
) -> dict[str, Any] | None:
    row = db.execute(
        select(CandidateDiscoverySnapshot)
        .where(CandidateDiscoverySnapshot.cache_version == CANDIDATE_DISCOVERY_CACHE_VERSION)
        .where(CandidateDiscoverySnapshot.signal_date == signal_date)
        .where(CandidateDiscoverySnapshot.next_trade_date == next_date)
        .where(CandidateDiscoverySnapshot.candidate_limit == limit)
        .where(CandidateDiscoverySnapshot.include_fundamentals.is_(include_fundamentals))
    ).scalar_one_or_none()
    if row is None:
        return None
    discovery = row.discovery_json
    if not isinstance(discovery, dict):
        return None
    if not _candidate_discovery_passes_no_future_guard(discovery, signal_date):
        return None
    return discovery


def _candidate_discovery_snapshot_row(
    db: Any,
    *,
    signal_date: date,
    next_date: date,
    limit: int,
    include_fundamentals: bool,
) -> CandidateDiscoverySnapshot | None:
    return db.execute(
        select(CandidateDiscoverySnapshot)
        .where(CandidateDiscoverySnapshot.cache_version == CANDIDATE_DISCOVERY_CACHE_VERSION)
        .where(CandidateDiscoverySnapshot.signal_date == signal_date)
        .where(CandidateDiscoverySnapshot.next_trade_date == next_date)
        .where(CandidateDiscoverySnapshot.candidate_limit == limit)
        .where(CandidateDiscoverySnapshot.include_fundamentals.is_(include_fundamentals))
    ).scalar_one_or_none()


def _store_candidate_discovery_db_cache(
    db: Any,
    *,
    signal_date: date,
    next_date: date,
    limit: int,
    include_fundamentals: bool,
    discovery: dict[str, Any],
) -> None:
    payload = _normalized_candidate_discovery(discovery)
    row = _candidate_discovery_snapshot_row(
        db,
        signal_date=signal_date,
        next_date=next_date,
        limit=limit,
        include_fundamentals=include_fundamentals,
    )
    now = datetime.utcnow()
    if row is None:
        db.add(
            CandidateDiscoverySnapshot(
                cache_version=CANDIDATE_DISCOVERY_CACHE_VERSION,
                signal_date=signal_date,
                next_trade_date=next_date,
                candidate_limit=limit,
                include_fundamentals=include_fundamentals,
                discovery_json=payload,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        row.discovery_json = payload
        row.updated_at = now
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = _candidate_discovery_snapshot_row(
            db,
            signal_date=signal_date,
            next_date=next_date,
            limit=limit,
            include_fundamentals=include_fundamentals,
        )
        if row is None:
            raise
        row.discovery_json = payload
        row.updated_at = datetime.utcnow()
        db.commit()


def _store_candidate_discovery_cache(
    cache_dir: str | Path | None,
    *,
    signal_date: date,
    next_date: date,
    limit: int,
    include_fundamentals: bool,
    discovery: dict[str, Any],
) -> None:
    if cache_dir is None:
        return
    path = _candidate_discovery_cache_path(
        cache_dir,
        signal_date=signal_date,
        next_date=next_date,
        limit=limit,
        include_fundamentals=include_fundamentals,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CANDIDATE_DISCOVERY_CACHE_VERSION,
        "signal_date": signal_date.isoformat(),
        "next_date": next_date.isoformat(),
        "limit": limit,
        "include_fundamentals": include_fundamentals,
        "discovery": _normalized_candidate_discovery(discovery),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _parse(value: str) -> date:
    return date.fromisoformat(value)


def _trade_dates(db, start_date: date, end_date: date) -> list[date]:
    return list(
        db.execute(
            select(DailyBar.trade_date)
            .where(DailyBar.trade_date >= start_date)
            .where(DailyBar.trade_date <= end_date)
            .group_by(DailyBar.trade_date)
            .order_by(DailyBar.trade_date)
        ).scalars()
    )


def _feature_coverage(db, trade_date: date) -> tuple[int, int, float]:
    feature_rows = int(
        db.execute(
            select(func.count(func.distinct(StockFeatureDaily.symbol))).where(
                StockFeatureDaily.trade_date == trade_date
            )
        ).scalar_one()
        or 0
    )
    active_symbols = int(
        db.execute(
            select(func.count())
            .select_from(Security)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).scalar_one()
        or 0
    )
    coverage = round(feature_rows / active_symbols, 4) if active_symbols else 0.0
    return feature_rows, active_symbols, coverage


def _feature_coverage_by_date(
    db,
    trade_dates: list[date],
) -> dict[date, tuple[int, int, float]]:
    if not trade_dates:
        return {}
    active_symbols = int(
        db.execute(
            select(func.count())
            .select_from(Security)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).scalar_one()
        or 0
    )
    feature_counts = {
        row.trade_date: int(row.feature_rows or 0)
        for row in db.execute(
            select(
                StockFeatureDaily.trade_date.label("trade_date"),
                func.count().label("feature_rows"),
            )
            .where(StockFeatureDaily.trade_date.in_(trade_dates))
            .group_by(StockFeatureDaily.trade_date)
        ).all()
    }
    return {
        trade_date: (
            feature_rows := feature_counts.get(trade_date, 0),
            active_symbols,
            round(feature_rows / active_symbols, 4) if active_symbols else 0.0,
        )
        for trade_date in trade_dates
    }


def _count_by_trade_date_range(
    db,
    model: type,
    *,
    start_date: date,
    end_date: date,
) -> dict[date, int]:
    return {
        row.trade_date: int(row.row_count or 0)
        for row in db.execute(
            select(
                model.trade_date.label("trade_date"),
                func.count().label("row_count"),
            )
            .where(model.trade_date >= start_date)
            .where(model.trade_date <= end_date)
            .group_by(model.trade_date)
        ).all()
    }


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _coverage_grade(
    *,
    trade_days: int,
    feature_day_ratio: float | None,
    avg_feature_active_coverage: float | None,
    avg_sector_rows: float | None,
    min_trade_days: int,
    min_active_feature_coverage: float,
    min_sector_rows: int,
    is_incomplete_tail_month: bool = False,
) -> str:
    if trade_days <= 0:
        return "no_data"
    if (
        (trade_days < min_trade_days and not is_incomplete_tail_month)
        or (feature_day_ratio or 0.0) < 0.80
        or (avg_feature_active_coverage or 0.0) < min_active_feature_coverage
        or (avg_sector_rows or 0.0) < min_sector_rows
    ):
        return "partial"
    if (
        (feature_day_ratio or 0.0) >= 0.95
        and (avg_feature_active_coverage or 0.0) >= 0.90
        and (avg_sector_rows or 0.0) >= min_sector_rows
    ):
        return "strong"
    return "usable"


def _coverage_warnings(
    *,
    month: str,
    trade_days: int,
    feature_day_ratio: float | None,
    avg_feature_active_coverage: float | None,
    avg_sector_rows: float | None,
    min_trade_days: int,
    min_active_feature_coverage: float,
    min_sector_rows: int,
    is_incomplete_tail_month: bool = False,
) -> list[str]:
    warnings: list[str] = []
    if trade_days <= 0:
        return [f"{month} 没有日线样本，不能纳入回归判断。"]
    if trade_days < min_trade_days and not is_incomplete_tail_month:
        warnings.append(f"{month} 交易日样本偏少（{trade_days}天），只作局部参考。")
    if (feature_day_ratio or 0.0) < 0.80:
        warnings.append(f"{month} 特征日期覆盖不足，先不要用它调参。")
    if (avg_feature_active_coverage or 0.0) < min_active_feature_coverage:
        coverage_pct = (avg_feature_active_coverage or 0.0) * 100
        warnings.append(
            f"{month} 样本偏窄：特征/活跃证券覆盖约{coverage_pct:.1f}%，"
            "只作压力测试，不参与放宽策略。"
        )
    if (avg_sector_rows or 0.0) < min_sector_rows:
        warnings.append(f"{month} 板块特征样本不足，板块优先逻辑需要谨慎解释。")
    return warnings


def _is_incomplete_tail_month(month: str, end_date: date) -> bool:
    if month != end_date.strftime("%Y-%m"):
        return False
    last_day = monthrange(end_date.year, end_date.month)[1]
    return end_date.day < last_day


def build_replay_data_coverage_report(
    *,
    start_date: str,
    end_date: str,
    min_trade_days: int = 10,
    min_active_feature_coverage: float = 0.70,
    min_sector_rows: int = 20,
) -> dict[str, Any]:
    start = _parse(start_date)
    end = _parse(end_date)
    with SessionLocal() as db:
        active_symbols = int(
            db.execute(
                select(func.count())
                .select_from(Security)
                .where(Security.is_active.is_(True))
                .where(Security.is_st.is_(False))
            ).scalar_one()
            or 0
        )
        bar_counts = _count_by_trade_date_range(
            db,
            DailyBar,
            start_date=start,
            end_date=end,
        )
        feature_counts = _count_by_trade_date_range(
            db,
            StockFeatureDaily,
            start_date=start,
            end_date=end,
        )
        sector_counts = _count_by_trade_date_range(
            db,
            SectorFeatureDaily,
            start_date=start,
            end_date=end,
        )

    dates_by_month: dict[str, list[date]] = {}
    for trade_date in sorted(bar_counts):
        dates_by_month.setdefault(trade_date.strftime("%Y-%m"), []).append(trade_date)

    months: list[dict[str, Any]] = []
    for month, month_dates in sorted(dates_by_month.items()):
        is_incomplete_tail_month = _is_incomplete_tail_month(month, end)
        trade_days = len(month_dates)
        feature_days = sum(
            1 for current_date in month_dates if feature_counts.get(current_date, 0) > 0
        )
        sector_days = sum(
            1 for current_date in month_dates if sector_counts.get(current_date, 0) > 0
        )
        avg_bar_symbols = _avg(
            [float(bar_counts.get(current_date, 0)) for current_date in month_dates]
        )
        avg_feature_symbols = _avg(
            [float(feature_counts.get(current_date, 0)) for current_date in month_dates]
        )
        avg_sector_rows = _avg(
            [float(sector_counts.get(current_date, 0)) for current_date in month_dates]
        )
        feature_day_ratio = _ratio(float(feature_days), float(trade_days))
        sector_day_ratio = _ratio(float(sector_days), float(trade_days))
        avg_market_feature_coverage = _avg(
            [
                feature_counts.get(current_date, 0) / bar_counts.get(current_date, 1)
                for current_date in month_dates
                if bar_counts.get(current_date, 0) > 0
            ]
        )
        avg_feature_active_coverage = _avg(
            [
                feature_counts.get(current_date, 0) / active_symbols
                for current_date in month_dates
                if active_symbols > 0
            ]
        )
        grade = _coverage_grade(
            trade_days=trade_days,
            feature_day_ratio=feature_day_ratio,
            avg_feature_active_coverage=avg_feature_active_coverage,
            avg_sector_rows=avg_sector_rows,
            min_trade_days=min_trade_days,
            min_active_feature_coverage=min_active_feature_coverage,
            min_sector_rows=min_sector_rows,
            is_incomplete_tail_month=is_incomplete_tail_month,
        )
        warnings = _coverage_warnings(
            month=month,
            trade_days=trade_days,
            feature_day_ratio=feature_day_ratio,
            avg_feature_active_coverage=avg_feature_active_coverage,
            avg_sector_rows=avg_sector_rows,
            min_trade_days=min_trade_days,
            min_active_feature_coverage=min_active_feature_coverage,
            min_sector_rows=min_sector_rows,
            is_incomplete_tail_month=is_incomplete_tail_month,
        )
        months.append(
            {
                "month": month,
                "grade": grade,
                "is_incomplete_tail_month": is_incomplete_tail_month,
                "trade_days": trade_days,
                "feature_days": feature_days,
                "sector_days": sector_days,
                "avg_daily_bar_symbols": avg_bar_symbols,
                "avg_feature_symbols": avg_feature_symbols,
                "avg_sector_rows": avg_sector_rows,
                "feature_day_ratio": feature_day_ratio,
                "sector_day_ratio": sector_day_ratio,
                "avg_market_feature_coverage": avg_market_feature_coverage,
                "avg_feature_active_coverage": avg_feature_active_coverage,
                "warnings": warnings,
            }
        )

    warning_months = [month for month in months if month["grade"] in {"partial", "no_data"}]
    strong_or_usable_months = [month for month in months if month["grade"] in {"strong", "usable"}]
    overall_grade = (
        "no_data"
        if not months
        else "partial"
        if warning_months
        else "strong"
        if all(month["grade"] == "strong" for month in months)
        else "usable"
    )
    warnings = [
        warning
        for month in months
        for warning in month["warnings"]
    ][:12]
    return {
        "start_date": start_date,
        "end_date": end_date,
        "overall": {
            "grade": overall_grade,
            "months": len(months),
            "usable_months": len(strong_or_usable_months),
            "warning_months": len(warning_months),
            "active_symbols": active_symbols,
            "min_trade_days": min_trade_days,
            "min_active_feature_coverage": min_active_feature_coverage,
            "min_sector_rows": min_sector_rows,
        },
        "months": months,
        "warnings": warnings,
    }


def _nth_trade_date_after(db, signal_date: date, horizon: int) -> date | None:
    if horizon <= 0:
        return signal_date
    return db.execute(
        select(DailyBar.trade_date)
        .where(DailyBar.trade_date >= signal_date)
        .group_by(DailyBar.trade_date)
        .order_by(DailyBar.trade_date)
        .offset(max(0, horizon - 1))
        .limit(1)
    ).scalar_one_or_none()


def _forward_returns(
    db,
    *,
    symbol: str,
    entry_date: date | None,
    horizons: tuple[int, ...],
) -> dict[int, float | None]:
    if entry_date is None:
        return {horizon: None for horizon in horizons}
    entry_open = db.execute(
        select(DailyBar.open)
        .where(DailyBar.symbol == symbol)
        .where(DailyBar.trade_date == entry_date)
    ).scalar_one_or_none()
    if entry_open is None or float(entry_open) <= 0:
        return {horizon: None for horizon in horizons}

    result: dict[int, float | None] = {}
    for horizon in horizons:
        target_date = _nth_trade_date_after(db, entry_date, horizon)
        if target_date is None:
            result[horizon] = None
            continue
        target_close = db.execute(
            select(DailyBar.close)
            .where(DailyBar.symbol == symbol)
            .where(DailyBar.trade_date == target_date)
        ).scalar_one_or_none()
        result[horizon] = (
            round(float(target_close) / float(entry_open) - 1.0, 6)
            if target_close is not None
            else None
        )
    return result


def _daily_bar_cache_by_symbol_date(
    db,
    *,
    symbols: set[str],
    start_date: date | None,
    end_date: date | None,
) -> dict[tuple[str, date], tuple[float, float]]:
    if not symbols or start_date is None or end_date is None:
        return {}
    rows = db.execute(
        select(DailyBar.symbol, DailyBar.trade_date, DailyBar.open, DailyBar.close)
        .where(DailyBar.symbol.in_(sorted(symbols)))
        .where(DailyBar.trade_date >= start_date)
        .where(DailyBar.trade_date <= end_date)
        .order_by(DailyBar.symbol, DailyBar.trade_date)
    ).all()
    return {
        (str(row.symbol), row.trade_date): (float(row.open), float(row.close))
        for row in rows
    }


def _target_date_from_trade_dates(
    trade_dates: list[date],
    trade_date_index: dict[date, int],
    *,
    entry_date: date,
    horizon: int,
) -> date | None:
    entry_index = trade_date_index.get(entry_date)
    if entry_index is None:
        return None
    target_index = entry_index + max(0, horizon - 1)
    if target_index >= len(trade_dates):
        return None
    return trade_dates[target_index]


def _forward_returns_from_cache(
    bar_cache: dict[tuple[str, date], tuple[float, float]],
    trade_dates: list[date],
    trade_date_index: dict[date, int],
    *,
    symbol: str,
    entry_date: date | None,
    horizons: tuple[int, ...],
) -> dict[int, float | None]:
    if entry_date is None:
        return {horizon: None for horizon in horizons}
    entry_bar = bar_cache.get((symbol, entry_date))
    if entry_bar is None:
        return {horizon: None for horizon in horizons}
    entry_open = entry_bar[0]
    if entry_open <= 0:
        return {horizon: None for horizon in horizons}

    result: dict[int, float | None] = {}
    for horizon in horizons:
        target_date = _target_date_from_trade_dates(
            trade_dates,
            trade_date_index,
            entry_date=entry_date,
            horizon=horizon,
        )
        target_bar = bar_cache.get((symbol, target_date)) if target_date else None
        result[horizon] = (
            round(target_bar[1] / entry_open - 1.0, 6)
            if target_bar is not None
            else None
        )
    return result


def _guarded_forward_returns(
    db,
    *,
    symbol: str,
    entry_date: date | None,
    horizons: tuple[int, ...],
    stop_loss_pct: float,
    trailing_drawdown_pct: float,
) -> tuple[dict[int, float | None], dict[int, int | None], dict[int, str | None]]:
    if entry_date is None:
        empty_returns = {horizon: None for horizon in horizons}
        empty_days = {horizon: None for horizon in horizons}
        empty_reasons = {horizon: None for horizon in horizons}
        return empty_returns, empty_days, empty_reasons

    max_horizon = max(horizons) if horizons else 0
    bars = list(
        db.execute(
            select(DailyBar.trade_date, DailyBar.open, DailyBar.close)
            .where(DailyBar.symbol == symbol)
            .where(DailyBar.trade_date >= entry_date)
            .order_by(DailyBar.trade_date)
            .limit(max_horizon)
        ).all()
    )
    if not bars:
        empty_returns = {horizon: None for horizon in horizons}
        empty_days = {horizon: None for horizon in horizons}
        empty_reasons = {horizon: None for horizon in horizons}
        return empty_returns, empty_days, empty_reasons

    entry_open = float(bars[0].open)
    if entry_open <= 0:
        empty_returns = {horizon: None for horizon in horizons}
        empty_days = {horizon: None for horizon in horizons}
        empty_reasons = {horizon: None for horizon in horizons}
        return empty_returns, empty_days, empty_reasons

    returns: dict[int, float | None] = {}
    exit_days: dict[int, int | None] = {}
    exit_reasons: dict[int, str | None] = {}
    for horizon in horizons:
        if len(bars) < horizon:
            returns[horizon] = None
            exit_days[horizon] = None
            exit_reasons[horizon] = None
            continue
        peak = entry_open
        guarded_return = None
        exit_day = None
        exit_reason = None
        for index, row in enumerate(bars[:horizon], start=1):
            close = float(row.close)
            peak = max(peak, close)
            current_return = close / entry_open - 1.0
            drawdown = close / peak - 1.0 if peak > 0 else 0.0
            if current_return <= -abs(stop_loss_pct):
                guarded_return = current_return
                exit_day = index
                exit_reason = "stop_loss"
                break
            if drawdown <= -abs(trailing_drawdown_pct):
                guarded_return = current_return
                exit_day = index
                exit_reason = "trailing_drawdown"
                break
        if guarded_return is None:
            guarded_return = float(bars[horizon - 1].close) / entry_open - 1.0
            exit_day = horizon
            exit_reason = "horizon"
        returns[horizon] = round(guarded_return, 6)
        exit_days[horizon] = exit_day
        exit_reasons[horizon] = exit_reason
    return returns, exit_days, exit_reasons


def _guarded_forward_returns_from_cache(
    bar_cache: dict[tuple[str, date], tuple[float, float]],
    trade_dates: list[date],
    trade_date_index: dict[date, int],
    *,
    symbol: str,
    entry_date: date | None,
    horizons: tuple[int, ...],
    stop_loss_pct: float,
    trailing_drawdown_pct: float,
) -> tuple[dict[int, float | None], dict[int, int | None], dict[int, str | None]]:
    if entry_date is None:
        empty_returns = {horizon: None for horizon in horizons}
        empty_days = {horizon: None for horizon in horizons}
        empty_reasons = {horizon: None for horizon in horizons}
        return empty_returns, empty_days, empty_reasons

    entry_index = trade_date_index.get(entry_date)
    if entry_index is None:
        empty_returns = {horizon: None for horizon in horizons}
        empty_days = {horizon: None for horizon in horizons}
        empty_reasons = {horizon: None for horizon in horizons}
        return empty_returns, empty_days, empty_reasons

    max_horizon = max(horizons) if horizons else 0
    bars = []
    for trade_date in trade_dates[entry_index : entry_index + max_horizon]:
        bar = bar_cache.get((symbol, trade_date))
        if bar is not None:
            bars.append((trade_date, bar[0], bar[1]))
    if not bars:
        empty_returns = {horizon: None for horizon in horizons}
        empty_days = {horizon: None for horizon in horizons}
        empty_reasons = {horizon: None for horizon in horizons}
        return empty_returns, empty_days, empty_reasons

    entry_open = bars[0][1]
    if entry_open <= 0:
        empty_returns = {horizon: None for horizon in horizons}
        empty_days = {horizon: None for horizon in horizons}
        empty_reasons = {horizon: None for horizon in horizons}
        return empty_returns, empty_days, empty_reasons

    returns: dict[int, float | None] = {}
    exit_days: dict[int, int | None] = {}
    exit_reasons: dict[int, str | None] = {}
    for horizon in horizons:
        if len(bars) < horizon:
            returns[horizon] = None
            exit_days[horizon] = None
            exit_reasons[horizon] = None
            continue
        peak = entry_open
        guarded_return = None
        exit_day = None
        exit_reason = None
        for index, (_trade_date, _open, close) in enumerate(bars[:horizon], start=1):
            peak = max(peak, close)
            current_return = close / entry_open - 1.0
            drawdown = close / peak - 1.0 if peak > 0 else 0.0
            if current_return <= -abs(stop_loss_pct):
                guarded_return = current_return
                exit_day = index
                exit_reason = "stop_loss"
                break
            if drawdown <= -abs(trailing_drawdown_pct):
                guarded_return = current_return
                exit_day = index
                exit_reason = "trailing_drawdown"
                break
        if guarded_return is None:
            guarded_return = bars[horizon - 1][2] / entry_open - 1.0
            exit_day = horizon
            exit_reason = "horizon"
        returns[horizon] = round(guarded_return, 6)
        exit_days[horizon] = exit_day
        exit_reasons[horizon] = exit_reason
    return returns, exit_days, exit_reasons


def _feature_float(features: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = features.get(key)
    return float(value) if value is not None else default


def _has_controlled_stock_drawdown(features: dict[str, Any]) -> bool:
    max_drawdown_20d = _feature_float(features, "max_drawdown_20d", -0.10)
    if max_drawdown_20d > -0.22:
        return True
    return (
        _feature_float(features, "return_5d") >= 0.03
        and _feature_float(features, "distance_to_20d_low", 1.0) <= 0.04
    )


def _volume_confirmation_delta(features: dict[str, Any]) -> float:
    volume_score = _feature_float(features, "volume_confirmation_score", 50.0)
    price_volume_score = _feature_float(features, "price_volume_trend_score", 50.0)
    confirmation = volume_score * 0.55 + price_volume_score * 0.45
    if confirmation >= 68.0:
        return min(1.2, (confirmation - 68.0) / 20.0 * 1.2)
    if confirmation <= 45.0:
        return -min(0.8, (45.0 - confirmation) / 18.0 * 0.8)
    return 0.0


def _is_low_dimensional_candidate(features: dict[str, Any]) -> bool:
    sector_avg_return_20d = _feature_float(features, "sector_avg_return_20d")
    sector_positive_20d_rate = _feature_float(features, "sector_positive_20d_rate")
    if (
        sector_avg_return_20d >= OVEREXTENDED_RETURN_20D_MIN
        or sector_positive_20d_rate >= OVEREXTENDED_POSITIVE_20D_MIN
    ):
        return False
    return (
        _feature_float(features, "trend_score", 50.0) >= 70.0
        and _feature_float(features, "relative_strength_score", 50.0) >= 62.0
        and _feature_float(features, "sector_strength_score", 50.0) >= 60.0
        and _feature_float(features, "sector_breadth_score", 50.0) >= 40.0
        and _feature_float(features, "sector_trend_continuity_score", 50.0) >= 65.0
        and _feature_float(features, "sector_trend_resilience_score", 50.0) >= 58.0
        and MAINLINE_RETURN_20D_MIN <= sector_avg_return_20d <= MAINLINE_RETURN_20D_MAX
        and sector_positive_20d_rate >= 55.0
        and _feature_float(features, "return_20d") <= 0.28
        and abs(_feature_float(features, "distance_to_ma20")) <= 0.12
        and _has_controlled_stock_drawdown(features)
    )


def _low_dimensional_score(features: dict[str, Any]) -> float:
    drawdown_control_score = max(
        0.0,
        min(
            100.0,
            (_feature_float(features, "max_drawdown_20d", -0.10) + 0.24) / 0.18 * 100.0,
        ),
    )
    return (
        _feature_float(features, "sector_strength_score", 50.0) * 0.24
        + _feature_float(features, "sector_trend_continuity_score", 50.0) * 0.22
        + _feature_float(features, "trend_score", 50.0) * 0.20
        + _feature_float(features, "relative_strength_score", 50.0) * 0.14
        + _feature_float(features, "sector_breadth_score", 50.0) * 0.07
        + _feature_float(features, "sector_trend_resilience_score", 50.0) * 0.05
        + drawdown_control_score * 0.03
        + (100.0 - _feature_float(features, "overheat_score", 50.0)) * 0.025
        + (100.0 - _feature_float(features, "volume_trap_risk_score", 50.0)) * 0.025
        + _volume_confirmation_delta(features)
    )


def _low_dimensional_candidates(
    db,
    *,
    signal_date: date,
    limit: int,
) -> list[tuple[StockFeatureDaily, Security, dict[str, Any], float]]:
    sector_features = {
        str(row.sector_code): dict(row.features or {})
        for row in db.execute(
            select(SectorFeatureDaily).where(SectorFeatureDaily.trade_date == signal_date)
        ).scalars()
    }
    rows = list(
        db.execute(
            select(StockFeatureDaily, Security)
            .join(Security, Security.symbol == StockFeatureDaily.symbol)
            .where(StockFeatureDaily.trade_date == signal_date)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).all()
    )
    candidates = []
    for feature, security in rows:
        features = {
            **sector_features.get(str(security.industry or ""), {}),
            **(feature.features or {}),
        }
        if _is_low_dimensional_candidate(features):
            candidates.append((feature, security, features, _low_dimensional_score(features)))
    return sorted(candidates, key=lambda item: item[3], reverse=True)[:limit]


def _cache_float(features: dict[str, Any], key: str) -> float | None:
    value = features.get(key)
    return float(value) if value is not None else None


def _features_from_low_dimensional_snapshot(
    snapshot: LowDimensionalFeatureSnapshot,
) -> dict[str, Any]:
    return {
        key: value
        for key in LOW_DIMENSIONAL_CACHE_FEATURE_KEYS
        if (value := getattr(snapshot, key)) is not None
    }


def sync_low_dimensional_feature_snapshots(
    db,
    *,
    start: date,
    end: date,
) -> int:
    sector_features = {
        (row.trade_date, str(row.sector_code)): dict(row.features or {})
        for row in db.execute(
            select(SectorFeatureDaily).where(
                SectorFeatureDaily.trade_date >= start,
                SectorFeatureDaily.trade_date <= end,
            )
        ).scalars()
    }
    rows = db.execute(
        select(StockFeatureDaily, Security)
        .join(Security, Security.symbol == StockFeatureDaily.symbol)
        .where(StockFeatureDaily.trade_date >= start)
        .where(StockFeatureDaily.trade_date <= end)
        .where(Security.is_active.is_(True))
        .where(Security.is_st.is_(False))
        .order_by(StockFeatureDaily.trade_date, StockFeatureDaily.symbol)
    ).all()

    db.execute(
        delete(LowDimensionalFeatureSnapshot).where(
            LowDimensionalFeatureSnapshot.trade_date >= start,
            LowDimensionalFeatureSnapshot.trade_date <= end,
        )
    )
    snapshots: list[LowDimensionalFeatureSnapshot] = []
    for stock_feature, security in rows:
        features = {
            **sector_features.get(
                (stock_feature.trade_date, str(security.industry or "")),
                {},
            ),
            **(stock_feature.features or {}),
        }
        values = {
            key: _cache_float(features, key) for key in LOW_DIMENSIONAL_CACHE_FEATURE_KEYS
        }
        snapshots.append(
            LowDimensionalFeatureSnapshot(
                symbol=stock_feature.symbol,
                trade_date=stock_feature.trade_date,
                sector=security.industry,
                **values,
            )
        )
    db.add_all(snapshots)
    return len(snapshots)


def _feature_json_number(key: str, *, dialect_name: str):
    del dialect_name
    value = func.json_extract(StockFeatureDaily.features, f"$.{key}")
    return cast(value, Numeric(18, 6))


def _feature_text_number(features_text: str, key: str) -> float | None:
    pattern = FEATURE_TEXT_NUMBER_PATTERNS.get(key)
    if pattern is None:
        return None
    match = pattern.search(features_text)
    return float(match.group(1)) if match else None


def _feature_text_passes_low_dimensional_prefilter(features_text: str) -> bool:
    trend_score = _feature_text_number(features_text, "trend_score")
    relative_strength_score = _feature_text_number(
        features_text,
        "relative_strength_score",
    )
    return_20d = _feature_text_number(features_text, "return_20d")
    distance_to_ma20 = _feature_text_number(features_text, "distance_to_ma20")
    if (
        trend_score is None
        or relative_strength_score is None
        or return_20d is None
        or distance_to_ma20 is None
    ):
        return False
    return (
        trend_score >= 70.0
        and relative_strength_score >= 62.0
        and return_20d <= 0.28
        and abs(distance_to_ma20) <= 0.12
    )


def _low_dimensional_feature_prefilter_stmt(
    *,
    start: date,
    end: date,
    dialect_name: str,
):
    if dialect_name != "sqlite":
        features_text = cast(StockFeatureDaily.features, Text)
        return (
            select(
                StockFeatureDaily.symbol,
                StockFeatureDaily.trade_date,
                features_text.label("features_text"),
            )
            .where(StockFeatureDaily.trade_date >= start)
            .where(StockFeatureDaily.trade_date <= end)
            .order_by(StockFeatureDaily.trade_date)
        )

    trend_score = _feature_json_number("trend_score", dialect_name=dialect_name)
    relative_strength_score = _feature_json_number(
        "relative_strength_score",
        dialect_name=dialect_name,
    )
    return_20d = _feature_json_number("return_20d", dialect_name=dialect_name)
    distance_to_ma20 = _feature_json_number(
        "distance_to_ma20",
        dialect_name=dialect_name,
    )
    return (
        select(
            StockFeatureDaily.symbol,
            StockFeatureDaily.trade_date,
            StockFeatureDaily.features,
        )
        .where(StockFeatureDaily.trade_date >= start)
        .where(StockFeatureDaily.trade_date <= end)
        .where(trend_score >= 70.0)
        .where(relative_strength_score >= 62.0)
        .where(return_20d <= 0.28)
        .where(func.abs(distance_to_ma20) <= 0.12)
        .order_by(StockFeatureDaily.trade_date)
    )


def _low_dimensional_candidates_by_date(
    db,
    *,
    trade_dates: list[date],
    limit: int,
) -> dict[date, list[tuple[FeatureSnapshot, Security, dict[str, Any], float]]]:
    if not trade_dates:
        return {}

    start = min(trade_dates)
    end = max(trade_dates)
    sector_features = {
        (row.trade_date, str(row.sector_code)): dict(row.features or {})
        for row in db.execute(
            select(SectorFeatureDaily).where(
                SectorFeatureDaily.trade_date >= start,
                SectorFeatureDaily.trade_date <= end,
            )
        ).scalars()
    }
    security_by_symbol = {
        security.symbol: security
        for security in db.execute(
            select(Security)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).scalars()
    }
    buckets: dict[date, list[tuple[FeatureSnapshot, Security, dict[str, Any], float]]] = {}
    stmt = _low_dimensional_feature_prefilter_stmt(
        start=start,
        end=end,
        dialect_name=db.bind.dialect.name,
    )
    for row in db.execute(stmt).yield_per(2000):
        security = security_by_symbol.get(row.symbol)
        if security is None:
            continue
        raw_features = getattr(row, "features", None)
        if raw_features is None:
            raw_features = getattr(row, "features_text", None)
        if isinstance(raw_features, str):
            if not _feature_text_passes_low_dimensional_prefilter(raw_features):
                continue
            try:
                parsed_features = json.loads(raw_features)
            except json.JSONDecodeError:
                continue
        else:
            parsed_features = dict(raw_features or {})
        feature = FeatureSnapshot(
            symbol=str(row.symbol),
            trade_date=row.trade_date,
            features=parsed_features,
        )
        features = {
            **sector_features.get((feature.trade_date, str(security.industry or "")), {}),
            **feature.features,
        }
        if not _is_low_dimensional_candidate(features):
            continue
        bucket = buckets.setdefault(feature.trade_date, [])
        bucket.append((feature, security, features, _low_dimensional_score(features)))
        if len(bucket) > limit * 3:
            bucket.sort(key=lambda item: item[3], reverse=True)
            del bucket[limit:]

    for bucket in buckets.values():
        bucket.sort(key=lambda item: item[3], reverse=True)
        del bucket[limit:]
    return buckets


def _cached_low_dimensional_trade_dates(
    db,
    *,
    trade_dates: list[date],
) -> set[date]:
    if not trade_dates:
        return set()
    return set(
        db.execute(
            select(LowDimensionalFeatureSnapshot.trade_date)
            .where(LowDimensionalFeatureSnapshot.trade_date.in_(trade_dates))
            .distinct()
        ).scalars()
    )


def _cached_low_dimensional_candidates_by_date(
    db,
    *,
    trade_dates: list[date],
    limit: int,
) -> dict[date, list[tuple[FeatureSnapshot, Security, dict[str, Any], float]]]:
    if not trade_dates:
        return {}

    buckets: dict[date, list[tuple[FeatureSnapshot, Security, dict[str, Any], float]]] = {}
    rows = db.execute(
        select(LowDimensionalFeatureSnapshot, Security)
        .join(Security, Security.symbol == LowDimensionalFeatureSnapshot.symbol)
        .where(LowDimensionalFeatureSnapshot.trade_date.in_(trade_dates))
        .where(LowDimensionalFeatureSnapshot.trend_score >= 70.0)
        .where(LowDimensionalFeatureSnapshot.relative_strength_score >= 62.0)
        .where(LowDimensionalFeatureSnapshot.sector_strength_score >= 60.0)
        .where(LowDimensionalFeatureSnapshot.sector_trend_continuity_score >= 65.0)
        .where(LowDimensionalFeatureSnapshot.sector_trend_resilience_score >= 58.0)
        .where(LowDimensionalFeatureSnapshot.sector_avg_return_20d >= MAINLINE_RETURN_20D_MIN)
        .where(LowDimensionalFeatureSnapshot.sector_avg_return_20d <= MAINLINE_RETURN_20D_MAX)
        .where(LowDimensionalFeatureSnapshot.sector_positive_20d_rate >= 55.0)
        .where(
            or_(
                LowDimensionalFeatureSnapshot.sector_breadth_score.is_(None),
                LowDimensionalFeatureSnapshot.sector_breadth_score >= 40.0,
            )
        )
        .where(
            or_(
                LowDimensionalFeatureSnapshot.return_20d.is_(None),
                LowDimensionalFeatureSnapshot.return_20d <= 0.28,
            )
        )
        .where(
            or_(
                LowDimensionalFeatureSnapshot.distance_to_ma20.is_(None),
                and_(
                    LowDimensionalFeatureSnapshot.distance_to_ma20 >= -0.12,
                    LowDimensionalFeatureSnapshot.distance_to_ma20 <= 0.12,
                ),
            )
        )
        .where(
            or_(
                LowDimensionalFeatureSnapshot.max_drawdown_20d.is_(None),
                LowDimensionalFeatureSnapshot.max_drawdown_20d > -0.22,
                and_(
                    LowDimensionalFeatureSnapshot.return_5d >= 0.03,
                    LowDimensionalFeatureSnapshot.distance_to_20d_low <= 0.04,
                ),
            )
        )
        .where(Security.is_active.is_(True))
        .where(Security.is_st.is_(False))
        .order_by(LowDimensionalFeatureSnapshot.trade_date)
    ).yield_per(2000)
    for snapshot, security in rows:
        features = _features_from_low_dimensional_snapshot(snapshot)
        if not _is_low_dimensional_candidate(features):
            continue
        feature = FeatureSnapshot(
            symbol=snapshot.symbol,
            trade_date=snapshot.trade_date,
            features=features,
        )
        bucket = buckets.setdefault(snapshot.trade_date, [])
        bucket.append((feature, security, features, _low_dimensional_score(features)))
        if len(bucket) > limit * 3:
            bucket.sort(key=lambda item: item[3], reverse=True)
            del bucket[limit:]

    for bucket in buckets.values():
        bucket.sort(key=lambda item: item[3], reverse=True)
        del bucket[limit:]
    return buckets


def _low_dimensional_candidates_by_date_with_cache(
    db,
    *,
    trade_dates: list[date],
    limit: int,
) -> dict[date, list[tuple[FeatureSnapshot, Security, dict[str, Any], float]]]:
    cached_dates = _cached_low_dimensional_trade_dates(db, trade_dates=trade_dates)
    cached_candidates = _cached_low_dimensional_candidates_by_date(
        db,
        trade_dates=sorted(cached_dates),
        limit=limit,
    )
    missing_dates = [trade_date for trade_date in trade_dates if trade_date not in cached_dates]
    if not missing_dates:
        return cached_candidates

    raw_candidates = _low_dimensional_candidates_by_date(
        db,
        trade_dates=missing_dates,
        limit=limit,
    )
    return {**cached_candidates, **raw_candidates}


def _trend_factor_candidates(
    db,
    *,
    signal_date: date,
    factor_key: str,
    limit: int,
) -> list[tuple[StockFeatureDaily, Security, dict[str, Any], float]]:
    sector_features = {
        str(row.sector_code): dict(row.features or {})
        for row in db.execute(
            select(SectorFeatureDaily).where(SectorFeatureDaily.trade_date == signal_date)
        ).scalars()
    }
    rows = list(
        db.execute(
            select(StockFeatureDaily, Security)
            .join(Security, Security.symbol == StockFeatureDaily.symbol)
            .where(StockFeatureDaily.trade_date == signal_date)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).all()
    )
    candidates = []
    for feature, security in rows:
        features = {
            **sector_features.get(str(security.industry or ""), {}),
            **(feature.features or {}),
        }
        if not _is_low_dimensional_candidate(features):
            continue
        factor_value = _feature_float(features, factor_key, -1.0)
        if factor_value < 0:
            continue
        candidates.append((feature, security, features, factor_value))
    return sorted(candidates, key=lambda item: item[3], reverse=True)[:limit]


def run_trend_factor_walk_forward_replay(
    *,
    start_date: str,
    end_date: str,
    factor_keys: tuple[str, ...] = (
        "trend_score",
        "trend_quality_score",
        "route_trend_score",
        "price_volume_trend_score",
        "ma_alignment_score",
    ),
    limit: int = 5,
    horizons: tuple[int, ...] = (5, 10, 20),
) -> dict[str, Any]:
    start = _parse(start_date)
    end = _parse(end_date)
    with SessionLocal() as db:
        trade_dates = _trade_dates(db, start, end)
        factor_candidates: dict[str, list[WalkForwardCandidate]] = {
            factor_key: [] for factor_key in factor_keys
        }
        for index, signal_date in enumerate(trade_dates):
            next_date = trade_dates[index + 1] if index + 1 < len(trade_dates) else None
            if next_date is None:
                continue
            for factor_key in factor_keys:
                for feature, security, _features, score in _trend_factor_candidates(
                    db,
                    signal_date=signal_date,
                    factor_key=factor_key,
                    limit=limit,
                ):
                    factor_candidates[factor_key].append(
                        WalkForwardCandidate(
                            symbol=feature.symbol,
                            name=security.name,
                            sector=security.industry,
                            sector_style=_sector_style(security),
                            selection_mode=f"trend_factor:{factor_key}",
                            score=round(score, 4),
                            entry_date=next_date.isoformat(),
                            forward_returns=_forward_returns(
                                db,
                                symbol=feature.symbol,
                                entry_date=next_date,
                                horizons=horizons,
                            ),
                        )
                    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "factors": {
            factor_key: {
                "candidate_count": len(candidates),
                "top_symbols": [candidate.symbol for candidate in candidates[:10]],
                "horizons": {
                    horizon: _return_summary(
                        [
                            value
                            for candidate in candidates
                            if (value := candidate.forward_returns.get(horizon)) is not None
                        ]
                    )
                    for horizon in horizons
                },
            }
            for factor_key, candidates in factor_candidates.items()
        },
    }


def run_low_dimensional_walk_forward_replay(
    *,
    start_date: str,
    end_date: str,
    limit: int = 15,
    horizons: tuple[int, ...] = (1, 5, 10, 20),
    min_coverage_ratio: float = 0.70,
    stop_loss_pct: float = 0.06,
    trailing_drawdown_pct: float = 0.08,
) -> WalkForwardReplayResult:
    start = _parse(start_date)
    end = _parse(end_date)
    days: list[WalkForwardDay] = []

    with SessionLocal() as db:
        trade_dates = _trade_dates(db, start, end)
        trade_date_index = {trade_date: index for index, trade_date in enumerate(trade_dates)}
        coverage_by_date = _feature_coverage_by_date(db, trade_dates)
        candidates_by_date = _low_dimensional_candidates_by_date_with_cache(
            db,
            trade_dates=trade_dates,
            limit=limit,
        )
        selected_symbols: set[str] = set()
        entry_dates: list[date] = []
        max_horizon = max(horizons) if horizons else 0
        max_target_index = 0
        for index, signal_date in enumerate(trade_dates):
            next_date = trade_dates[index + 1] if index + 1 < len(trade_dates) else None
            if next_date is None:
                continue
            bucket = candidates_by_date.get(signal_date, [])
            if not bucket:
                continue
            selected_symbols.update(
                str(feature.symbol)
                for feature, _security, _features, _score in bucket
            )
            entry_dates.append(next_date)
            entry_index = trade_date_index[next_date]
            max_target_index = max(
                max_target_index,
                min(len(trade_dates) - 1, entry_index + max(0, max_horizon - 1)),
            )
        bar_cache = _daily_bar_cache_by_symbol_date(
            db,
            symbols=selected_symbols,
            start_date=min(entry_dates) if entry_dates else None,
            end_date=trade_dates[max_target_index] if entry_dates else None,
        )
        for index, signal_date in enumerate(trade_dates):
            next_date = trade_dates[index + 1] if index + 1 < len(trade_dates) else None
            feature_rows, active_symbols, coverage = coverage_by_date.get(
                signal_date,
                (0, 0, 0.0),
            )
            warnings = []
            if coverage < min_coverage_ratio:
                warnings.append(
                    f"特征覆盖不足：{feature_rows}/{active_symbols}，该日只作局部参考。"
                )
            candidates: list[WalkForwardCandidate] = []
            if next_date is not None and feature_rows > 0:
                for feature, security, features, score in candidates_by_date.get(
                    signal_date,
                    [],
                ):
                    relative_strength = _feature_float(
                        features,
                        "relative_strength_score",
                        50.0,
                    )
                    sector_return_20d = _feature_float(features, "sector_avg_return_20d")
                    effective_stop_loss_pct, effective_trailing_drawdown_pct = (
                        _guard_parameters_for_features(
                            features,
                            stop_loss_pct=stop_loss_pct,
                            trailing_drawdown_pct=trailing_drawdown_pct,
                        )
                    )
                    guarded_returns, guard_exit_days, guard_exit_reasons = (
                        _guarded_forward_returns_from_cache(
                            bar_cache,
                            trade_dates,
                            trade_date_index,
                            symbol=feature.symbol,
                            entry_date=next_date,
                            horizons=horizons,
                            stop_loss_pct=effective_stop_loss_pct,
                            trailing_drawdown_pct=effective_trailing_drawdown_pct,
                        )
                    )
                    forward_returns = _forward_returns_from_cache(
                        bar_cache,
                        trade_dates,
                        trade_date_index,
                        symbol=feature.symbol,
                        entry_date=next_date,
                        horizons=horizons,
                    )
                    candidates.append(
                        WalkForwardCandidate(
                            symbol=feature.symbol,
                            name=security.name,
                            sector=security.industry,
                            sector_style=_sector_style(security),
                            selection_mode="low_dimensional_mainline",
                            score=round(score, 4),
                            entry_date=next_date.isoformat(),
                            forward_returns=forward_returns,
                            guarded_forward_returns=guarded_returns,
                            guard_exit_days=guard_exit_days,
                            guard_exit_reasons=guard_exit_reasons,
                            sector_strength_score=_feature_float(
                                features,
                                "sector_strength_score",
                                50.0,
                            ),
                            sector_return_20d=sector_return_20d,
                            reasons=[
                                "低维主线：板块确认但未过热",
                                f"趋势{_feature_float(features, 'trend_score', 50.0):.1f}",
                                f"相对强度{relative_strength:.1f}",
                                f"板块20日{sector_return_20d * 100:.1f}%",
                            ],
                            risk_flags=[],
                        )
                    )
            days.append(
                WalkForwardDay(
                    signal_date=signal_date.isoformat(),
                    next_trade_date=next_date.isoformat() if next_date else None,
                    universe_size=feature_rows,
                    feature_rows=feature_rows,
                    active_symbols=active_symbols,
                    feature_coverage_ratio=coverage,
                    candidates=candidates,
                    warnings=warnings,
                )
            )

    return WalkForwardReplayResult(
        start_date=start_date,
        end_date=end_date,
        processed_days=len(days),
        days=days,
    )


def run_candidate_walk_forward_replay(
    *,
    start_date: str,
    end_date: str,
    limit: int = 15,
    horizons: tuple[int, ...] = (1, 5, 10, 20),
    min_coverage_ratio: float = 0.70,
    include_fundamentals: bool = True,
    candidate_scope: str = "all",
    discovery_cache_dir: str | Path | None = None,
    stop_loss_pct: float = 0.06,
    trailing_drawdown_pct: float = 0.08,
    forward_return_cache: dict[ForwardReturnCacheKey, ForwardReturnBundle] | None = None,
) -> WalkForwardReplayResult:
    start = _parse(start_date)
    end = _parse(end_date)
    days: list[WalkForwardDay] = []

    with SessionLocal() as db:
        trade_dates = _trade_dates(db, start, end)
        coverage_by_date = _feature_coverage_by_date(db, trade_dates)
        for index, signal_date in enumerate(trade_dates):
            next_date = trade_dates[index + 1] if index + 1 < len(trade_dates) else None
            feature_rows, active_symbols, coverage = coverage_by_date.get(
                signal_date,
                (0, 0, 0.0),
            )
            warnings = []
            if coverage < min_coverage_ratio:
                warnings.append(
                    f"特征覆盖不足：{feature_rows}/{active_symbols}，该日只作局部参考。"
                )

            candidates: list[WalkForwardCandidate] = []
            universe_size = 0
            if next_date is not None and feature_rows > 0:
                discovery = _load_candidate_discovery_db_cache(
                    db,
                    signal_date=signal_date,
                    next_date=next_date,
                    limit=limit,
                    include_fundamentals=include_fundamentals,
                )
                if discovery is None:
                    discovery = _load_candidate_discovery_cache(
                        discovery_cache_dir,
                        signal_date=signal_date,
                        next_date=next_date,
                        limit=limit,
                        include_fundamentals=include_fundamentals,
                    )
                    if discovery is not None:
                        _store_candidate_discovery_db_cache(
                            db,
                            signal_date=signal_date,
                            next_date=next_date,
                            limit=limit,
                            include_fundamentals=include_fundamentals,
                            discovery=discovery,
                        )
                if discovery is None:
                    discovery = discover_next_session_candidates(
                        db,
                        feature_date=signal_date.isoformat(),
                        next_trade_date=next_date.isoformat(),
                        pool_name="walk_forward_replay",
                        limit=limit,
                        min_universe_size=0,
                        include_fundamentals=include_fundamentals,
                    )
                    db.rollback()
                    _ensure_candidate_discovery_has_no_future_features(
                        discovery,
                        signal_date,
                    )
                    _store_candidate_discovery_db_cache(
                        db,
                        signal_date=signal_date,
                        next_date=next_date,
                        limit=limit,
                        include_fundamentals=include_fundamentals,
                        discovery=discovery,
                    )
                    _store_candidate_discovery_cache(
                        discovery_cache_dir,
                        signal_date=signal_date,
                        next_date=next_date,
                        limit=limit,
                        include_fundamentals=include_fundamentals,
                        discovery=discovery,
                    )
                universe_size = int(discovery.get("universe_size") or 0)
                candidate_items = list(discovery.get("candidates", []))
                if candidate_scope == "action_long":
                    candidate_items = select_long_action_candidates(
                        discovery,
                        candidate_items,
                        max_items=min(limit, 3),
                    )
                elif candidate_scope == "action":
                    candidate_items = select_action_candidates(
                        discovery,
                        candidate_items,
                        max_items=min(limit, 3),
                    )
                elif candidate_scope == "potential_watch":
                    candidate_items = [
                        item
                        for item in candidate_items
                        if str(item.get("selection_mode") or "").strip() == "potential_watch"
                    ]
                elif candidate_scope == "startup_preheat":
                    candidate_items = [
                        item for item in candidate_items if _is_startup_preheat_candidate_item(item)
                    ]
                elif candidate_scope == "startup_confirmed":
                    candidate_items = [
                        item
                        for item in candidate_items
                        if _is_startup_confirmed_candidate_item(item)
                    ]
                elif candidate_scope == "sector_watch":
                    tier_discovery = {
                        **discovery,
                        "market_stress": _historical_market_stress_from_discovery(discovery),
                    }
                    candidate_items = build_candidate_tiers(
                        tier_discovery,
                        candidate_items,
                        max_core_items=min(limit, 3),
                    ).get("sector_watch", [])
                elif candidate_scope != "all":
                    raise ValueError(f"Unsupported candidate_scope: {candidate_scope}")
                for item in candidate_items:
                    symbol = str(item.get("symbol") or "")
                    cache_key = (
                        symbol,
                        next_date,
                        tuple(horizons),
                        stop_loss_pct,
                        trailing_drawdown_pct,
                    )
                    cached_returns = (
                        forward_return_cache.get(cache_key)
                        if forward_return_cache is not None
                        else None
                    )
                    if cached_returns is None:
                        forward_returns = _forward_returns(
                            db,
                            symbol=symbol,
                            entry_date=next_date,
                            horizons=horizons,
                        )
                        guarded_returns, guard_exit_days, guard_exit_reasons = (
                            _guarded_forward_returns(
                                db,
                                symbol=symbol,
                                entry_date=next_date,
                                horizons=horizons,
                                stop_loss_pct=stop_loss_pct,
                                trailing_drawdown_pct=trailing_drawdown_pct,
                            )
                        )
                        if forward_return_cache is not None:
                            forward_return_cache[cache_key] = (
                                forward_returns,
                                guarded_returns,
                                guard_exit_days,
                                guard_exit_reasons,
                            )
                    else:
                        (
                            forward_returns,
                            guarded_returns,
                            guard_exit_days,
                            guard_exit_reasons,
                        ) = cached_returns
                    candidates.append(
                        WalkForwardCandidate(
                            symbol=symbol,
                            name=item.get("name"),
                            sector=item.get("sector"),
                            sector_style=_sector_style(
                                item.get("sector_style"),
                                str(item.get("sector") or ""),
                            ),
                            selection_mode=str(item.get("selection_mode") or ""),
                            score=float(item.get("score") or 0.0),
                            entry_date=next_date.isoformat(),
                            forward_returns=forward_returns,
                            guarded_forward_returns=guarded_returns,
                            guard_exit_days=guard_exit_days,
                            guard_exit_reasons=guard_exit_reasons,
                            reasons=[str(reason) for reason in item.get("reasons") or []],
                            risk_flags=[str(flag) for flag in item.get("risk_flags") or []],
                            sector_strength_score=_optional_float(
                                item,
                                "sector_strength_score",
                            ),
                            sector_return_20d=_optional_float(
                                item,
                                "sector_return_20d",
                                "sector_avg_return_20d",
                            ),
                            startup_signal_score=_optional_float(
                                item,
                                "startup_signal_score",
                            ),
                            startup_signal_label=(
                                str(item.get("startup_signal_label"))
                                if item.get("startup_signal_label")
                                else None
                            ),
                            startup_signal_reasons=[
                                str(reason)
                                for reason in item.get("startup_signal_reasons") or []
                            ],
                        )
                    )
                db.rollback()

            days.append(
                WalkForwardDay(
                    signal_date=signal_date.isoformat(),
                    next_trade_date=next_date.isoformat() if next_date else None,
                    universe_size=universe_size,
                    feature_rows=feature_rows,
                    active_symbols=active_symbols,
                    feature_coverage_ratio=coverage,
                    candidates=candidates,
                    warnings=warnings,
                )
            )

    return WalkForwardReplayResult(
        start_date=start_date,
        end_date=end_date,
        processed_days=len(days),
        days=days,
    )


def compare_candidate_walk_forward_scopes(
    *,
    start_date: str,
    end_date: str,
    scopes: tuple[str, ...] = ("all", "action", "action_long"),
    limit: int = 15,
    horizons: tuple[int, ...] = (5, 10, 20),
    min_coverage_ratio: float = 0.70,
    include_fundamentals: bool = True,
    discovery_cache_dir: str | Path | None = DEFAULT_CANDIDATE_DISCOVERY_CACHE_DIR,
    stop_loss_pct: float = 0.06,
    trailing_drawdown_pct: float = 0.08,
) -> dict[str, Any]:
    cache_dir = discovery_cache_dir
    forward_return_cache: dict[ForwardReturnCacheKey, ForwardReturnBundle] = {}
    scope_summaries: dict[str, Any] = {}
    for scope in scopes:
        result = run_candidate_walk_forward_replay(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            horizons=horizons,
            min_coverage_ratio=min_coverage_ratio,
            include_fundamentals=include_fundamentals,
            candidate_scope=scope,
            discovery_cache_dir=cache_dir,
            stop_loss_pct=stop_loss_pct,
            trailing_drawdown_pct=trailing_drawdown_pct,
            forward_return_cache=forward_return_cache,
        )
        scope_summaries[scope] = summarize_walk_forward_replay(
            result,
            horizons=horizons,
        )
    return {
        "start_date": start_date,
        "end_date": end_date,
        "scopes": scope_summaries,
        "discovery_cache_dir": str(cache_dir) if cache_dir is not None else None,
    }
