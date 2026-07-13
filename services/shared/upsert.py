from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session


def upsert_rows(
    db: Session,
    model: type,
    rows: list[dict[str, Any]],
    update_columns: list[str],
    constraint: str | None = None,
    index_elements: list[Any] | None = None,
) -> int:
    if not rows:
        return 0

    dialect = db.bind.dialect.name if db.bind is not None else ""

    if dialect == "mysql":
        stmt = mysql_insert(model).values(rows)
        stmt = stmt.on_duplicate_key_update(
            **{column: getattr(stmt.inserted, column) for column in update_columns}
        )
    elif dialect == "postgresql":
        stmt = postgres_insert(model).values(rows)
        kwargs: dict[str, Any] = {
            "set_": {column: getattr(stmt.excluded, column) for column in update_columns}
        }
        if constraint:
            kwargs["constraint"] = constraint
        elif index_elements:
            kwargs["index_elements"] = index_elements
        stmt = stmt.on_conflict_do_update(**kwargs)
    elif dialect == "sqlite" and index_elements:
        stmt = sqlite_insert(model).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=index_elements,
            set_={column: getattr(stmt.excluded, column) for column in update_columns},
        )
    else:
        # Fallback for local tests or SQLite-like engines: try regular inserts.
        db.execute(model.__table__.insert(), rows)
        return len(rows)

    db.execute(stmt)
    return len(rows)
