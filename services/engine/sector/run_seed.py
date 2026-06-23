from __future__ import annotations

from services.engine.sector.repository import seed_sector_profiles
from services.shared.database import SessionLocal


def main() -> None:
    with SessionLocal() as db:
        rows = seed_sector_profiles(db)
        db.commit()
    print({"sector_profiles": rows})


if __name__ == "__main__":
    main()
