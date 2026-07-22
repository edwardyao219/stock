from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.engine.intraday.startup_state import (
    STARTUP_LABELS,
    StartupEvidence,
    resolve_startup_state,
)
from services.engine.research_pool.repository import (
    candidate_batch_summary,
    filter_latest_candidate_batch_items,
)
from services.engine.theme.attribution import (
    build_theme_moneyflow_signal,
    load_latest_theme_moneyflow_rows,
)
from services.shared.models import (
    IntradayMarketTurnSnapshot,
    RealtimeQuote,
    ResearchPoolItem,
    SectorFeatureDaily,
    Security,
)
from services.shared.symbols import is_growth_board_symbol

SectorSignal = tuple[str, float, list[str], list[str], list[str]]
AdjustmentSignal = tuple[float, list[str], list[str], list[str]]
MarketStressSignal = tuple[float, list[str], list[str], list[str], dict[str, Any] | None]


@dataclass(frozen=True)
class IntradayCandidate:
    symbol: str
    name: str | None
    sector: str | None
    quote_time: str
    price: float | None
    day_change_pct: float | None
    candidate_rank: int | None
    candidate_score: float | None
    intraday_state: str
    intraday_label: str
    intraday_score: float
    startup_stage: str
    startup_label: str
    startup_score: float
    startup_reason: str
    review_window: str
    review_window_label: str
    sector_signal: str
    sector_signal_label: str
    sector_quality_score: float
    sector_quality_label: str
    selection_tier: str
    selection_tier_label: str
    selection_reason: str
    summary: str
    startup_tracked: bool = False
    startup_confirmation_evidence: list[str] = field(default_factory=list)
    startup_invalidation_reasons: list[str] = field(default_factory=list)
    startup_next_conditions: list[str] = field(default_factory=list)
    theme_signal_label: str | None = None
    theme_signal_reason: str | None = None
    caution_reasons: list[str] = field(default_factory=list)
    support_flags: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


INTRADAY_LABELS = {
    "strong_continuation": "强势延续",
    "gap_down_repair": "低开修复",
    "pullback_repair": "回调修复",
    "balanced": "盘中整理",
    "fresh": "首笔快照",
    "fading": "转弱回落",
    "distribution": "放量分歧",
    "downside": "下压走弱",
}

REVIEW_WINDOW_LABELS = {
    "early_divergence": "早盘分歧",
    "morning": "上午快照",
    "midday": "午间复盘",
    "afternoon": "下午跟踪",
    "late_session": "尾盘前",
    "after_close": "盘后复盘",
}

SECTOR_SIGNAL_LABELS = {
    "strong_sector": "强势板块确认",
    "neutral_sector": "板块中性",
    "weak_sector": "弱板块降权",
    "unknown_sector": "板块数据不足",
}

SECTOR_QUALITY_LABELS = {
    "mainline": "主线板块",
    "strong": "强势板块",
    "neutral": "普通板块",
    "weak": "弱势板块",
    "unknown": "板块数据不足",
}

SELECTION_TIER_LABELS = {
    "formal": "正式候选",
    "watch": "观察确认",
    "defer": "暂缓",
}

SELECTION_TIER_PRIORITY = {
    "formal": 2,
    "watch": 1,
    "defer": 0,
}

DEFAULT_FORMAL_LIMIT = 3
DEFAULT_FORMAL_PER_SECTOR_LIMIT = 2
EARLY_SECTOR_SCAN_MAX_SECTORS = 3
EARLY_SECTOR_SCAN_MAX_SYMBOLS = 40
EARLY_SECTOR_SCAN_SCORE = 58.0


def _to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _available_daily_feature_date(trade_date: date, as_of: datetime | None) -> date:
    if as_of is not None and as_of.date() == trade_date:
        return trade_date - timedelta(days=1)
    return trade_date


def _pct(current: Decimal | None, previous: Decimal | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return float((current / previous - Decimal("1")).quantize(Decimal("0.000001")))


def _range_position(
    price: Decimal | None,
    high: Decimal | None,
    low: Decimal | None,
) -> float | None:
    if price is None or high is None or low is None or high <= low:
        return None
    position = (price - low) / (high - low)
    return float(max(Decimal("0"), min(Decimal("1"), position)).quantize(Decimal("0.000001")))


def _tag_number(tags: list[str], prefix: str, cast):
    for tag in tags:
        if tag.startswith(prefix):
            try:
                return cast(tag.removeprefix(prefix))
            except ValueError:
                return None
    return None


def _tag_text(tags: list[str], prefix: str) -> str | None:
    return next((tag.removeprefix(prefix) for tag in tags if tag.startswith(prefix)), None)


def _candidate_items_source(
    db: Session,
    *,
    pool_name: str,
) -> list[ResearchPoolItem]:
    stmt = (
        select(ResearchPoolItem)
        .where(ResearchPoolItem.pool_name == pool_name)
        .where(ResearchPoolItem.status == "active")
    )
    items = []
    for item in db.execute(stmt).scalars():
        tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
        if "after_close_candidate" in tags or "next_session" in tags or "manual_focus" in tags:
            items.append(item)
    return items


def _candidate_items(
    db: Session,
    *,
    pool_name: str,
) -> list[ResearchPoolItem]:
    return filter_latest_candidate_batch_items(
        _candidate_items_source(db, pool_name=pool_name)
    )


def _latest_quotes(
    db: Session,
    symbols: list[str],
    *,
    trade_date: date,
    as_of: datetime | None = None,
) -> dict[str, RealtimeQuote]:
    if not symbols:
        return {}
    filters = [
        RealtimeQuote.symbol.in_(symbols),
        RealtimeQuote.trade_date == trade_date,
    ]
    if as_of is not None:
        filters.append(RealtimeQuote.quote_time <= as_of)
    latest_times = (
        select(
            RealtimeQuote.symbol.label("symbol"),
            func.max(RealtimeQuote.quote_time).label("quote_time"),
        )
        .where(*filters)
        .group_by(RealtimeQuote.symbol)
        .subquery()
    )
    stmt = select(RealtimeQuote).join(
        latest_times,
        (RealtimeQuote.symbol == latest_times.c.symbol)
        & (RealtimeQuote.quote_time == latest_times.c.quote_time),
    )
    return {item.symbol: item for item in db.execute(stmt).scalars()}


def _previous_quote(db: Session, quote: RealtimeQuote) -> RealtimeQuote | None:
    stmt = (
        select(RealtimeQuote)
        .where(RealtimeQuote.symbol == quote.symbol)
        .where(RealtimeQuote.trade_date == quote.trade_date)
        .where(RealtimeQuote.quote_time < quote.quote_time)
        .order_by(RealtimeQuote.quote_time.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _sector_feature_map(
    db: Session,
    sectors: list[str],
    *,
    trade_date: date,
) -> dict[str, dict[str, Any]]:
    if not sectors:
        return {}
    latest_dates = (
        select(
            SectorFeatureDaily.sector_code.label("sector_code"),
            func.max(SectorFeatureDaily.trade_date).label("trade_date"),
        )
        .where(SectorFeatureDaily.sector_code.in_(sectors))
        .where(SectorFeatureDaily.trade_date <= trade_date)
        .group_by(SectorFeatureDaily.sector_code)
        .subquery()
    )
    stmt = select(SectorFeatureDaily).join(
        latest_dates,
        (SectorFeatureDaily.sector_code == latest_dates.c.sector_code)
        & (SectorFeatureDaily.trade_date == latest_dates.c.trade_date),
    )
    return {row.sector_code: row.features for row in db.execute(stmt).scalars()}


def _feature_float(features: dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    if not features:
        return default
    value = features.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sector_signal(features: dict[str, Any] | None) -> SectorSignal:
    if not features:
        return "unknown_sector", -1.5, [], ["sector_data_missing"], ["板块数据不足，先按个股观察"]

    strength = _feature_float(features, "sector_strength_score", 50.0)
    continuity = _feature_float(features, "sector_trend_continuity_score", 50.0)
    momentum = _feature_float(features, "sector_momentum_score", 50.0)
    breadth = _feature_float(features, "sector_breadth_score", 50.0)
    avg_return_20d = _feature_float(features, "sector_avg_return_20d", 0.0)
    positive_20d_rate = _feature_float(features, "sector_positive_20d_rate", 50.0)
    stock_count = _feature_float(features, "sector_stock_count", 0.0)

    support_flags: list[str] = []
    risk_flags: list[str] = []
    caution_reasons: list[str] = []
    if (
        stock_count >= 5
        and strength >= 68
        and continuity >= 65
        and momentum >= 58
        and breadth >= 52
        and avg_return_20d >= 0.02
        and positive_20d_rate >= 52
    ):
        support_flags.append("sector_mainline_confirmed")
        return "strong_sector", 7.0, support_flags, risk_flags, caution_reasons

    if (
        strength <= 48
        or continuity <= 45
        or momentum <= 45
        or breadth <= 42
        or avg_return_20d <= -0.03
        or positive_20d_rate <= 38
    ):
        risk_flags.append("sector_weak_context")
        caution_reasons.append("板块弱势或持续性不足，个股反抽先降权观察")
        return "weak_sector", -7.0, support_flags, risk_flags, caution_reasons

    return "neutral_sector", 0.0, support_flags, risk_flags, caution_reasons


def _hot_sector_codes(
    db: Session,
    *,
    trade_date: date,
    limit: int = EARLY_SECTOR_SCAN_MAX_SECTORS,
) -> list[str]:
    latest_dates = (
        select(
            SectorFeatureDaily.sector_code.label("sector_code"),
            func.max(SectorFeatureDaily.trade_date).label("trade_date"),
        )
        .where(SectorFeatureDaily.trade_date <= trade_date)
        .group_by(SectorFeatureDaily.sector_code)
        .subquery()
    )
    stmt = select(SectorFeatureDaily).join(
        latest_dates,
        (SectorFeatureDaily.sector_code == latest_dates.c.sector_code)
        & (SectorFeatureDaily.trade_date == latest_dates.c.trade_date),
    )
    strong: list[tuple[float, str]] = []
    observe: list[tuple[float, str]] = []
    for row in db.execute(stmt).scalars():
        features = row.features or {}
        signal, _, _, _, _ = _sector_signal(features)
        strength = _feature_float(features, "sector_strength_score", 50.0)
        continuity = _feature_float(features, "sector_trend_continuity_score", 50.0)
        momentum = _feature_float(features, "sector_momentum_score", 50.0)
        breadth = _feature_float(features, "sector_breadth_score", 50.0)
        avg_return_20d = _feature_float(features, "sector_avg_return_20d", 0.0)
        positive_20d_rate = _feature_float(features, "sector_positive_20d_rate", 50.0)
        score = (
            strength * 0.35
            + continuity * 0.25
            + momentum * 0.20
            + breadth * 0.10
            + positive_20d_rate * 0.10
        )
        if signal == "strong_sector":
            strong.append((score, row.sector_code))
            continue
        observe_trend = (
            strength >= 60
            and continuity >= 55
            and momentum >= 55
            and breadth >= 50
            and avg_return_20d >= 0.03
            and positive_20d_rate >= 50
        )
        durable_month_hot = (
            strength >= 56
            and continuity >= 55
            and avg_return_20d >= 0.08
            and positive_20d_rate >= 60
        )
        if observe_trend or durable_month_hot:
            observe.append((score, row.sector_code))
    scored = strong or observe
    return [sector for _, sector in sorted(scored, reverse=True)[:limit]]


def _intraday_leading_sector_codes(
    db: Session,
    *,
    trade_date: date,
    as_of: datetime | None = None,
    limit: int = EARLY_SECTOR_SCAN_MAX_SECTORS,
) -> list[str]:
    snapshot_stmt = (
        select(IntradayMarketTurnSnapshot)
        .where(IntradayMarketTurnSnapshot.trade_date == trade_date)
        .order_by(IntradayMarketTurnSnapshot.snapshot_time.desc())
        .limit(1)
    )
    if as_of is not None:
        snapshot_stmt = snapshot_stmt.where(IntradayMarketTurnSnapshot.snapshot_time <= as_of)
    snapshot = db.execute(snapshot_stmt).scalar_one_or_none()
    state = snapshot.state_json or {} if snapshot is not None else {}
    if not state.get("data_ready"):
        return []
    return [
        str(item.get("sector") or "").strip()
        for item in state.get("leading_sustained_sectors") or []
        if isinstance(item, dict) and str(item.get("sector") or "").strip()
    ][:limit]


def _scan_sector_codes(
    db: Session,
    *,
    trade_date: date,
    as_of: datetime | None = None,
    limit: int = EARLY_SECTOR_SCAN_MAX_SECTORS,
) -> list[str]:
    sectors = _intraday_leading_sector_codes(
        db,
        trade_date=trade_date,
        as_of=as_of,
        limit=limit,
    )
    daily_feature_date = _available_daily_feature_date(trade_date, as_of)
    for sector in _hot_sector_codes(db, trade_date=daily_feature_date, limit=limit):
        if sector not in sectors:
            sectors.append(sector)
    return sectors[:limit]


def _round_robin_sector_values(
    by_sector: dict[str, list[Any]],
    sectors: list[str],
    limit: int,
) -> list[Any]:
    result = []
    max_sector_size = max((len(by_sector[sector]) for sector in sectors), default=0)
    for index in range(max_sector_size):
        for sector in sectors:
            if index < len(by_sector[sector]):
                result.append(by_sector[sector][index])
                if len(result) >= limit:
                    return result
    return result


def early_sector_scan_symbols(
    db: Session,
    *,
    trade_date: date,
    as_of: datetime | None = None,
    include_growth_board: bool = False,
    limit: int = EARLY_SECTOR_SCAN_MAX_SYMBOLS,
) -> list[str]:
    if limit <= 0:
        return []
    scan_sectors = _scan_sector_codes(db, trade_date=trade_date, as_of=as_of)
    if not scan_sectors:
        return []

    stmt = (
        select(Security.symbol, Security.industry)
        .where(Security.industry.in_(scan_sectors))
        .where(Security.is_active.is_(True))
        .where(Security.is_st.is_(False))
        .order_by(Security.symbol.asc())
    )
    if not include_growth_board:
        stmt = (
            stmt.where(~Security.symbol.startswith("300"))
            .where(~Security.symbol.startswith("301"))
            .where(~Security.symbol.startswith("688"))
        )
    by_sector: dict[str, list[str]] = {sector: [] for sector in scan_sectors}
    for symbol, sector in db.execute(stmt):
        by_sector[sector].append(symbol)
    return _round_robin_sector_values(by_sector, scan_sectors, limit)


def _sector_quality(features: dict[str, Any] | None, signal: str) -> tuple[float, str]:
    if not features:
        return 0.0, SECTOR_QUALITY_LABELS["unknown"]

    strength = _feature_float(features, "sector_strength_score", 50.0)
    continuity = _feature_float(features, "sector_trend_continuity_score", 50.0)
    momentum = _feature_float(features, "sector_momentum_score", 50.0)
    breadth = _feature_float(features, "sector_breadth_score", 50.0)
    avg_return_20d = _feature_float(features, "sector_avg_return_20d", 0.0)
    positive_20d_rate = _feature_float(features, "sector_positive_20d_rate", 50.0)

    return_component = max(-10.0, min(20.0, avg_return_20d * 100.0))
    score = (
        strength * 0.28
        + continuity * 0.24
        + momentum * 0.18
        + breadth * 0.12
        + positive_20d_rate * 0.10
        + return_component * 0.08
    )
    if signal == "strong_sector":
        score += 8.0
    elif signal == "weak_sector":
        score -= 12.0

    score = round(max(0.0, min(100.0, score)), 4)
    if signal == "weak_sector" or score < 48:
        label_key = "weak"
    elif score >= 76:
        label_key = "mainline"
    elif score >= 64:
        label_key = "strong"
    else:
        label_key = "neutral"
    return score, SECTOR_QUALITY_LABELS[label_key]


def _volume_signal(
    quote: RealtimeQuote,
    previous: RealtimeQuote | None,
    state: str,
) -> AdjustmentSignal:
    if previous is None or quote.volume is None or previous.volume is None:
        return 0.0, [], [], []
    current_volume = Decimal(str(quote.volume))
    previous_volume = Decimal(str(previous.volume))
    if current_volume <= previous_volume or previous_volume <= 0:
        return 0.0, [], [], []
    volume_ratio = current_volume / previous_volume
    if volume_ratio < Decimal("1.8"):
        return 0.0, [], [], []
    if state in {"strong_continuation", "gap_down_repair", "pullback_repair"}:
        return 3.0, ["intraday_volume_confirmed"], [], []
    if state in {"distribution", "fading", "downside"}:
        return -5.0, [], ["volume_expansion_on_weakness"], ["放量回落，先看承接是否恢复"]
    return 0.0, [], [], []


def _startup_signal(
    quote: RealtimeQuote,
    previous: RealtimeQuote | None,
    *,
    state: str,
    volume_confirmed: bool,
) -> tuple[str, str, float, str, list[str], list[str], list[str]]:
    day_change = _pct(quote.price, quote.pre_close)
    previous_day_change = _pct(
        previous.price if previous else None,
        previous.pre_close if previous else None,
    )
    snapshot_change = _pct(quote.price, previous.price if previous else None)
    range_position = _range_position(quote.price, quote.high, quote.low)

    if day_change is not None and day_change >= 0.085:
        return (
            "invalidated",
            STARTUP_LABELS["invalidated"],
            25.0,
            f"当日已上涨{day_change:.2%}，属于启动后的高位段，不再按早启动排序",
            [],
            ["intraday_overextended"],
            ["当日涨幅偏高，启动后的追高风险上升"],
        )
    if (
        previous_day_change is not None
        and previous_day_change <= 0.015
        and day_change is not None
        and 0.015 <= day_change <= 0.05
        and snapshot_change is not None
        and snapshot_change >= 0.006
        and range_position is not None
        and range_position >= 0.65
        and volume_confirmed
    ):
        return (
            "probing",
            STARTUP_LABELS["probing"],
            92.0,
            (
                f"前一快照涨幅{previous_day_change:.2%}，最新升至{day_change:.2%}，"
                "价格靠近日内高位且量能确认"
            ),
            ["intraday_fresh_start"],
            [],
            [],
        )
    if (
        day_change is not None
        and 0.025 <= day_change <= 0.075
        and snapshot_change is not None
        and snapshot_change >= 0.01
        and range_position is not None
        and range_position >= 0.65
        and volume_confirmed
    ):
        return (
            "probing",
            STARTUP_LABELS["probing"],
            82.0,
            f"最新快照继续上涨{snapshot_change:.2%}，价格与量能同步加速",
            ["intraday_accelerating"],
            [],
            [],
        )
    if state in {"gap_down_repair", "pullback_repair"}:
        return (
            "preheat",
            STARTUP_LABELS["preheat"],
            60.0,
            "当前属于回落后的修复，尚未形成新的启动确认",
            [],
            [],
            [],
        )
    return (
        "preheat",
        STARTUP_LABELS["preheat"],
        45.0,
        "尚未同时出现价格抬升、日内高位和量能确认",
        [],
        [],
        [],
    )


def _sector_feedback_signal(
    sector: str | None,
    sector_feedback: dict[str, dict[str, int]] | None,
) -> AdjustmentSignal:
    if not sector or not sector_feedback:
        return 0.0, [], [], []
    feedback = sector_feedback.get(sector)
    if not feedback:
        return 0.0, [], [], []
    weakened = int(feedback.get("weakened_count", 0) or 0)
    held = int(feedback.get("held_strength_count", 0) or 0)
    repaired = int(feedback.get("repaired_count", 0) or 0)
    if weakened >= 3 and weakened > held + repaired:
        return (
            -4.0,
            [],
            ["sector_feedback_intraday_weakened"],
            ["板块近几日盘中转弱偏多，追高先降权"],
        )
    if held >= 3 and held >= weakened * 2:
        return 2.5, ["sector_feedback_strength_holding"], [], []
    if repaired >= 3 and weakened <= repaired:
        return 1.5, ["sector_feedback_repairing"], [], []
    return 0.0, [], [], []


def _classify_intraday_state(
    quote: RealtimeQuote,
    previous: RealtimeQuote | None,
) -> tuple[str, list[str], list[str]]:
    session_change = _pct(quote.price, quote.pre_close)
    open_gap = _pct(quote.open, quote.pre_close)
    change_from_open = _pct(quote.price, quote.open)
    price_change_from_prev = _pct(quote.price, previous.price if previous else None)
    range_position = _range_position(quote.price, quote.high, quote.low)
    high_gain = _pct(quote.high, quote.pre_close)
    pullback_from_high = _pct(quote.high, quote.price)

    state = "balanced"
    if previous is None:
        state = "fresh"
    if session_change is not None and session_change <= -0.015:
        state = "downside"
    if (
        high_gain is not None
        and high_gain >= 0.06
        and session_change is not None
        and session_change <= 0
    ):
        state = "distribution"
    elif (
        high_gain is not None
        and high_gain >= 0.06
        and pullback_from_high is not None
        and pullback_from_high >= 0.045
    ):
        state = "distribution"
    elif (
        price_change_from_prev is not None
        and price_change_from_prev < 0
        and range_position is not None
        and range_position <= 0.35
    ):
        state = "fading"
    elif (
        open_gap is not None
        and open_gap <= -0.015
        and change_from_open is not None
        and change_from_open >= 0.018
        and session_change is not None
        and session_change >= -0.003
        and range_position is not None
        and range_position >= 0.65
    ):
        state = "gap_down_repair"
    elif (
        price_change_from_prev is not None
        and price_change_from_prev >= 0
        and range_position is not None
        and range_position >= 0.65
    ):
        state = "strong_continuation"
    elif (
        previous is None
        and session_change is not None
        and session_change >= 0.03
        and high_gain is not None
        and high_gain >= 0.04
        and range_position is not None
        and range_position >= 0.65
    ):
        state = "strong_continuation"
    elif (
        pullback_from_high is not None
        and 0.015 <= pullback_from_high <= 0.07
        and range_position is not None
        and range_position >= 0.35
    ):
        state = "pullback_repair"

    support_flags: list[str] = []
    risk_flags: list[str] = []
    if state == "gap_down_repair":
        support_flags.append("intraday_gap_down_repair")
    elif state == "strong_continuation":
        support_flags.append("intraday_strength_continuation")
    elif state == "pullback_repair":
        support_flags.append("intraday_pullback_repair")
    elif state == "distribution":
        risk_flags.append("intraday_distribution")
    elif state == "fading":
        risk_flags.append("intraday_strength_fading")
    elif state == "downside":
        risk_flags.append("intraday_downside_pressure")
    return state, support_flags, risk_flags


def _intraday_score(
    *,
    candidate_rank: int | None,
    candidate_score: float | None,
    state: str,
    day_change_pct: float | None,
    sector_score_delta: float = 0.0,
) -> float:
    score = candidate_score if candidate_score is not None else 60.0
    if candidate_rank is not None:
        score += max(0.0, 8.0 - min(candidate_rank, 8))
    score += {
        "gap_down_repair": 8.0,
        "strong_continuation": 6.0,
        "pullback_repair": 4.0,
        "balanced": 0.0,
        "fresh": -1.0,
        "fading": -6.0,
        "distribution": -10.0,
        "downside": -12.0,
    }.get(state, 0.0)
    if day_change_pct is not None:
        if -0.015 <= day_change_pct <= 0.055:
            score += 2.0
        elif day_change_pct >= 0.085:
            score -= 3.0
    score += sector_score_delta
    return round(max(0.0, min(100.0, score)), 4)


def _review_window(quote: RealtimeQuote) -> str:
    clock = quote.quote_time.time()
    if clock.hour >= 15:
        return "after_close"
    if clock.hour == 9 and 15 <= clock.minute <= 50:
        return "early_divergence"
    if clock.hour < 11 or (clock.hour == 11 and clock.minute < 15):
        return "morning"
    if clock.hour < 13:
        return "midday"
    if clock.hour > 14 or (clock.hour == 14 and clock.minute >= 30):
        return "late_session"
    return "afternoon"


def _is_early_divergence_time(value: datetime | None) -> bool:
    if value is None:
        return False
    clock = value.time()
    return clock.hour == 9 and 15 <= clock.minute <= 50


def _early_sector_scan_items(
    db: Session,
    *,
    trade_date: date,
    pool_name: str,
    as_of: datetime | None,
    existing_symbols: set[str],
    include_growth_board: bool,
) -> list[ResearchPoolItem]:
    intraday_leading_sector_codes = _intraday_leading_sector_codes(
        db,
        trade_date=trade_date,
        as_of=as_of,
    )
    is_early_scan = _is_early_divergence_time(as_of)
    if not is_early_scan and not intraday_leading_sector_codes:
        return []

    scan_sectors = (
        _scan_sector_codes(db, trade_date=trade_date, as_of=as_of)
        if is_early_scan
        else intraday_leading_sector_codes
    )
    if not scan_sectors:
        return []
    intraday_leading_sectors = set(intraday_leading_sector_codes)

    latest_times = (
        select(
            RealtimeQuote.symbol.label("symbol"),
            func.max(RealtimeQuote.quote_time).label("quote_time"),
        )
        .where(RealtimeQuote.trade_date == trade_date)
        .where(RealtimeQuote.quote_time <= as_of)
        .group_by(RealtimeQuote.symbol)
        .subquery()
    )
    stmt = (
        select(Security)
        .join(latest_times, Security.symbol == latest_times.c.symbol)
        .join(
            RealtimeQuote,
            (RealtimeQuote.symbol == latest_times.c.symbol)
            & (RealtimeQuote.quote_time == latest_times.c.quote_time),
        )
        .where(Security.industry.in_(scan_sectors))
        .where(Security.is_active.is_(True))
        .where(Security.is_st.is_(False))
        .where(RealtimeQuote.price > 0)
        .where(RealtimeQuote.pre_close > 0)
        .order_by(RealtimeQuote.amount.desc())
    )

    items: list[ResearchPoolItem] = []
    by_sector: dict[str, list[Security]] = {sector: [] for sector in scan_sectors}
    for security in db.execute(stmt).scalars():
        if security.symbol in existing_symbols:
            continue
        if not include_growth_board and is_growth_board_symbol(security.symbol):
            continue
        by_sector[security.industry].append(security)
    for security in _round_robin_sector_values(
        by_sector,
        scan_sectors,
        EARLY_SECTOR_SCAN_MAX_SYMBOLS,
    ):
        tags = [
            "early_sector_scan",
            "mode:potential_watch",
            "rank:99",
            f"score:{EARLY_SECTOR_SCAN_SCORE}",
        ]
        if security.industry in intraday_leading_sectors:
            tags.append("intraday_leading_sector_scan")
        items.append(
            ResearchPoolItem(
                pool_name=pool_name,
                symbol=security.symbol,
                note=f"早盘热门板块扩展扫描：{security.industry}",
                tags_json={"tags": tags},
                status="active",
            )
        )
    return items


def _caution_reasons(
    *,
    quote: RealtimeQuote,
    state: str,
    review_window: str,
    sector_cautions: list[str],
) -> list[str]:
    reasons = list(sector_cautions)
    session_change = _pct(quote.price, quote.pre_close)
    range_position = _range_position(quote.price, quote.high, quote.low)
    pullback_from_high = _pct(quote.high, quote.price)

    if review_window == "midday" and state in {"balanced", "fresh", "pullback_repair"}:
        reasons.append("午间先看上午承接，下午放量站稳再加入正式列表")
    if review_window == "early_divergence":
        reasons.append("早盘分歧期只做观察确认，不追高，等9:45后承接稳定")
    if review_window == "late_session" and state in {"distribution", "fading", "downside"}:
        reasons.append("尾盘前不追回落，等盘后确认资金是否撤退")
    if state == "distribution":
        reasons.append("冲高回落幅度偏大，疑似放量分歧")
    elif state == "fading":
        reasons.append("最新快照转弱且靠近日内低位")
    elif state == "downside":
        reasons.append("跌幅扩大，短线承接不足")
    if session_change is not None and session_change >= 0.085:
        reasons.append("当日涨幅偏高，追高性价比下降")
    if pullback_from_high is not None and pullback_from_high >= 0.045:
        reasons.append("距离日内高点回撤较深")
    if range_position is not None and range_position <= 0.25:
        reasons.append("价格处在日内低位，先等修复")

    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def _market_stress_signal(market_stress: dict[str, Any] | None) -> MarketStressSignal:
    if not market_stress:
        return 0.0, [], [], [], None

    status = str(market_stress.get("stress_status") or "neutral")
    recovery_stage = str(market_stress.get("recovery_stage") or "normal")
    label = str(market_stress.get("stress_label") or "中性")
    action = str(market_stress.get("risk_action_label") or "")
    raw_reasons = market_stress.get("stress_reasons") or []
    reasons = [str(reason) for reason in raw_reasons if str(reason).strip()]
    first_reason = reasons[0] if reasons else "市场压力信号不明确"
    payload = {
        "trade_date": market_stress.get("trade_date"),
        "snapshot_scope_label": market_stress.get("snapshot_scope_label"),
        "stress_status": status,
        "stress_label": label,
        "stress_score": market_stress.get("stress_score"),
        "risk_action_label": action,
        "stress_reasons": reasons,
        "recovery_stage": recovery_stage,
        "recovery_snapshot_count": market_stress.get("recovery_snapshot_count", 0),
        "recovery_required_count": market_stress.get("recovery_required_count", 0),
    }

    if status == "risk_off":
        caution = f"全市场压力大，{action or '停止扩散，只做观察和风控'}；{first_reason}"
        return -12.0, [], ["market_risk_off"], [caution], payload
    if status == "caution":
        caution = f"全市场偏谨慎，{action or '降低频率，等盘中确认'}；{first_reason}"
        if recovery_stage == "limited":
            return -5.0, [], [], [caution], payload
        return -5.0, [], ["market_caution"], [caution], payload
    if status == "supportive":
        return 2.0, ["market_supportive"], [], [], payload
    return 0.0, [], [], [], payload


def _selection_tier(
    *,
    state: str,
    review_window: str,
    sector_signal: str,
    support_flags: list[str],
    risk_flags: list[str],
    caution_reasons: list[str],
    intraday_score: float,
) -> tuple[str, str, str]:
    hard_risks = {
        "intraday_distribution",
        "intraday_strength_fading",
        "intraday_downside_pressure",
        "volume_expansion_on_weakness",
        "sector_feedback_intraday_weakened",
        "intraday_overextended",
    }
    if hard_risks.intersection(risk_flags):
        reason = caution_reasons[0] if caution_reasons else "盘中转弱，先暂缓追入"
        return "defer", SELECTION_TIER_LABELS["defer"], reason

    supportive_state = state in {"strong_continuation", "gap_down_repair"}
    weak_sector_watch_context = (
        sector_signal == "weak_sector"
        and supportive_state
        and (
            "candidate_potential_watch" in support_flags
            or "candidate_manual_focus" in support_flags
        )
        and intraday_score >= 50
    )
    if weak_sector_watch_context:
        context_label = "手动关注" if "candidate_manual_focus" in support_flags else "潜力观察"
        return (
            "watch",
            SELECTION_TIER_LABELS["watch"],
            f"{context_label}盘中走强，但板块未确认且板块弱势，只做观察确认不追高",
        )

    theme_watch_context = (
        sector_signal == "weak_sector"
        and state in {"strong_continuation", "gap_down_repair", "pullback_repair"}
        and "theme_moneyflow_supported" in support_flags
        and (
            "candidate_potential_watch" in support_flags
            or "candidate_manual_focus" in support_flags
        )
        and intraday_score >= 50
    )
    if theme_watch_context:
        return (
            "watch",
            SELECTION_TIER_LABELS["watch"],
            "主题资金有支撑但行业板块未确认，只做观察确认不追高",
        )

    if sector_signal == "weak_sector":
        reason = caution_reasons[0] if caution_reasons else "板块弱势或盘中转弱，先暂缓追入"
        if sector_signal == "weak_sector" and "板块弱势" not in reason:
            reason = f"板块弱势，{reason}"
        return "defer", SELECTION_TIER_LABELS["defer"], reason

    if "market_risk_off" in risk_flags:
        reason = caution_reasons[0] if caution_reasons else "全市场压力大，停止扩散，只做观察"
        return "watch", SELECTION_TIER_LABELS["watch"], reason

    if review_window == "early_divergence":
        if "sector_hot_pool_scan" in support_flags:
            return (
                "watch",
                SELECTION_TIER_LABELS["watch"],
                "热门板块早盘扩展扫描，只做观察确认不追高",
            )
        reason = caution_reasons[0] if caution_reasons else "早盘分歧期先整体扫描，只做观察确认"
        return "watch", SELECTION_TIER_LABELS["watch"], reason

    volume_confirmed = "intraday_volume_confirmed" in support_flags
    sector_confirmed = sector_signal == "strong_sector"
    no_risk = not risk_flags
    if (
        sector_confirmed
        and supportive_state
        and no_risk
        and intraday_score >= 82
        and (volume_confirmed or "sector_feedback_strength_holding" in support_flags)
    ):
        reason = "强势板块同步，盘中趋势与量能确认，可列入正式候选"
        if state == "gap_down_repair":
            reason = "强势板块同步，低开修复且量能确认，可列入正式候选"
        return "formal", SELECTION_TIER_LABELS["formal"], reason

    if state in {"pullback_repair", "balanced", "fresh"} or review_window in {
        "midday",
        "afternoon",
    }:
        reason = caution_reasons[0] if caution_reasons else "走势尚需确认，先放观察池等承接"
        if "确认" not in reason:
            reason = f"{reason}，暂列观察确认"
        return "watch", SELECTION_TIER_LABELS["watch"], reason

    if sector_signal in {"neutral_sector", "unknown_sector"}:
        reason = caution_reasons[0] if caution_reasons else "板块确认度不足，先观察不追"
        return "watch", SELECTION_TIER_LABELS["watch"], reason

    return "watch", SELECTION_TIER_LABELS["watch"], "信号未完全共振，先观察确认"


def _summary(
    quote: RealtimeQuote,
    state: str,
    *,
    review_window: str,
    sector_signal: str,
) -> str:
    parts = [
        REVIEW_WINDOW_LABELS.get(review_window, "盘中快照"),
        INTRADAY_LABELS.get(state, "盘中快照"),
        SECTOR_SIGNAL_LABELS.get(sector_signal, "板块数据不足"),
    ]
    session_change = _pct(quote.price, quote.pre_close)
    open_gap = _pct(quote.open, quote.pre_close)
    range_position = _range_position(quote.price, quote.high, quote.low)
    if session_change is not None:
        parts.append(f"相对昨收{session_change:+.2%}")
    if open_gap is not None:
        parts.append(f"开盘缺口{open_gap:+.2%}")
    if range_position is not None:
        parts.append(f"日内位置{range_position:.0%}")
    return "，".join(parts)


def _theme_signal_text(
    *,
    theme_name: str | None,
    pct_change: float | None,
    net_amount_rate: float | None,
) -> tuple[str | None, str | None]:
    if not theme_name:
        return None, None

    metrics: list[str] = []
    if pct_change is not None:
        metrics.append(f"涨幅{pct_change:.2f}%")
    if net_amount_rate is not None:
        metrics.append(f"净流入率{net_amount_rate:.2f}%")
    metric_text = f"（{'，'.join(metrics)}）" if metrics else ""
    return (
        "主题资金支撑",
        f"{theme_name}主题资金有支撑{metric_text}，只作为观察支撑，不单独触发买入",
    )


def _ordered_candidates(candidates: list[IntradayCandidate]) -> list[IntradayCandidate]:
    def leading_sector_rank(item: IntradayCandidate) -> int:
        return _tag_number(item.support_flags, "intraday_leading_sector_rank:", int) or 999

    return sorted(
        candidates,
        key=lambda item: (
            item.selection_tier != "defer",
            leading_sector_rank(item) < 999,
            -leading_sector_rank(item),
            SELECTION_TIER_PRIORITY.get(item.selection_tier, 0),
            item.startup_score,
            item.sector_quality_score,
            item.intraday_score,
            -(item.candidate_rank or 999),
            item.day_change_pct or -99,
        ),
        reverse=True,
    )


def _downgrade_formal_candidate(item: IntradayCandidate, reason: str) -> IntradayCandidate:
    caution_reasons = list(item.caution_reasons)
    if reason not in caution_reasons:
        caution_reasons.insert(0, reason)
    return replace(
        item,
        selection_tier="watch",
        selection_tier_label=SELECTION_TIER_LABELS["watch"],
        selection_reason=reason,
        caution_reasons=caution_reasons,
    )


def _apply_formal_limits(
    candidates: list[IntradayCandidate],
    *,
    formal_limit: int,
    formal_per_sector_limit: int,
) -> list[IntradayCandidate]:
    if formal_limit <= 0:
        formal_limit = 1
    if formal_per_sector_limit <= 0:
        formal_per_sector_limit = 1

    selected_formal = 0
    formal_by_sector: dict[str, int] = {}
    limited: list[IntradayCandidate] = []
    for item in _ordered_candidates(candidates):
        if item.selection_tier != "formal":
            limited.append(item)
            continue

        sector_key = item.sector or "未分类"
        sector_count = formal_by_sector.get(sector_key, 0)
        if selected_formal >= formal_limit:
            limited.append(
                _downgrade_formal_candidate(
                    item,
                    f"正式名额收敛到{formal_limit}只，先放观察池等下一次确认",
                )
            )
            continue
        if sector_count >= formal_per_sector_limit:
            limited.append(
                _downgrade_formal_candidate(
                    item,
                    f"同板块正式名额已达{formal_per_sector_limit}只，避免集中押注，先观察",
                )
            )
            continue

        formal_by_sector[sector_key] = sector_count + 1
        selected_formal += 1
        limited.append(item)
    return limited


def _soft_display_sector_cap(limit: int) -> int:
    return max(2, min(4, (max(1, limit) + 4) // 5))


def _candidate_sector_distribution(
    candidates: list[IntradayCandidate],
    displayed: list[IntradayCandidate],
) -> dict[str, object]:
    counts = Counter(item.sector or "未分类" for item in displayed)
    displayed_count = len(displayed)
    return {
        "eligible_count": len(candidates),
        "displayed_count": displayed_count,
        "sector_count": len(counts),
        "top_sectors": [
            {
                "sector": sector,
                "count": count,
                "ratio": round(count / displayed_count, 6) if displayed_count else 0.0,
            }
            for sector, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ],
    }


def _select_display_candidates(
    candidates: list[IntradayCandidate],
    *,
    limit: int,
) -> list[IntradayCandidate]:
    ordered = _ordered_candidates(candidates)
    limit = max(1, limit)
    selected: list[IntradayCandidate] = []
    selected_symbols: set[str] = set()
    sector_counts: dict[str, int] = {}

    def add(item: IntradayCandidate) -> None:
        selected.append(item)
        selected_symbols.add(item.symbol)
        sector_key = item.sector or "未分类"
        sector_counts[sector_key] = sector_counts.get(sector_key, 0) + 1

    sector_cap = _soft_display_sector_cap(limit)
    overflow: list[IntradayCandidate] = []
    for item in ordered:
        if item.symbol in selected_symbols:
            continue
        sector_key = item.sector or "未分类"
        if (
            item.selection_tier != "formal"
            and sector_counts.get(sector_key, 0) >= sector_cap
        ):
            overflow.append(item)
            continue
        add(item)
        if len(selected) >= limit:
            return selected

    for item in overflow:
        if item.symbol in selected_symbols:
            continue
        add(item)
        if len(selected) >= limit:
            return selected
    return selected


def discover_intraday_candidates(
    db: Session,
    *,
    trade_date: date,
    pool_name: str = "experiment",
    limit: int = 15,
    formal_limit: int = DEFAULT_FORMAL_LIMIT,
    formal_per_sector_limit: int = DEFAULT_FORMAL_PER_SECTOR_LIMIT,
    include_growth_board: bool = False,
    as_of: datetime | None = None,
    sector_feedback: dict[str, dict[str, int]] | None = None,
    market_stress: dict[str, Any] | None = None,
    sustained_startup_sectors: set[str] | None = None,
) -> dict[str, Any]:
    intraday_leading_sectors = _intraday_leading_sector_codes(
        db,
        trade_date=trade_date,
        as_of=as_of,
    )
    intraday_leading_ranks = {
        sector: index for index, sector in enumerate(intraday_leading_sectors, start=1)
    }
    source_pool_items = _candidate_items_source(db, pool_name=pool_name)
    candidate_batch = candidate_batch_summary(source_pool_items)
    pool_items = filter_latest_candidate_batch_items(source_pool_items)
    pool_items = [
        *pool_items,
        *_early_sector_scan_items(
            db,
            trade_date=trade_date,
            pool_name=pool_name,
            as_of=as_of,
            existing_symbols={item.symbol for item in pool_items},
            include_growth_board=include_growth_board,
        ),
    ]
    symbols = [item.symbol for item in pool_items]
    securities = {
        item.symbol: item
        for item in db.execute(select(Security).where(Security.symbol.in_(symbols))).scalars()
    }
    daily_feature_date = _available_daily_feature_date(trade_date, as_of)
    sector_features = _sector_feature_map(
        db,
        sorted({security.industry for security in securities.values() if security.industry}),
        trade_date=daily_feature_date,
    )
    theme_moneyflow_rows = load_latest_theme_moneyflow_rows(
        db,
        trade_date=daily_feature_date,
    )
    latest_quotes = _latest_quotes(db, symbols, trade_date=trade_date, as_of=as_of)
    (
        market_stress_delta,
        market_stress_support,
        market_stress_risks,
        market_stress_cautions,
        market_stress_payload,
    ) = _market_stress_signal(market_stress)
    candidates: list[IntradayCandidate] = []
    for item in pool_items:
        if not include_growth_board and is_growth_board_symbol(item.symbol):
            continue
        quote = latest_quotes.get(item.symbol)
        if quote is None:
            continue
        if (
            quote.price is None
            or quote.price <= 0
            or quote.pre_close is None
            or quote.pre_close <= 0
        ):
            continue
        tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
        rank = _tag_number(tags, "rank:", int)
        candidate_score = _tag_number(tags, "score:", float)
        previous = _previous_quote(db, quote)
        state, support_flags, risk_flags = _classify_intraday_state(quote, previous)
        if "manual_focus" in tags:
            support_flags.append("candidate_manual_focus")
        if "mode:potential_watch" in tags:
            support_flags.append("candidate_potential_watch")
        if "early_sector_scan" in tags:
            support_flags.append("sector_hot_pool_scan")
        if "intraday_leading_sector_scan" in tags:
            support_flags.append("intraday_leading_sector_scan")
        day_change_pct = _pct(quote.price, quote.pre_close)
        security = securities.get(item.symbol)
        leading_sector_rank = intraday_leading_ranks.get(
            security.industry if security else None
        )
        if leading_sector_rank is not None:
            if "intraday_leading_sector_scan" not in support_flags:
                support_flags.append("intraday_leading_sector_scan")
            support_flags.append(f"intraday_leading_sector_rank:{leading_sector_rank}")
        sector_signal, sector_delta, sector_support, sector_risks, sector_cautions = _sector_signal(
            sector_features.get(security.industry) if security and security.industry else None
        )
        support_flags = [*support_flags, *sector_support]
        risk_flags = [*risk_flags, *sector_risks]
        sector_quality_score, sector_quality_label = _sector_quality(
            sector_features.get(security.industry) if security and security.industry else None,
            sector_signal,
        )
        volume_delta, volume_support, volume_risks, volume_cautions = _volume_signal(
            quote,
            previous,
            state,
        )
        (
            startup_stage,
            startup_label,
            startup_score,
            startup_reason,
            startup_support,
            startup_risks,
            startup_cautions,
        ) = _startup_signal(
            quote,
            previous,
            state=state,
            volume_confirmed="intraday_volume_confirmed" in volume_support,
        )
        feedback_delta, feedback_support, feedback_risks, feedback_cautions = (
            _sector_feedback_signal(
                security.industry if security else None,
                sector_feedback,
            )
        )
        support_flags = [
            *support_flags,
            *volume_support,
            *startup_support,
            *feedback_support,
        ]
        risk_flags = [*risk_flags, *volume_risks, *startup_risks, *feedback_risks]
        theme_signal = build_theme_moneyflow_signal(
            tags=tags,
            note=item.note,
            rows=theme_moneyflow_rows,
        )
        theme_signal_label, theme_signal_reason = _theme_signal_text(
            theme_name=theme_signal.theme_name,
            pct_change=theme_signal.pct_change,
            net_amount_rate=theme_signal.net_amount_rate,
        )
        support_flags = [*support_flags, *theme_signal.support_flags]
        risk_flags = [*risk_flags, *theme_signal.risk_flags]
        support_flags = [*support_flags, *market_stress_support]
        risk_flags = [*risk_flags, *market_stress_risks]
        review_window = _review_window(quote)
        caution_reasons = _caution_reasons(
            quote=quote,
            state=state,
            review_window=review_window,
            sector_cautions=[
                *sector_cautions,
                *volume_cautions,
                *startup_cautions,
                *feedback_cautions,
                *theme_signal.caution_reasons,
                *market_stress_cautions,
            ],
        )
        intraday_score = _intraday_score(
            candidate_rank=rank,
            candidate_score=candidate_score,
            state=state,
            day_change_pct=day_change_pct,
            sector_score_delta=(
                sector_delta
                + volume_delta
                + feedback_delta
                + theme_signal.score_delta
                + market_stress_delta
            ),
        )
        selection_tier, selection_tier_label, selection_reason = _selection_tier(
            state=state,
            review_window=review_window,
            sector_signal=sector_signal,
            support_flags=support_flags,
            risk_flags=risk_flags,
            caution_reasons=caution_reasons,
            intraday_score=intraday_score,
        )
        sector_name = security.industry if security else None
        if sustained_startup_sectors is not None:
            if sector_name in sustained_startup_sectors:
                support_flags.append("intraday_sector_startup_sustained")
            elif selection_tier == "formal":
                selection_tier = "watch"
                selection_tier_label = SELECTION_TIER_LABELS["watch"]
                selection_reason = "板块未形成连续扩散，个股即使走强也只做观察确认"
        startup_tracked = "candidate_pool:startup_preheat" in tags
        prior_startup_state = _tag_text(tags, "startup_state:") or startup_stage
        hard_startup_risks = {
            "intraday_distribution",
            "intraday_strength_fading",
            "intraday_downside_pressure",
            "volume_expansion_on_weakness",
            "sector_feedback_intraday_weakened",
            "intraday_overextended",
        }.intersection(risk_flags)
        decision = resolve_startup_state(
            prior_startup_state,
            StartupEvidence(
                trade_date=trade_date,
                as_of=as_of or quote.quote_time,
                individual_supportive=startup_stage == "probing",
                volume_confirmed="intraday_volume_confirmed" in support_flags,
                sector_sustained=(
                    sustained_startup_sectors is not None
                    and sector_name in sustained_startup_sectors
                ),
                sector_strength_holding="sector_feedback_strength_holding" in support_flags,
                formal_eligible=selection_tier == "formal",
                market_risk_off="market_risk_off" in risk_flags,
                hard_risk_reasons=(
                    tuple(caution_reasons[:1] or sorted(hard_startup_risks))
                    if hard_startup_risks
                    else ()
                ),
            ),
        )
        startup_stage = decision.state
        startup_label = decision.label
        if decision.invalidation_reasons:
            startup_reason = "；".join(decision.invalidation_reasons)
        elif decision.confirmation_evidence:
            startup_reason = "；".join(decision.confirmation_evidence)
        if startup_tracked and startup_stage == "invalidated":
            selection_tier = "defer"
            selection_tier_label = SELECTION_TIER_LABELS["defer"]
            selection_reason = startup_reason
        elif startup_tracked and startup_stage != "confirmed" and selection_tier == "formal":
            selection_tier = "watch"
            selection_tier_label = SELECTION_TIER_LABELS["watch"]
            selection_reason = "启动尚未确认，等待板块扩散、个股承接与市场风险阀门共振"
        candidates.append(
            IntradayCandidate(
                symbol=item.symbol,
                name=security.name if security else None,
                sector=security.industry if security else None,
                quote_time=quote.quote_time.isoformat(timespec="seconds"),
                price=_to_float(quote.price),
                day_change_pct=day_change_pct,
                candidate_rank=rank,
                candidate_score=candidate_score,
                intraday_state=state,
                intraday_label=INTRADAY_LABELS.get(state, "盘中快照"),
                intraday_score=intraday_score,
                startup_stage=startup_stage,
                startup_label=startup_label,
                startup_score=startup_score,
                startup_reason=startup_reason,
                review_window=review_window,
                review_window_label=REVIEW_WINDOW_LABELS.get(review_window, "盘中快照"),
                sector_signal=sector_signal,
                sector_signal_label=SECTOR_SIGNAL_LABELS.get(sector_signal, "板块数据不足"),
                sector_quality_score=sector_quality_score,
                sector_quality_label=sector_quality_label,
                selection_tier=selection_tier,
                selection_tier_label=selection_tier_label,
                selection_reason=selection_reason,
                summary=_summary(
                    quote,
                    state,
                    review_window=review_window,
                    sector_signal=sector_signal,
                ),
                startup_tracked=startup_tracked,
                startup_confirmation_evidence=list(decision.confirmation_evidence),
                startup_invalidation_reasons=list(decision.invalidation_reasons),
                startup_next_conditions=list(decision.next_conditions),
                theme_signal_label=theme_signal_label,
                theme_signal_reason=theme_signal_reason,
                caution_reasons=caution_reasons,
                support_flags=support_flags,
                risk_flags=risk_flags,
            )
        )

    if market_stress_payload and market_stress_payload.get("recovery_stage") == "limited":
        formal_limit = min(formal_limit, 1)
    limited_candidates = _apply_formal_limits(
        candidates,
        formal_limit=formal_limit,
        formal_per_sector_limit=formal_per_sector_limit,
    )
    selected = _select_display_candidates(limited_candidates, limit=limit)
    return {
        "trade_date": trade_date.isoformat(),
        "as_of": as_of.isoformat(timespec="seconds") if as_of else None,
        "pool_name": pool_name,
        "candidate_count": len(selected),
        "candidate_batch": candidate_batch,
        "market_stress": market_stress_payload,
        "sector_distribution": _candidate_sector_distribution(limited_candidates, selected),
        "candidates": [item.to_dict() for item in selected],
    }
