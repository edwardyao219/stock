from __future__ import annotations

from datetime import date
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
