from __future__ import annotations

from sqlalchemy import inspect, text

from services.shared import models  # noqa: F401
from services.shared.database import Base, engine


def _add_mysql_column_if_missing(table: str, column: str, ddl: str) -> None:
    inspector = inspect(engine)
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _execute_mysql(sql: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql))


def _drop_mysql_index_if_exists(table: str, index_name: str) -> None:
    inspector = inspect(engine)
    indexes = {item["name"] for item in inspector.get_indexes(table)}
    if index_name not in indexes:
        return
    _execute_mysql(f"ALTER TABLE {table} DROP INDEX {index_name}")


def _create_mysql_unique_index_if_missing(table: str, index_name: str, columns: str) -> None:
    inspector = inspect(engine)
    indexes = {item["name"] for item in inspector.get_indexes(table)}
    if index_name in indexes:
        return
    _execute_mysql(f"ALTER TABLE {table} ADD UNIQUE INDEX {index_name} ({columns})")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "mysql":
        _add_mysql_column_if_missing("securities", "sector_style", "VARCHAR(64) NULL")
        _add_mysql_column_if_missing("securities", "analysis_framework", "VARCHAR(64) NULL")
        _add_mysql_column_if_missing("securities", "holding_style", "VARCHAR(64) NULL")
        _add_mysql_column_if_missing("trade_plans", "entry_trigger_price", "NUMERIC(18, 4) NULL")
        _add_mysql_column_if_missing("trade_plans", "max_gap_up_pct", "NUMERIC(8, 4) NULL")
        _add_mysql_column_if_missing("trade_plans", "trailing_drawdown_pct", "NUMERIC(8, 4) NULL")
        _add_mysql_column_if_missing(
            "risk_profiles",
            "scope_type",
            "VARCHAR(32) NOT NULL DEFAULT 'global'",
        )
        _add_mysql_column_if_missing("risk_profiles", "scope_value", "VARCHAR(64) NULL")
        _add_mysql_column_if_missing("risk_profiles", "strategy_type", "VARCHAR(32) NULL")
        _add_mysql_column_if_missing("risk_profiles", "priority", "INTEGER NOT NULL DEFAULT 0")
        _add_mysql_column_if_missing("fundamental_snapshots", "available_date", "DATE NULL")
        _add_mysql_column_if_missing("research_pool_items", "tags_json", "TEXT NULL")
        _drop_mysql_index_if_exists(
            "paper_positions",
            "uq_paper_position_account_symbol_status",
        )
        _drop_mysql_index_if_exists(
            "parameter_recommendations",
            "uq_parameter_recommendation_daily_target",
        )
        _create_mysql_unique_index_if_missing(
            "parameter_recommendations",
            "uq_parameter_recommendation_daily_target",
            "report_date, source_report_type, rule_id, scope_type, scope_value, "
            "target_type, target_name, action",
        )
        _execute_mysql(
            "UPDATE fundamental_snapshots "
            "SET available_date = report_date "
            "WHERE available_date IS NULL"
        )
        _execute_mysql(
            "ALTER TABLE candidate_discovery_snapshots "
            "MODIFY COLUMN discovery_json LONGTEXT NOT NULL"
        )


if __name__ == "__main__":
    main()
