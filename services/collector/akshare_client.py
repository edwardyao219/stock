from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class AShareSecurity:
    symbol: str
    name: str
    exchange: str
    is_st: bool
    is_active: bool = True


@dataclass(frozen=True)
class IndustryBoard:
    code: str
    name: str


@dataclass(frozen=True)
class IndustryConstituent:
    board_code: str
    board_name: str
    symbol: str
    name: str
    exchange: str
    is_st: bool


@dataclass(frozen=True)
class DailyBarRow:
    symbol: str
    trade_date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    pre_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    turnover_rate: Decimal | None


@dataclass(frozen=True)
class IndexDailyRow:
    symbol: str
    trade_date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    amount: Decimal | None


def _akshare() -> Any:
    import akshare as ak

    return ak


def _decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    return Decimal(str(value))


def _exchange_for_symbol(symbol: str) -> str:
    if symbol.startswith(("6", "9")):
        return "SH"
    if symbol.startswith(("0", "2", "3")):
        return "SZ"
    if symbol.startswith(("4", "8")):
        return "BJ"
    return "UNKNOWN"


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value is not None and not pd.isna(value) and str(value).strip() != "":
            return value
    return None


def fetch_trade_dates() -> list[str]:
    ak = _akshare()
    df = ak.tool_trade_date_hist_sina()
    if "trade_date" in df.columns:
        column = "trade_date"
    else:
        column = df.columns[0]
    return pd.to_datetime(df[column]).dt.date.astype(str).tolist()


def fetch_a_share_securities() -> list[AShareSecurity]:
    ak = _akshare()
    df = ak.stock_zh_a_spot_em()
    securities: list[AShareSecurity] = []
    for row in df.to_dict("records"):
        symbol = str(row.get("代码", "")).strip()
        name = str(row.get("名称", "")).strip()
        if not symbol or not name:
            continue
        securities.append(
            AShareSecurity(
                symbol=symbol,
                name=name,
                exchange=_exchange_for_symbol(symbol),
                is_st="ST" in name.upper(),
            )
        )
    return securities


def fetch_industry_boards() -> list[IndustryBoard]:
    ak = _akshare()
    df = ak.stock_board_industry_name_em()
    boards: list[IndustryBoard] = []
    for raw in df.to_dict("records"):
        name = str(_first(raw, "板块名称", "名称", "行业名称") or "").strip()
        code = str(_first(raw, "板块代码", "代码", "行业代码") or name).strip()
        if not name:
            continue
        boards.append(IndustryBoard(code=code, name=name))
    return boards


def fetch_industry_constituents(board: IndustryBoard) -> list[IndustryConstituent]:
    ak = _akshare()
    df = ak.stock_board_industry_cons_em(symbol=board.name)
    constituents: list[IndustryConstituent] = []
    for raw in df.to_dict("records"):
        symbol = str(_first(raw, "代码", "股票代码") or "").strip()
        name = str(_first(raw, "名称", "股票名称") or "").strip()
        if not symbol or not name:
            continue
        constituents.append(
            IndustryConstituent(
                board_code=board.code,
                board_name=board.name,
                symbol=symbol,
                name=name,
                exchange=_exchange_for_symbol(symbol),
                is_st="ST" in name.upper(),
            )
        )
    return constituents


def fetch_stock_daily_bars(symbol: str, start_date: str, end_date: str) -> list[DailyBarRow]:
    ak = _akshare()
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )
    rows: list[DailyBarRow] = []
    previous_close: Decimal | None = None
    for raw in df.to_dict("records"):
        close = _decimal(raw.get("收盘"))
        if close is None:
            continue
        rows.append(
            DailyBarRow(
                symbol=symbol,
                trade_date=pd.to_datetime(raw.get("日期")).date().isoformat(),
                open=_decimal(raw.get("开盘")) or close,
                high=_decimal(raw.get("最高")) or close,
                low=_decimal(raw.get("最低")) or close,
                close=close,
                pre_close=previous_close,
                volume=_decimal(raw.get("成交量")),
                amount=_decimal(raw.get("成交额")),
                turnover_rate=_decimal(raw.get("换手率")),
            )
        )
        previous_close = close
    return rows


def fetch_index_daily_bars(symbol: str, start_date: str, end_date: str) -> list[IndexDailyRow]:
    ak = _akshare()
    df = ak.index_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
    )
    rows: list[IndexDailyRow] = []
    for raw in df.to_dict("records"):
        close = _decimal(raw.get("收盘"))
        if close is None:
            continue
        rows.append(
            IndexDailyRow(
                symbol=symbol,
                trade_date=pd.to_datetime(raw.get("日期")).date().isoformat(),
                open=_decimal(raw.get("开盘")) or close,
                high=_decimal(raw.get("最高")) or close,
                low=_decimal(raw.get("最低")) or close,
                close=close,
                volume=_decimal(raw.get("成交量")),
                amount=_decimal(raw.get("成交额")),
            )
        )
    return rows
