from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.engine.features.market_regime import MarketRegimeSnapshot, classify_market_regime
from services.engine.features.market_turn import classify_verified_market_turn_state
from services.engine.plans.repository import latest_feature_date, load_feature_contexts
from services.engine.research_pool.repository import add_symbols_to_pool, list_pool_items
from services.engine.rules.evaluator import evaluate_group
from services.engine.rules.seed_rules import MVP_RULES
from services.engine.signals.route import build_signal_route
from services.shared.models import (
    DailyBar,
    ParameterRecommendation,
    ResearchPoolItem,
    SectorFeatureDaily,
    Security,
    StockFeatureDaily,
    TushareDatasetSyncReceipt,
    TushareLimitListD,
)
from services.shared.symbols import is_growth_board_symbol

LEARNING_SOURCE_REPORT_TYPES = (
    "backtest_learning_review",
    "paper_learning_review",
    "paper_trading_review",
)
LEARNING_STATUSES = ("pending", "approved", "applied")
LEARNING_SCOPE_WEIGHTS = {"symbol": 1.0, "sector": 0.7, "rule": 0.45}
LEARNING_PRIORITY_WEIGHTS = {"high": 1.0, "medium": 0.8, "low": 0.6}
LEARNING_LOOKBACK_DAYS = 60
LEARNING_RECENCY_HALF_LIFE_DAYS = 21.0
LEARNING_RECENCY_MIN_WEIGHT = 0.25
LEARNING_NEGATIVE_ACTIONS = {
    "reduce_priority_or_require_confirmation",
    "tighten_entry_or_reduce_priority",
    "tighten_entry_quality",
    "test_avoid_high_position_volume_spike",
    "reduce_or_pause",
    "test_tighten_or_filter",
    "observe_or_require_fresh_confirmation",
}
LEARNING_POSITIVE_ACTIONS = {
    "keep_or_test_small_priority_increase",
    "test_small_increase_after_stable_reviews",
    "test_small_priority_increase",
    "test_priority_boost",
}
LEARNING_FORMAL_BLOCK_ACTIONS = {"observe_or_require_fresh_confirmation"}
LEARNING_FORMAL_BLOCK_TARGETS = {"backtest_validation_quality"}
LONG_HORIZON_LEARNING_ACTIONS = {"keep_or_test_small_priority_increase"}
CANDIDATE_SCORE_WEIGHTS = {
    "route": 0.50,
    "trend": 0.16,
    "relative": 0.10,
    "sector": 0.08,
    "volume": 0.06,
    "risk": 0.04,
    "overheat": 0.03,
    "volume_trap": 0.03,
}
CANDIDATE_FORMAL_SCORE_MIN = 55.0
CANDIDATE_FORMAL_TREND_MIN = 62.0
CANDIDATE_FORMAL_RELATIVE_MIN = 58.0
CANDIDATE_FORMAL_SECTOR_MIN = 58.0
CANDIDATE_FORMAL_VOLUME_MIN = 35.0
CANDIDATE_FORMAL_OVERHEAT_MAX = 82.0
CANDIDATE_FORMAL_VOLUME_TRAP_MAX = 72.0
CANDIDATE_FORMAL_RETURN_20D_MAX = 0.38
CANDIDATE_OBSERVATION_TREND_MIN = 56.0
CANDIDATE_OBSERVATION_RELATIVE_MIN = 50.0
CANDIDATE_OBSERVATION_SECTOR_MIN = 48.0
CANDIDATE_OBSERVATION_VOLUME_MIN = 30.0
CANDIDATE_OBSERVATION_RISK_MAX = 78.0
CANDIDATE_OBSERVATION_OVERHEAT_MAX = 82.0
CANDIDATE_OBSERVATION_VOLUME_TRAP_MAX = 75.0
CANDIDATE_OBSERVATION_RETURN_20D_MIN = -0.08
CANDIDATE_OBSERVATION_RETURN_20D_MAX = 0.38
CANDIDATE_OBSERVATION_DAY_CHANGE_MIN = -0.06
CANDIDATE_OBSERVATION_SUPPORT_COUNT_MIN = 3
CANDIDATE_EXPLORATION_TREND_MIN = 70.0
CANDIDATE_EXPLORATION_RELATIVE_MIN = 60.0
CANDIDATE_EXPLORATION_SECTOR_MIN = 64.0
CANDIDATE_EXPLORATION_RISK_MAX = 74.0
CANDIDATE_EXPLORATION_OVERHEAT_MAX = 82.0
CANDIDATE_EXPLORATION_VOLUME_TRAP_MAX = 76.0
CANDIDATE_EXPLORATION_RETURN_20D_MIN = -0.03
CANDIDATE_EXPLORATION_RETURN_20D_MAX = 0.36
CANDIDATE_EXPLORATION_SCORE_MIN = 55.0
CANDIDATE_POTENTIAL_TREND_MIN = 88.0
CANDIDATE_POTENTIAL_RELATIVE_MIN = 45.0
CANDIDATE_POTENTIAL_VOLUME_MIN = 50.0
CANDIDATE_POTENTIAL_PRICE_VOLUME_MIN = 52.0
CANDIDATE_POTENTIAL_ROUTE_MIN = 58.0
CANDIDATE_POTENTIAL_SCORE_MIN = 54.0
CANDIDATE_POTENTIAL_FRESH_SCORE_MIN = 51.0
CANDIDATE_POTENTIAL_FRESH_SCORE_DELTA_FLOOR = -3.0
CANDIDATE_POTENTIAL_RISK_MAX = 65.0
CANDIDATE_POTENTIAL_OVERHEAT_MAX = 65.0
CANDIDATE_POTENTIAL_VOLUME_TRAP_MAX = 58.0
CANDIDATE_POTENTIAL_RETURN_20D_MIN = -0.05
CANDIDATE_POTENTIAL_RETURN_20D_MAX = 0.18
CANDIDATE_POTENTIAL_DAY_CHANGE_MIN = 0.03
CANDIDATE_POTENTIAL_DAY_CHANGE_MAX = 0.11
CANDIDATE_POTENTIAL_DISTANCE_TO_MA20_MAX = 0.12
CANDIDATE_POTENTIAL_SECTOR_STRENGTH_MIN = 38.0
CANDIDATE_POTENTIAL_SECTOR_STRENGTH_MAX = 62.0
CANDIDATE_POTENTIAL_SECTOR_RETURN_20D_MIN = -0.10
CANDIDATE_POTENTIAL_SECTOR_POSITIVE_20D_MIN = 25.0
CANDIDATE_POTENTIAL_SECTOR_COUNT_MIN = 5.0
CANDIDATE_POTENTIAL_PREHEAT_TREND_MIN = 74.0
CANDIDATE_POTENTIAL_PREHEAT_RELATIVE_MIN = 58.0
CANDIDATE_POTENTIAL_PREHEAT_VOLUME_MIN = 58.0
CANDIDATE_POTENTIAL_PREHEAT_PRICE_VOLUME_MIN = 64.0
CANDIDATE_POTENTIAL_PREHEAT_ROUTE_MIN = 56.0
CANDIDATE_POTENTIAL_PREHEAT_SCORE_MIN = 58.0
CANDIDATE_POTENTIAL_PREHEAT_SCORE_DELTA_FLOOR = -2.0
CANDIDATE_POTENTIAL_PREHEAT_DAY_CHANGE_MIN = 0.018
CANDIDATE_POTENTIAL_PREHEAT_DAY_CHANGE_MAX = 0.075
CANDIDATE_POTENTIAL_PREHEAT_RETURN_20D_MIN = -0.04
CANDIDATE_POTENTIAL_PREHEAT_RETURN_20D_MAX = 0.16
CANDIDATE_POTENTIAL_PREHEAT_DISTANCE_TO_MA20_MIN = -0.03
CANDIDATE_POTENTIAL_PREHEAT_DISTANCE_TO_MA20_MAX = 0.08
CANDIDATE_POTENTIAL_LIMIT = 4
CANDIDATE_HARD_OVERHEAT_MAX = 88.0
CANDIDATE_HARD_VOLUME_TRAP_MAX = 82.0
CANDIDATE_HARD_RETURN_20D_MAX = 0.45
CANDIDATE_RULE_SCORE_BONUSES = {
    "R004": 7.0,
    "R002": 5.0,
    "R007": 4.0,
    "R005": 2.0,
    "R006": -1.0,
    "R001": -3.0,
}
CANDIDATE_DEFAULT_LIMIT = 15
FEATURE_DATE_MIN_COVERAGE_RATIO = 0.80
FEATURE_DATE_COUNTS_CACHE_KEY = "research_pool_feature_date_counts"
CANDIDATE_SECTOR_SOFT_PENALTIES = (0.0, 2.4, 5.8, 9.5, 13.0)
ROBUST_FACTOR_PULLBACK_BONUS_MAX = 1.8
ROBUST_FACTOR_TREND_RELATIVE_BONUS_MAX = 1.2
STYLE_HORIZON_DAYS = {
    "growth_cycle": 10,
    "cyclical": 20,
    "consumer_quality": 20,
    "property_chain": 20,
    "compound": 20,
    "healthcare": 10,
    "market_beta": 5,
    "theme": 5,
    "unknown": 10,
}
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
ROBUST_FACTOR_OVEREXTENSION_PENALTY_MAX = 2.4
SECTOR_MONTHLY_LEAD_BONUS_MAX = 2.4
PRICE_VOLUME_TREND_BONUS_MAX = 1.0
PRICE_VOLUME_TREND_WEAK_PENALTY_MAX = 0.8
SECTOR_MAINLINE_RETURN_20D_MIN = 0.08
SECTOR_MAINLINE_RETURN_20D_MAX = 0.18
SECTOR_OVEREXTENDED_RETURN_20D_MIN = 0.24
SECTOR_OVEREXTENDED_POSITIVE_20D_MIN = 85.0
TECH_MAINLINE_BONUS_MAX = 2.0
CANDIDATE_TAG_PREFIXES = (
    "batch:",
    "rank:",
    "score:",
    "watch_keep:",
    "dropped:",
    "hold_until:",
    "rule:",
    "strategy:",
    "style:",
    "style_horizon:",
    "mode:",
    "hold_style:",
    "tier:",
    "tier_reason:",
    "candidate_summary:",
    "candidate_pool:",
    "candidate_pool_reason:",
    "style_gate:",
    "style_gate_reason:",
    "startup_signal_score:",
    "startup_signal_label:",
    "startup_signal_reason:",
)
WATCH_KEEP_RETIRE_AFTER = 2
LONG_HORIZON_WATCH_KEEP_RETIRE_AFTER = 5
REGIME_SCORE_DELTAS = {
    "strong_trend": 2.0,
    "rebound": 1.0,
    "rebound_unconfirmed": -4.0,
    "range": 0.0,
    "weak_trend": -6.0,
    "panic": -12.0,
    "unknown": 0.0,
}


@dataclass(frozen=True)
class CandidateStrategyMatch:
    rule_id: str
    name: str
    strategy_type: str
    score_bonus: float


@dataclass(frozen=True)
class NextSessionCandidate:
    symbol: str
    name: str | None
    sector: str | None
    sector_style: str
    suggested_horizon_days: int
    horizon_reason: str
    day_change_pct: float | None
    score: float
    route_score: float | None
    route_label: str | None
    route_reason: str | None
    selection_mode: str
    selected_rule_id: str | None
    selected_rule_name: str | None
    selected_strategy_type: str | None
    trend_score: float | None
    relative_strength_score: float | None
    sector_strength_score: float | None
    volume_confirmation_score: float | None
    price_volume_trend_score: float | None
    sector_avg_return_20d: float | None
    return_20d: float | None
    distance_to_ma20: float | None
    startup_signal_score: float | None
    startup_signal_label: str | None
    startup_signal_reasons: list[str]
    reasons: list[str]
    risk_flags: list[str]
    matched_rules: list[CandidateStrategyMatch]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["matched_rules"] = [dict(item) for item in payload["matched_rules"]]
        return payload


def _float(context: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = context.get(key)
    return float(value) if value is not None else default


def _optional_float(context: dict[str, Any], key: str) -> float | None:
    value = context.get(key)
    return float(value) if value is not None else None


def _volume_confirmation_value(context: dict[str, Any]) -> float | None:
    value = _optional_float(context, "volume_confirmation_score")
    return value if value is not None else _optional_float(context, "volume_score")


def _sector_style(context: dict[str, Any]) -> str:
    explicit = context.get("sector_style")
    if explicit:
        return str(explicit)
    sector = str(context.get("sector_code") or context.get("industry") or "")
    for style, keywords in SECTOR_STYLE_KEYWORDS.items():
        if any(keyword in sector for keyword in keywords):
            return style
    return "unknown"


def _style_horizon_days(context: dict[str, Any]) -> int:
    return STYLE_HORIZON_DAYS.get(_sector_style(context), STYLE_HORIZON_DAYS["unknown"])


def _style_horizon_reason(context: dict[str, Any]) -> str:
    style = _sector_style(context)
    horizon = _style_horizon_days(context)
    if style == "growth_cycle":
        return f"风格周期：growth_cycle偏{horizon}日观察，科技成长先看承接延续"
    if style == "cyclical":
        return f"风格周期：cyclical偏{horizon}日观察，周期主线更看趋势持续"
    if style == "theme":
        return f"风格周期：theme偏{horizon}日观察，题材样本不足只做短看"
    if style == "market_beta":
        return f"风格周期：market_beta偏{horizon}日观察，需结合指数和成交额"
    return f"风格周期：{style}偏{horizon}日观察"


def _candidate_score(context: dict[str, Any]) -> float:
    route = build_signal_route(context)
    trend = route.trend_score
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    risk = route.risk_score
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    fundamental_bonus = 4.0 if context.get("fundamental_verdict") == "supportive" else 0.0
    factor_delta = _technical_factor_delta(context)
    return max(
        0.0,
        min(
            100.0,
            route.route_score * CANDIDATE_SCORE_WEIGHTS["route"]
            + trend * CANDIDATE_SCORE_WEIGHTS["trend"]
            + relative * CANDIDATE_SCORE_WEIGHTS["relative"]
            + sector * CANDIDATE_SCORE_WEIGHTS["sector"]
            + volume * CANDIDATE_SCORE_WEIGHTS["volume"]
            + (100.0 - risk) * CANDIDATE_SCORE_WEIGHTS["risk"]
            + (100.0 - overheat) * CANDIDATE_SCORE_WEIGHTS["overheat"]
            + (100.0 - volume_trap) * CANDIDATE_SCORE_WEIGHTS["volume_trap"]
            + fundamental_bonus
            + factor_delta,
        ),
    )


def _candidate_score_with_delta(context: dict[str, Any], score_delta: float = 0.0) -> float:
    return max(0.0, min(100.0, _candidate_score(context) + score_delta))


def _day_change_pct(context: dict[str, Any]) -> float | None:
    value = context.get("return_1d")
    return float(value) if value is not None else None


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 50.0


def _score_between(value: float | None, low: float, high: float) -> float:
    if value is None:
        return 50.0
    if high == low:
        return 50.0
    score = (value - low) / (high - low) * 100
    return max(0.0, min(100.0, score))


def _technical_factor_delta(context: dict[str, Any]) -> float:
    sector_flow = context.get("sector_fund_flow_score")
    sector_breadth = context.get("sector_breadth_score")
    sector_momentum = context.get("sector_momentum_score")
    sector_continuity = context.get("sector_trend_continuity_score")
    sector_resilience = context.get("sector_trend_resilience_score")
    sector_avg_return_20d = context.get("sector_avg_return_20d")
    sector_positive_20d_rate = context.get("sector_positive_20d_rate")
    sector_stock_count = _float(context, "sector_stock_count", 0.0)
    stock_flow = context.get("moneyflow_support_score")
    trend_quality = context.get("trend_quality_score")
    price_volume_trend = context.get("price_volume_trend_score")
    pullback_volume = context.get("pullback_volume_ratio")
    volume_ratio = context.get("volume_ratio")
    distance_to_ma20 = context.get("distance_to_ma20")
    return_20d = context.get("return_20d")
    relative = _float(context, "relative_strength_score", 50.0)
    trend = _float(context, "trend_score", 50.0)
    overheat = _float(context, "overheat_score", 50.0)

    delta = 0.0
    if sector_flow is not None:
        sector_flow_score = _score_between(float(sector_flow), 40.0, 72.0)
        delta += (sector_flow_score - 50.0) / 50.0 * 1.8
    if sector_breadth is not None:
        sector_breadth_score = _score_between(float(sector_breadth), 45.0, 72.0)
        delta += (sector_breadth_score - 50.0) / 50.0 * 1.2
    if sector_momentum is not None:
        sector_momentum_score = _score_between(float(sector_momentum), 45.0, 75.0)
        delta += (sector_momentum_score - 50.0) / 50.0 * 1.1
    if sector_continuity is not None:
        sector_continuity_score = _score_between(float(sector_continuity), 50.0, 82.0)
        delta += (sector_continuity_score - 50.0) / 50.0 * 1.0
    if sector_resilience is not None:
        sector_resilience_score = _score_between(float(sector_resilience), 48.0, 78.0)
        delta += (sector_resilience_score - 50.0) / 50.0 * 0.9
    if (
        sector_avg_return_20d is not None
        and sector_positive_20d_rate is not None
        and sector_stock_count >= 5
    ):
        monthly_lead_score = (
            _score_between(float(sector_avg_return_20d), 0.02, 0.16) * 0.45
            + _score_between(float(sector_positive_20d_rate), 50.0, 80.0) * 0.35
            + _score_between(_float(context, "sector_trend_continuity_score", 50.0), 55.0, 82.0)
            * 0.20
        )
        if monthly_lead_score >= 58.0:
            delta += (monthly_lead_score - 50.0) / 50.0 * SECTOR_MONTHLY_LEAD_BONUS_MAX
        elif float(sector_avg_return_20d) < -0.03 or float(sector_positive_20d_rate) < 35.0:
            delta -= 1.2
    if stock_flow is not None:
        stock_flow_score = _score_between(float(stock_flow), 38.0, 68.0)
        delta += (stock_flow_score - 50.0) / 50.0 * 1.2
    if trend_quality is not None:
        trend_quality_score = _score_between(float(trend_quality), 52.0, 82.0)
        delta += (trend_quality_score - 50.0) / 50.0 * 1.5

    if (
        pullback_volume is not None
        and distance_to_ma20 is not None
        and trend_quality is not None
        and 0.72 <= float(pullback_volume) <= 1.08
        and -0.04 <= float(distance_to_ma20) <= 0.08
        and float(trend_quality) >= 65.0
    ):
        delta += 1.4
    elif pullback_volume is not None and float(pullback_volume) >= 1.24:
        delta -= 1.0

    if distance_to_ma20 is not None and return_20d is not None:
        distance_value = float(distance_to_ma20)
        return_20d_value = float(return_20d)
        if -0.04 <= distance_value <= 0.08 and 0.03 <= return_20d_value <= 0.22:
            pullback_score = (
                _score_between(0.08 - abs(distance_value - 0.02), 0.0, 0.08) * 0.55
                + _score_between(0.22 - abs(return_20d_value - 0.12), 0.0, 0.22) * 0.45
            )
            delta += (pullback_score / 100.0) * ROBUST_FACTOR_PULLBACK_BONUS_MAX
        elif distance_value >= 0.16 and return_20d_value >= 0.28:
            delta -= ROBUST_FACTOR_OVEREXTENSION_PENALTY_MAX
        elif distance_value >= 0.12 and return_20d_value >= 0.24:
            delta -= ROBUST_FACTOR_OVEREXTENSION_PENALTY_MAX * 0.65

    if trend >= 70.0 and relative >= 65.0:
        trend_relative_score = min(trend, relative)
        delta += (
            _score_between(trend_relative_score, 65.0, 90.0)
            / 100.0
            * ROBUST_FACTOR_TREND_RELATIVE_BONUS_MAX
        )

    if price_volume_trend is not None:
        price_volume_trend_score = float(price_volume_trend)
        if (
            price_volume_trend_score >= 66.0
            and trend >= 68.0
            and relative >= 60.0
            and overheat <= 72.0
        ):
            delta += (
                _score_between(price_volume_trend_score, 62.0, 86.0)
                / 100.0
                * PRICE_VOLUME_TREND_BONUS_MAX
            )
        elif (
            price_volume_trend_score <= 45.0
            and _float(context, "volume_trap_risk_score", 50.0) >= 60.0
        ):
            delta -= (
                _score_between(50.0 - price_volume_trend_score, 0.0, 18.0)
                / 100.0
                * PRICE_VOLUME_TREND_WEAK_PENALTY_MAX
            )

    if _is_tech_growth_context(context) and _sector_mainline_confirmed(context):
        tech_score = (
            _score_between(trend, 68.0, 86.0) * 0.38
            + _score_between(relative, 62.0, 82.0) * 0.34
            + _score_between(_float(context, "sector_trend_continuity_score", 50.0), 65.0, 82.0)
            * 0.28
        )
        if tech_score >= 55.0:
            delta += (tech_score / 100.0) * TECH_MAINLINE_BONUS_MAX

    if volume_ratio is not None:
        volume_ratio_value = float(volume_ratio)
        if 0.85 <= volume_ratio_value <= 1.85:
            delta += 0.5
        elif volume_ratio_value >= 2.6 and overheat >= 70.0:
            delta -= 0.8

    return max(-4.0, min(4.0, delta))


def _is_tech_growth_context(context: dict[str, Any]) -> bool:
    sector_style = str(context.get("sector_style") or "").lower()
    analysis_framework = str(context.get("analysis_framework") or "").lower()
    sector = str(context.get("sector_code") or context.get("industry") or "")
    if sector_style in {"growth_cycle", "theme"}:
        return True
    if analysis_framework in {"tech_growth_cycle", "theme_momentum"}:
        return True
    tech_keywords = (
        "半导体",
        "通信",
        "元器件",
        "软件",
        "IT",
        "光学",
        "电子",
        "PCB",
        "算力",
        "液冷",
        "芯片",
    )
    return any(keyword.lower() in sector.lower() for keyword in tech_keywords)


def _sector_leadership_delta(context: dict[str, Any]) -> float:
    leadership_score = _float(context, "sector_leadership_score", 50.0)
    leadership_tier = str(context.get("sector_leadership_tier") or "").lower()
    sector_strength = _float(context, "sector_strength_score", 50.0)
    sector_breadth = _float(context, "sector_breadth_score", 50.0)
    sector_momentum = _float(context, "sector_momentum_score", 50.0)
    sector_flow = _float(context, "sector_fund_flow_score", 50.0)
    sector_continuity = _float(context, "sector_trend_continuity_score", 50.0)
    sector_resilience = _float(context, "sector_trend_resilience_score", 50.0)
    sector_confidence = _float(context, "sector_sample_confidence", 0.0)
    sector_stock_count = _float(context, "sector_stock_count", 0.0)
    sector_avg_return_20d = context.get("sector_avg_return_20d")
    sector_positive_20d_rate = context.get("sector_positive_20d_rate")

    delta = 0.0
    if leadership_tier == "core_leader":
        delta += 1.3
    elif leadership_tier == "followable":
        delta += 0.7
    elif leadership_tier == "weak":
        delta -= 1.0

    if leadership_score >= 76:
        delta += 1.0
    elif leadership_score <= 45:
        delta -= 1.1

    if sector_strength >= 72 and sector_breadth >= 60 and sector_momentum >= 60:
        delta += 1.8
    elif sector_strength >= 66 and sector_breadth >= 56 and sector_momentum >= 56:
        delta += 0.9

    if sector_flow >= 60:
        delta += 0.8
    elif sector_flow <= 42:
        delta -= 0.9

    if sector_continuity >= 70:
        delta += 1.0
    elif sector_continuity <= 45:
        delta -= 0.8

    if sector_resilience >= 66:
        delta += 0.9
    elif sector_resilience <= 44:
        delta -= 0.9

    if (
        sector_avg_return_20d is not None
        and sector_positive_20d_rate is not None
        and sector_stock_count >= 5
    ):
        monthly_lead_score = (
            _score_between(float(sector_avg_return_20d), 0.02, 0.16) * 0.42
            + _score_between(float(sector_positive_20d_rate), 50.0, 80.0) * 0.38
            + _score_between(sector_continuity, 55.0, 82.0) * 0.20
        )
        if monthly_lead_score >= 70.0:
            delta += 2.0
        elif monthly_lead_score >= 58.0:
            delta += 1.1
        elif float(sector_avg_return_20d) < -0.03 or float(sector_positive_20d_rate) < 35.0:
            delta -= 1.4

    if sector_strength <= 48:
        delta -= 1.4
    if sector_breadth <= 44 and sector_momentum <= 48:
        delta -= 1.2

    if sector_confidence < 0.15 or sector_stock_count <= 2:
        delta *= 0.5

    return max(-4.0, min(4.0, delta))


def _market_regime_snapshot(
    contexts: list[dict[str, Any]], feature_date: date
) -> MarketRegimeSnapshot:
    if not contexts:
        return MarketRegimeSnapshot(
            trade_date=feature_date.isoformat(),
            regime="unknown",
            trend_score=50.0,
            breadth_score=50.0,
            emotion_score=50.0,
            volatility_score=50.0,
            risk_level="unknown",
        )

    trend_score = _avg([_float(item, "trend_score", 50.0) for item in contexts])
    returns_1d = [
        float(item["return_1d"]) for item in contexts if item.get("return_1d") is not None
    ]
    returns_5d = [
        float(item["return_5d"]) for item in contexts if item.get("return_5d") is not None
    ]
    breadth_score = (
        sum(1 for value in returns_1d if value > 0) / len(returns_1d) * 100 if returns_1d else 50.0
    )
    momentum_score = _avg(
        [max(0.0, min(100.0, (value + 0.05) / 0.12 * 100)) for value in returns_5d]
    )
    volume_score = _avg(
        [
            _float(item, "volume_confirmation_score", _float(item, "volume_score", 50.0))
            for item in contexts
        ]
    )
    emotion_score = max(
        0.0, min(100.0, breadth_score * 0.45 + momentum_score * 0.35 + volume_score * 0.20)
    )
    volatility_score = _avg([_float(item, "volatility_score", 50.0) for item in contexts])
    regime = classify_market_regime(
        trend_score=trend_score,
        breadth_score=breadth_score,
        emotion_score=emotion_score,
        volatility_score=volatility_score,
    )
    risk_level = (
        "high"
        if regime in {"panic", "weak_trend"}
        else "medium"
        if regime in {"range", "rebound_unconfirmed"}
        else "normal"
    )
    return MarketRegimeSnapshot(
        trade_date=feature_date.isoformat(),
        regime=regime,
        trend_score=round(trend_score, 4),
        breadth_score=round(breadth_score, 4),
        emotion_score=round(emotion_score, 4),
        volatility_score=round(volatility_score, 4),
        risk_level=risk_level,
    )


def _emotion_gate(snapshot: MarketRegimeSnapshot) -> dict[str, Any]:
    notes: list[str] = []
    state = "neutral"
    position_scale = 0.5
    if snapshot.regime in {"panic", "weak_trend"} or (
        snapshot.emotion_score <= 35.0 and snapshot.breadth_score <= 40.0
    ):
        state = "risk_off"
        position_scale = 0.0
        notes.append("市场情绪偏弱，不新开仓或只保留观察。")
    elif snapshot.regime == "rebound_unconfirmed":
        state = "caution"
        position_scale = 0.25
        notes.append("上涨广度修复但中短趋势仍弱，先观察，不按反弹扩仓。")
    elif (
        snapshot.regime in {"strong_trend", "rebound"}
        and snapshot.emotion_score >= 55.0
        and snapshot.breadth_score >= 50.0
    ):
        state = "risk_on"
        position_scale = 1.0
        notes.append("市场情绪配合，可以按主策略正常执行。")
    else:
        notes.append("市场情绪中性，降低预期并等待板块确认。")
    return {
        "state": state,
        "position_scale": position_scale,
        "notes": notes,
    }


def _regime_score_delta(
    context: dict[str, Any],
    regime: str,
    participation_snapshot: dict[str, float] | None = None,
) -> float:
    delta = REGIME_SCORE_DELTAS.get(regime, 0.0)
    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    risk = _float(context, "risk_score", 50.0)
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    return_5d = _float(context, "return_5d", 0.0)
    return_20d = _float(context, "return_20d", 0.0)

    if regime in {"weak_trend", "panic", "rebound_unconfirmed"}:
        if trend >= 80 and relative >= 70 and sector >= 65 and risk <= 45 and return_5d >= 0:
            delta += 3.0
        if overheat >= 68 or volume_trap >= 55:
            delta -= 3.0
    elif regime == "range":
        if trend >= 72 and relative >= 64 and sector >= 62:
            delta += 2.0
        if return_20d >= 0.28 or overheat >= 72:
            delta -= 2.0
    elif regime in {"strong_trend", "rebound"}:
        if trend >= 72 and relative >= 62 and 0.03 <= return_20d <= 0.28:
            delta += 1.5
        if return_20d >= 0.34 or overheat >= 78 or volume_trap >= 65:
            delta -= 3.0
    if participation_snapshot:
        participation_score = participation_snapshot.get("participation_score", 50.0)
        liquidity_score = participation_snapshot.get("liquidity_score", 50.0)
        if participation_score < 45.0 or liquidity_score < 45.0:
            delta -= 2.0
        elif participation_score >= 68.0 and liquidity_score >= 68.0:
            delta += 1.0
    return delta


def _regime_note(regime: str) -> str:
    mapping = {
        "strong_trend": "市场环境：强趋势，允许正常跟随上升信号",
        "rebound": "市场环境：反弹，优先选择趋势已确认的票",
        "rebound_unconfirmed": "市场环境：反弹修复未确认，只观察高质量趋势票，不追高扩仓",
        "range": "市场环境：震荡，只看趋势和板块都较强的票",
        "weak_trend": "市场环境：弱趋势，做减法，只保留少数强趋势候选",
        "panic": "市场环境：恐慌，原则上不新开仓，只观察极少数逆势强票",
        "unknown": "市场环境：未知，按保守模式筛选",
    }
    return mapping.get(regime, mapping["unknown"])


def _passes_market_regime_gate(
    context: dict[str, Any],
    *,
    regime: str,
    selection_mode: str,
) -> bool:
    if regime in {"strong_trend", "rebound", "unknown"}:
        return True
    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    risk = _float(context, "risk_score", 50.0)
    overheat = _float(context, "overheat_score", 50.0)
    if regime == "rebound_unconfirmed":
        return (
            selection_mode == "observation"
            and trend >= 76
            and relative >= 66
            and sector >= 64
            and volume >= 50
            and risk <= 50
            and overheat <= 60
        )
    if regime == "range":
        if selection_mode == "potential_watch":
            if _is_startup_preheat_context(context):
                return risk <= 58 and overheat <= 56 and volume >= 60.0
            return (
                trend >= CANDIDATE_POTENTIAL_TREND_MIN
                and volume >= 45.0
                and risk <= CANDIDATE_POTENTIAL_RISK_MAX
                and overheat <= CANDIDATE_POTENTIAL_OVERHEAT_MAX
            )
        if selection_mode == "observation":
            return trend >= 62 and relative >= 58 and sector >= 58
        return trend >= 64 and relative >= 58 and sector >= 58
    if regime == "weak_trend":
        if selection_mode == "potential_watch":
            if _is_startup_preheat_context(context):
                return (
                    trend >= 82
                    and relative >= 64
                    and volume >= 64
                    and risk <= 52
                    and overheat <= 52
                )
            return (
                trend >= 92
                and relative >= CANDIDATE_POTENTIAL_RELATIVE_MIN
                and volume >= CANDIDATE_POTENTIAL_VOLUME_MIN
                and risk <= 58
                and overheat <= CANDIDATE_POTENTIAL_OVERHEAT_MAX
            )
        if selection_mode == "observation":
            return (
                trend >= CANDIDATE_OBSERVATION_TREND_MIN
                and relative >= CANDIDATE_OBSERVATION_RELATIVE_MIN
                and sector >= CANDIDATE_OBSERVATION_SECTOR_MIN
                and volume >= CANDIDATE_OBSERVATION_VOLUME_MIN
                and risk <= CANDIDATE_OBSERVATION_RISK_MAX
            )
        return (
            selection_mode == "formal_strategy"
            and trend >= 76
            and relative >= 66
            and sector >= 64
            and volume >= 45
            and risk <= 55
        )
    if regime == "panic":
        return (
            selection_mode == "formal_strategy"
            and trend >= 84
            and relative >= 72
            and sector >= 70
            and volume >= 55
            and risk <= 42
            and overheat <= 70
        )
    return selection_mode == "formal_strategy"


def _market_quality_snapshot(contexts: list[dict[str, Any]]) -> dict[str, float]:
    if not contexts:
        return {
            "strong_trend_rate": 0.0,
            "up_signal_rate": 0.0,
            "weak_structure_rate": 0.0,
        }

    strong_trend = 0
    up_signal = 0
    weak_structure = 0
    for item in contexts:
        trend = _float(item, "trend_score", 50.0)
        relative = _float(item, "relative_strength_score", 50.0)
        sector = _float(item, "sector_strength_score", 50.0)
        risk = _float(item, "risk_score", 50.0)
        return_5d = _float(item, "return_5d", 0.0)
        if trend >= 70 and relative >= 64:
            strong_trend += 1
        if trend >= 64 and relative >= 58 and sector >= 58 and risk <= 62 and return_5d >= 0:
            up_signal += 1
        if trend <= 42 or relative <= 42 or return_5d <= -0.06:
            weak_structure += 1

    total = len(contexts)
    return {
        "strong_trend_rate": round(strong_trend / total * 100, 4),
        "up_signal_rate": round(up_signal / total * 100, 4),
        "weak_structure_rate": round(weak_structure / total * 100, 4),
    }


def _market_participation_snapshot(contexts: list[dict[str, Any]]) -> dict[str, float]:
    if not contexts:
        return {
            "participation_score": 50.0,
            "liquidity_score": 50.0,
            "volume_support_rate": 0.0,
            "leadership_rate": 0.0,
        }

    amount_percentiles = [
        _float(item, "amount_percentile_60d", 50.0)
        for item in contexts
        if item.get("amount_percentile_60d") is not None
    ]
    amount_ratios = [
        _float(item, "amount_ratio_5d", 1.0)
        for item in contexts
        if item.get("amount_ratio_5d") is not None
    ]
    recent_amount_ratios = [
        _float(item, "recent_amount_ratio_20d", 1.0)
        for item in contexts
        if item.get("recent_amount_ratio_20d") is not None
    ]
    volume_scores = [
        _float(item, "volume_confirmation_score", _float(item, "volume_score", 50.0))
        for item in contexts
    ]
    leadership_rate = (
        sum(
            1
            for item in contexts
            if _float(item, "trend_score", 50.0) >= 70
            and _float(item, "relative_strength_score", 50.0) >= 65
        )
        / len(contexts)
        * 100
    )
    volume_support_rate = (
        sum(
            1
            for item in contexts
            if _float(item, "volume_confirmation_score", _float(item, "volume_score", 50.0)) >= 60
        )
        / len(contexts)
        * 100
    )
    participation_score = max(
        0.0,
        min(
            100.0,
            (_avg(amount_percentiles) if amount_percentiles else 50.0) * 0.45
            + _score_between(_avg(amount_ratios) if amount_ratios else 1.0, 0.70, 1.35) * 0.20
            + _score_between(
                _avg(recent_amount_ratios) if recent_amount_ratios else 1.0, 0.70, 1.30
            )
            * 0.15
            + (_avg(volume_scores) if volume_scores else 50.0) * 0.20,
        ),
    )
    liquidity_score = max(
        0.0,
        min(
            100.0,
            participation_score * 0.55
            + (100.0 - abs(50.0 - volume_support_rate) * 2.0) * 0.20
            + (100.0 - abs(50.0 - leadership_rate) * 2.0) * 0.25,
        ),
    )
    return {
        "participation_score": round(participation_score, 4),
        "liquidity_score": round(liquidity_score, 4),
        "volume_support_rate": round(volume_support_rate, 4),
        "leadership_rate": round(leadership_rate, 4),
    }


def _verified_market_turn_snapshot(
    db: Session,
    *,
    feature_date: date,
    contexts: list[dict[str, Any]],
) -> dict[str, Any]:
    eligible_symbols = set(
        db.execute(
            select(Security.symbol)
            .where(Security.list_date.is_not(None))
            .where(Security.list_date <= feature_date)
        ).scalars()
    )
    current_bars = list(
        db.execute(select(DailyBar).where(DailyBar.trade_date == feature_date)).scalars()
    )
    current_bars = [item for item in current_bars if item.symbol in eligible_symbols]
    valid_bars = [item for item in current_bars if item.pre_close and item.pre_close > 0]
    expected_bar_count = len(eligible_symbols)
    coverage_ratio = len(valid_bars) / expected_bar_count if expected_bar_count else 0.0
    breadth_ratio = (
        sum(1 for item in valid_bars if item.close > item.pre_close) / len(valid_bars)
        if valid_bars
        else 0.0
    )
    previous_date = db.execute(
        select(func.max(DailyBar.trade_date))
        .where(DailyBar.trade_date < feature_date)
    ).scalar_one_or_none()
    previous_amount = 0.0
    previous_coverage_ratio = 0.0
    if previous_date is not None:
        previous_bars = list(
            db.execute(select(DailyBar).where(DailyBar.trade_date == previous_date)).scalars()
        )
        previous_amount_bars = [
            item
            for item in previous_bars
            if item.symbol in eligible_symbols and item.amount is not None
        ]
        previous_coverage_ratio = (
            len(previous_amount_bars) / expected_bar_count if expected_bar_count else 0.0
        )
        previous_amount = sum(float(item.amount) for item in previous_amount_bars)
    current_amount_bars = [item for item in current_bars if item.amount is not None]
    current_amount_coverage_ratio = (
        len(current_amount_bars) / expected_bar_count if expected_bar_count else 0.0
    )
    current_amount = sum(float(item.amount) for item in current_amount_bars)
    amount_change_pct = current_amount / previous_amount - 1 if previous_amount > 0 else None
    index_bar = db.execute(
        select(DailyBar)
        .where(DailyBar.symbol == "sh000001")
        .where(DailyBar.trade_date == feature_date)
    ).scalar_one_or_none()
    index_change_pct = (
        float(index_bar.close / index_bar.pre_close - 1)
        if index_bar and index_bar.pre_close and index_bar.pre_close > 0
        else None
    )
    limit_rows = list(
        db.execute(
            select(TushareLimitListD.limit).where(TushareLimitListD.trade_date == feature_date)
        ).scalars()
    )
    limit_receipt = db.execute(
        select(TushareDatasetSyncReceipt)
        .where(TushareDatasetSyncReceipt.dataset == "limit_list_d")
        .where(TushareDatasetSyncReceipt.trade_date == feature_date)
    ).scalar_one_or_none()
    limit_list_complete = bool(
        limit_receipt is not None and limit_receipt.row_count == len(limit_rows)
    )
    limit_down_count = sum(1 for value in limit_rows if str(value or "") == "D")
    sector_rows = list(
        db.execute(
            select(SectorFeatureDaily).where(SectorFeatureDaily.trade_date == feature_date)
        ).scalars()
    )
    expected_sector_count = len(
        set(
            db.execute(
                select(Security.industry)
                .where(Security.list_date.is_not(None))
                .where(Security.list_date <= feature_date)
                .where(Security.industry.is_not(None))
            ).scalars()
        )
    )
    sector_scores: dict[str, list[tuple[float, float]]] = {}
    for row in sector_rows:
        features = row.features or {}
        sector_scores.setdefault(str(row.sector_code), []).append(
            (
                _float(features, "sector_strength_score", 50.0),
                _float(features, "sector_breadth_score", 50.0),
            )
        )
    sector_expansion_count = sum(
        1
        for values in sector_scores.values()
        if len(values) >= 2
        and _avg([item[0] for item in values]) >= 60.0
        and _avg([item[1] for item in values]) >= 55.0
    )
    data_ready = bool(
        coverage_ratio >= 0.98
        and current_amount_coverage_ratio >= 0.98
        and previous_coverage_ratio >= 0.98
        and amount_change_pct is not None
        and index_change_pct is not None
        and limit_list_complete
        and len(sector_rows) >= max(1, int(expected_sector_count * 0.80))
    )
    state = classify_verified_market_turn_state(
        breadth_ratio=breadth_ratio,
        amount_change_pct=amount_change_pct,
        limit_down_count=limit_down_count if limit_list_complete else None,
        index_change_pct=index_change_pct,
        sector_expansion_count=sector_expansion_count,
        data_ready=data_ready,
    )
    snapshot = state.to_dict()
    snapshot.update(
        {
            "data_ready": data_ready,
            "coverage_ratio": round(coverage_ratio, 6),
            "current_amount_coverage_ratio": round(current_amount_coverage_ratio, 6),
            "previous_amount_coverage_ratio": round(previous_coverage_ratio, 6),
            "breadth_ratio": round(breadth_ratio, 6),
            "amount_change_pct": round(amount_change_pct, 6)
            if amount_change_pct is not None
            else None,
            "limit_down_count": limit_down_count if limit_list_complete else None,
            "limit_list_complete": limit_list_complete,
            "index_change_pct": round(index_change_pct, 6)
            if index_change_pct is not None
            else None,
            "sector_expansion_count": sector_expansion_count,
        }
    )
    return snapshot


def _regime_candidate_limit(
    requested_limit: int,
    *,
    regime: str,
    quality_snapshot: dict[str, float],
    participation_snapshot: dict[str, float],
) -> int:
    base_limit = max(1, requested_limit)
    if regime in {"strong_trend", "rebound"}:
        cap = base_limit
    elif regime == "rebound_unconfirmed":
        cap = min(base_limit, 8)
    elif regime == "range":
        cap = min(base_limit, 20)
    elif regime == "weak_trend":
        cap = min(base_limit, 15)
    elif regime == "panic":
        cap = min(base_limit, 3)
    else:
        cap = min(base_limit, 8)

    up_signal_rate = quality_snapshot.get("up_signal_rate", 0.0)
    strong_trend_rate = quality_snapshot.get("strong_trend_rate", 0.0)
    participation_score = participation_snapshot.get("participation_score", 50.0)
    liquidity_score = participation_snapshot.get("liquidity_score", 50.0)

    if regime in {"weak_trend", "rebound_unconfirmed"}:
        if up_signal_rate >= 8.0 and strong_trend_rate >= 6.0 and participation_score >= 60.0:
            cap = min(cap, 15)
        elif up_signal_rate >= 5.0 and participation_score >= 55.0:
            cap = min(cap, 12)
        elif up_signal_rate >= 2.0:
            cap = min(cap, 8)
        else:
            cap = min(cap, 3)
    elif up_signal_rate < 2.0:
        cap = min(cap, 3)
    elif up_signal_rate < 5.0:
        cap = min(cap, 5)
    if participation_score < 40.0 or liquidity_score < 45.0:
        cap = min(cap, 3)
    elif participation_score < 55.0 or liquidity_score < 55.0:
        cap = min(cap, 5)
    if regime in {"weak_trend", "rebound_unconfirmed"} and liquidity_score < 48.0:
        cap = min(cap, 10)
    return max(1, cap)


def _sector_focus_groups(
    contexts: list[dict[str, Any]],
    *,
    max_groups: int = 6,
) -> list[dict[str, Any]]:
    if not contexts:
        return []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for context in contexts:
        sector = str(context.get("sector_code") or context.get("industry") or "").strip()
        if not sector:
            continue
        grouped.setdefault(sector, []).append(context)

    groups: list[dict[str, Any]] = []
    for sector, items in grouped.items():
        stock_count = len(items)
        if stock_count <= 0:
            continue
        strength = _avg([_float(item, "sector_strength_score", 50.0) for item in items])
        breadth = _avg([_float(item, "sector_breadth_score", 50.0) for item in items])
        momentum = _avg([_float(item, "sector_momentum_score", 50.0) for item in items])
        continuity = _avg([_float(item, "sector_trend_continuity_score", 50.0) for item in items])
        resilience = _avg([_float(item, "sector_trend_resilience_score", 50.0) for item in items])
        leadership = _avg([_float(item, "sector_leadership_score", 50.0) for item in items])
        avg_return_20d = _avg([_float(item, "return_20d", 0.0) * 100 for item in items])
        rising_count = sum(1 for item in items if _float(item, "return_20d", 0.0) > 0)
        focus_score = (
            strength * 0.22
            + breadth * 0.16
            + momentum * 0.16
            + continuity * 0.18
            + resilience * 0.14
            + leadership * 0.14
        )
        leaders = sorted(
            items,
            key=lambda item: (
                _float(item, "trend_score", 50.0),
                _float(item, "relative_strength_score", 50.0),
                -abs(_float(item, "distance_to_ma20", 0.0)),
            ),
            reverse=True,
        )
        groups.append(
            {
                "sector": sector,
                "focus_score": round(focus_score, 4),
                "strength_score": round(strength, 4),
                "breadth_score": round(breadth, 4),
                "momentum_score": round(momentum, 4),
                "continuity_score": round(continuity, 4),
                "resilience_score": round(resilience, 4),
                "leadership_score": round(leadership, 4),
                "avg_return_20d_pct": round(avg_return_20d, 4),
                "positive_ratio": round(rising_count / stock_count, 4),
                "stock_count": stock_count,
                "leaders": [
                    {
                        "symbol": str(item.get("symbol") or ""),
                        "name": item.get("name"),
                        "trend_score": round(_float(item, "trend_score", 50.0), 4),
                        "relative_strength_score": round(
                            _float(item, "relative_strength_score", 50.0), 4
                        ),
                        "return_20d_pct": round(_float(item, "return_20d", 0.0) * 100, 4),
                    }
                    for item in leaders[:3]
                ],
            }
        )

    return sorted(
        groups,
        key=lambda item: (
            item["focus_score"],
            item["continuity_score"],
            item["leadership_score"],
            item["stock_count"],
        ),
        reverse=True,
    )[:max_groups]


def _is_long_horizon_context(context: dict[str, Any]) -> bool:
    holding_style = str(context.get("holding_style") or "").lower()
    sector_style = str(context.get("sector_style") or "").lower()
    analysis_framework = str(context.get("analysis_framework") or "").lower()
    return_20d = _float(context, "return_20d", 0.0)
    trend = _float(context, "trend_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)
    return (
        holding_style
        in {
            "compound",
            "low_turnover_compound",
            "trend_with_catalyst",
            "cycle_trend",
            "monthly_trend",
        }
        or sector_style
        in {
            "compound",
            "growth_cycle",
            "theme",
        }
        or analysis_framework
        in {
            "tech_growth_cycle",
            "sector_trend",
            "monthly_sector_trend",
        }
        or (
            trend >= 72
            and sector >= 68
            and relative >= 62
            and 0.02 <= return_20d <= 0.32
            and -0.05 <= distance_to_ma20 <= 0.12
        )
    )


def _strategy_priority(strategy_type: str | None) -> int:
    mapping = {
        "long_term": 3,
        "swing": 2,
        "watch_breakout": 1,
        "short_term": 0,
    }
    return mapping.get(str(strategy_type or ""), 0)


def _retire_after_count(tags: list[str]) -> int:
    if any(str(tag).startswith("strategy:long_term") for tag in tags):
        return LONG_HORIZON_WATCH_KEEP_RETIRE_AFTER
    if any(str(tag).startswith("hold_style:") for tag in tags):
        return LONG_HORIZON_WATCH_KEEP_RETIRE_AFTER
    return WATCH_KEEP_RETIRE_AFTER


def _matching_rules(context: dict[str, Any]) -> list[CandidateStrategyMatch]:
    matches: list[CandidateStrategyMatch] = []
    for rule in MVP_RULES:
        if rule.strategy_type.value == "filter":
            continue
        if evaluate_group(rule.entry, context):
            matches.append(
                CandidateStrategyMatch(
                    rule_id=rule.id,
                    name=rule.name,
                    strategy_type=rule.strategy_type.value,
                    score_bonus=CANDIDATE_RULE_SCORE_BONUSES.get(rule.id, 0.0),
                )
            )
    return sorted(
        matches,
        key=lambda item: (
            _strategy_priority(item.strategy_type),
            item.score_bonus,
        ),
        reverse=True,
    )


def _observation_match() -> CandidateStrategyMatch:
    return CandidateStrategyMatch(
        rule_id="OBS001",
        name="观察候选",
        strategy_type="watch_breakout",
        score_bonus=0.0,
    )


def _exploration_match() -> CandidateStrategyMatch:
    return CandidateStrategyMatch(
        rule_id="EXP001",
        name="强板块趋势探索",
        strategy_type="watch_breakout",
        score_bonus=0.0,
    )


def _potential_watch_match() -> CandidateStrategyMatch:
    return CandidateStrategyMatch(
        rule_id="POT001",
        name="潜力启动观察",
        strategy_type="watch_breakout",
        score_bonus=0.0,
    )


def _sector_mainline_confirmed(context: dict[str, Any]) -> bool:
    sector_strength = _float(context, "sector_strength_score", 50.0)
    sector_breadth = _float(context, "sector_breadth_score", 50.0)
    sector_continuity = _float(context, "sector_trend_continuity_score", 50.0)
    sector_resilience = _float(context, "sector_trend_resilience_score", 50.0)
    sector_avg_return_20d = context.get("sector_avg_return_20d")
    sector_positive_20d_rate = context.get("sector_positive_20d_rate")
    sector_stock_count = _float(context, "sector_stock_count", 0.0)
    if sector_avg_return_20d is None or sector_positive_20d_rate is None:
        return False
    return (
        sector_stock_count >= 5
        and sector_strength >= CANDIDATE_FORMAL_SECTOR_MIN
        and sector_breadth >= 40.0
        and sector_continuity >= 65.0
        and sector_resilience >= 58.0
        and SECTOR_MAINLINE_RETURN_20D_MIN
        <= float(sector_avg_return_20d)
        <= SECTOR_MAINLINE_RETURN_20D_MAX
        and float(sector_positive_20d_rate) >= 55.0
    )


def _is_long_horizon_strength_context(context: dict[str, Any]) -> bool:
    relative = _float(context, "relative_strength_score", 50.0)
    sector_avg_return_20d = context.get("sector_avg_return_20d")
    sector_positive_20d_rate = context.get("sector_positive_20d_rate")
    sector_stock_count = _float(context, "sector_stock_count", 0.0)
    return_20d = _float(context, "return_20d", 0.0)
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)
    if return_20d > 0.28 or distance_to_ma20 > 0.10:
        return False
    if relative >= 85.0:
        return True
    return (
        sector_avg_return_20d is not None
        and sector_positive_20d_rate is not None
        and sector_stock_count >= 5
        and 0.16 <= float(sector_avg_return_20d) <= SECTOR_MAINLINE_RETURN_20D_MAX
        and float(sector_positive_20d_rate) >= 65.0
    )


def _is_long_horizon_extension_context(context: dict[str, Any]) -> bool:
    if _is_long_horizon_strength_context(context):
        return False
    return_20d = _float(context, "return_20d", 0.0)
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)
    if return_20d > 0.28 or distance_to_ma20 > 0.10:
        return False
    volume = _float(
        context,
        "volume_confirmation_score",
        _float(context, "volume_score", 50.0),
    )
    return (
        _float(context, "relative_strength_score", 50.0) >= 78.0
        and _float(context, "trend_score", 50.0) >= 76.0
        and _float(context, "sector_strength_score", 50.0) >= 60.0
        and _float(context, "sector_trend_continuity_score", 50.0) >= 68.0
        and _float(context, "sector_trend_resilience_score", 50.0) >= 60.0
        and volume >= 45.0
        and _float(context, "overheat_score", 50.0) <= 65.0
        and _float(context, "volume_trap_risk_score", 50.0) <= 55.0
    )


def _sector_first_gate(context: dict[str, Any], *, allow_overextended: bool = False) -> bool:
    if _sector_mainline_confirmed(context):
        return True
    return allow_overextended and _sector_extension_risk_high(context)


def _sector_watch_gap_confirmed(context: dict[str, Any]) -> bool:
    sector_avg_return_20d = context.get("sector_avg_return_20d")
    sector_positive_20d_rate = context.get("sector_positive_20d_rate")
    if sector_avg_return_20d is None or sector_positive_20d_rate is None:
        return False
    if _sector_mainline_confirmed(context) or _sector_extension_risk_high(context):
        return False

    return (
        _float(context, "sector_stock_count", 0.0) >= 5
        and _float(context, "sector_strength_score", 50.0) >= 60.0
        and _float(context, "sector_breadth_score", 50.0) >= 55.0
        and _float(context, "sector_trend_continuity_score", 50.0) >= 65.0
        and _float(context, "sector_trend_resilience_score", 50.0) >= 58.0
        and 0.06 <= float(sector_avg_return_20d) <= 0.23
        and float(sector_positive_20d_rate) >= 55.0
    )


def _sector_watch_gate(context: dict[str, Any], *, allow_overextended: bool = False) -> bool:
    return _sector_first_gate(
        context, allow_overextended=allow_overextended
    ) or _sector_watch_gap_confirmed(context)


def _sector_extension_risk_high(context: dict[str, Any]) -> bool:
    sector_avg_return_20d = context.get("sector_avg_return_20d")
    sector_positive_20d_rate = context.get("sector_positive_20d_rate")
    if sector_avg_return_20d is None or sector_positive_20d_rate is None:
        return False
    return (
        float(sector_avg_return_20d) >= SECTOR_OVEREXTENDED_RETURN_20D_MIN
        or float(sector_positive_20d_rate) >= SECTOR_OVEREXTENDED_POSITIVE_20D_MIN
    )


def _is_low_dimensional_mainline_context(context: dict[str, Any]) -> bool:
    if not _sector_mainline_confirmed(context):
        return False
    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    risk = _float(context, "risk_score", 50.0)
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)
    pullback_volume = context.get("pullback_volume_ratio")
    trend_quality = _float(context, "trend_quality_score", trend)

    if trend < 70.0 or relative < 62.0 or sector < 60.0:
        return False
    if trend_quality < 62.0 or volume < 30.0:
        return False
    if risk > 65.0 or overheat > 72.0 or volume_trap > 66.0:
        return False
    if return_20d < 0.03 or return_20d > 0.24:
        return False
    if distance_to_ma20 < -0.04 or distance_to_ma20 > 0.10:
        return False
    return pullback_volume is None or float(pullback_volume) <= 1.18


def _support_flags(context: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    return_20d = _float(context, "return_20d", 0.0)
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)
    pullback_volume = context.get("pullback_volume_ratio")
    sector_leadership = _float(context, "sector_leadership_score", 50.0)
    sector_continuity = _float(context, "sector_trend_continuity_score", 50.0)
    sector_resilience = _float(context, "sector_trend_resilience_score", 50.0)
    sector_avg_return_20d = context.get("sector_avg_return_20d")
    sector_positive_20d_rate = context.get("sector_positive_20d_rate")
    sector_stock_count = _float(context, "sector_stock_count", 0.0)

    if trend >= 70:
        flags.append("趋势强度领先")
    elif trend >= 60:
        flags.append("趋势结构可观察")
    if relative >= 65:
        flags.append("相对强度领先市场")
    elif relative >= 56:
        flags.append("相对强度不弱")
    if sector >= 65:
        flags.append("所在板块强度较好")
    if sector_leadership >= 72:
        flags.append("板块主线地位靠前")
    elif sector_leadership >= 62:
        flags.append("板块仍有主线跟随价值")
    if sector_continuity >= 70:
        flags.append("板块中期趋势延续性较好")
    if sector_resilience >= 66:
        flags.append("板块回撤韧性还在")
    if (
        sector_avg_return_20d is not None
        and sector_positive_20d_rate is not None
        and sector_stock_count >= 5
        and float(sector_avg_return_20d) >= 0.06
        and float(sector_positive_20d_rate) >= 55
    ):
        flags.append("板块20日主线扩散较好")
    if _sector_mainline_confirmed(context):
        flags.append("板块主线确认且未明显过热")
    elif _sector_watch_gap_confirmed(context):
        flags.append("强板块趋势观察补位")
    if _is_low_dimensional_mainline_context(context):
        flags.append("低维主线：板块趋势和个股强度共振")
    if _is_startup_preheat_context(context):
        flags.append("启动前夜：T-1量价修复，20日涨幅仍不高")
    if _is_long_horizon_strength_context(context):
        flags.append("中期强者：相对强度或板块扩散足够强")
    elif _is_long_horizon_extension_context(context):
        flags.append("中期扩展观察：趋势连续性和相对强度接近中期强者")
    if _is_tech_growth_context(context) and _sector_mainline_confirmed(context):
        flags.append("科技成长主线顺势")
    if volume >= 58:
        flags.append("量能温和确认")
    elif volume >= 45:
        flags.append("量能未明显失速")
    if 0.03 <= return_20d <= 0.25:
        flags.append("20日涨幅处在可跟踪区间")
    if -0.04 <= distance_to_ma20 <= 0.12:
        flags.append("价格未明显远离MA20")
    if -0.04 <= distance_to_ma20 <= 0.08 and 0.03 <= return_20d <= 0.22:
        flags.append("回调质量符合5月较稳因子")
    if trend >= 70 and relative >= 65:
        flags.append("趋势+相对强度因子仍有支撑")
    if _is_startup_preheat_context(context):
        flags.append("成交量开始确认，价格未明显远离MA20")
    if pullback_volume is not None and float(pullback_volume) <= 1.1:
        flags.append("回踩量能没有异常放大")
    if context.get("fundamental_verdict") == "supportive":
        flags.append("基本面评分有支撑")
    return flags


def _risk_flags(context: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    risk = _float(context, "risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    day_change_pct = _day_change_pct(context)
    upper_shadow = context.get("upper_shadow_pct")
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)

    if _sector_extension_risk_high(context):
        flags.append("板块20日涨幅/扩散已偏拥挤")
    if overheat >= 72:
        flags.append(f"过热分数偏高{overheat:.1f}")
    if volume_trap >= 60:
        flags.append(f"放量诱多风险{volume_trap:.1f}")
    if risk >= 65:
        flags.append(f"综合风险偏高{risk:.1f}")
    if return_20d >= 0.28:
        flags.append(f"20日涨幅偏高{return_20d * 100:.2f}%")
    if day_change_pct is not None and day_change_pct >= 0.085:
        flags.append(f"今日涨幅较大{day_change_pct * 100:.2f}%")
    if upper_shadow is not None and float(upper_shadow) >= 0.06:
        flags.append(f"上影线偏长{float(upper_shadow) * 100:.2f}%")
    if distance_to_ma20 >= 0.14:
        flags.append(f"距离MA20偏远{distance_to_ma20 * 100:.2f}%")
    return flags


def _candidate_reasons(
    context: dict[str, Any],
    learning_notes: list[str] | None = None,
    long_horizon_learning_notes: list[str] | None = None,
    market_regime: str = "unknown",
    market_participation_snapshot: dict[str, float] | None = None,
) -> list[str]:
    route = build_signal_route(context)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    day_change_pct = _day_change_pct(context)
    reasons = [
        f"路线 {route.route_label} 第{route.route_score:.1f}分",
        f"路线判断：{route.route_reason}",
        f"趋势{_float(context, 'trend_score', 50.0):.1f}",
        f"相对强度{_float(context, 'relative_strength_score', 50.0):.1f}",
        f"板块强度{_float(context, 'sector_strength_score', 50.0):.1f}",
        f"板块连续性{_float(context, 'sector_trend_continuity_score', 50.0):.1f}",
        f"板块韧性{_float(context, 'sector_trend_resilience_score', 50.0):.1f}",
        f"量能确认{volume:.1f}",
        f"今日涨幅{day_change_pct * 100:.2f}%" if day_change_pct is not None else "今日涨幅-",
        f"20日涨幅{_float(context, 'return_20d', 0.0) * 100:.2f}%",
        f"风险：过热{_float(context, 'overheat_score', 50.0):.1f} / "
        f"诱多{_float(context, 'volume_trap_risk_score', 50.0):.1f}",
    ]
    support_flags = _support_flags(context)
    priority_order = {
        "低维主线：板块趋势和个股强度共振": 0,
        "中期强者：相对强度或板块扩散足够强": 1,
        "启动前夜：T-1量价修复，20日涨幅仍不高": 2,
        "中期扩展观察：趋势连续性和相对强度接近中期强者": 3,
        "科技成长主线顺势": 4,
        "回调质量符合5月较稳因子": 5,
        "趋势+相对强度因子仍有支撑": 6,
        "板块主线确认且未明显过热": 7,
        "板块20日主线扩散较好": 8,
        "板块中期趋势延续性较好": 9,
        "板块回撤韧性还在": 10,
    }
    priority_support = sorted(
        [item for item in support_flags if item in priority_order],
        key=lambda item: priority_order[item],
    )
    support = [*priority_support, *[item for item in support_flags if item not in priority_order]][
        :7
    ]
    if support:
        reasons.append(f"支撑：{'，'.join(support)}")
    reasons.append(_style_horizon_reason(context))
    reasons.append(_regime_note(market_regime))
    if market_regime in {"weak_trend", "panic", "rebound_unconfirmed"} and _float(
        context, "trend_score", 50.0
    ) >= 76:
        reasons.append("动态筛选：弱环境里只按逆势强趋势观察，仍需盘中触发确认")
    elif market_regime == "range":
        reasons.append("动态筛选：震荡环境优先趋势、相对强度和板块共振")
    if market_participation_snapshot:
        participation_score = market_participation_snapshot.get("participation_score", 50.0)
        liquidity_score = market_participation_snapshot.get("liquidity_score", 50.0)
        if participation_score < 45.0 or liquidity_score < 45.0:
            reasons.append("资金参与偏弱，继续做减法")
        elif participation_score >= 65.0 and liquidity_score >= 65.0:
            reasons.append("资金参与顺畅，趋势更容易延续")
    if _is_long_horizon_context(context):
        reasons.append("中期口径：先看板块主线，回调只要不破趋势结构就继续跟踪")
    if learning_notes:
        reasons.extend(learning_notes[:2])
    if long_horizon_learning_notes:
        reasons.append(f"长期学习：{'；'.join(long_horizon_learning_notes[:2])}")
    risks = _risk_flags(context)[:3]
    if risks:
        reasons.append(f"注意：{'，'.join(risks)}")
    return reasons


def _load_learning_recommendations(
    db: Session, feature_date: date
) -> list[ParameterRecommendation]:
    recommendations: list[ParameterRecommendation] = []
    window_start = feature_date - timedelta(days=LEARNING_LOOKBACK_DAYS)
    for source_report_type in LEARNING_SOURCE_REPORT_TYPES:
        stmt = (
            select(ParameterRecommendation)
            .where(ParameterRecommendation.report_date <= feature_date)
            .where(ParameterRecommendation.report_date >= window_start)
            .where(ParameterRecommendation.source_report_type == source_report_type)
            .where(ParameterRecommendation.status.in_(LEARNING_STATUSES))
            .order_by(
                ParameterRecommendation.priority.desc(),
                ParameterRecommendation.report_date.desc(),
                ParameterRecommendation.id.desc(),
            )
        )
        recommendations.extend(db.execute(stmt).scalars())
    return sorted(
        recommendations,
        key=lambda item: (
            LEARNING_PRIORITY_WEIGHTS.get(item.priority, 0.0),
            item.report_date,
            item.id,
        ),
        reverse=True,
    )


def _learning_source_label(item: ParameterRecommendation) -> str:
    if item.source_report_type == "paper_learning_review":
        return "纸面学习"
    if item.source_report_type == "paper_trading_review":
        return "纸面实盘"
    return "历史回归"


def _proposed_priority_delta(item: ParameterRecommendation) -> float | None:
    proposed = item.proposed_json or {}
    value = proposed.get("priority_score_delta")
    return float(value) if value is not None else None


def _learning_recommendation_matches_rule(
    item: ParameterRecommendation,
    rule_id: str,
) -> bool:
    if item.rule_id and item.rule_id != rule_id:
        return False
    proposed = item.proposed_json or {}
    source_rule_id = proposed.get("source_rule_id")
    return source_rule_id in (None, rule_id)


def _learning_blocks_formal_upgrade(item: ParameterRecommendation) -> bool:
    return (
        item.action in LEARNING_FORMAL_BLOCK_ACTIONS
        or item.target_name in LEARNING_FORMAL_BLOCK_TARGETS
    )


def _learning_recency_weight(report_date: date, feature_date: date) -> float:
    days_old = max(0, (feature_date - report_date).days)
    if days_old <= 0:
        return 1.0
    weight = 0.5 ** (days_old / LEARNING_RECENCY_HALF_LIFE_DAYS)
    return max(LEARNING_RECENCY_MIN_WEIGHT, weight)


def _candidate_learning_adjustment(
    context: dict[str, Any],
    match: CandidateStrategyMatch,
    recommendations: list[ParameterRecommendation],
    *,
    feature_date: date,
) -> tuple[float, list[str], str | None]:
    symbol = str(context["symbol"])
    sector = context.get("sector_code") or context.get("industry")
    total_delta = 0.0
    notes: list[str] = []
    formal_block_reason: str | None = None

    for item in recommendations:
        if not _learning_recommendation_matches_rule(item, match.rule_id):
            continue
        if item.scope_type == "symbol":
            if item.scope_value != symbol:
                continue
            scope_label = symbol
        elif item.scope_type == "sector":
            if item.scope_value != sector:
                continue
            scope_label = str(sector or "unknown")
        elif item.scope_type == "rule":
            if item.scope_value not in (None, match.rule_id):
                continue
            scope_label = f"策略{match.rule_id}"
        else:
            continue

        priority_weight = LEARNING_PRIORITY_WEIGHTS.get(item.priority, 0.7)
        scope_weight = LEARNING_SCOPE_WEIGHTS.get(item.scope_type, 0.4)
        recency_weight = _learning_recency_weight(item.report_date, feature_date)
        recency_days = max(0, (feature_date - item.report_date).days)
        source_label = _learning_source_label(item)
        proposed_delta = _proposed_priority_delta(item)
        blocks_formal_upgrade = _learning_blocks_formal_upgrade(item)
        if item.action in LEARNING_NEGATIVE_ACTIONS:
            raw_delta = (
                proposed_delta if proposed_delta is not None and proposed_delta < 0 else -6.0
            )
            if item.action == "reduce_priority_or_require_confirmation":
                raw_delta = (
                    proposed_delta if proposed_delta is not None and proposed_delta < 0 else -10.0
                )
            total_delta += raw_delta * priority_weight * scope_weight * recency_weight
            recency_note = f"（{recency_days}天前）" if recency_days else ""
            if blocks_formal_upgrade:
                formal_block_reason = (
                    f"{source_label}：{scope_label} 样本外验证转弱，只保留观察"
                )
                notes.append(
                    f"{source_label}{recency_note}：{scope_label} 样本外验证转弱，只保留观察"
                )
            else:
                notes.append(
                    f"{source_label}{recency_note}：{match.rule_id} 在 {scope_label} 偏弱，降权观察"
                )
        elif item.action in LEARNING_POSITIVE_ACTIONS:
            raw_delta = proposed_delta if proposed_delta is not None and proposed_delta > 0 else 2.5
            total_delta += raw_delta * priority_weight * scope_weight * recency_weight
            recency_note = f"（{recency_days}天前）" if recency_days else ""
            notes.append(
                f"{source_label}{recency_note}：{match.rule_id} 在 {scope_label} 适配，排序小幅加分"
            )
        elif blocks_formal_upgrade:
            recency_note = f"（{recency_days}天前）" if recency_days else ""
            formal_block_reason = f"{source_label}：{scope_label} 样本外验证转弱，只保留观察"
            notes.append(
                f"{source_label}{recency_note}：{scope_label} 样本外验证转弱，只保留观察"
            )

    return total_delta, notes[:2], formal_block_reason


def _candidate_long_horizon_learning(
    context: dict[str, Any],
    match: CandidateStrategyMatch,
    recommendations: list[ParameterRecommendation],
    *,
    feature_date: date,
) -> list[str]:
    symbol = str(context["symbol"])
    sector = context.get("sector_code") or context.get("industry")
    notes: list[str] = []

    for item in recommendations:
        if item.action not in LONG_HORIZON_LEARNING_ACTIONS:
            continue
        if item.rule_id and item.rule_id != match.rule_id:
            continue
        recency_days = max(0, (feature_date - item.report_date).days)
        recency_note = f"（{recency_days}天前）" if recency_days else ""
        if item.scope_type == "symbol" and item.scope_value == symbol:
            notes.append(f"历史回归{recency_note}：{symbol} 可作为长期跟踪候选")
        elif item.scope_type == "sector" and item.scope_value == sector:
            notes.append(f"历史回归{recency_note}：{sector} 适合长期跟踪")
        elif item.scope_type == "rule" and item.scope_value in (None, match.rule_id):
            notes.append(f"历史回归{recency_note}：{match.rule_id} 可作为长期跟踪候选")

    return notes[:2]


def _passes_hard_safety_filters(context: dict[str, Any]) -> bool:
    if context.get("is_st") or context.get("is_suspended"):
        return False
    if context.get("fundamental_verdict") == "weak":
        return False
    close = _float(context, "close", 0.0)
    if close <= 0:
        return False
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    if overheat > CANDIDATE_HARD_OVERHEAT_MAX or volume_trap > CANDIDATE_HARD_VOLUME_TRAP_MAX:
        return False
    if return_20d > CANDIDATE_HARD_RETURN_20D_MAX:
        return False
    return True


def _passes_candidate_filters(context: dict[str, Any], *, score_delta: float = 0.0) -> bool:
    if not _passes_hard_safety_filters(context):
        return False
    if not _sector_first_gate(context):
        return False
    if _sector_extension_risk_high(context):
        return False
    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    if (
        trend < CANDIDATE_FORMAL_TREND_MIN
        or relative < CANDIDATE_FORMAL_RELATIVE_MIN
        or sector < CANDIDATE_FORMAL_SECTOR_MIN
    ):
        return False
    if volume < CANDIDATE_FORMAL_VOLUME_MIN:
        return False
    if overheat > CANDIDATE_FORMAL_OVERHEAT_MAX or volume_trap > CANDIDATE_FORMAL_VOLUME_TRAP_MAX:
        return False
    if return_20d > CANDIDATE_FORMAL_RETURN_20D_MAX:
        return False
    return _candidate_score_with_delta(context, score_delta) >= CANDIDATE_FORMAL_SCORE_MIN


def _passes_pullback_candidate_filters(
    context: dict[str, Any], *, score_delta: float = 0.0
) -> bool:
    if not _passes_hard_safety_filters(context):
        return False
    if not _sector_first_gate(context):
        return False

    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    risk = _float(context, "risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)
    pullback_volume = _float(context, "pullback_volume_ratio", 0.0)

    if trend < 68 or relative < 60 or sector < 60:
        return False
    if volume < 30:
        return False
    if risk > 72:
        return False
    if return_20d < -0.03 or return_20d > 0.34:
        return False
    if distance_to_ma20 < -0.08 or distance_to_ma20 > 0.05:
        return False
    if pullback_volume and pullback_volume > 1.18:
        return False
    return _candidate_score_with_delta(context, score_delta) >= 60.0


def _passes_observation_filters(context: dict[str, Any], *, score_delta: float = 0.0) -> bool:
    if not _passes_hard_safety_filters(context):
        return False
    if not _sector_watch_gate(context, allow_overextended=True):
        return False

    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    risk = _float(context, "risk_score", 50.0)
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    day_change_pct = _day_change_pct(context)

    if trend < 62 or relative < 54 or sector < 54:
        return False
    if volume < 32:
        return False
    if risk > 68 or overheat > 84 or volume_trap > 78:
        return False
    if return_20d < -0.06 or return_20d > 0.38:
        return False
    if day_change_pct is not None and day_change_pct < -0.06:
        return False

    route = build_signal_route(context)
    if route.route_score < 42.0 and trend < 68:
        return False
    if _candidate_score_with_delta(context, score_delta) >= 57.0:
        return True
    return route.route_score >= 50.0 and trend >= 62.0 and sector >= 54.0 and volume >= 32.0


def _passes_exploration_filters(context: dict[str, Any], *, score_delta: float = 0.0) -> bool:
    if not _passes_hard_safety_filters(context):
        return False
    if not _sector_watch_gate(context, allow_overextended=True):
        return False

    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    risk = _float(context, "risk_score", 50.0)
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    day_change_pct = _day_change_pct(context)
    route = build_signal_route(context)

    if (
        trend < CANDIDATE_EXPLORATION_TREND_MIN
        or relative < CANDIDATE_EXPLORATION_RELATIVE_MIN
        or sector < CANDIDATE_EXPLORATION_SECTOR_MIN
    ):
        return False
    if (
        risk > CANDIDATE_EXPLORATION_RISK_MAX
        or overheat > CANDIDATE_EXPLORATION_OVERHEAT_MAX
        or volume_trap > CANDIDATE_EXPLORATION_VOLUME_TRAP_MAX
    ):
        return False
    if (
        return_20d < CANDIDATE_EXPLORATION_RETURN_20D_MIN
        or return_20d > CANDIDATE_EXPLORATION_RETURN_20D_MAX
    ):
        return False
    if day_change_pct is not None and day_change_pct < CANDIDATE_OBSERVATION_DAY_CHANGE_MIN:
        return False
    return (
        _candidate_score_with_delta(context, score_delta) >= CANDIDATE_EXPLORATION_SCORE_MIN
        or route.route_score >= 50.0
    )


def _is_startup_preheat_context(context: dict[str, Any]) -> bool:
    day_change_pct = _day_change_pct(context)
    if day_change_pct is None:
        return False

    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    sector_breadth = _float(context, "sector_breadth_score", 50.0)
    sector_resilience = _float(context, "sector_trend_resilience_score", 50.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    price_volume = _float(context, "price_volume_trend_score", volume)
    risk = _float(context, "risk_score", 50.0)
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)
    sector_avg_return_20d = context.get("sector_avg_return_20d")
    sector_positive_20d_rate = context.get("sector_positive_20d_rate")
    sector_stock_count = _float(context, "sector_stock_count", 0.0)

    if not (
        CANDIDATE_POTENTIAL_PREHEAT_DAY_CHANGE_MIN
        <= day_change_pct
        <= CANDIDATE_POTENTIAL_PREHEAT_DAY_CHANGE_MAX
    ):
        return False
    if (
        trend < CANDIDATE_POTENTIAL_PREHEAT_TREND_MIN
        or relative < CANDIDATE_POTENTIAL_PREHEAT_RELATIVE_MIN
    ):
        return False
    if sector < CANDIDATE_POTENTIAL_SECTOR_STRENGTH_MIN or sector > 68.0:
        return False
    if (
        volume < CANDIDATE_POTENTIAL_PREHEAT_VOLUME_MIN
        or price_volume < CANDIDATE_POTENTIAL_PREHEAT_PRICE_VOLUME_MIN
    ):
        return False
    if risk > 60.0 or overheat > 58.0 or volume_trap > 52.0:
        return False
    if not (
        CANDIDATE_POTENTIAL_PREHEAT_RETURN_20D_MIN
        <= return_20d
        <= CANDIDATE_POTENTIAL_PREHEAT_RETURN_20D_MAX
    ):
        return False
    if not (
        CANDIDATE_POTENTIAL_PREHEAT_DISTANCE_TO_MA20_MIN
        <= distance_to_ma20
        <= CANDIDATE_POTENTIAL_PREHEAT_DISTANCE_TO_MA20_MAX
    ):
        return False
    if sector_stock_count < CANDIDATE_POTENTIAL_SECTOR_COUNT_MIN:
        return False
    if sector_avg_return_20d is None or sector_positive_20d_rate is None:
        return False
    if float(sector_avg_return_20d) < -0.06 or float(sector_positive_20d_rate) < 35.0:
        return False

    sector_is_warming = (
        sector_breadth >= 55.0
        or sector_resilience >= 58.0
        or float(sector_avg_return_20d) >= 0.0
        or float(sector_positive_20d_rate) >= 45.0
    )
    return sector_is_warming


def _startup_signal_profile(context: dict[str, Any]) -> dict[str, Any]:
    if not _is_startup_preheat_context(context):
        return {"score": None, "label": None, "reasons": []}

    day_change_pct = _day_change_pct(context) or 0.0
    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    sector_breadth = _float(context, "sector_breadth_score", 50.0)
    sector_resilience = _float(context, "sector_trend_resilience_score", 50.0)
    sector_avg_return_20d = _float(context, "sector_avg_return_20d", 0.0)
    sector_positive_20d_rate = _float(context, "sector_positive_20d_rate", 0.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    price_volume = _float(context, "price_volume_trend_score", volume)
    risk = _float(context, "risk_score", 50.0)
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)

    sector_score = 0.0
    if sector >= 52.0:
        sector_score += 6.0
    if sector_breadth >= 55.0:
        sector_score += 7.0
    if sector_resilience >= 58.0:
        sector_score += 7.0
    if sector_avg_return_20d >= 0.0:
        sector_score += 5.0
    if sector_positive_20d_rate >= 45.0:
        sector_score += 5.0

    price_volume_score = 0.0
    if trend >= CANDIDATE_POTENTIAL_PREHEAT_TREND_MIN:
        price_volume_score += 8.0
    if relative >= CANDIDATE_POTENTIAL_PREHEAT_RELATIVE_MIN:
        price_volume_score += 7.0
    if volume >= CANDIDATE_POTENTIAL_PREHEAT_VOLUME_MIN:
        price_volume_score += 8.0
    if price_volume >= CANDIDATE_POTENTIAL_PREHEAT_PRICE_VOLUME_MIN:
        price_volume_score += 8.0
    if (
        CANDIDATE_POTENTIAL_PREHEAT_DAY_CHANGE_MIN
        <= day_change_pct
        <= CANDIDATE_POTENTIAL_PREHEAT_DAY_CHANGE_MAX
    ):
        price_volume_score += 7.0
    if (
        CANDIDATE_POTENTIAL_PREHEAT_DISTANCE_TO_MA20_MIN
        <= distance_to_ma20
        <= CANDIDATE_POTENTIAL_PREHEAT_DISTANCE_TO_MA20_MAX
    ):
        price_volume_score += 7.0

    risk_score = 0.0
    if risk <= 45.0:
        risk_score += 8.0
    if overheat <= 45.0:
        risk_score += 7.0
    if volume_trap <= 40.0:
        risk_score += 6.0
    if (
        CANDIDATE_POTENTIAL_PREHEAT_RETURN_20D_MIN
        <= return_20d
        <= CANDIDATE_POTENTIAL_PREHEAT_RETURN_20D_MAX
    ):
        risk_score += 4.0

    score = round(min(100.0, sector_score + price_volume_score + risk_score), 1)
    label = "启动观察" if score >= 70.0 else "预热观察"
    reasons = [
        (
            "板块修复："
            f"扩散{sector_breadth:.1f}/韧性{sector_resilience:.1f}，"
            f"20日均涨{sector_avg_return_20d * 100:.2f}%，板块转暖但主线未确认"
        ),
        (
            "量价修复："
            f"T-1涨幅{day_change_pct * 100:.2f}%，量能{volume:.1f}/量价{price_volume:.1f}，"
            f"距离MA20 {distance_to_ma20 * 100:.2f}%"
        ),
        (
            "风险可控："
            f"过热{overheat:.1f}/诱多{volume_trap:.1f}/20日涨幅{return_20d * 100:.2f}%，"
            "不代表买点，只观察次日承接"
        ),
    ]
    return {"score": score, "label": label, "reasons": reasons}


def _passes_potential_watch_filters(
    context: dict[str, Any], *, score_delta: float = 0.0
) -> bool:
    if not _passes_hard_safety_filters(context):
        return False
    if _sector_first_gate(context, allow_overextended=True):
        return False

    trend = _float(context, "trend_score", 50.0)
    relative = _float(context, "relative_strength_score", 50.0)
    sector = _float(context, "sector_strength_score", 50.0)
    volume = _float(context, "volume_confirmation_score", _float(context, "volume_score", 50.0))
    price_volume = _float(context, "price_volume_trend_score", volume)
    risk = _float(context, "risk_score", 50.0)
    overheat = _float(context, "overheat_score", 50.0)
    volume_trap = _float(context, "volume_trap_risk_score", 50.0)
    return_20d = _float(context, "return_20d", 0.0)
    day_change_pct = _day_change_pct(context)
    distance_to_ma20 = _float(context, "distance_to_ma20", 0.0)
    sector_avg_return_20d = context.get("sector_avg_return_20d")
    sector_positive_20d_rate = context.get("sector_positive_20d_rate")
    sector_stock_count = _float(context, "sector_stock_count", 0.0)
    route = build_signal_route(context)
    is_startup_preheat = _is_startup_preheat_context(context)

    if is_startup_preheat:
        effective_score_delta = max(score_delta, CANDIDATE_POTENTIAL_PREHEAT_SCORE_DELTA_FLOOR)
        return (
            route.route_score >= CANDIDATE_POTENTIAL_PREHEAT_ROUTE_MIN
            and _candidate_score_with_delta(context, effective_score_delta)
            >= CANDIDATE_POTENTIAL_PREHEAT_SCORE_MIN
        )

    if trend < CANDIDATE_POTENTIAL_TREND_MIN or relative < CANDIDATE_POTENTIAL_RELATIVE_MIN:
        return False
    if not (
        CANDIDATE_POTENTIAL_SECTOR_STRENGTH_MIN
        <= sector
        <= CANDIDATE_POTENTIAL_SECTOR_STRENGTH_MAX
    ):
        return False
    if (
        volume < CANDIDATE_POTENTIAL_VOLUME_MIN
        and price_volume < CANDIDATE_POTENTIAL_PRICE_VOLUME_MIN
    ):
        return False
    if (
        risk > CANDIDATE_POTENTIAL_RISK_MAX
        or overheat > CANDIDATE_POTENTIAL_OVERHEAT_MAX
        or volume_trap > CANDIDATE_POTENTIAL_VOLUME_TRAP_MAX
    ):
        return False
    if (
        return_20d < CANDIDATE_POTENTIAL_RETURN_20D_MIN
        or return_20d > CANDIDATE_POTENTIAL_RETURN_20D_MAX
    ):
        return False
    if day_change_pct is None or not (
        CANDIDATE_POTENTIAL_DAY_CHANGE_MIN
        <= day_change_pct
        <= CANDIDATE_POTENTIAL_DAY_CHANGE_MAX
    ):
        return False
    if distance_to_ma20 > CANDIDATE_POTENTIAL_DISTANCE_TO_MA20_MAX:
        return False
    if sector_stock_count < CANDIDATE_POTENTIAL_SECTOR_COUNT_MIN:
        return False
    if sector_avg_return_20d is None or sector_positive_20d_rate is None:
        return False
    if float(sector_avg_return_20d) < CANDIDATE_POTENTIAL_SECTOR_RETURN_20D_MIN:
        return False
    if float(sector_positive_20d_rate) < CANDIDATE_POTENTIAL_SECTOR_POSITIVE_20D_MIN:
        return False
    score_min = (
        CANDIDATE_POTENTIAL_FRESH_SCORE_MIN
        if _is_fresh_potential_watch_context(context)
        else CANDIDATE_POTENTIAL_SCORE_MIN
    )
    effective_score_delta = _potential_watch_score_delta(context, score_delta)
    return route.route_score >= CANDIDATE_POTENTIAL_ROUTE_MIN and _candidate_score_with_delta(
        context, effective_score_delta
    ) >= score_min


def _is_fresh_potential_watch_context(context: dict[str, Any]) -> bool:
    day_change_pct = _day_change_pct(context)
    if day_change_pct is None:
        return False
    return_20d = _float(context, "return_20d", 0.0)
    overheat = _float(context, "overheat_score", 50.0)
    sector_breadth = _float(context, "sector_breadth_score", 50.0)
    sector_resilience = _float(context, "sector_trend_resilience_score", 50.0)
    return (
        0.08 <= day_change_pct <= CANDIDATE_POTENTIAL_DAY_CHANGE_MAX
        and 0.0 <= return_20d <= 0.08
        and overheat <= 35.0
        and (sector_breadth >= 70.0 or sector_resilience >= 64.0)
    )


def _potential_watch_score_delta(context: dict[str, Any], score_delta: float) -> float:
    if _is_fresh_potential_watch_context(context):
        return max(score_delta, CANDIDATE_POTENTIAL_FRESH_SCORE_DELTA_FLOOR)
    return score_delta


def _candidate_note(
    context: dict[str, Any],
    match: CandidateStrategyMatch | None,
    learning_notes: list[str] | None = None,
    market_participation_snapshot: dict[str, float] | None = None,
) -> str:
    parts = []
    route = build_signal_route(context)
    if match is not None:
        parts.append(f"策略 {match.rule_id} {match.name}")
    parts.append(f"路线 {route.route_label} 第{route.route_score:.1f}分")
    day_change_pct = _day_change_pct(context)
    if day_change_pct is not None:
        parts.append(f"今日涨幅 {day_change_pct * 100:.2f}%")
    parts.append(
        f"趋势 {_float(context, 'trend_score', 50.0):.1f} / "
        f"量能 "
        f"{_float(context, 'volume_confirmation_score', _float(context, 'volume_score', 50.0)):.1f}"
    )
    support = _support_flags(context)[:3]
    if support:
        parts.append(f"入选理由：{'，'.join(support)}")
    parts.append(_style_horizon_reason(context))
    if learning_notes:
        parts.append(f"历史回归：{'；'.join(learning_notes[:2])}")
    if market_participation_snapshot:
        parts.append(
            "资金参与 "
            f"{market_participation_snapshot.get('participation_score', 50.0):.1f} / "
            f"流动性 {market_participation_snapshot.get('liquidity_score', 50.0):.1f}"
        )
    risks = _risk_flags(context)[:3]
    parts.append(f"风险提示：{'，'.join(risks) if risks else '未见明显过热或诱多信号'}")
    return "；".join(parts)


def _candidate_sector_key(item: NextSessionCandidate) -> str:
    sector = str(item.sector or "").strip()
    return sector or "unknown"


def _candidate_position_risk_penalty(item: NextSessionCandidate) -> float:
    penalty = 0.0
    for flag in item.risk_flags:
        text = str(flag)
        if "距离MA20偏远" in text:
            penalty += 4.0
        elif "今日涨幅较大" in text:
            penalty += 3.0
        elif "20日涨幅偏高" in text:
            penalty += 3.0
        elif "过热分数偏高" in text:
            penalty += 2.5
        elif "放量诱多风险" in text:
            penalty += 2.5
        else:
            penalty += 1.5
    return penalty


def _weak_market_observation_score(item: NextSessionCandidate) -> float:
    reasons_text = " ".join(str(reason) for reason in item.reasons)
    score = _action_rank_score(item)
    if "回调质量符合5月较稳因子" in reasons_text:
        score += 3.5
    if "价格未明显远离MA20" in reasons_text:
        score += 2.0
    if "20日涨幅处在可跟踪区间" in reasons_text:
        score += 1.5
    if "趋势+相对强度因子仍有支撑" in reasons_text:
        score += 1.0
    if "中期口径" in reasons_text:
        score += 1.0
    return score


def _low_dimensional_mainline_rank_bonus(item: NextSessionCandidate) -> float:
    reasons_text = " ".join(str(reason) for reason in item.reasons)
    if "低维主线：板块趋势和个股强度共振" in reasons_text:
        return 18.0
    return 0.0


def _action_rank_score(item: NextSessionCandidate) -> float:
    return (
        item.score
        + _low_dimensional_mainline_rank_bonus(item)
        - _candidate_position_risk_penalty(item) * 0.8
    )


def _sector_first_priority(item: NextSessionCandidate) -> float:
    reasons_text = " ".join(str(reason) for reason in item.reasons)
    priority = float(_strategy_priority(item.selected_strategy_type))
    if "低维主线：板块趋势和个股强度共振" in reasons_text:
        priority += 2.0
    if "中期强者：相对强度或板块扩散足够强" in reasons_text:
        priority += 1.8
    if "科技成长主线顺势" in reasons_text:
        priority += 1.5
    if "板块20日主线扩散较好" in reasons_text:
        priority += 1.0
    if "板块中期趋势延续性较好" in reasons_text:
        priority += 0.6
    if "板块回撤韧性还在" in reasons_text:
        priority += 0.3
    if item.risk_flags:
        priority -= min(0.8, len(item.risk_flags) * 0.25)
    return priority


def _sector_concentration_penalty(
    item: NextSessionCandidate,
    current_count: int,
) -> float:
    base_penalty = (
        CANDIDATE_SECTOR_SOFT_PENALTIES[current_count]
        if current_count < len(CANDIDATE_SECTOR_SOFT_PENALTIES)
        else CANDIDATE_SECTOR_SOFT_PENALTIES[-1]
        + (current_count - len(CANDIDATE_SECTOR_SOFT_PENALTIES) + 1) * 3.0
    )
    strategy_type = str(item.selected_strategy_type or "")
    if strategy_type == "long_term":
        base_penalty *= 0.7
    elif strategy_type == "swing":
        base_penalty *= 0.85

    reasons_text = " ".join(str(reason) for reason in item.reasons)
    if "板块主线地位靠前" in reasons_text:
        base_penalty *= 0.7
    elif "板块仍有主线跟随价值" in reasons_text:
        base_penalty *= 0.85
    if "板块中期趋势延续性较好" in reasons_text:
        base_penalty *= 0.8
    if "板块回撤韧性还在" in reasons_text:
        base_penalty *= 0.85
    return base_penalty


def _rank_with_sector_balance(
    candidates: list[NextSessionCandidate],
    *,
    limit: int,
    score_fn: Any | None = None,
    max_per_sector: int | None = None,
) -> list[NextSessionCandidate]:
    if len(candidates) <= 1:
        return candidates[:limit]

    effective_score_fn = score_fn or (lambda item: item.score)
    remaining = list(candidates)
    selected: list[NextSessionCandidate] = []
    sector_counts: dict[str, int] = {}

    while remaining and len(selected) < limit:
        eligible_indices = range(len(remaining))
        if max_per_sector is not None:
            capped = [
                index
                for index, item in enumerate(remaining)
                if sector_counts.get(_candidate_sector_key(item), 0) < max_per_sector
            ]
            if capped:
                eligible_indices = capped
        best_index = 0
        best_effective_score = -10_000.0
        for index in eligible_indices:
            item = remaining[index]
            sector_key = _candidate_sector_key(item)
            effective_score = effective_score_fn(item) - _sector_concentration_penalty(
                item,
                sector_counts.get(sector_key, 0),
            )
            effective_score += _sector_first_priority(item) * 0.6
            if effective_score > best_effective_score:
                best_effective_score = effective_score
                best_index = index
        chosen = remaining.pop(best_index)
        selected.append(chosen)
        sector_key = _candidate_sector_key(chosen)
        sector_counts[sector_key] = sector_counts.get(sector_key, 0) + 1

    return selected


def _regime_rank_score_fn(
    regime: str,
    participation_snapshot: dict[str, float] | None = None,
) -> Any:
    if regime in {"weak_trend", "panic", "rebound_unconfirmed"}:
        return _weak_market_observation_score
    if regime == "range" and participation_snapshot:
        participation_score = participation_snapshot.get("participation_score", 50.0)
        liquidity_score = participation_snapshot.get("liquidity_score", 50.0)
        if participation_score < 45.0 or liquidity_score < 45.0:
            return _weak_market_observation_score
    return _action_rank_score


def _sector_first_final_rank_score(item: NextSessionCandidate, score_fn: Any) -> float:
    return score_fn(item) + _sector_first_priority(item) * 2.0


def _is_fresh_potential_watch_candidate(item: NextSessionCandidate) -> bool:
    reasons_text = " ".join(str(reason) for reason in item.reasons)
    return "潜力启动：20日涨幅仍低" in reasons_text or "启动前夜：T-1量价修复" in reasons_text


def _potential_startup_confirmation_bonus(item: NextSessionCandidate) -> float:
    if not _is_fresh_potential_watch_candidate(item):
        return 0.0

    volume_values = [
        value
        for value in (item.volume_confirmation_score, item.price_volume_trend_score)
        if value is not None
    ]
    volume_score = sum(volume_values) / len(volume_values) if volume_values else 50.0
    return_20d = item.return_20d
    distance_to_ma20 = item.distance_to_ma20
    sector_return = item.sector_avg_return_20d
    startup_score = item.startup_signal_score or 0.0

    bonus = 0.0
    bonus += _score_between(startup_score, 70.0, 92.0) * 0.04
    bonus += _score_between(volume_score, 64.0, 84.0) * 0.08
    bonus += _score_between(sector_return, 0.0, 0.06) * 0.05
    if return_20d is not None:
        bonus += _score_between(0.16 - abs(return_20d - 0.09), 0.0, 0.16) * 0.05
    if distance_to_ma20 is not None:
        bonus += _score_between(0.09 - abs(distance_to_ma20 - 0.025), 0.0, 0.09) * 0.04
    return min(18.0, bonus)


def _potential_watch_rank_score(item: NextSessionCandidate) -> float:
    fresh_start_bonus = 30.0 if _is_fresh_potential_watch_candidate(item) else 0.0
    return item.score + fresh_start_bonus + _potential_startup_confirmation_bonus(item)


def _is_crowded_sector_observation(item: NextSessionCandidate) -> bool:
    return item.selection_mode == "observation" and any(
        "板块20日涨幅/扩散已偏拥挤" in str(flag) for flag in item.risk_flags
    )


def _surface_fresh_potential_after_crowded_sector(
    candidates: list[NextSessionCandidate],
) -> list[NextSessionCandidate]:
    fresh_potential = [
        item
        for item in candidates
        if item.selection_mode == "potential_watch" and _is_fresh_potential_watch_candidate(item)
    ]
    if not fresh_potential:
        return candidates

    result: list[NextSessionCandidate] = []
    used_symbols: set[str] = set()
    crowded_sector_counts: dict[str, int] = {}
    pending_potential = list(fresh_potential)
    for item in candidates:
        sector_key = _candidate_sector_key(item)
        if _is_crowded_sector_observation(item) and crowded_sector_counts.get(sector_key, 0) >= 2:
            for index, potential in enumerate(pending_potential):
                if _candidate_sector_key(potential) == sector_key:
                    continue
                result.append(potential)
                used_symbols.add(potential.symbol)
                pending_potential.pop(index)
                break

        if item.symbol not in used_symbols:
            result.append(item)
            used_symbols.add(item.symbol)
        if _is_crowded_sector_observation(item):
            crowded_sector_counts[sector_key] = crowded_sector_counts.get(sector_key, 0) + 1

    return result


def _candidate_sector_groups(candidates: list[NextSessionCandidate]) -> list[dict[str, Any]]:
    grouped: dict[str, list[NextSessionCandidate]] = {}
    for item in candidates:
        grouped.setdefault(_candidate_sector_key(item), []).append(item)

    groups = []
    for sector, items in grouped.items():
        ordered = sorted(
            items,
            key=lambda item: (
                _strategy_priority(item.selected_strategy_type),
                item.score,
            ),
            reverse=True,
        )
        groups.append(
            {
                "sector": sector,
                "count": len(ordered),
                "avg_score": round(sum(item.score for item in ordered) / len(ordered), 4),
                "top_symbol": ordered[0].symbol if ordered else None,
                "candidates": [item.to_dict() for item in ordered],
            }
        )
    return sorted(
        groups,
        key=lambda item: (
            item["count"],
            item["avg_score"],
        ),
        reverse=True,
    )


def _candidate_discovery_diagnostics(
    *,
    candidate_count: int,
    requested_limit: int,
    effective_limit: int,
    market_regime: str,
    market_regime_snapshot: dict[str, Any],
    participation_snapshot: dict[str, float],
    universe_size: int,
    min_universe_size: int,
    sector_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    reasons: list[str] = []
    gate_state = str(market_regime_snapshot.get("emotion_gate") or "")
    participation_score = float(participation_snapshot.get("participation_score", 50.0))
    liquidity_score = float(participation_snapshot.get("liquidity_score", 50.0))
    top_group = sector_groups[0] if sector_groups else {}
    top_sector = str(top_group.get("sector") or "").strip() or None
    top_sector_count = int(top_group.get("count") or 0)
    sector_count = len([item for item in sector_groups if str(item.get("sector") or "").strip()])

    if universe_size < min_universe_size:
        reasons.append(f"本地特征宇宙只有{universe_size}只，样本覆盖不足。")
    if effective_limit < requested_limit:
        reasons.append(f"市场状态把候选上限从{requested_limit}只收缩到{effective_limit}只。")
    if market_regime in {"weak_trend", "panic", "rebound_unconfirmed"} or gate_state == "risk_off":
        label = {
            "panic": "恐慌",
            "weak_trend": "弱趋势",
            "rebound_unconfirmed": "反弹修复未确认",
        }.get(market_regime, "谨慎")
        reasons.append(f"市场处于{label}，情绪阀门{gate_state or 'neutral'}，先保留少数观察票。")
    if participation_score < 45.0 or liquidity_score < 48.0:
        reasons.append(f"资金参与偏弱，参与{participation_score:.1f}/流动性{liquidity_score:.1f}。")
    if candidate_count and top_sector and (
        sector_count == 1 or top_sector_count / max(candidate_count, 1) >= 0.67
    ):
        reasons.append(f"候选集中在{top_sector}，板块宽度不足，暂不硬凑其他行业。")
    if candidate_count < effective_limit:
        reasons.append(
            f"候选数{candidate_count}低于当前上限{effective_limit}，说明趋势/风险过滤仍偏严格。"
        )

    if candidate_count == 0:
        state = "empty"
        summary = "没有自动候选：先不强行给票。"
    elif reasons:
        state = "limited"
        summary = f"候选偏少：{candidate_count}只，先解释原因再考虑调参。"
    else:
        state = "normal"
        summary = f"候选正常：{candidate_count}只，继续按板块和趋势验证。"

    return {
        "state": state,
        "summary": summary,
        "reasons": reasons,
        "candidate_count": candidate_count,
        "requested_limit": requested_limit,
        "effective_limit": effective_limit,
        "sector_count": sector_count,
        "top_sector": top_sector,
        "top_sector_count": top_sector_count,
    }


def _build_candidate(
    context: dict[str, Any],
    matches: list[CandidateStrategyMatch],
    *,
    selection_mode: str = "formal_strategy",
    score_delta: float = 0.0,
    learning_notes: list[str] | None = None,
    long_horizon_learning_notes: list[str] | None = None,
    market_regime: str = "unknown",
    market_participation_snapshot: dict[str, float] | None = None,
) -> NextSessionCandidate:
    selected_match = matches[0]
    route = build_signal_route(context)
    startup_signal = (
        _startup_signal_profile(context)
        if selection_mode == "potential_watch"
        else {"score": None, "label": None, "reasons": []}
    )
    score = _candidate_score_with_delta(context, score_delta) + sum(
        item.score_bonus for item in matches
    )
    selection_text = {
        "formal_strategy": "正式策略命中",
        "potential_watch": "潜力观察",
        "exploration": "强板块趋势探索",
    }.get(selection_mode, "观察候选")
    reasons = [
        f"入选层级：{selection_text}",
        *_candidate_reasons(
            context,
            learning_notes=learning_notes,
            long_horizon_learning_notes=long_horizon_learning_notes,
            market_regime=market_regime,
            market_participation_snapshot=market_participation_snapshot,
        ),
        f"命中策略 {selected_match.rule_id} {selected_match.name}",
    ]
    if selection_mode == "observation" and _sector_watch_gap_confirmed(context):
        reasons.insert(1, "强板块趋势观察补位：板块偏强但行动确认不足，只观察不行动")
    if selection_mode == "exploration":
        reasons.insert(1, "强板块趋势探索：板块趋势较强但买点未完全确认，只观察不行动")
    if selection_mode == "potential_watch":
        reasons.insert(1, "潜力观察：个股启动但板块未确认，只观察不行动")
        if _is_startup_preheat_context(context):
            reasons.insert(2, "启动前夜：T-1量价修复，20日涨幅仍不高，只观察次日承接")
            reasons.insert(3, "成交量开始确认：温和放量配合价格修复，但未进入核心行动")
            if startup_signal["score"] is not None and startup_signal["label"]:
                reasons.insert(
                    4,
                    (
                        f"{startup_signal['label']}：评分{float(startup_signal['score']):.1f}，"
                        "板块修复+量价修复+风险可控，不代表买点"
                    ),
                )
        elif _is_fresh_potential_watch_context(context):
            reasons.insert(2, "潜力启动：20日涨幅仍低，今日向上启动，后续看承接确认")
    return NextSessionCandidate(
        symbol=str(context["symbol"]),
        name=context.get("name"),
        sector=context.get("sector_code") or context.get("industry"),
        sector_style=_sector_style(context),
        suggested_horizon_days=_style_horizon_days(context),
        horizon_reason=_style_horizon_reason(context),
        day_change_pct=_day_change_pct(context),
        score=round(min(100.0, score), 4),
        route_score=route.route_score,
        route_label=route.route_label,
        route_reason=route.route_reason,
        selection_mode=selection_mode,
        selected_rule_id=selected_match.rule_id,
        selected_rule_name=selected_match.name,
        selected_strategy_type=selected_match.strategy_type,
        trend_score=_optional_float(context, "trend_score"),
        relative_strength_score=_optional_float(context, "relative_strength_score"),
        sector_strength_score=_optional_float(context, "sector_strength_score"),
        volume_confirmation_score=_volume_confirmation_value(context),
        price_volume_trend_score=_optional_float(context, "price_volume_trend_score"),
        sector_avg_return_20d=_optional_float(context, "sector_avg_return_20d"),
        return_20d=_optional_float(context, "return_20d"),
        distance_to_ma20=_optional_float(context, "distance_to_ma20"),
        startup_signal_score=startup_signal["score"],
        startup_signal_label=startup_signal["label"],
        startup_signal_reasons=startup_signal["reasons"],
        reasons=reasons,
        risk_flags=_risk_flags(context),
        matched_rules=matches,
    )


def _feature_date_counts(db: Session, *, before: date) -> list[tuple[date, int]]:
    rows = db.info.get(FEATURE_DATE_COUNTS_CACHE_KEY)
    if rows is None:
        rows = [
            (row.trade_date, int(row.feature_count))
            for row in db.execute(
                select(StockFeatureDaily.trade_date, func.count().label("feature_count"))
                .group_by(StockFeatureDaily.trade_date)
                .order_by(StockFeatureDaily.trade_date.desc())
            ).all()
        ]
        db.info[FEATURE_DATE_COUNTS_CACHE_KEY] = rows
    return [
        (trade_date, count)
        for trade_date, count in rows
        if trade_date < before
    ]


def _effective_feature_date(
    db: Session,
    *,
    feature_date: str | None,
    next_trade_date: str,
) -> tuple[date | None, str | None, float | None]:
    requested_date = date.fromisoformat(feature_date) if feature_date else None
    reference_date = date.fromisoformat(next_trade_date)
    rows = _feature_date_counts(db, before=reference_date)
    if not rows:
        return None, feature_date, None

    max_count = max(count for _, count in rows)
    min_count = max(1, int(max_count * FEATURE_DATE_MIN_COVERAGE_RATIO))
    rows_by_date = {trade_date: count for trade_date, count in rows}
    if (
        requested_date
        and requested_date in rows_by_date
        and rows_by_date[requested_date] >= min_count
    ):
        return requested_date, feature_date, round(rows_by_date[requested_date] / max_count, 6)

    if requested_date is None:
        latest_date = latest_feature_date(db, before=reference_date)
        if latest_date and rows_by_date.get(latest_date, 0) >= min_count:
            return latest_date, feature_date, round(rows_by_date[latest_date] / max_count, 6)

    for trade_date, count in rows:
        if requested_date is not None and trade_date > requested_date:
            continue
        if count >= min_count:
            return trade_date, feature_date, round(count / max_count, 6)
    fallback_date, fallback_count = rows[0]
    return fallback_date, feature_date, round(fallback_count / max_count, 6)


def _watch_keep_count(tags: list[str]) -> int:
    for tag in tags:
        if str(tag).startswith("watch_keep:"):
            try:
                return int(str(tag).removeprefix("watch_keep:"))
            except ValueError:
                return 0
    return 0


def _hold_until_date(tags: list[str]) -> date | None:
    for tag in tags:
        value = str(tag)
        if not value.startswith("hold_until:"):
            continue
        try:
            return date.fromisoformat(value.removeprefix("hold_until:"))
        except ValueError:
            return None
    return None


def _is_growth_board_context(context: dict[str, Any]) -> bool:
    return is_growth_board_symbol(context.get("symbol"))


def discover_next_session_candidates(
    db: Session,
    *,
    next_trade_date: str,
    feature_date: str | None = None,
    pool_name: str = "experiment",
    symbols: list[str] | None = None,
    limit: int = CANDIDATE_DEFAULT_LIMIT,
    include_growth_board: bool = False,
    include_fundamentals: bool = True,
    min_universe_size: int = 3000,
) -> dict[str, Any]:
    effective_feature_date, requested_feature_date, feature_coverage_ratio = (
        _effective_feature_date(
            db,
            feature_date=feature_date,
            next_trade_date=next_trade_date,
        )
    )
    if effective_feature_date is None:
        return {"feature_date": "", "candidates": [], "written": 0}

    contexts = load_feature_contexts(
        db,
        feature_date=effective_feature_date.isoformat(),
        symbols=symbols,
        include_fundamentals=include_fundamentals,
    )
    if not include_growth_board:
        contexts = [context for context in contexts if not _is_growth_board_context(context)]
    learning_recommendations = _load_learning_recommendations(db, effective_feature_date)
    market_regime = _market_regime_snapshot(contexts, effective_feature_date)
    emotion_gate = _emotion_gate(market_regime)
    quality_snapshot = _market_quality_snapshot(contexts)
    participation_snapshot = _market_participation_snapshot(contexts)
    market_turn = _verified_market_turn_snapshot(
        db,
        feature_date=effective_feature_date,
        contexts=contexts,
    )
    rank_score_fn = _regime_rank_score_fn(market_regime.regime, participation_snapshot)
    requested_limit = max(1, min(limit, CANDIDATE_DEFAULT_LIMIT))
    effective_limit = _regime_candidate_limit(
        requested_limit,
        regime=market_regime.regime,
        quality_snapshot=quality_snapshot,
        participation_snapshot=participation_snapshot,
    )
    universe_size = len(contexts)
    context_by_symbol = {str(context["symbol"]): context for context in contexts}
    formal_candidates: list[NextSessionCandidate] = []
    observation_candidates: list[NextSessionCandidate] = []
    potential_candidates: list[NextSessionCandidate] = []
    exploration_candidates: list[NextSessionCandidate] = []
    learning_notes_by_symbol: dict[str, list[str]] = {}
    long_horizon_learning_notes_by_symbol: dict[str, list[str]] = {}
    style_gate_reasons_by_symbol: dict[str, str] = {}

    for context in contexts:
        if not _passes_hard_safety_filters(context):
            continue
        matches = _matching_rules(context)
        score_delta = _regime_score_delta(
            context,
            market_regime.regime,
            participation_snapshot,
        )
        score_delta += _sector_leadership_delta(context)
        learning_notes: list[str] = []
        formal_upgrade_blocked = False
        if matches:
            learning_score_delta, learning_notes, formal_block_reason = (
                _candidate_learning_adjustment(
                    context,
                    matches[0],
                    learning_recommendations,
                    feature_date=effective_feature_date,
                )
            )
            formal_upgrade_blocked = formal_block_reason is not None
            if formal_block_reason:
                style_gate_reasons_by_symbol[str(context["symbol"])] = formal_block_reason
            score_delta += learning_score_delta
            long_horizon_learning_notes = _candidate_long_horizon_learning(
                context,
                matches[0],
                learning_recommendations,
                feature_date=effective_feature_date,
            )
            if learning_notes:
                learning_notes_by_symbol[str(context["symbol"])] = learning_notes
            if long_horizon_learning_notes:
                long_horizon_learning_notes_by_symbol[str(context["symbol"])] = (
                    long_horizon_learning_notes
                )
        if (
            matches
            and not formal_upgrade_blocked
            and _passes_market_regime_gate(
                context,
                regime=market_regime.regime,
                selection_mode="formal_strategy",
            )
            and _passes_candidate_filters(context, score_delta=score_delta)
        ):
            formal_candidates.append(
                _build_candidate(
                    context,
                    matches,
                    score_delta=score_delta,
                    learning_notes=learning_notes,
                    long_horizon_learning_notes=long_horizon_learning_notes_by_symbol.get(
                        str(context["symbol"])
                    ),
                    market_regime=market_regime.regime,
                    market_participation_snapshot=participation_snapshot,
                )
            )
            continue
        if (
            matches
            and not formal_upgrade_blocked
            and _passes_market_regime_gate(
                context,
                regime=market_regime.regime,
                selection_mode="formal_strategy",
            )
            and _is_long_horizon_context(context)
            and _passes_pullback_candidate_filters(
                context,
                score_delta=score_delta,
            )
        ):
            formal_candidates.append(
                _build_candidate(
                    context,
                    matches,
                    score_delta=score_delta + 2.0,
                    learning_notes=learning_notes,
                    long_horizon_learning_notes=long_horizon_learning_notes_by_symbol.get(
                        str(context["symbol"])
                    ),
                    market_regime=market_regime.regime,
                    market_participation_snapshot=participation_snapshot,
                )
            )
            continue
        if _passes_market_regime_gate(
            context,
            regime=market_regime.regime,
            selection_mode="observation",
        ) and _passes_observation_filters(context, score_delta=score_delta):
            observation_candidates.append(
                _build_candidate(
                    context,
                    [_observation_match()],
                    selection_mode="observation",
                    score_delta=score_delta,
                    learning_notes=learning_notes,
                    long_horizon_learning_notes=long_horizon_learning_notes_by_symbol.get(
                        str(context["symbol"])
                    ),
                    market_regime=market_regime.regime,
                    market_participation_snapshot=participation_snapshot,
                )
            )
            continue
        if _passes_market_regime_gate(
            context,
            regime=market_regime.regime,
            selection_mode="potential_watch",
        ) and _passes_potential_watch_filters(context, score_delta=score_delta):
            potential_score_delta = _potential_watch_score_delta(context, score_delta)
            potential_candidates.append(
                _build_candidate(
                    context,
                    [_potential_watch_match()],
                    selection_mode="potential_watch",
                    score_delta=potential_score_delta,
                    learning_notes=learning_notes,
                    long_horizon_learning_notes=long_horizon_learning_notes_by_symbol.get(
                        str(context["symbol"])
                    ),
                    market_regime=market_regime.regime,
                    market_participation_snapshot=participation_snapshot,
                )
            )
            continue
        if _passes_exploration_filters(context, score_delta=score_delta):
            exploration_candidates.append(
                _build_candidate(
                    context,
                    [_exploration_match()],
                    selection_mode="exploration",
                    score_delta=score_delta,
                    learning_notes=learning_notes,
                    long_horizon_learning_notes=long_horizon_learning_notes_by_symbol.get(
                        str(context["symbol"])
                    ),
                    market_regime=market_regime.regime,
                    market_participation_snapshot=participation_snapshot,
                )
            )

    ranked_formal = sorted(
        formal_candidates,
        key=lambda item: (
            _sector_first_priority(item),
            rank_score_fn(item),
            len(item.matched_rules),
        ),
        reverse=True,
    )
    selected_formal = _rank_with_sector_balance(
        ranked_formal,
        limit=effective_limit,
        score_fn=rank_score_fn,
    )
    selected_symbols = {item.symbol for item in selected_formal}
    remaining_slots = max(0, effective_limit - len(selected_formal))
    ranked_observation = [
        item
        for item in sorted(
            observation_candidates,
            key=lambda item: (
                _sector_first_priority(item),
                rank_score_fn(item),
            ),
            reverse=True,
        )
        if item.symbol not in selected_symbols
    ]
    selected_observation = _rank_with_sector_balance(
        ranked_observation,
        limit=remaining_slots,
        score_fn=rank_score_fn,
        max_per_sector=1
        if market_regime.regime in {"weak_trend", "panic", "rebound_unconfirmed"}
        else None,
    )
    action_symbols = {item.symbol for item in [*selected_formal, *selected_observation]}
    exploration_limit = max(requested_limit, effective_limit)
    remaining_exploration_slots = max(
        0,
        exploration_limit - len(selected_formal) - len(selected_observation),
    )
    ranked_exploration = [
        item
        for item in sorted(
            exploration_candidates,
            key=lambda item: (
                _sector_first_priority(item),
                item.score,
                item.route_score or 0.0,
            ),
            reverse=True,
        )
        if item.symbol not in action_symbols
    ]
    selected_exploration = _rank_with_sector_balance(
        ranked_exploration,
        limit=remaining_exploration_slots,
        score_fn=lambda item: item.score,
    )
    already_selected = [*selected_formal, *selected_observation, *selected_exploration]
    already_selected_symbols = {item.symbol for item in already_selected}
    already_selected_sectors = {_candidate_sector_key(item) for item in already_selected}
    potential_watch_limit = min(CANDIDATE_POTENTIAL_LIMIT, max(1, requested_limit // 3))
    ranked_potential = [
        item
        for item in sorted(
            potential_candidates,
            key=lambda item: (
                _is_fresh_potential_watch_candidate(item),
                _candidate_sector_key(item) not in already_selected_sectors,
                _potential_watch_rank_score(item),
                item.route_score or 0.0,
            ),
            reverse=True,
        )
        if item.symbol not in already_selected_symbols
    ]
    selected_potential = _rank_with_sector_balance(
        ranked_potential,
        limit=potential_watch_limit,
        score_fn=_potential_watch_rank_score,
    )
    final_score_fn = rank_score_fn
    selected = sorted(
        selected_formal + selected_observation + selected_potential + selected_exploration,
        key=lambda item: (
            {
                "formal_strategy": 3,
                "observation": 2,
                "potential_watch": 1,
                "exploration": 0,
            }.get(item.selection_mode, 0),
            _sector_first_final_rank_score(item, final_score_fn),
        ),
        reverse=True,
    )
    selected = _surface_fresh_potential_after_crowded_sector(selected)
    sector_groups = _candidate_sector_groups(selected)
    sector_focus = _sector_focus_groups(contexts)
    candidate_diagnostics = _candidate_discovery_diagnostics(
        candidate_count=len(selected),
        requested_limit=limit,
        effective_limit=effective_limit,
        market_regime=market_regime.regime,
        market_regime_snapshot={"emotion_gate": emotion_gate["state"]},
        participation_snapshot=participation_snapshot,
        universe_size=universe_size,
        min_universe_size=min_universe_size,
        sector_groups=sector_groups,
    )
    selected_symbol_set = {item.symbol for item in selected}
    previous_items = list_pool_items(db, pool_name=pool_name)
    today = datetime.utcnow().date()
    stale_auto_items = [
        item
        for item in previous_items
        if item["symbol"] not in selected_symbol_set
        and item["status"] == "active"
        and "manual_focus" not in item["tags"]
        and (
            not selected
            or _hold_until_date(item["tags"]) is None
            or _hold_until_date(item["tags"]) < today
        )
        and (
            "after_close_candidate" in item["tags"]
            or "next_session" in item["tags"]
            or any(str(tag).startswith("rank:") for tag in item["tags"])
        )
    ]

    retired = 0
    now = datetime.utcnow()
    for stale in stale_auto_items:
        item = db.execute(
            select(ResearchPoolItem)
            .where(ResearchPoolItem.pool_name == pool_name)
            .where(ResearchPoolItem.symbol == stale["symbol"])
        ).scalar_one_or_none()
        if item is None:
            continue
        current_tags = (item.tags_json or {}).get("tags", [])
        next_keep = _watch_keep_count(current_tags) + 1
        retire_after = _retire_after_count(current_tags)
        cleaned_tags = [
            tag
            for tag in current_tags
            if not any(str(tag).startswith(prefix) for prefix in CANDIDATE_TAG_PREFIXES)
        ]
        cleaned_tags.extend(
            [f"watch_keep:{next_keep}", f"dropped:{effective_feature_date.isoformat()}"]
        )
        item.tags_json = {"tags": list(dict.fromkeys(cleaned_tags))}
        item.updated_at = now
        if not selected or next_keep >= retire_after:
            item.status = "retired"
            retired += 1
        else:
            item.status = "active"

    written = 0
    candidate_batch_id = datetime.utcnow().isoformat(timespec="seconds")
    for rank, item in enumerate(selected, start=1):
        tags = [
            "after_close_candidate",
            "next_session",
            effective_feature_date.isoformat(),
            f"batch:{candidate_batch_id}",
            f"hold_until:{next_trade_date}",
            f"rank:{rank}",
            f"score:{item.score:.2f}",
        ]
        if item.selected_rule_id:
            tags.append(f"rule:{item.selected_rule_id}")
        if item.selected_strategy_type:
            tags.append(f"strategy:{item.selected_strategy_type}")
        tags.append(f"style:{item.sector_style}")
        tags.append(f"style_horizon:{item.suggested_horizon_days}d")
        hold_style = context_by_symbol[item.symbol].get("holding_style")
        if hold_style:
            tags.append(f"hold_style:{hold_style}")
        tags.append(f"mode:{item.selection_mode}")
        style_gate_reason = style_gate_reasons_by_symbol.get(item.symbol)
        if style_gate_reason:
            tags.append("style_gate:stand_down")
            tags.append(f"style_gate_reason:{style_gate_reason}")
        if item.startup_signal_score is not None:
            tags.append(f"startup_signal_score:{item.startup_signal_score:.1f}")
        if item.startup_signal_label:
            tags.append(f"startup_signal_label:{item.startup_signal_label}")
        for reason in item.startup_signal_reasons[:3]:
            tags.append(f"startup_signal_reason:{reason}")
        if item.selection_mode == "potential_watch" and item.startup_signal_label:
            tags.append("candidate_pool:startup_preheat")
            tags.append(
                "candidate_pool_reason:启动前夜：T-1量价修复但还没确认，"
                "先盯次日承接，不代表买点。"
            )
        written += add_symbols_to_pool(
            db,
            [item.symbol],
            pool_name=pool_name,
            note=_candidate_note(
                context_by_symbol[item.symbol],
                item.matched_rules[0],
                learning_notes=learning_notes_by_symbol.get(item.symbol),
                market_participation_snapshot=participation_snapshot,
            ),
            tags=tags,
            replace_tag_prefixes=CANDIDATE_TAG_PREFIXES,
        )

    return {
        "feature_date": effective_feature_date.isoformat(),
        "requested_feature_date": requested_feature_date,
        "feature_coverage_ratio": feature_coverage_ratio,
        "universe_size": universe_size,
        "requested_limit": limit,
        "effective_limit": effective_limit,
        "include_growth_board": include_growth_board,
        "market_regime": market_regime.regime,
        "market_regime_snapshot": {
            "trade_date": market_regime.trade_date,
            "regime": market_regime.regime,
            "trend_score": market_regime.trend_score,
            "breadth_score": market_regime.breadth_score,
            "emotion_score": market_regime.emotion_score,
            "emotion_gate": emotion_gate["state"],
            "volatility_score": market_regime.volatility_score,
            "risk_level": market_regime.risk_level,
            "market_turn": market_turn,
            **quality_snapshot,
        },
        "emotion_gate": emotion_gate,
        "market_turn": market_turn,
        "market_participation_snapshot": participation_snapshot,
        "universe_warning": (
            ""
            if universe_size >= min_universe_size
            else f"当前本地市场特征宇宙只有 {universe_size} 只股票，候选结果不是全市场扫描。"
        ),
        "candidates": [item.to_dict() for item in selected],
        "sector_groups": sector_groups,
        "sector_focus": sector_focus,
        "candidate_diagnostics": candidate_diagnostics,
        "written": written,
        "retired": retired,
    }
