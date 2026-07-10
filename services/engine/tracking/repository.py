from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from services.engine.workspace.repository import WorkspaceItem
from services.shared.models import StockTrackingSnapshot


@dataclass(frozen=True)
class TrackingSnapshotPayload:
    symbol: str
    snapshot_date: date
    stage: str
    stage_label: str
    tracking_score: float
    name: str | None
    industry: str | None
    sector_style: str | None
    latest_trade_date: date | None
    latest_close: float | None
    current_price: float | None
    day_change_pct: float | None
    return_5d: float | None
    return_20d: float | None
    metrics: dict[str, float | None]
    evidence: list[str]
    risks: list[str]
    source: dict[str, object]


STAGE_LABELS = {
    "trend_holding": "趋势持有",
    "startup_confirming": "启动确认",
    "watching": "持续观察",
    "risk_review": "风险复核",
    "archived": "资料留存",
}


def _avg(values: list[float | None]) -> float | None:
    usable = [item for item in values if item is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _score(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def _has_open_trade(item: WorkspaceItem) -> bool:
    return any(trade.status == "open" for trade in item.recent_paper_trades)


def _has_action_plan(item: WorkspaceItem) -> bool:
    return any(plan.can_buy_now or plan.execution_status == "tradable" for plan in item.plans)


def _is_next_session_candidate(item: WorkspaceItem) -> bool:
    return "after_close_candidate" in item.manual_tags or "next_session" in item.manual_tags


def _tracking_score(item: WorkspaceItem) -> float:
    base = _avg(
        [
            item.trend_quality_score,
            item.trend_score,
            item.relative_strength_score,
            item.sector_strength_score,
            item.volume_confirmation_score,
            item.candidate_score,
            item.startup_signal_score,
        ]
    )
    raw = base if base is not None else 45.0
    bonus = 0.0
    if _has_open_trade(item):
        bonus += 4.0
    if _has_action_plan(item):
        bonus += 3.0
    if item.candidate_tier == "core_action":
        bonus += 3.0
    if item.startup_signal_score is not None and item.startup_signal_score >= 75:
        bonus += 2.0
    penalty = (
        max(0.0, (item.risk_score or 0.0) - 60.0) * 0.35
        + max(0.0, (item.overheat_score or 0.0) - 70.0) * 0.25
        + max(0.0, (item.volume_trap_risk_score or 0.0) - 65.0) * 0.35
        + (6.0 if (item.return_20d or 0.0) >= 0.32 else 0.0)
    )
    return round(max(0.0, min(100.0, raw + bonus - penalty)), 2)


def _stage(item: WorkspaceItem, tracking_score: float) -> str:
    if (
        item.candidate_tier == "risk_reject"
        or (item.risk_score or 0.0) >= 75
        or (item.volume_trap_risk_score or 0.0) >= 80
    ):
        return "risk_review"
    if _has_open_trade(item) and tracking_score >= 55:
        return "trend_holding"
    if _has_action_plan(item) or item.candidate_tier == "core_action" or (item.startup_signal_score or 0.0) >= 75:
        return "startup_confirming"
    if _is_next_session_candidate(item) or item.candidate_tier == "watch_wait":
        return "watching"
    return "archived"


def _risks(item: WorkspaceItem) -> list[str]:
    risks: list[str] = []
    if (item.risk_score or 0.0) >= 70:
        risks.append(f"综合风险 {_score(item.risk_score)}，需要先降权")
    if (item.volume_trap_risk_score or 0.0) >= 65:
        risks.append(f"放量诱多风险 {_score(item.volume_trap_risk_score)}，不能只看放量")
    if (item.overheat_score or 0.0) >= 70:
        risks.append(f"过热 {_score(item.overheat_score)}，追高性价比下降")
    if (item.distance_to_ma20 or 0.0) >= 0.14:
        risks.append(f"偏离20日线 {_pct(item.distance_to_ma20)}，更适合等回踩")
    if (item.return_20d or 0.0) >= 0.3:
        risks.append(f"20日涨幅 {_pct(item.return_20d)}，主升后回撤风险变大")
    if item.sector_strength_score is not None and item.sector_strength_score < 45:
        risks.append(f"板块强度 {_score(item.sector_strength_score)}，个股强也要防板块拖累")
    return risks or ["暂未看到需要立刻降级的硬风险，继续看承接。"]


def _evidence(item: WorkspaceItem) -> list[str]:
    lines = [
        f"板块 {item.industry or '-'} / 强度 {_score(item.sector_strength_score)}",
        f"趋势 {_score(item.trend_score)} / 质量 {_score(item.trend_quality_score)} / 相对强度 {_score(item.relative_strength_score)}",
        f"量能 {_score(item.volume_confirmation_score)} / 5日量比 {_score(item.amount_ratio_5d)}",
        f"今日 {_pct(item.day_change_pct)} / 5日 {_pct(item.return_5d)} / 20日 {_pct(item.return_20d)}",
    ]
    if item.candidate_score is not None:
        lines.append(f"候选 {_score(item.candidate_score)} / 启动 {_score(item.startup_signal_score)}")
    if item.route_label:
        lines.append(f"路线 {item.route_label}：{item.route_reason or '-'}")
    return lines


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def build_tracking_snapshot_payload(
    item: WorkspaceItem,
    *,
    snapshot_date: date,
) -> TrackingSnapshotPayload:
    tracking_score = _tracking_score(item)
    stage = _stage(item, tracking_score)
    return TrackingSnapshotPayload(
        symbol=item.symbol,
        snapshot_date=snapshot_date,
        stage=stage,
        stage_label=STAGE_LABELS[stage],
        tracking_score=tracking_score,
        name=item.name,
        industry=item.industry,
        sector_style=item.sector_style,
        latest_trade_date=_parse_date(item.latest_trade_date),
        latest_close=item.latest_close,
        current_price=item.current_price,
        day_change_pct=item.day_change_pct,
        return_5d=item.return_5d,
        return_20d=item.return_20d,
        metrics={
            "trend_score": item.trend_score,
            "trend_quality_score": item.trend_quality_score,
            "relative_strength_score": item.relative_strength_score,
            "sector_strength_score": item.sector_strength_score,
            "volume_confirmation_score": item.volume_confirmation_score,
            "risk_score": item.risk_score,
            "overheat_score": item.overheat_score,
            "volume_trap_risk_score": item.volume_trap_risk_score,
            "distance_to_ma20": item.distance_to_ma20,
            "amount_ratio_5d": item.amount_ratio_5d,
            "candidate_score": item.candidate_score,
            "startup_signal_score": item.startup_signal_score,
        },
        evidence=_evidence(item),
        risks=_risks(item),
        source={
            "source": item.source,
            "manual_tags": item.manual_tags,
            "candidate_tier": item.candidate_tier,
            "candidate_tier_label": item.candidate_tier_label,
            "candidate_rank": item.candidate_rank,
            "feature_date": item.feature_date,
            "quote_time": item.quote_time,
        },
    )


def upsert_tracking_snapshot(
    db: Session,
    payload: TrackingSnapshotPayload,
) -> StockTrackingSnapshot:
    row = db.execute(
        select(StockTrackingSnapshot).where(
            StockTrackingSnapshot.symbol == payload.symbol,
            StockTrackingSnapshot.snapshot_date == payload.snapshot_date,
        )
    ).scalar_one_or_none()
    if row is None:
        row = StockTrackingSnapshot(symbol=payload.symbol, snapshot_date=payload.snapshot_date)
        db.add(row)

    row.stage = payload.stage
    row.stage_label = payload.stage_label
    row.tracking_score = payload.tracking_score
    row.name = payload.name
    row.industry = payload.industry
    row.sector_style = payload.sector_style
    row.latest_trade_date = payload.latest_trade_date
    row.latest_close = payload.latest_close
    row.current_price = payload.current_price
    row.day_change_pct = payload.day_change_pct
    row.return_5d = payload.return_5d
    row.return_20d = payload.return_20d
    row.metrics_json = payload.metrics
    row.evidence_json = {"items": payload.evidence}
    row.risks_json = {"items": payload.risks}
    row.source_json = payload.source
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def list_tracking_snapshots(
    db: Session,
    *,
    symbol: str,
    limit: int = 120,
) -> list[StockTrackingSnapshot]:
    return list(
        db.execute(
            select(StockTrackingSnapshot)
            .where(StockTrackingSnapshot.symbol == symbol)
            .order_by(desc(StockTrackingSnapshot.snapshot_date))
            .limit(limit)
        ).scalars()
    )
