from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

PERCENT_FIELDS = {
    "TOTALOPERATEREVETZ": "revenue_growth",
    "PARENTNETPROFITTZ": "profit_growth",
    "ROEJQ": "roe",
    "XSMLL": "gross_margin",
    "XSJLL": "net_margin",
    "ZCFZL": "debt_ratio",
}

BANK_EXTRA_FIELDS = {
    "NET_INTEREST_SPREAD": "net_interest_spread",
    "NET_INTEREST_MARGIN": "net_interest_margin",
    "NONPERLOAN": "nonperforming_loan_ratio",
    "LOAN_PROVISION_RATIO": "loan_provision_ratio",
}

VALUATION_FIELDS = {
    "PE(TTM)": "pe_ttm",
    "市净率": "pb",
}


def market_symbol(symbol: str) -> str:
    code = str(symbol).strip()
    if "." in code:
        return code.upper()
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return code


def _akshare() -> Any:
    import akshare as ak

    return ak


def _parse_date(value: Any) -> date | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return pd.to_datetime(value).date()


def _decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _percent(value: Any) -> Decimal | None:
    number = _decimal(value)
    if number is None:
        return None
    return number / Decimal("100")


def _annualized_roe(report_date: date, roe: Decimal | None) -> Decimal | None:
    if roe is None:
        return None
    if report_date.month == 3:
        return roe * Decimal("4")
    if report_date.month == 6:
        return roe * Decimal("2")
    if report_date.month == 9:
        return roe * Decimal("1.333333")
    return roe


def snapshot_from_indicator_row(symbol: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    report_date = _parse_date(raw.get("REPORT_DATE"))
    if report_date is None:
        return None

    available_date = (
        _parse_date(raw.get("NOTICE_DATE"))
        or _parse_date(raw.get("UPDATE_DATE"))
        or report_date
    )
    row: dict[str, Any] = {
        "symbol": symbol,
        "report_date": report_date.isoformat(),
        "available_date": available_date.isoformat(),
        "extra_json": {
            "source": "akshare.stock_financial_analysis_indicator_em",
            "notice_date": available_date.isoformat(),
        },
    }

    for source_field, target_field in PERCENT_FIELDS.items():
        row[target_field] = _percent(raw.get(source_field))

    roe_kcj = _percent(raw.get("ROEKCJQ"))
    if row.get("roe") is None and roe_kcj is not None:
        row["roe"] = roe_kcj
    roe_annualized = _annualized_roe(report_date, row.get("roe"))
    if roe_annualized is not None:
        row["extra_json"]["roe_annualized"] = str(roe_annualized)

    for source_field, target_field in BANK_EXTRA_FIELDS.items():
        value = _percent(raw.get(source_field))
        if value is not None:
            row["extra_json"][target_field] = str(value)

    return row


def snapshot_from_valuation_row(symbol: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    trade_date = _parse_date(raw.get("数据日期"))
    if trade_date is None:
        return None

    row: dict[str, Any] = {
        "symbol": symbol,
        "report_date": trade_date.isoformat(),
        "available_date": trade_date.isoformat(),
        "extra_json": {
            "source": "akshare.stock_value_em",
            "valuation_date": trade_date.isoformat(),
            "close": str(_decimal(raw.get("当日收盘价")) or ""),
            "market_cap": str(_decimal(raw.get("总市值")) or ""),
            "float_market_cap": str(_decimal(raw.get("流通市值")) or ""),
        },
    }

    for source_field, target_field in VALUATION_FIELDS.items():
        row[target_field] = _decimal(raw.get(source_field))
    row["dividend_yield"] = _decimal(raw.get("DIVIDEND_YIELD_TTM"))
    cash_ttm = _decimal(raw.get("DIVIDEND_CASH_TTM"))
    if cash_ttm is not None:
        row["extra_json"]["dividend_cash_ttm"] = str(cash_ttm)

    return row


def dividend_events_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in rows:
        ex_date = _parse_date(raw.get("除权除息日") or raw.get("除权日"))
        cash_per_10 = _decimal(raw.get("派息") or raw.get("派息比例"))
        if ex_date is None or cash_per_10 is None or cash_per_10 <= 0:
            continue
        events.append(
            {
                "ex_date": ex_date,
                "cash_per_share": cash_per_10 / Decimal("10"),
                "cash_per_10": cash_per_10,
            }
        )
    return sorted(events, key=lambda item: item["ex_date"])


def apply_dividend_yield_to_valuation_rows(
    valuation_rows: list[dict[str, Any]],
    dividend_events: list[dict[str, Any]],
    window_days: int = 365,
) -> list[dict[str, Any]]:
    enriched = []
    for row in valuation_rows:
        trade_date = _parse_date(row.get("数据日期"))
        close = _decimal(row.get("当日收盘价"))
        if trade_date is None or close is None or close <= 0:
            enriched.append(row)
            continue

        window_start = trade_date - timedelta(days=window_days)
        cash_sum = sum(
            event["cash_per_share"]
            for event in dividend_events
            if window_start < event["ex_date"] <= trade_date
        )
        copied = dict(row)
        if cash_sum > 0:
            copied["DIVIDEND_YIELD_TTM"] = cash_sum / close
            copied["DIVIDEND_CASH_TTM"] = cash_sum
        enriched.append(copied)
    return enriched


def fetch_financial_indicator_snapshots(symbol: str) -> list[dict[str, Any]]:
    ak = _akshare()
    df = ak.stock_financial_analysis_indicator_em(
        symbol=market_symbol(symbol),
        indicator="按报告期",
    )
    rows: list[dict[str, Any]] = []
    for raw in df.to_dict("records"):
        snapshot = snapshot_from_indicator_row(symbol, raw)
        if snapshot is not None:
            rows.append(snapshot)
    return rows


def fetch_valuation_snapshots(symbol: str) -> list[dict[str, Any]]:
    ak = _akshare()
    df = ak.stock_value_em(symbol=symbol)
    rows: list[dict[str, Any]] = []
    for raw in df.to_dict("records"):
        snapshot = snapshot_from_valuation_row(symbol, raw)
        if snapshot is not None:
            rows.append(snapshot)
    return rows


def fetch_dividend_adjusted_valuation_snapshots(symbol: str) -> list[dict[str, Any]]:
    ak = _akshare()
    valuation_df = ak.stock_value_em(symbol=symbol)
    dividend_df = ak.stock_history_dividend_detail(symbol=symbol, indicator="分红")
    dividend_events = dividend_events_from_rows(dividend_df.to_dict("records"))
    valuation_rows = apply_dividend_yield_to_valuation_rows(
        valuation_df.to_dict("records"),
        dividend_events,
    )
    rows: list[dict[str, Any]] = []
    for raw in valuation_rows:
        snapshot = snapshot_from_valuation_row(symbol, raw)
        if snapshot is not None:
            rows.append(snapshot)
    return rows
