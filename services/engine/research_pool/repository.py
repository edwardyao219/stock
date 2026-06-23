from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import ResearchPoolItem


def add_symbols_to_pool(
    db: Session,
    symbols: list[str],
    pool_name: str = "manual",
    note: str | None = None,
    tags: list[str] | None = None,
) -> int:
    now = datetime.utcnow()
    written = 0
    for symbol in symbols:
        item = db.execute(
            select(ResearchPoolItem)
            .where(ResearchPoolItem.pool_name == pool_name)
            .where(ResearchPoolItem.symbol == symbol)
        ).scalar_one_or_none()
        if item is None:
            item = ResearchPoolItem(pool_name=pool_name, symbol=symbol)
            db.add(item)
        item.note = note
        item.tags_json = {"tags": tags or []}
        item.status = "active"
        item.updated_at = now
        written += 1
    return written


def list_pool_symbols(db: Session, pool_name: str = "manual", active_only: bool = True) -> list[str]:
    stmt = select(ResearchPoolItem.symbol).where(ResearchPoolItem.pool_name == pool_name)
    if active_only:
        stmt = stmt.where(ResearchPoolItem.status == "active")
    return list(db.execute(stmt.order_by(ResearchPoolItem.symbol)).scalars())


def list_pool_items(db: Session, pool_name: str = "manual") -> list[dict[str, Any]]:
    stmt = (
        select(ResearchPoolItem)
        .where(ResearchPoolItem.pool_name == pool_name)
        .order_by(ResearchPoolItem.symbol)
    )
    return [
        {
            "pool_name": item.pool_name,
            "symbol": item.symbol,
            "note": item.note,
            "tags": (item.tags_json or {}).get("tags", []),
            "status": item.status,
        }
        for item in db.execute(stmt).scalars()
    ]
