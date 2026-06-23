from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy import or_

from services.engine.risk.profiles import (
    BANKING_COMPOUND_PROFILE,
    DEFAULT_RISK_PROFILE,
    THEME_SHORT_PROFILE,
    RiskProfile,
)
from services.shared.models import RiskProfileRecord


def _profile_from_record(record: RiskProfileRecord) -> RiskProfile:
    config = {
        **DEFAULT_RISK_PROFILE.to_dict(),
        **(record.config_json or {}),
        "name": record.name,
        "scope_type": record.scope_type,
        "scope_value": record.scope_value,
        "strategy_type": record.strategy_type,
        "priority": record.priority,
    }
    return RiskProfile(**config)


def load_risk_profile(db: Session, name: str = "default") -> RiskProfile:
    record = db.execute(select(RiskProfileRecord).where(RiskProfileRecord.name == name)).scalar_one_or_none()
    if record is None:
        return DEFAULT_RISK_PROFILE
    return _profile_from_record(record)


def load_matching_risk_profile(
    db: Session,
    strategy_type: str,
    sector_code: str | None = None,
    style: str | None = None,
) -> RiskProfile:
    candidates = list(
        db.execute(
            select(RiskProfileRecord)
            .where(RiskProfileRecord.status == "active")
            .where(
                or_(
                    RiskProfileRecord.scope_type == "global",
                    (RiskProfileRecord.scope_type == "sector")
                    & (RiskProfileRecord.scope_value == sector_code),
                    (RiskProfileRecord.scope_type == "style")
                    & (RiskProfileRecord.scope_value == style),
                )
            )
            .where(
                or_(
                    RiskProfileRecord.strategy_type.is_(None),
                    RiskProfileRecord.strategy_type == strategy_type,
                )
            )
            .order_by(RiskProfileRecord.priority.desc())
        ).scalars()
    )
    if not candidates:
        return DEFAULT_RISK_PROFILE
    return _profile_from_record(candidates[0])


def seed_default_risk_profile(db: Session) -> RiskProfileRecord:
    seeded: RiskProfileRecord | None = None
    profiles = [
        (
            DEFAULT_RISK_PROFILE,
            "Default adjustable risk profile for generated trade plans.",
        ),
        (
            BANKING_COMPOUND_PROFILE,
            "Banking and stable dividend sectors: wider stops, longer holding, compound-oriented exits.",
        ),
        (
            THEME_SHORT_PROFILE,
            "High-beta short-term theme trades: tighter risk and faster exits.",
        ),
    ]
    for profile, description in profiles:
        record = db.execute(
            select(RiskProfileRecord).where(RiskProfileRecord.name == profile.name)
        ).scalar_one_or_none()
        if record is None:
            record = RiskProfileRecord(
                name=profile.name,
                description=description,
                scope_type=profile.scope_type,
                scope_value=profile.scope_value,
                strategy_type=profile.strategy_type,
                priority=profile.priority,
                config_json=profile.to_dict(),
                status="active",
            )
            db.add(record)
            db.flush()
        seeded = seeded or record
    return seeded
