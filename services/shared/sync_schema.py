from __future__ import annotations

from datetime import date

from sqlalchemy import Text, cast, inspect, select, text
from sqlalchemy.orm import Session

from services.shared import models  # noqa: F401
from services.shared.database import Base, engine

FINANCIAL_PRESENCE_FIELDS = (
    "revenue_growth",
    "profit_growth",
    "roe",
    "gross_margin",
    "net_margin",
    "debt_ratio",
    "operating_revenue",
    "parent_net_profit",
    "deducted_parent_net_profit",
    "operating_cash_flow",
)


def _conservative_financial_available_date(report_date: date) -> date:
    return {
        3: date(report_date.year, 4, 30),
        6: date(report_date.year, 8, 31),
        9: date(report_date.year, 10, 31),
        12: date(report_date.year + 1, 4, 30),
    }[report_date.month]


def _cleanup_legacy_mixed_fundamental_snapshots(db: Session) -> int:
    rows = db.execute(
        select(models.FundamentalSnapshot).where(
            cast(models.FundamentalSnapshot.extra_json, Text).like(
                "%akshare.stock_value_em%"
            )
        )
    ).scalars()
    changed = 0
    for row in rows:
        if (row.extra_json or {}).get("source") != "akshare.stock_value_em":
            continue
        if not any(getattr(row, field) is not None for field in FINANCIAL_PRESENCE_FIELDS):
            continue
        try:
            row.available_date = _conservative_financial_available_date(row.report_date)
        except KeyError:
            continue
        row.pe_ttm = None
        row.pb = None
        row.dividend_yield = None
        row.extra_json = {
            "source": "legacy_mixed_snapshot",
            "availability_quality": "legacy_conservative_date",
        }
        changed += 1
    return changed


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
        _add_mysql_column_if_missing(
            "fundamental_snapshots", "operating_revenue", "NUMERIC(24, 4) NULL"
        )
        _add_mysql_column_if_missing(
            "fundamental_snapshots", "parent_net_profit", "NUMERIC(24, 4) NULL"
        )
        _add_mysql_column_if_missing(
            "fundamental_snapshots",
            "deducted_parent_net_profit",
            "NUMERIC(24, 4) NULL",
        )
        _add_mysql_column_if_missing(
            "fundamental_snapshots", "operating_cash_flow", "NUMERIC(24, 4) NULL"
        )
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
        with Session(engine) as db:
            _cleanup_legacy_mixed_fundamental_snapshots(db)
            db.commit()
        _execute_mysql(
            "ALTER TABLE candidate_discovery_snapshots "
            "MODIFY COLUMN discovery_json LONGTEXT NOT NULL"
        )
        _execute_mysql("ALTER TABLE review_reports MODIFY COLUMN content_md LONGTEXT NOT NULL")
        _execute_mysql("ALTER TABLE review_reports MODIFY COLUMN metrics_json LONGTEXT NOT NULL")


if __name__ == "__main__":
    main()
