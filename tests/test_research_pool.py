from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.research_pool.repository import add_symbols_to_pool, list_pool_items, list_pool_symbols
from services.engine.research_pool.service import _parse_date
from services.shared.database import Base


def test_add_symbols_to_research_pool_upserts_items() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        add_symbols_to_pool(db, ["000001", "600519"], note="first", tags=["manual"])
        add_symbols_to_pool(db, ["000001"], note="updated", tags=["bank"])
        db.commit()

        symbols = list_pool_symbols(db)
        items = list_pool_items(db)

    assert symbols == ["000001", "600519"]
    by_symbol = {item["symbol"]: item for item in items}
    assert by_symbol["000001"]["note"] == "updated"
    assert by_symbol["000001"]["tags"] == ["bank"]


def test_parse_pool_research_dates_accepts_akshare_and_iso_formats() -> None:
    assert _parse_date("20240101").isoformat() == "2024-01-01"
    assert _parse_date("2024-01-01").isoformat() == "2024-01-01"
    assert _parse_date(None) is None
