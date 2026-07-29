from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from services.collector import tushare_proxy_client as client
from services.engine.fundamental.akshare_client import market_symbol


def _decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _percent(value: Any) -> Decimal | None:
    number = _decimal(value)
    return number / Decimal("100") if number is not None else None


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _query_rows(api_name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    response = client.query(api_name, params=params)
    if response.has_more:
        raise RuntimeError(f"incomplete Tushare {api_name} response")
    return [dict(zip(response.fields, item, strict=False)) for item in response.items]


def _report_date(row: dict[str, Any]) -> str | None:
    return _date(row.get("end_date"))


def _available_date(row: dict[str, Any]) -> str | None:
    return _date(row.get("f_ann_date")) or _date(row.get("ann_date"))


def merge_tushare_financial_rows(
    symbol: str,
    indicators: list[dict[str, Any]],
    incomes: list[dict[str, Any]],
    cashflows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for raw in indicators:
        report_date = _report_date(raw)
        if report_date is None:
            continue
        merged[report_date] = {
            "symbol": symbol,
            "report_date": report_date,
            "available_date": _available_date(raw) or report_date,
            "revenue_growth": _percent(raw.get("q_sales_yoy")),
            "profit_growth": _percent(raw.get("q_profit_yoy")),
            "roe": _percent(raw.get("roe")),
            "gross_margin": _percent(raw.get("grossprofit_margin")),
            "net_margin": _percent(raw.get("netprofit_margin")),
            "debt_ratio": _percent(raw.get("debt_to_assets")),
            "deducted_parent_net_profit": _decimal(raw.get("profit_dedt")),
            "extra_json": {
                "source": "tushare_proxy",
                "field_sources": {},
            },
        }
        if merged[report_date]["deducted_parent_net_profit"] is not None:
            merged[report_date]["extra_json"]["field_sources"][
                "deducted_parent_net_profit"
            ] = "fina_indicator"

    for raw in incomes:
        report_date = _report_date(raw)
        if report_date not in merged:
            continue
        row = merged[report_date]
        announcement = _available_date(raw)
        if announcement and announcement > str(row["available_date"]):
            row["available_date"] = announcement
        for source_field, target_field in (
            ("total_revenue", "operating_revenue"),
            ("n_income_attr_p", "parent_net_profit"),
        ):
            value = _decimal(raw.get(source_field))
            row[target_field] = value
            if value is not None:
                row["extra_json"]["field_sources"][target_field] = "income"

    for raw in cashflows:
        report_date = _report_date(raw)
        if report_date not in merged:
            continue
        row = merged[report_date]
        announcement = _available_date(raw)
        if announcement and announcement > str(row["available_date"]):
            row["available_date"] = announcement
        value = _decimal(raw.get("n_cashflow_act"))
        row["operating_cash_flow"] = value
        if value is not None:
            row["extra_json"]["field_sources"]["operating_cash_flow"] = "cashflow"

    return [merged[key] for key in sorted(merged, reverse=True)]


def fetch_tushare_financial_snapshots(symbol: str) -> list[dict[str, Any]]:
    ts_code = market_symbol(symbol)
    indicators = _query_rows("fina_indicator", {"ts_code": ts_code})
    incomes = _query_rows("income", {"ts_code": ts_code, "report_type": "1"})
    cashflows = _query_rows("cashflow", {"ts_code": ts_code, "report_type": "1"})
    return merge_tushare_financial_rows(symbol, indicators, incomes, cashflows)
