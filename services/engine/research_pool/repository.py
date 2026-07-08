from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from services.shared.models import ResearchPoolItem

CANDIDATE_NOTE_PREFIX = "候选理由："


def candidate_tags(tags: list[str]) -> bool:
    return "after_close_candidate" in tags or "next_session" in tags


def manual_focus_tags(tags: list[str]) -> bool:
    return "manual_focus" in tags


def candidate_feature_date(tags: list[str]) -> str | None:
    dates: list[str] = []
    for tag in tags:
        value = str(tag)
        try:
            datetime.fromisoformat(value)
        except ValueError:
            continue
        dates.append(value)
    return max(dates) if dates else None


def tag_value(tags: list[str], prefix: str) -> str | None:
    for tag in reversed(tags):
        if str(tag).startswith(prefix):
            return str(tag).removeprefix(prefix)
    return None


def candidate_batch_id(tags: list[str]) -> str | None:
    return tag_value(tags, "batch:")


def latest_auto_candidate_batch(
    items: list[ResearchPoolItem],
) -> tuple[str | None, str | None, str | None]:
    batch_ids = [
        batch_id
        for item in items
        for tags in [[str(tag) for tag in (item.tags_json or {}).get("tags", [])]]
        for batch_id in [candidate_batch_id(tags)]
        if batch_id and candidate_tags(tags) and not manual_focus_tags(tags)
    ]
    if batch_ids:
        return None, None, max(batch_ids)

    feature_dates = [
        feature_date
        for item in items
        for tags in [[str(tag) for tag in (item.tags_json or {}).get("tags", [])]]
        for feature_date in [candidate_feature_date(tags)]
        if feature_date and candidate_tags(tags) and not manual_focus_tags(tags)
    ]
    if feature_dates:
        return max(feature_dates), None, None

    hold_until_values = [
        hold_until
        for item in items
        for tags in [[str(tag) for tag in (item.tags_json or {}).get("tags", [])]]
        for hold_until in [tag_value(tags, "hold_until:")]
        if hold_until and candidate_tags(tags) and not manual_focus_tags(tags)
    ]
    return None, max(hold_until_values) if hold_until_values else None, None


def is_stale_auto_candidate(
    item: ResearchPoolItem,
    latest_batch: tuple[str | None, str | None, str | None],
) -> bool:
    latest_feature_date, latest_hold_until, latest_batch_id = latest_batch
    if not latest_feature_date and not latest_hold_until and not latest_batch_id:
        return False
    tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
    if not candidate_tags(tags) or manual_focus_tags(tags):
        return False
    batch_id = candidate_batch_id(tags)
    if latest_batch_id:
        return batch_id != latest_batch_id
    feature_date = candidate_feature_date(tags)
    if latest_feature_date:
        return bool(feature_date and feature_date < latest_feature_date)
    hold_until = tag_value(tags, "hold_until:")
    return bool(hold_until and latest_hold_until and hold_until < latest_hold_until)


def filter_latest_candidate_batch_items(items: list[ResearchPoolItem]) -> list[ResearchPoolItem]:
    latest_by_pool = {
        pool_name: latest_auto_candidate_batch(pool_items)
        for pool_name, pool_items in _items_by_pool(items).items()
    }
    return [
        item
        for item in items
        if not is_stale_auto_candidate(
            item,
            latest_by_pool.get(item.pool_name, (None, None, None)),
        )
    ]


def candidate_batch_summary(items: list[ResearchPoolItem]) -> dict[str, int | str | None]:
    latest_by_pool = {
        pool_name: latest_auto_candidate_batch(pool_items)
        for pool_name, pool_items in _items_by_pool(items).items()
    }
    latest_batch = max(
        latest_by_pool.values(),
        key=lambda batch: batch[2] or batch[0] or batch[1] or "",
        default=(None, None, None),
    )
    latest_feature_date, latest_hold_until, latest_batch_id = latest_batch
    stale_count = 0
    current_auto_count = 0
    manual_count = 0
    for item in items:
        tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
        if manual_focus_tags(tags):
            manual_count += 1
        if candidate_tags(tags) and not manual_focus_tags(tags):
            if is_stale_auto_candidate(
                item,
                latest_by_pool.get(item.pool_name, (None, None, None)),
            ):
                stale_count += 1
            else:
                current_auto_count += 1
    return {
        "auto_feature_date": latest_feature_date,
        "auto_hold_until": latest_hold_until,
        "auto_batch_id": latest_batch_id,
        "source_item_count": len(items),
        "usable_item_count": len(items) - stale_count,
        "current_auto_candidate_count": current_auto_count,
        "manual_focus_count": manual_count,
        "stale_auto_candidate_count": stale_count,
    }


def _items_by_pool(items: list[ResearchPoolItem]) -> dict[str, list[ResearchPoolItem]]:
    grouped: dict[str, list[ResearchPoolItem]] = {}
    for item in items:
        grouped.setdefault(item.pool_name, []).append(item)
    return grouped


def _merge_note(
    *,
    current_note: str | None,
    incoming_note: str | None,
    current_tags: list[str],
    incoming_tags: list[str],
) -> str | None:
    if incoming_note is None:
        return current_note
    has_manual_focus = "manual_focus" in current_tags
    incoming_manual_focus = "manual_focus" in incoming_tags
    incoming_candidate = "after_close_candidate" in incoming_tags
    if not has_manual_focus or incoming_manual_focus or not current_note:
        return incoming_note
    if incoming_candidate:
        manual_note = current_note.split(f"；{CANDIDATE_NOTE_PREFIX}", 1)[0]
        return f"{manual_note}；{CANDIDATE_NOTE_PREFIX}{incoming_note}"
    return current_note


def add_symbols_to_pool(
    db: Session,
    symbols: list[str],
    pool_name: str = "manual",
    note: str | None = None,
    tags: list[str] | None = None,
    replace_tag_prefixes: tuple[str, ...] | None = None,
) -> int:
    now = datetime.utcnow()
    written = 0
    for symbol in symbols:
        incoming_tags = tags or []
        item = db.execute(
            select(ResearchPoolItem)
            .where(ResearchPoolItem.pool_name == pool_name)
            .where(ResearchPoolItem.symbol == symbol)
        ).scalar_one_or_none()
        if item is None:
            item = ResearchPoolItem(pool_name=pool_name, symbol=symbol)
            db.add(item)
            current_tags = []
        else:
            current_tags = (item.tags_json or {}).get("tags", [])
        if replace_tag_prefixes:
            current_tags = [
                tag
                for tag in current_tags
                if not any(str(tag).startswith(prefix) for prefix in replace_tag_prefixes)
            ]
        merged_tags = list(dict.fromkeys([*current_tags, *incoming_tags]))
        item.note = _merge_note(
            current_note=item.note,
            incoming_note=note,
            current_tags=current_tags,
            incoming_tags=incoming_tags,
        )
        item.tags_json = {"tags": merged_tags}
        item.status = "active"
        item.updated_at = now
        written += 1
    return written


def list_pool_symbols(
    db: Session,
    pool_name: str = "manual",
    active_only: bool = True,
    latest_candidate_batch_only: bool = False,
) -> list[str]:
    if latest_candidate_batch_only:
        item_stmt = select(ResearchPoolItem).where(ResearchPoolItem.pool_name == pool_name)
        if active_only:
            item_stmt = item_stmt.where(ResearchPoolItem.status == "active")
        items = filter_latest_candidate_batch_items(list(db.execute(item_stmt).scalars()))
        return sorted(item.symbol for item in items)

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


def retire_pool_symbols(
    db: Session,
    *,
    pool_name: str,
    symbols: list[str],
    status: str = "retired",
) -> int:
    if not symbols:
        return 0
    stmt = (
        select(ResearchPoolItem)
        .where(ResearchPoolItem.pool_name == pool_name)
        .where(ResearchPoolItem.symbol.in_(symbols))
    )
    rows = list(db.execute(stmt).scalars())
    now = datetime.utcnow()
    for item in rows:
        item.status = status
        item.updated_at = now
    return len(rows)


def delete_pool_symbols(
    db: Session,
    *,
    pool_name: str,
    symbols: list[str],
) -> int:
    if not symbols:
        return 0
    result = db.execute(
        delete(ResearchPoolItem)
        .where(ResearchPoolItem.pool_name == pool_name)
        .where(ResearchPoolItem.symbol.in_(symbols))
    )
    return int(result.rowcount or 0)
