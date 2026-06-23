from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.sector.profiles import DEFAULT_SECTOR_PROFILES
from services.shared.models import SectorProfile
from services.shared.upsert import upsert_rows


def seed_sector_profiles(db: Session) -> int:
    rows = [profile.to_record() for profile in DEFAULT_SECTOR_PROFILES]
    return upsert_rows(
        db,
        SectorProfile,
        rows,
        update_columns=[
            "sector_style",
            "analysis_framework",
            "default_strategy_type",
            "preferred_holding_style",
            "key_drivers_json",
            "risk_notes",
        ],
        index_elements=[SectorProfile.sector_name],
    )


def load_sector_profile(db: Session, sector_name: str | None) -> SectorProfile | None:
    if not sector_name:
        return None
    return db.execute(select(SectorProfile).where(SectorProfile.sector_name == sector_name)).scalar_one_or_none()
