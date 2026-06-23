from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

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
        for symbol, industry in mapping.items():
            security = db.execute(select(Security).where(Security.symbol == symbol)).scalar_one_or_none()
            if security is None:
                missing.append(symbol)
                continue
            security.industry = industry
            updated += 1
        db.commit()
    return IndustryMappingResult(updated=updated, missing=missing)
