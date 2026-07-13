from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from services.collector import tushare_proxy_client as client
from services.collector.akshare_client import DailyBarRow
from services.collector.repository import upsert_daily_bars
from services.shared.models import (
    Security,
    TushareCyqPerf,
    TushareDaily,
    TushareDailyBasic,
    TushareLimitListD,
    TushareMoneyflow,
    TushareMoneyflowDc,
    TushareMoneyflowIndDc,
    TushareStkLimit,
)
from services.shared.upsert import upsert_rows


def _date(value: Any) -> date:
    text = str(value)
    if "-" in text:
        return date.fromisoformat(text)
    return date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:8]}")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _integer(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _required_row_keys(row: dict[str, Any]) -> tuple[str, date]:
    ts_code = str(row.get("ts_code") or "").strip()
    raw_trade_date = row.get("trade_date")
    if not ts_code or not raw_trade_date:
        raise ValueError("Tushare row missing ts_code or trade_date")
    return ts_code, _date(raw_trade_date)


def _rows(fields: list[str], items: list[list[Any]]) -> list[dict[str, Any]]:
    return [dict(zip(fields, item, strict=False)) for item in items]


def _symbol_from_ts_code(value: Any) -> str:
    return str(value or "").split(".", 1)[0].strip()


def _daily_bar_rows_from_tushare(rows: list[dict[str, Any]]) -> list[DailyBarRow]:
    daily_rows: list[DailyBarRow] = []
    for row in rows:
        symbol = _symbol_from_ts_code(row.get("ts_code"))
        close = _decimal(row.get("close"))
        trade_date = row.get("trade_date")
        if not symbol or close is None or not trade_date:
            continue
        amount = _decimal(row.get("amount"))
        daily_rows.append(
            DailyBarRow(
                symbol=symbol,
                trade_date=_date(trade_date).isoformat(),
                open=_decimal(row.get("open")) or close,
                high=_decimal(row.get("high")) or close,
                low=_decimal(row.get("low")) or close,
                close=close,
                pre_close=_decimal(row.get("pre_close")),
                volume=_decimal(row.get("vol")),
                amount=amount * Decimal("1000") if amount is not None else None,
                turnover_rate=None,
            )
        )
    return daily_rows


def sync_tushare_daily(
    db,
    *,
    trade_date: str,
    ts_code: str | None = None,
) -> int:
    params = {"trade_date": trade_date}
    if ts_code:
        params["ts_code"] = ts_code
    response = client.query("daily", params=params)
    rows = []
    for row in _rows(response.fields, response.items):
        rows.append(
            {
                "ts_code": row.get("ts_code"),
                "trade_date": _date(row.get("trade_date")),
                "open": _decimal(row.get("open")),
                "high": _decimal(row.get("high")),
                "low": _decimal(row.get("low")),
                "close": _decimal(row.get("close")),
                "pre_close": _decimal(row.get("pre_close")),
                "change": _decimal(row.get("change")),
                "pct_chg": _decimal(row.get("pct_chg")),
                "vol": _decimal(row.get("vol")),
                "amount": _decimal(row.get("amount")),
            }
        )
    written = upsert_rows(
        db,
        TushareDaily,
        rows,
        update_columns=[
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
        ],
        constraint="uq_tushare_daily_code_date",
    )
    upsert_daily_bars(db, _daily_bar_rows_from_tushare(_rows(response.fields, response.items)))
    return written


def sync_tushare_index_daily(
    db,
    *,
    ts_code: str,
    start_date: str,
    end_date: str,
    symbol: str,
) -> int:
    response = client.query(
        "index_daily",
        params={
            "ts_code": ts_code,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    bars: list[DailyBarRow] = []
    for row in _rows(response.fields, response.items):
        close = _decimal(row.get("close"))
        trade_date = row.get("trade_date")
        if close is None or not trade_date:
            continue
        amount = _decimal(row.get("amount"))
        bars.append(
            DailyBarRow(
                symbol=symbol,
                trade_date=_date(trade_date).isoformat(),
                open=_decimal(row.get("open")) or close,
                high=_decimal(row.get("high")) or close,
                low=_decimal(row.get("low")) or close,
                close=close,
                pre_close=_decimal(row.get("pre_close")),
                volume=_decimal(row.get("vol")),
                amount=amount * Decimal("1000") if amount is not None else None,
                turnover_rate=None,
            )
        )
    return upsert_daily_bars(db, bars)


def sync_tushare_daily_basic(db, *, trade_date: str) -> int:
    response = client.query(
        "daily_basic",
        params={
            "trade_date": trade_date,
            "fields": "ts_code,trade_date,turnover_rate,volume_ratio,pe_ttm,pb,total_mv,circ_mv",
        },
    )
    rows = []
    for row in _rows(response.fields, response.items):
        rows.append(
            {
                "ts_code": row.get("ts_code"),
                "trade_date": _date(row.get("trade_date")),
                "turnover_rate": _decimal(row.get("turnover_rate")),
                "volume_ratio": _decimal(row.get("volume_ratio")),
                "pe_ttm": _decimal(row.get("pe_ttm")),
                "pb": _decimal(row.get("pb")),
                "total_mv": _decimal(row.get("total_mv")),
                "circ_mv": _decimal(row.get("circ_mv")),
            }
        )
    return upsert_rows(
        db,
        TushareDailyBasic,
        rows,
        update_columns=["turnover_rate", "volume_ratio", "pe_ttm", "pb", "total_mv", "circ_mv"],
        constraint="uq_tushare_daily_basic_code_date",
    )


def sync_tushare_stk_limit(db, *, trade_date: str) -> int:
    response = client.query("stk_limit", params={"trade_date": trade_date})
    rows = []
    for row in _rows(response.fields, response.items):
        rows.append(
            {
                "ts_code": row.get("ts_code"),
                "trade_date": _date(row.get("trade_date")),
                "up_limit": _decimal(row.get("up_limit")),
                "down_limit": _decimal(row.get("down_limit")),
            }
        )
    return upsert_rows(
        db,
        TushareStkLimit,
        rows,
        update_columns=["up_limit", "down_limit"],
        constraint="uq_tushare_stk_limit_code_date",
    )


def sync_tushare_moneyflow(db, *, trade_date: str) -> int:
    response = client.query("moneyflow", params={"trade_date": trade_date})
    rows = []
    for row in _rows(response.fields, response.items):
        rows.append(
            {
                "ts_code": row.get("ts_code"),
                "trade_date": _date(row.get("trade_date")),
                "buy_sm_amount": _decimal(row.get("buy_sm_amount")),
                "sell_sm_amount": _decimal(row.get("sell_sm_amount")),
                "buy_md_amount": _decimal(row.get("buy_md_amount")),
                "sell_md_amount": _decimal(row.get("sell_md_amount")),
                "buy_lg_amount": _decimal(row.get("buy_lg_amount")),
                "sell_lg_amount": _decimal(row.get("sell_lg_amount")),
                "buy_elg_amount": _decimal(row.get("buy_elg_amount")),
                "sell_elg_amount": _decimal(row.get("sell_elg_amount")),
                "net_mf_amount": _decimal(row.get("net_mf_amount")),
            }
        )
    return upsert_rows(
        db,
        TushareMoneyflow,
        rows,
        update_columns=[
            "buy_sm_amount",
            "sell_sm_amount",
            "buy_md_amount",
            "sell_md_amount",
            "buy_lg_amount",
            "sell_lg_amount",
            "buy_elg_amount",
            "sell_elg_amount",
            "net_mf_amount",
        ],
        constraint="uq_tushare_moneyflow_code_date",
    )


def sync_tushare_moneyflow_dc(db, *, trade_date: str) -> int:
    response = client.query("moneyflow_dc", params={"trade_date": trade_date})
    rows = []
    for row in _rows(response.fields, response.items):
        ts_code, row_date = _required_row_keys(row)
        rows.append(
            {
                "ts_code": ts_code,
                "trade_date": row_date,
                "name": row.get("name"),
                "pct_change": _decimal(row.get("pct_change")),
                "close": _decimal(row.get("close")),
                "net_amount": _decimal(row.get("net_amount")),
                "net_amount_rate": _decimal(row.get("net_amount_rate")),
                "buy_elg_amount": _decimal(row.get("buy_elg_amount")),
                "buy_elg_amount_rate": _decimal(row.get("buy_elg_amount_rate")),
                "buy_lg_amount": _decimal(row.get("buy_lg_amount")),
                "buy_lg_amount_rate": _decimal(row.get("buy_lg_amount_rate")),
                "buy_md_amount": _decimal(row.get("buy_md_amount")),
                "buy_md_amount_rate": _decimal(row.get("buy_md_amount_rate")),
                "buy_sm_amount": _decimal(row.get("buy_sm_amount")),
                "buy_sm_amount_rate": _decimal(row.get("buy_sm_amount_rate")),
            }
        )
    update_columns = (
        [key for key in rows[0] if key not in {"ts_code", "trade_date"}] if rows else []
    )
    return upsert_rows(
        db,
        TushareMoneyflowDc,
        rows,
        update_columns=update_columns,
        constraint="uq_tushare_moneyflow_dc_code_date",
        index_elements=["ts_code", "trade_date"],
    )


def sync_tushare_limit_list_d(db, *, trade_date: str) -> int:
    response = client.query("limit_list_d", params={"trade_date": trade_date})
    rows = []
    for row in _rows(response.fields, response.items):
        ts_code, row_date = _required_row_keys(row)
        rows.append(
            {
                "ts_code": ts_code,
                "trade_date": row_date,
                "industry": row.get("industry"),
                "name": row.get("name"),
                "close": _decimal(row.get("close")),
                "pct_chg": _decimal(row.get("pct_chg")),
                "amount": _decimal(row.get("amount")),
                "limit_amount": _decimal(row.get("limit_amount")),
                "float_mv": _decimal(row.get("float_mv")),
                "total_mv": _decimal(row.get("total_mv")),
                "turnover_ratio": _decimal(row.get("turnover_ratio")),
                "fd_amount": _decimal(row.get("fd_amount")),
                "first_time": row.get("first_time"),
                "last_time": row.get("last_time"),
                "open_times": _integer(row.get("open_times")),
                "up_stat": row.get("up_stat"),
                "limit_times": _integer(row.get("limit_times")),
                "limit": row.get("limit"),
            }
        )
    update_columns = (
        [key for key in rows[0] if key not in {"ts_code", "trade_date"}] if rows else []
    )
    return upsert_rows(
        db,
        TushareLimitListD,
        rows,
        update_columns=update_columns,
        constraint="uq_tushare_limit_list_d_code_date",
        index_elements=["ts_code", "trade_date"],
    )


def sync_tushare_cyq_perf(db, *, trade_date: str) -> int:
    response = client.query("cyq_perf", params={"trade_date": trade_date})
    rows = []
    for row in _rows(response.fields, response.items):
        ts_code, row_date = _required_row_keys(row)
        rows.append(
            {
                "ts_code": ts_code,
                "trade_date": row_date,
                "his_low": _decimal(row.get("his_low")),
                "his_high": _decimal(row.get("his_high")),
                "cost_5pct": _decimal(row.get("cost_5pct")),
                "cost_15pct": _decimal(row.get("cost_15pct")),
                "cost_50pct": _decimal(row.get("cost_50pct")),
                "cost_85pct": _decimal(row.get("cost_85pct")),
                "cost_95pct": _decimal(row.get("cost_95pct")),
                "weight_avg": _decimal(row.get("weight_avg")),
                "winner_rate": _decimal(row.get("winner_rate")),
            }
        )
    update_columns = (
        [key for key in rows[0] if key not in {"ts_code", "trade_date"}] if rows else []
    )
    return upsert_rows(
        db,
        TushareCyqPerf,
        rows,
        update_columns=update_columns,
        constraint="uq_tushare_cyq_perf_code_date",
        index_elements=["ts_code", "trade_date"],
    )


def sync_tushare_moneyflow_ind_dc(db, *, trade_date: str) -> int:
    response = client.query("moneyflow_ind_dc", params={"trade_date": trade_date})
    rows = []
    for row in _rows(response.fields, response.items):
        rows.append(
            {
                "trade_date": _date(row.get("trade_date")),
                "content_type": row.get("content_type"),
                "ts_code": row.get("ts_code"),
                "name": row.get("name"),
                "pct_change": _decimal(row.get("pct_change")),
                "close": _decimal(row.get("close")),
                "net_amount": _decimal(row.get("net_amount")),
                "net_amount_rate": _decimal(row.get("net_amount_rate")),
            }
        )
    return upsert_rows(
        db,
        TushareMoneyflowIndDc,
        rows,
        update_columns=["name", "pct_change", "close", "net_amount", "net_amount_rate"],
        constraint="uq_tushare_moneyflow_ind_dc",
    )


def sync_tushare_stock_basic(db, *, list_status: str = "L") -> int:
    response = client.query(
        "stock_basic",
        params={
            "exchange": "",
            "list_status": list_status,
            "fields": "ts_code,symbol,name,industry,market,list_date",
        },
    )
    rows = []
    for row in _rows(response.fields, response.items):
        ts_code = str(row.get("ts_code") or "").strip()
        symbol = str(row.get("symbol") or "").strip()
        name = str(row.get("name") or "").strip()
        industry = str(row.get("industry") or "").strip()
        if not symbol and ts_code:
            symbol = ts_code.split(".", 1)[0]
        if not symbol or not name:
            continue
        if not industry:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "exchange": "SH"
                if ts_code.endswith(".SH") or symbol.startswith(("6", "9"))
                else "SZ"
                if ts_code.endswith(".SZ") or symbol.startswith(("0", "2", "3"))
                else "BJ"
                if ts_code.endswith(".BJ") or symbol.startswith(("4", "8"))
                else "UNKNOWN",
                "list_date": _date(row.get("list_date")),
                "industry": industry,
                "is_st": "ST" in name.upper(),
                "is_active": True,
            }
        )
    total = 0
    chunk_size = 500
    for index in range(0, len(rows), chunk_size):
        total += upsert_rows(
            db,
            Security,
            rows[index : index + chunk_size],
            update_columns=["name", "exchange", "list_date", "industry", "is_st", "is_active"],
            constraint="uq_security_symbol",
        )
    return total
