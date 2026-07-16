from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
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


_PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)


@contextmanager
def _without_proxy_env():
    previous = {key: os.environ.pop(key, None) for key in _PROXY_ENV_KEYS}
    original_session = requests.Session

    class _NoProxySession(original_session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.trust_env = False

    requests.Session = _NoProxySession
    requests.sessions.Session = _NoProxySession
    try:
        yield
    finally:
        requests.Session = original_session
        requests.sessions.Session = original_session
        for key, value in previous.items():
            if value is not None:
                os.environ[key] = value


def _decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    return Decimal(str(value))


def _exchange_for_symbol(symbol: str) -> str:
    if symbol.startswith("92"):
        return "BJ"
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


def _normalize_a_share_symbol(value: Any) -> str:
    symbol = str(value or "").strip()
    lowered = symbol.lower()
    if len(lowered) == 8 and lowered[:2] in {"sh", "sz", "bj"} and lowered[2:].isdigit():
        return lowered[2:]
    return symbol


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value is not None and not pd.isna(value) and str(value).strip() != "":
            return value
    return None


def fetch_trade_dates() -> list[str]:
    ak = _akshare()
    with _without_proxy_env():
        df = ak.tool_trade_date_hist_sina()
    if "trade_date" in df.columns:
        column = "trade_date"
    else:
        column = df.columns[0]
    return pd.to_datetime(df[column]).dt.date.astype(str).tolist()


def fetch_a_share_securities() -> list[AShareSecurity]:
    ak = _akshare()
    try:
        with _without_proxy_env():
            df = ak.stock_zh_a_spot_em()
    except Exception:
        with _without_proxy_env():
            df = ak.stock_info_a_code_name()
    securities: list[AShareSecurity] = []
    for row in df.to_dict("records"):
        symbol = str(_first(row, "代码", "code") or "").strip()
        name = str(_first(row, "名称", "name") or "").strip()
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


def fetch_stock_security(symbol: str) -> AShareSecurity:
    ak = _akshare()
    try:
        with _without_proxy_env():
            df = ak.stock_individual_info_em(symbol=symbol)
        raw = {
            str(item.get("item") or item.get("项目") or ""): item.get("value") or item.get("值")
            for item in df.to_dict("records")
        }
        name = str(raw.get("股票简称") or raw.get("简称") or raw.get("名称") or "").strip()
        if name:
            return AShareSecurity(
                symbol=symbol,
                name=name,
                exchange=_exchange_for_symbol(symbol),
                is_st="ST" in name.upper(),
            )
    except Exception:
        pass

    return fetch_eastmoney_stock_security(symbol)


def fetch_eastmoney_stock_security(symbol: str) -> AShareSecurity:
    secid = f"{'1' if symbol.startswith('6') else '0'}.{symbol}"
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        "https://push2.eastmoney.com/api/qt/stock/get",
        params={
            "fields": "f57,f58,f107,f127,f128,f129",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "secid": secid,
        },
        timeout=12,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    name = str(data.get("f58") or "").strip()
    if not name:
        raise ValueError(f"No security metadata returned for {symbol}")
    return AShareSecurity(
        symbol=str(data.get("f57") or symbol).strip(),
        name=name,
        exchange=_exchange_for_symbol(symbol),
        is_st="ST" in name.upper(),
    )


def fetch_realtime_quotes(
    symbols: set[str] | None = None,
    quote_time: datetime | None = None,
) -> list[RealtimeQuoteRow]:
    ak = _akshare()
    current_time = quote_time or datetime.utcnow()
    target_symbols = symbols or set()
    source = "akshare.stock_zh_a_spot_em"
    try:
        with _without_proxy_env():
            df = ak.stock_zh_a_spot_em()
    except Exception:
        if symbols and len(symbols) <= 200:
            return fetch_sina_realtime_quotes(symbols=symbols, quote_time=current_time)
        with _without_proxy_env():
            df = ak.stock_zh_a_spot()
        source = "akshare.stock_zh_a_spot"
    rows: list[RealtimeQuoteRow] = []
    for raw in df.to_dict("records"):
        symbol = _normalize_a_share_symbol(_first(raw, "代码", "股票代码"))
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
                source=source,
            )
        )

    matched_symbols = {row.symbol for row in rows}
    coverage_ratio = (
        len(matched_symbols & target_symbols) / len(target_symbols) if target_symbols else 1.0
    )
    if coverage_ratio >= 0.98:
        return rows

    # The legacy full-market endpoint can return a partial page set without raising.
    try:
        with _without_proxy_env():
            fallback_df = ak.stock_zh_a_spot()
    except Exception:
        return rows

    fallback_rows: list[RealtimeQuoteRow] = []
    for raw in fallback_df.to_dict("records"):
        symbol = _normalize_a_share_symbol(_first(raw, "代码", "股票代码"))
        if not symbol or (symbols and symbol not in symbols):
            continue
        fallback_rows.append(
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
                source="akshare.stock_zh_a_spot.retry",
            )
        )
    fallback_match_count = len({row.symbol for row in fallback_rows} & target_symbols)
    if fallback_match_count > len(matched_symbols & target_symbols):
        return fallback_rows
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
    with _without_proxy_env():
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
    with _without_proxy_env():
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
    try:
        with _without_proxy_env():
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
    except Exception:
        try:
            return fetch_sina_stock_daily_bars(symbol, start_date, end_date)
        except Exception:
            return fetch_eastmoney_stock_daily_bars(symbol, start_date, end_date)
    return _daily_bars_from_dataframe(symbol, df)


def _daily_bars_from_dataframe(symbol: str, df: pd.DataFrame) -> list[DailyBarRow]:
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


def fetch_eastmoney_stock_daily_bars(
    symbol: str,
    start_date: str,
    end_date: str,
) -> list[DailyBarRow]:
    secid = f"{'1' if symbol.startswith('6') else '0'}.{symbol}"
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": "101",
            "fqt": "1",
            "secid": secid,
            "beg": start_date,
            "end": end_date,
        },
        timeout=12,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    rows: list[DailyBarRow] = []
    previous_close: Decimal | None = None
    for line in data.get("klines") or []:
        parts = line.split(",")
        if len(parts) < 11:
            continue
        close = _decimal(parts[2])
        if close is None:
            continue
        rows.append(
            DailyBarRow(
                symbol=symbol,
                trade_date=parts[0],
                open=_decimal(parts[1]) or close,
                high=_decimal(parts[3]) or close,
                low=_decimal(parts[4]) or close,
                close=close,
                pre_close=previous_close,
                volume=_decimal(parts[5]),
                amount=_decimal(parts[6]),
                turnover_rate=_decimal(parts[10]),
            )
        )
        previous_close = close
    return rows


def fetch_sina_stock_daily_bars(
    symbol: str,
    start_date: str,
    end_date: str,
) -> list[DailyBarRow]:
    sina_symbol = f"{_market_prefix_for_symbol(symbol)}{symbol}"
    if not sina_symbol:
        return []
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/CN_MarketDataService.getKLineData",
        params={"symbol": sina_symbol, "scale": "240", "ma": "no", "datalen": "1500"},
        headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
        timeout=12,
    )
    response.raise_for_status()
    match = re.search(r"var _data=\((.*)\);?", response.text, flags=re.S)
    if not match:
        return []
    raw_rows = json.loads(match.group(1))
    rows: list[DailyBarRow] = []
    previous_close: Decimal | None = None
    parsed_start = datetime.strptime(start_date, "%Y%m%d").date()
    parsed_end = datetime.strptime(end_date, "%Y%m%d").date()
    for raw in raw_rows:
        trade_date = datetime.strptime(str(raw.get("day")), "%Y-%m-%d").date()
        if trade_date < parsed_start or trade_date > parsed_end:
            continue
        close = _decimal(raw.get("close"))
        if close is None:
            continue
        volume = _decimal(raw.get("volume"))
        rows.append(
            DailyBarRow(
                symbol=symbol,
                trade_date=trade_date.isoformat(),
                open=_decimal(raw.get("open")) or close,
                high=_decimal(raw.get("high")) or close,
                low=_decimal(raw.get("low")) or close,
                close=close,
                pre_close=previous_close,
                volume=volume,
                amount=None,
                turnover_rate=None,
            )
        )
        previous_close = close
    return rows


def fetch_index_daily_bars(symbol: str, start_date: str, end_date: str) -> list[IndexDailyRow]:
    ak = _akshare()
    with _without_proxy_env():
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
