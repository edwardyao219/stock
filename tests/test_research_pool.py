from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.research_pool.repository import (
    add_symbols_to_pool,
    candidate_feature_date,
    filter_latest_candidate_batch_items,
    list_pool_items,
    list_pool_symbols,
)
from services.engine.research_pool.service import _parse_date
from services.shared.database import Base
from services.shared.models import ResearchPoolItem


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
    assert by_symbol["000001"]["tags"] == ["manual", "bank"]


def test_add_symbols_to_research_pool_preserves_manual_focus_note() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        add_symbols_to_pool(db, ["002745"], note="手动关注 002745", tags=["manual_focus"])
        add_symbols_to_pool(
            db,
            ["002745"],
            note="策略 OBS001 观察候选",
            tags=["after_close_candidate"],
        )
        db.commit()

        items = list_pool_items(db, pool_name="manual")

    assert items[0]["note"] == "手动关注 002745；候选理由：策略 OBS001 观察候选"
    assert items[0]["tags"] == ["manual_focus", "after_close_candidate"]


def test_parse_pool_research_dates_accepts_akshare_and_iso_formats() -> None:
    assert _parse_date("20240101").isoformat() == "2024-01-01"
    assert _parse_date("2024-01-01").isoformat() == "2024-01-01"
    assert _parse_date(None) is None


def test_candidate_feature_date_uses_latest_date_when_tags_keep_history() -> None:
    assert (
        candidate_feature_date(
            [
                "after_close_candidate",
                "2026-05-08",
                "2026-06-30",
                "hold_until:2026-07-01",
                "mode:exploration",
            ]
        )
        == "2026-06-30"
    )


def test_filter_latest_candidate_batch_items_prefers_latest_batch_with_same_feature_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        add_symbols_to_pool(
            db,
            ["600171"],
            pool_name="experiment",
            tags=[
                "after_close_candidate",
                "next_session",
                "2026-06-30",
                "batch:2026-06-30T09:00:00",
                "rank:1",
            ],
        )
        add_symbols_to_pool(
            db,
            ["002156"],
            pool_name="experiment",
            tags=[
                "after_close_candidate",
                "next_session",
                "2026-06-30",
                "batch:2026-06-30T10:00:00",
                "rank:1",
            ],
        )
        db.commit()
        rows = list(db.query(ResearchPoolItem).order_by(ResearchPoolItem.symbol).all())

    filtered = filter_latest_candidate_batch_items(rows)

    assert [item.symbol for item in filtered] == ["002156"]


def test_filter_latest_candidate_batch_items_keeps_latest_batch_per_pool_alias() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        add_symbols_to_pool(
            db,
            ["002156"],
            pool_name="experiment",
            tags=[
                "after_close_candidate",
                "next_session",
                "2026-06-30",
                "batch:2026-07-01T02:33:38",
                "rank:1",
            ],
        )
        add_symbols_to_pool(
            db,
            ["688802"],
            pool_name="experiment_star",
            tags=[
                "after_close_candidate",
                "next_session",
                "2026-06-30",
                "batch:2026-07-01T02:33:48",
                "rank:1",
            ],
        )
        add_symbols_to_pool(
            db,
            ["600171"],
            pool_name="experiment",
            tags=[
                "after_close_candidate",
                "next_session",
                "2026-06-29",
                "batch:2026-06-30T15:00:00",
                "rank:1",
            ],
        )
        db.commit()
        rows = list(db.query(ResearchPoolItem).order_by(ResearchPoolItem.symbol).all())

    filtered = filter_latest_candidate_batch_items(rows)

    assert [item.symbol for item in filtered] == ["002156", "688802"]
