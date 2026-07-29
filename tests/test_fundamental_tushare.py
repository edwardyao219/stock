from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.collector import tushare_proxy_client as client
from services.engine.fundamental import sync as fundamental_sync
from services.engine.fundamental.sync import merge_financial_sources
from services.shared.database import Base
from services.shared.models import FundamentalSnapshot


def test_fetch_tushare_financial_snapshots_merges_three_statements(monkeypatch) -> None:
    from services.engine.fundamental.tushare_client import (
        fetch_tushare_financial_snapshots,
    )

    responses = {
        "fina_indicator": client.TushareResponse(
            fields=[
                "ts_code",
                "ann_date",
                "end_date",
                "q_sales_yoy",
                "q_profit_yoy",
                "roe",
                "grossprofit_margin",
                "netprofit_margin",
                "debt_to_assets",
                "profit_dedt",
            ],
            items=[
                [
                    "002558.SZ",
                    "20260424",
                    "20260331",
                    "221.7",
                    "210.5",
                    "6.81",
                    "95.38",
                    "50.07",
                    "19.86",
                    "270",
                ]
            ],
            has_more=False,
            count=1,
        ),
        "income": client.TushareResponse(
            fields=[
                "ts_code",
                "ann_date",
                "f_ann_date",
                "end_date",
                "total_revenue",
                "n_income_attr_p",
            ],
            items=[
                [
                    "002558.SZ",
                    "20260424",
                    "20260425",
                    "20260331",
                    "1000",
                    "300",
                ]
            ],
            has_more=False,
            count=1,
        ),
        "cashflow": client.TushareResponse(
            fields=["ts_code", "f_ann_date", "end_date", "n_cashflow_act"],
            items=[["002558.SZ", "20260425", "20260331", "330"]],
            has_more=False,
            count=1,
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_query(api_name: str, params=None):
        calls.append((api_name, dict(params or {})))
        return responses[api_name]

    monkeypatch.setattr(client, "query", fake_query)

    rows = fetch_tushare_financial_snapshots("002558")

    assert calls == [
        ("fina_indicator", {"ts_code": "002558.SZ"}),
        ("income", {"ts_code": "002558.SZ", "report_type": "1"}),
        ("cashflow", {"ts_code": "002558.SZ", "report_type": "1"}),
    ]
    assert len(rows) == 1
    assert rows[0]["report_date"] == "2026-03-31"
    assert rows[0]["available_date"] == "2026-04-25"
    assert rows[0]["revenue_growth"] == Decimal("2.217")
    assert rows[0]["profit_growth"] == Decimal("2.105")
    assert rows[0]["roe"] == Decimal("0.0681")
    assert rows[0]["gross_margin"] == Decimal("0.9538")
    assert rows[0]["net_margin"] == Decimal("0.5007")
    assert rows[0]["debt_ratio"] == Decimal("0.1986")
    assert rows[0]["operating_revenue"] == Decimal("1000")
    assert rows[0]["parent_net_profit"] == Decimal("300")
    assert rows[0]["deducted_parent_net_profit"] == Decimal("270")
    assert rows[0]["operating_cash_flow"] == Decimal("330")
    assert rows[0]["extra_json"] == {
        "source": "tushare_proxy",
        "field_sources": {
            "deducted_parent_net_profit": "fina_indicator",
            "operating_cash_flow": "cashflow",
            "operating_revenue": "income",
            "parent_net_profit": "income",
        },
    }


def test_tushare_financial_snapshots_keep_invalid_values_missing(monkeypatch) -> None:
    from services.engine.fundamental.tushare_client import (
        fetch_tushare_financial_snapshots,
    )

    empty = client.TushareResponse(fields=[], items=[], has_more=False, count=0)
    indicator = client.TushareResponse(
        fields=["ann_date", "end_date", "q_sales_yoy", "profit_dedt"],
        items=[["20260424", "20260331", "invalid", None]],
        has_more=False,
        count=1,
    )
    monkeypatch.setattr(
        client,
        "query",
        lambda api_name, params=None: indicator if api_name == "fina_indicator" else empty,
    )

    rows = fetch_tushare_financial_snapshots("002558")

    assert rows[0]["revenue_growth"] is None
    assert rows[0]["deducted_parent_net_profit"] is None
    assert rows[0]["available_date"] == "2026-04-24"


def test_merge_financial_sources_fills_only_missing_tushare_fields() -> None:
    rows = merge_financial_sources(
        [
            {
                "symbol": "002558",
                "report_date": "2026-03-31",
                "available_date": "2026-04-25",
                "parent_net_profit": Decimal("300"),
                "operating_cash_flow": None,
                "extra_json": {"source": "tushare_proxy"},
            }
        ],
        [
            {
                "symbol": "002558",
                "report_date": "2026-03-31",
                "available_date": "2026-04-24",
                "parent_net_profit": Decimal("999"),
                "operating_cash_flow": Decimal("330"),
                "extra_json": {"source": "akshare"},
            }
        ],
    )

    assert rows[0]["available_date"] == "2026-04-25"
    assert rows[0]["parent_net_profit"] == Decimal("300")
    assert rows[0]["operating_cash_flow"] == Decimal("330")
    assert rows[0]["extra_json"]["source"] == "merged"


def test_sync_fundamentals_keeps_tushare_rows_when_akshare_fails(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(fundamental_sync, "SessionLocal", session_factory)
    monkeypatch.setattr(
        fundamental_sync,
        "fetch_tushare_financial_snapshots",
        lambda symbol: [
            {
                "symbol": symbol,
                "report_date": "2026-03-31",
                "available_date": "2026-04-25",
                "parent_net_profit": 300,
                "extra_json": {"source": "tushare_proxy"},
            }
        ],
    )
    monkeypatch.setattr(
        fundamental_sync,
        "fetch_financial_indicator_snapshots",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("AkShare unavailable")),
    )

    result = fundamental_sync.sync_fundamentals(["002558"])

    with Session(engine) as db:
        row = db.query(FundamentalSnapshot).one()
    assert result["ok"] == 1
    assert row.parent_net_profit == Decimal("300.0000")
    assert row.extra_json["source"] == "tushare_proxy"


def test_sync_fundamentals_falls_back_when_tushare_fails(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(fundamental_sync, "SessionLocal", session_factory)
    monkeypatch.setattr(
        fundamental_sync,
        "fetch_tushare_financial_snapshots",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("Tushare unavailable")),
    )
    monkeypatch.setattr(
        fundamental_sync,
        "fetch_financial_indicator_snapshots",
        lambda symbol: [
            {
                "symbol": symbol,
                "report_date": "2026-03-31",
                "available_date": "2026-04-24",
                "operating_cash_flow": 330,
                "extra_json": {"source": "akshare"},
            }
        ],
    )

    result = fundamental_sync.sync_fundamentals(["002558"])

    with Session(engine) as db:
        row = db.query(FundamentalSnapshot).one()
    assert result["ok"] == 1
    assert row.operating_cash_flow == Decimal("330.0000")
    assert row.extra_json["source"] == "akshare"
