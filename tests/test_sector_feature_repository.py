from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from services.engine.features import repository
from services.engine.features.repository import upsert_sector_features
from services.engine.features.sector import SectorFeatureRow
from services.shared.database import Base
from services.shared.models import SectorFeatureDaily


def test_upsert_sector_features_replaces_same_date_snapshot() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                SectorFeatureDaily(
                    sector_code="旧板块",
                    trade_date=date(2026, 6, 24),
                    features={"sector_strength_score": 10},
                ),
                SectorFeatureDaily(
                    sector_code="保留旧日期",
                    trade_date=date(2026, 6, 23),
                    features={"sector_strength_score": 20},
                ),
            ]
        )
        db.commit()

        written = upsert_sector_features(
            db,
            [
                SectorFeatureRow(
                    sector_code="新板块A",
                    trade_date="2026-06-24",
                    features={"sector_strength_score": 80},
                ),
                SectorFeatureRow(
                    sector_code="新板块B",
                    trade_date="2026-06-24",
                    features={"sector_strength_score": 70},
                ),
            ],
        )
        db.commit()

        rows = db.execute(
            select(SectorFeatureDaily.sector_code, SectorFeatureDaily.trade_date).order_by(
                SectorFeatureDaily.trade_date, SectorFeatureDaily.sector_code
            )
        ).all()

    assert written == 2
    assert rows == [
        ("保留旧日期", date(2026, 6, 23)),
        ("新板块A", date(2026, 6, 24)),
        ("新板块B", date(2026, 6, 24)),
    ]


def test_upsert_sector_features_writes_large_snapshots_in_chunks(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    chunk_sizes: list[int] = []

    def fake_upsert_rows(db, model, rows, update_columns, constraint=None, index_elements=None):
        chunk_sizes.append(len(rows))
        return len(rows)

    monkeypatch.setattr(repository, "upsert_rows", fake_upsert_rows)

    with Session(engine) as db:
        written = upsert_sector_features(
            db,
            [
                SectorFeatureRow(
                    sector_code=f"板块{index}",
                    trade_date="2026-06-24",
                    features={"sector_strength_score": index},
                )
                for index in range(5)
            ],
            chunk_size=2,
        )

    assert written == 5
    assert chunk_sizes == [2, 2, 1]
