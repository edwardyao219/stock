from __future__ import annotations

from sqlalchemy import inspect, text

from services.shared.database import Base, engine
from services.shared import models  # noqa: F401


def _add_mysql_column_if_missing(table: str, column: str, ddl: str) -> None:
    inspector = inspect(engine)
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def main() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "mysql":
        _add_mysql_column_if_missing("trade_plans", "entry_trigger_price", "NUMERIC(18, 4) NULL")
        _add_mysql_column_if_missing("trade_plans", "max_gap_up_pct", "NUMERIC(8, 4) NULL")
        _add_mysql_column_if_missing("trade_plans", "trailing_drawdown_pct", "NUMERIC(8, 4) NULL")
        _add_mysql_column_if_missing("risk_profiles", "scope_type", "VARCHAR(32) NOT NULL DEFAULT 'global'")
        _add_mysql_column_if_missing("risk_profiles", "scope_value", "VARCHAR(64) NULL")
        _add_mysql_column_if_missing("risk_profiles", "strategy_type", "VARCHAR(32) NULL")
        _add_mysql_column_if_missing("risk_profiles", "priority", "INTEGER NOT NULL DEFAULT 0")


if __name__ == "__main__":
    main()
