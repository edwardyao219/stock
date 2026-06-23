from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from services.engine.sector.repository import load_sector_profile, seed_sector_profiles
from services.shared.database import SessionLocal
from services.shared.models import Security


@dataclass(frozen=True)
class IndustryMappingResult:
    updated: int
    missing: list[str]


def update_security_industries(mapping: dict[str, str]) -> IndustryMappingResult:
    updated = 0
    missing: list[str] = []
    with SessionLocal() as db:
        seed_sector_profiles(db)
        for symbol, industry in mapping.items():
            security = db.execute(select(Security).where(Security.symbol == symbol)).scalar_one_or_none()
            if security is None:
                missing.append(symbol)
                continue
            profile = load_sector_profile(db, industry)
            security.industry = industry
            if profile:
                security.sector_style = profile.sector_style
                security.analysis_framework = profile.analysis_framework
                security.holding_style = profile.preferred_holding_style
            updated += 1
        db.commit()
    return IndustryMappingResult(updated=updated, missing=missing)
