from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.fundamental.akshare_client import (
    apply_dividend_yield_to_valuation_rows,
    dividend_events_from_rows,
    market_symbol,
    merge_financial_statement_rows,
    snapshot_from_indicator_row,
    snapshot_from_valuation_row,
    statement_market_symbol,
)
from services.engine.fundamental.repository import (
    load_fundamental_context,
    load_latest_fundamental_snapshot,
    snapshot_to_context,
    upsert_fundamental_snapshots,
    upsert_valuation_snapshots,
)
from services.shared.database import Base
from services.shared.models import FundamentalSnapshot


def test_market_symbol_for_akshare_financial_indicator() -> None:
    assert market_symbol("600519") == "600519.SH"
    assert market_symbol("000001") == "000001.SZ"
    assert market_symbol("300750") == "300750.SZ"


def test_akshare_statement_rows_merge_by_report_date_and_map_quality_fields() -> None:
    assert statement_market_symbol("002558") == "SZ002558"
    rows = merge_financial_statement_rows(
        [{"REPORT_DATE": "2026-03-31", "TOTALOPERATEREVETZ": "5.2"}],
        [
            {
                "REPORT_DATE": "2026-03-31",
                "TOTAL_OPERATE_INCOME": "1000",
                "PARENT_NETPROFIT": "300",
                "DEDUCT_PARENT_NETPROFIT": "270",
            }
        ],
        [{"REPORT_DATE": "2026-03-31", "NETCASH_OPERATE": "330"}],
    )

    snapshot = snapshot_from_indicator_row("002558", rows[0])

    assert snapshot is not None
    assert snapshot["operating_revenue"] == Decimal("1000")
    assert snapshot["parent_net_profit"] == Decimal("300")
    assert snapshot["deducted_parent_net_profit"] == Decimal("270")
    assert snapshot["operating_cash_flow"] == Decimal("330")


def test_snapshot_from_indicator_row_maps_announcement_timing_and_bank_fields() -> None:
    snapshot = snapshot_from_indicator_row(
        "000001",
        {
            "REPORT_DATE": "2026-03-31",
            "NOTICE_DATE": "2026-04-24",
            "TOTALOPERATEREVETZ": "5.2",
            "PARENTNETPROFITTZ": "3.1",
            "ROEJQ": "11.5",
            "ZCFZL": "91.2",
            "NET_INTEREST_MARGIN": "2.03",
            "NONPERLOAN": "1.06",
            "LOAN_PROVISION_RATIO": "2.31",
        },
    )

    assert snapshot is not None
    assert snapshot["report_date"] == "2026-03-31"
    assert snapshot["available_date"] == "2026-04-24"
    assert snapshot["revenue_growth"] == Decimal("0.052")
    assert snapshot["profit_growth"] == Decimal("0.031")
    assert snapshot["roe"] == Decimal("0.115")
    assert snapshot["debt_ratio"] == Decimal("0.912")
    assert snapshot["extra_json"]["roe_annualized"] == "0.460"
    assert snapshot["extra_json"]["net_interest_margin"] == "0.0203"
    assert snapshot["extra_json"]["nonperforming_loan_ratio"] == "0.0106"
    assert snapshot["extra_json"]["loan_provision_ratio"] == "0.0231"


def test_snapshot_from_valuation_row_maps_daily_pb_and_pe() -> None:
    snapshot = snapshot_from_valuation_row(
        "000001",
        {
            "数据日期": "2026-06-23",
            "当日收盘价": "11.50",
            "PE(TTM)": "5.2",
            "市净率": "0.62",
            "DIVIDEND_YIELD_TTM": "0.055",
            "DIVIDEND_CASH_TTM": "0.6325",
            "总市值": "223000000000",
            "流通市值": "222000000000",
        },
    )

    assert snapshot is not None
    assert snapshot["report_date"] == "2026-06-23"
    assert snapshot["available_date"] == "2026-06-23"
    assert snapshot["pe_ttm"] == Decimal("5.2")
    assert snapshot["pb"] == Decimal("0.62")
    assert snapshot["dividend_yield"] == Decimal("0.055")
    assert snapshot["extra_json"]["dividend_cash_ttm"] == "0.6325"
    assert snapshot["extra_json"]["source"] == "akshare.stock_value_em"


def test_dividend_yield_uses_only_ex_dates_available_before_trade_date() -> None:
    events = dividend_events_from_rows(
        [
            {"除权除息日": "2025-06-12", "派息": "3.60"},
            {"除权除息日": "2025-10-15", "派息": "2.36"},
            {"除权除息日": "2026-06-12", "派息": "3.62"},
            {"除权除息日": "2026-10-15", "派息": "2.50"},
        ]
    )
    rows = apply_dividend_yield_to_valuation_rows(
        [
            {"数据日期": "2026-06-11", "当日收盘价": "10.00"},
            {"数据日期": "2026-06-13", "当日收盘价": "10.00"},
        ],
        events,
    )

    assert rows[0]["DIVIDEND_CASH_TTM"] == Decimal("0.596")
    assert rows[0]["DIVIDEND_YIELD_TTM"] == Decimal("0.0596")
    assert rows[1]["DIVIDEND_CASH_TTM"] == Decimal("0.598")
    assert rows[1]["DIVIDEND_YIELD_TTM"] == Decimal("0.0598")


def test_load_latest_fundamental_snapshot_uses_available_date_to_avoid_leakage() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        upsert_fundamental_snapshots(
            db,
            [
                {
                    "symbol": "000001",
                    "report_date": "2025-12-31",
                    "available_date": "2026-03-20",
                    "roe": 0.10,
                },
                {
                    "symbol": "000001",
                    "report_date": "2026-03-31",
                    "available_date": "2026-04-24",
                    "roe": 0.12,
                },
            ],
        )
        db.commit()

        before_notice = load_latest_fundamental_snapshot(db, "000001", date(2026, 4, 1))
        after_notice = load_latest_fundamental_snapshot(db, "000001", date(2026, 4, 25))

    assert before_notice is not None
    assert before_notice.report_date == date(2025, 12, 31)
    assert float(before_notice.roe) == 0.10
    assert after_notice is not None
    assert after_notice.report_date == date(2026, 3, 31)
    assert snapshot_to_context(after_notice)["fundamental_available_date"] == "2026-04-24"


def test_load_fundamental_context_ignores_legacy_valuation_snapshots() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        upsert_fundamental_snapshots(
            db,
            [
                {
                    "symbol": "000001",
                    "report_date": "2026-03-31",
                    "available_date": "2026-04-24",
                    "roe": 0.0283,
                },
            ],
        )
        upsert_valuation_snapshots(
            db,
            [
                {
                    "symbol": "000001",
                    "report_date": "2026-06-23",
                    "available_date": "2026-06-23",
                    "pb": 0.62,
                    "pe_ttm": 5.2,
                    "dividend_yield": 0.055,
                    "extra_json": {"source": "akshare.stock_value_em"},
                },
            ],
        )
        db.commit()

        context = load_fundamental_context(db, "000001", date(2026, 6, 23))

    assert context["fundamental_report_date"] == "2026-03-31"
    assert context["roe"] == 0.0283
    assert "valuation_date" not in context
    assert "pb" not in context
    assert "pe_ttm" not in context
    assert "dividend_yield" not in context


def test_financial_upsert_clears_colliding_valuation_and_keeps_quality_fields() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        upsert_valuation_snapshots(
            db,
            [
                {
                    "symbol": "002558",
                    "report_date": "2026-03-31",
                    "available_date": "2026-03-31",
                    "pe_ttm": 33.8,
                    "pb": 3.67,
                    "dividend_yield": 0.01,
                    "extra_json": {"source": "akshare.stock_value_em"},
                }
            ],
        )
        upsert_fundamental_snapshots(
            db,
            [
                {
                    "symbol": "002558",
                    "report_date": "2026-03-31",
                    "available_date": "2026-04-25",
                    "revenue_growth": 2.217,
                    "profit_growth": 2.105,
                    "operating_revenue": 1000,
                    "parent_net_profit": 300,
                    "deducted_parent_net_profit": 270,
                    "operating_cash_flow": 330,
                    "extra_json": {"source": "tushare_proxy"},
                }
            ],
        )
        db.commit()
        row = db.query(FundamentalSnapshot).one()

    assert row.available_date == date(2026, 4, 25)
    assert row.operating_revenue == Decimal("1000.0000")
    assert row.parent_net_profit == Decimal("300.0000")
    assert row.deducted_parent_net_profit == Decimal("270.0000")
    assert row.operating_cash_flow == Decimal("330.0000")
    assert row.pe_ttm is None
    assert row.pb is None
    assert row.dividend_yield is None
    assert row.extra_json == {"source": "tushare_proxy"}
