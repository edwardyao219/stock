from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import requests


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


@dataclass(frozen=True)
class RealtimeQuoteRow:
    symbol: str
    trade_date: str
    quote_time: datetime
    price: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    pre_close: Decimal | None
    pct_change: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    turnover_rate: Decimal | None
    source: str = "akshare.stock_zh_a_spot_em"


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


def _market_prefix_for_symbol(symbol: str) -> str:
    exchange = _exchange_for_symbol(symbol)
    if exchange == "SH":
        return "sh"
    if exchange == "SZ":
        return "sz"
    if exchange == "BJ":
        return "bj"
    return ""


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


def fetch_realtime_quotes(
    symbols: set[str] | None = None,
    quote_time: datetime | None = None,
) -> list[RealtimeQuoteRow]:
    ak = _akshare()
    current_time = quote_time or datetime.utcnow()
    try:
        df = ak.stock_zh_a_spot_em()
    except Exception:
        if symbols:
            return fetch_sina_realtime_quotes(symbols=symbols, quote_time=current_time)
        raise
    rows: list[RealtimeQuoteRow] = []
    for raw in df.to_dict("records"):
        symbol = str(_first(raw, "代码", "股票代码") or "").strip()
        if not symbol or (symbols and symbol not in symbols):
            continue
        rows.append(
            RealtimeQuoteRow(
                symbol=symbol,
                trade_date=current_time.date().isoformat(),
                quote_time=current_time,
                price=_decimal(_first(raw, "最新价", "最新")),
                open=_decimal(_first(raw, "今开", "开盘")),
                high=_decimal(_first(raw, "最高")),
                low=_decimal(_first(raw, "最低")),
                pre_close=_decimal(_first(raw, "昨收")),
                pct_change=_decimal(_first(raw, "涨跌幅")),
                volume=_decimal(_first(raw, "成交量")),
                amount=_decimal(_first(raw, "成交额")),
                turnover_rate=_decimal(_first(raw, "换手率")),
            )
        )
    return rows


def fetch_sina_realtime_quotes(
    symbols: set[str],
    quote_time: datetime | None = None,
) -> list[RealtimeQuoteRow]:
    current_time = quote_time or datetime.utcnow()
    sina_symbols = [
        f"{_market_prefix_for_symbol(symbol)}{symbol}"
        for symbol in sorted(symbols)
        if _market_prefix_for_symbol(symbol)
    ]
    if not sina_symbols:
        return []
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        "https://hq.sinajs.cn/list=" + ",".join(sina_symbols),
        headers={"Referer": "https://finance.sina.com.cn"},
        timeout=10,
    )
    response.raise_for_status()
    response.encoding = "gbk"

    rows: list[RealtimeQuoteRow] = []
    for line in response.text.splitlines():
        if '="' not in line:
            continue
        symbol_code = line.split("=", 1)[0].removeprefix("var hq_str_")[-6:]
        payload = line.split('"', 2)[1]
        parts = payload.split(",")
        if len(parts) < 32 or not parts[0]:
            continue
        parsed_quote_time = current_time
        if parts[30] and parts[31]:
            try:
                parsed_quote_time = datetime.fromisoformat(f"{parts[30]}T{parts[31]}")
            except ValueError:
                parsed_quote_time = current_time
        rows.append(
            RealtimeQuoteRow(
                symbol=symbol_code,
                trade_date=parsed_quote_time.date().isoformat(),
                quote_time=parsed_quote_time,
                price=_decimal(parts[3]),
                open=_decimal(parts[1]),
                high=_decimal(parts[4]),
                low=_decimal(parts[5]),
                pre_close=_decimal(parts[2]),
                pct_change=None,
                volume=_decimal(parts[8]),
                amount=_decimal(parts[9]),
                turnover_rate=None,
                source="sina.hq",
            )
        )
    return rows


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
