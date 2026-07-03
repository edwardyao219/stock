from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.research_pool.repository import filter_latest_candidate_batch_items
from services.shared.models import ResearchPoolItem, TradePlan

HIGH_QUALITY_RANK_MAX = 10
HIGH_QUALITY_CONFIDENCE_MIN = 78.0
HIGH_QUALITY_TREND_MIN = 68.0
HIGH_QUALITY_RELATIVE_MIN = 62.0
HIGH_QUALITY_SECTOR_MIN = 60.0
HIGH_QUALITY_RISK_MAX = 42.0


@dataclass(frozen=True)
class PlanEntryQuality:
    accepted: bool
    candidate_rank: int | None
    candidate_score: float | None
    confidence_score: float | None
    reasons: list[str]

    def detail_text(self) -> str:
        parts: list[str] = []
        if self.candidate_rank is not None:
            parts.append(f"第{self.candidate_rank}名")
        if self.candidate_score is not None:
            parts.append(f"候选{self.candidate_score:.1f}分")
        if self.confidence_score is not None:
            parts.append(f"置信度{self.confidence_score:.1f}")
        return "，".join(parts)


def _float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    return float(value)


def _decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _tag_number(tags: list[str], prefix: str, cast: Any) -> int | float | None:
    for tag in tags:
        if str(tag).startswith(prefix):
            try:
                return cast(str(tag).removeprefix(prefix))
            except ValueError:
                return None
    return None


def _has_candidate_tags(tags: list[str]) -> bool:
    return "after_close_candidate" in tags or "next_session" in tags


def candidate_rank_for_symbol(
    db: Session,
    symbol: str,
    *,
    pool_name: str | None = "experiment",
    feature_date: str | date | None = None,
) -> int | None:
    ranked_items = _candidate_ranked_items(
        db,
        symbol,
        pool_name=pool_name,
        feature_date=feature_date,
    )
    return ranked_items[0][0] if ranked_items else None


def candidate_score_for_symbol(
    db: Session,
    symbol: str,
    *,
    pool_name: str | None = "experiment",
    feature_date: str | date | None = None,
) -> float | None:
    ranked_items = _candidate_ranked_items(
        db,
        symbol,
        pool_name=pool_name,
        feature_date=feature_date,
    )
    return ranked_items[0][1] if ranked_items else None


def _candidate_ranked_items(
    db: Session,
    symbol: str,
    *,
    pool_name: str | None,
    feature_date: str | date | None,
) -> list[tuple[int, float | None]]:
    stmt = (
        select(ResearchPoolItem)
        .where(ResearchPoolItem.status == "active")
    )
    if pool_name:
        stmt = stmt.where(ResearchPoolItem.pool_name == pool_name)

    feature_date_text = feature_date.isoformat() if isinstance(feature_date, date) else feature_date
    ranked: list[tuple[int, float | None]] = []
    pool_items = filter_latest_candidate_batch_items(list(db.execute(stmt).scalars()))
    for item in pool_items:
        if item.symbol != symbol:
            continue
        tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
        if not _has_candidate_tags(tags):
            continue
        if feature_date_text and feature_date_text not in tags:
            continue
        rank = _tag_number(tags, "rank:", int)
        if rank is None:
            continue
        ranked.append((int(rank), _tag_number(tags, "score:", float)))
    return sorted(ranked, key=lambda item: item[0])


def _plan_snapshot(plan: TradePlan) -> dict[str, Any]:
    if not isinstance(plan.entry_condition_json, dict):
        return {}
    snapshot = plan.entry_condition_json.get("snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def evaluate_plan_entry_quality(
    db: Session,
    plan: TradePlan,
    *,
    pool_name: str | None = "experiment",
    feature_date: str | date | None = None,
) -> PlanEntryQuality:
    candidate_rank = candidate_rank_for_symbol(
        db,
        plan.symbol,
        pool_name=pool_name,
        feature_date=feature_date,
    )
    candidate_score = candidate_score_for_symbol(
        db,
        plan.symbol,
        pool_name=pool_name,
        feature_date=feature_date,
    )
    confidence_score = _float(plan.confidence_score)
    reasons: list[str] = []

    if candidate_rank is not None and candidate_rank <= HIGH_QUALITY_RANK_MAX:
        return PlanEntryQuality(
            accepted=True,
            candidate_rank=candidate_rank,
            candidate_score=candidate_score,
            confidence_score=confidence_score,
            reasons=[f"候选排名前{HIGH_QUALITY_RANK_MAX}"],
        )

    if confidence_score is None or confidence_score < HIGH_QUALITY_CONFIDENCE_MIN:
        reasons.append(f"置信度低于{HIGH_QUALITY_CONFIDENCE_MIN:.0f}")
        return PlanEntryQuality(False, candidate_rank, candidate_score, confidence_score, reasons)

    snapshot = _plan_snapshot(plan)
    if not snapshot:
        reasons.append("缺少趋势/相对强度快照")
        return PlanEntryQuality(False, candidate_rank, candidate_score, confidence_score, reasons)

    trend_score = _float(snapshot.get("trend_score"), 0.0) or 0.0
    relative_strength = _float(snapshot.get("relative_strength_score"), 0.0) or 0.0
    sector_strength = _float(snapshot.get("sector_strength_score"), 0.0) or 0.0
    risk_score = _float(snapshot.get("risk_score"), 100.0) or 100.0
    if (
        trend_score >= HIGH_QUALITY_TREND_MIN
        and relative_strength >= HIGH_QUALITY_RELATIVE_MIN
        and sector_strength >= HIGH_QUALITY_SECTOR_MIN
        and risk_score <= HIGH_QUALITY_RISK_MAX
    ):
        return PlanEntryQuality(
            accepted=True,
            candidate_rank=candidate_rank,
            candidate_score=candidate_score,
            confidence_score=confidence_score,
            reasons=["置信度和趋势结构达标"],
        )

    reasons.append(
        "趋势/相对强度/板块/风险未同时达标"
    )
    return PlanEntryQuality(False, candidate_rank, candidate_score, confidence_score, reasons)


def _limit_ratio(symbol: str) -> Decimal:
    if symbol.startswith(("4", "8")):
        return Decimal("1.30")
    if symbol.startswith(("3", "688", "689")):
        return Decimal("1.20")
    return Decimal("1.10")


def price_action_rejection_reason(
    plan: TradePlan,
    *,
    price: Decimal | None,
    open_price: Decimal | None,
    high: Decimal | None,
    low: Decimal | None,
    pre_close: Decimal | None,
    trigger_price: Decimal,
    limit_up: Decimal | None = None,
    hot_gain_reason: str = "intraday_gain_too_hot",
) -> str | None:
    price = _decimal(price)
    open_price = _decimal(open_price)
    high = _decimal(high)
    low = _decimal(low)
    pre_close = _decimal(pre_close)
    limit_up = _decimal(limit_up)
    if price is None:
        return "missing_price"

    if pre_close is not None and pre_close > 0:
        pct_change = price / pre_close - Decimal("1")
        if pct_change >= Decimal("0.085") and plan.rule_id != "OBS001":
            return hot_gain_reason

        effective_limit_up = limit_up or (pre_close * _limit_ratio(plan.symbol)).quantize(
            Decimal("0.0001")
        )
        if (
            high is not None
            and high >= effective_limit_up * Decimal("0.998")
            and price < effective_limit_up
        ):
            return "near_limit_up_not_sealed"
        if (
            high is not None
            and high / pre_close - Decimal("1") >= Decimal("0.07")
            and price <= pre_close
        ):
            return "spike_reversed_to_flat_or_red"

    if high is not None and high > 0:
        effective_low = low or price
        close_position = (
            (price - effective_low) / (high - effective_low)
            if high > effective_low
            else Decimal("1")
        )
        pullback_from_high = high / price - Decimal("1")
        if pullback_from_high >= Decimal("0.025") and price <= trigger_price * Decimal("1.01"):
            return "failed_breakout_pullback"
        if close_position < Decimal("0.35") and high > trigger_price:
            return "weak_close_position_after_trigger"

    if open_price is not None and pre_close is not None and pre_close > 0:
        gap_up_pct = open_price / pre_close - Decimal("1")
        if gap_up_pct >= Decimal("0.04") and price < open_price:
            return "gap_up_faded_below_open"

    return None


def plan_is_high_quality(
    db: Session,
    plan: TradePlan,
    *,
    pool_name: str | None = "experiment",
    feature_date: str | date | None = None,
) -> bool:
    return evaluate_plan_entry_quality(
        db,
        plan,
        pool_name=pool_name,
        feature_date=feature_date,
    ).accepted
