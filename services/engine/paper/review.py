from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.database import SessionLocal
from services.shared.models import PaperAlert, PaperPosition, PaperTradeReview, Security, TradePlan
from services.shared.upsert import upsert_rows


@dataclass(frozen=True)
class PaperTradeReviewSample:
    position_id: int
    account_id: int
    trade_plan_id: int | None
    symbol: str
    rule_id: str
    sector_code: str | None
    strategy_type: str
    entry_date: date
    exit_date: date
    holding_days: int
    pnl_pct: float
    mfe_pct: float
    mae_pct: float
    giveback_pct: float
    exit_reason: str
    signal_tags: list[str]
    alert_summary: dict[str, Any]
    evidence: dict[str, Any]
    verdict: str
    summary: str

    def to_row(self) -> dict[str, Any]:
        data = asdict(self)
        data["pnl_pct"] = Decimal(str(round(self.pnl_pct, 6)))
        data["mfe_pct"] = Decimal(str(round(self.mfe_pct, 6)))
        data["mae_pct"] = Decimal(str(round(self.mae_pct, 6)))
        data["giveback_pct"] = Decimal(str(round(self.giveback_pct, 6)))
        data["signal_tags_json"] = {"items": self.signal_tags}
        data["alert_summary_json"] = self.alert_summary
        data["evidence_json"] = self.evidence
        del data["signal_tags"]
        del data["alert_summary"]
        del data["evidence"]
        return data


def _float(value: Decimal | None) -> float:
    return float(value or 0)


def _holding_days(position: PaperPosition) -> int:
    if position.exit_date is None:
        return 0
    return (position.exit_date - position.entry_date).days + 1


def _plan_payload(db: Session, trade_plan_id: int | None) -> dict[str, Any]:
    if trade_plan_id is None:
        return {}
    plan = db.get(TradePlan, trade_plan_id)
    payload = plan.entry_condition_json if plan else {}
    return payload if isinstance(payload, dict) else {}


def _signal_tags(payload: dict[str, Any]) -> list[str]:
    evidence = payload.get("evidence") or {}
    tags = evidence.get("tags") or []
    names = []
    for tag in tags:
        if isinstance(tag, dict) and tag.get("name"):
            names.append(str(tag["name"]))
    return names


def _alert_summary(db: Session, position_id: int) -> dict[str, Any]:
    alerts = list(
        db.execute(select(PaperAlert).where(PaperAlert.position_id == position_id)).scalars()
    )
    by_type: dict[str, int] = {}
    high_count = 0
    for alert in alerts:
        by_type[alert.alert_type] = by_type.get(alert.alert_type, 0) + 1
        if alert.severity == "high":
            high_count += 1
    return {
        "total": len(alerts),
        "high_severity": high_count,
        "by_type": by_type,
    }


def _sector_code(db: Session, position: PaperPosition, payload: dict[str, Any]) -> str | None:
    snapshot = payload.get("snapshot") or {}
    sector = snapshot.get("sector_code") or snapshot.get("industry")
    if sector:
        return str(sector)
    security = db.execute(
        select(Security).where(Security.symbol == position.symbol)
    ).scalar_one_or_none()
    return security.industry if security else None


def _verdict(pnl_pct: float, mfe_pct: float, mae_pct: float, giveback_pct: float) -> str:
    if pnl_pct > 0 and giveback_pct <= 0.02:
        return "good_trade"
    if pnl_pct > 0:
        return "profit_giveback"
    if mfe_pct > 0.03 and pnl_pct <= 0:
        return "missed_exit"
    if mae_pct <= -0.04:
        return "bad_entry_or_stop"
    return "loss_or_noise"


def _summary(sample: PaperTradeReviewSample) -> str:
    return (
        f"{sample.symbol} {sample.rule_id} {sample.holding_days}天，"
        f"收益{sample.pnl_pct:.2%}，最大浮盈{sample.mfe_pct:.2%}，"
        f"最大不利{sample.mae_pct:.2%}，回吐{sample.giveback_pct:.2%}，"
        f"卖出原因：{sample.exit_reason}，结论：{sample.verdict}"
    )


def build_paper_trade_review_sample(
    db: Session,
    position: PaperPosition,
) -> PaperTradeReviewSample | None:
    if position.status != "closed" or position.exit_date is None or position.pnl_pct is None:
        return None
    payload = _plan_payload(db, position.trade_plan_id)
    pnl_pct = _float(position.pnl_pct)
    mfe_pct = float(position.highest_price / position.entry_price - Decimal("1"))
    mae_pct = float(position.lowest_price / position.entry_price - Decimal("1"))
    giveback_pct = max(0.0, mfe_pct - pnl_pct)
    sample = PaperTradeReviewSample(
        position_id=position.id,
        account_id=position.account_id,
        trade_plan_id=position.trade_plan_id,
        symbol=position.symbol,
        rule_id=position.rule_id,
        sector_code=_sector_code(db, position, payload),
        strategy_type=position.strategy_type,
        entry_date=position.entry_date,
        exit_date=position.exit_date,
        holding_days=_holding_days(position),
        pnl_pct=pnl_pct,
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        giveback_pct=giveback_pct,
        exit_reason=position.exit_reason or "unknown",
        signal_tags=_signal_tags(payload),
        alert_summary=_alert_summary(db, position.id),
        evidence=payload.get("evidence") or {},
        verdict=_verdict(pnl_pct, mfe_pct, mae_pct, giveback_pct),
        summary="",
    )
    return PaperTradeReviewSample(**{**asdict(sample), "summary": _summary(sample)})


def upsert_paper_trade_reviews(db: Session, report_date: date | None = None) -> int:
    stmt = (
        select(PaperPosition)
        .where(PaperPosition.status == "closed")
        .where(PaperPosition.exit_date.is_not(None))
        .where(PaperPosition.pnl_pct.is_not(None))
    )
    if report_date:
        stmt = stmt.where(PaperPosition.exit_date <= report_date)
    samples = [
        sample
        for position in db.execute(stmt).scalars()
        if (sample := build_paper_trade_review_sample(db, position)) is not None
    ]
    rows = [sample.to_row() for sample in samples]
    return upsert_rows(
        db,
        PaperTradeReview,
        rows,
        update_columns=[
            "account_id",
            "trade_plan_id",
            "symbol",
            "rule_id",
            "sector_code",
            "strategy_type",
            "entry_date",
            "exit_date",
            "holding_days",
            "pnl_pct",
            "mfe_pct",
            "mae_pct",
            "giveback_pct",
            "exit_reason",
            "signal_tags_json",
            "alert_summary_json",
            "evidence_json",
            "verdict",
            "summary",
        ],
        constraint="uq_paper_trade_review_position",
    )


def upsert_paper_trade_review_for_position(db: Session, position: PaperPosition) -> int:
    sample = build_paper_trade_review_sample(db, position)
    if sample is None:
        return 0
    return upsert_rows(
        db,
        PaperTradeReview,
        [sample.to_row()],
        update_columns=[
            "account_id",
            "trade_plan_id",
            "symbol",
            "rule_id",
            "sector_code",
            "strategy_type",
            "entry_date",
            "exit_date",
            "holding_days",
            "pnl_pct",
            "mfe_pct",
            "mae_pct",
            "giveback_pct",
            "exit_reason",
            "signal_tags_json",
            "alert_summary_json",
            "evidence_json",
            "verdict",
            "summary",
        ],
        constraint="uq_paper_trade_review_position",
    )


def generate_paper_trade_reviews(report_date: str | None = None) -> int:
    parsed_date = date.fromisoformat(report_date) if report_date else None
    with SessionLocal() as db:
        changed = upsert_paper_trade_reviews(db, parsed_date)
        db.commit()
        return changed
