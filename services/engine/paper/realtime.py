from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from time import sleep

from services.collector.akshare_client import RealtimeQuoteRow, fetch_sina_realtime_quotes
from services.collector.repository import upsert_realtime_quotes
from services.engine.paper.repository import (
    get_or_create_account,
    load_open_positions,
    load_trade_plans_for_trade_date,
)
from services.shared.database import SessionLocal
from services.shared.models import PaperPosition
from services.shared.time import now_local


@dataclass(frozen=True)
class RealtimePaperAlert:
    symbol: str
    alert_type: str
    severity: str
    message: str
    price: float | None
    current_stop: float | None
    pnl_pct: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RealtimePaperMonitorResult:
    status: str
    message: str
    quote_time: str
    target_symbols: int
    quotes: int
    updated_positions: int
    alerts: list[RealtimePaperAlert]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["alerts"] = [item.to_dict() for item in self.alerts]
        return data


def _decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _pnl_pct(position: PaperPosition, price: Decimal | None) -> float | None:
    if price is None or position.entry_price == 0:
        return None
    return float((price / position.entry_price - Decimal("1")).quantize(Decimal("0.000001")))


def _target_symbols(db, account_id: int, trade_date: date) -> set[str]:
    symbols = {position.symbol for position in load_open_positions(db, account_id)}
    symbols.update(plan.symbol for plan in load_trade_plans_for_trade_date(db, trade_date))
    return symbols


def _quote_map(quotes: list[RealtimeQuoteRow]) -> dict[str, RealtimeQuoteRow]:
    return {quote.symbol: quote for quote in quotes}


def _update_position_from_quote(
    position: PaperPosition,
    quote: RealtimeQuoteRow,
) -> tuple[bool, list[RealtimePaperAlert]]:
    price = _decimal(quote.price)
    high = _decimal(quote.high) or price
    low = _decimal(quote.low) or price
    changed = False
    alerts: list[RealtimePaperAlert] = []

    if high is not None and high > position.highest_price:
        position.highest_price = high
        changed = True
    if low is not None and low < position.lowest_price:
        position.lowest_price = low
        changed = True

    if position.take_profit_1 is not None and high is not None and high >= position.take_profit_1:
        trailing_stop = (position.highest_price * Decimal("0.94")).quantize(Decimal("0.0001"))
        if position.current_stop is None or trailing_stop > position.current_stop:
            position.current_stop = trailing_stop
            changed = True
        alerts.append(
            RealtimePaperAlert(
                symbol=position.symbol,
                alert_type="take_profit_touched",
                severity="medium",
                message=f"{position.symbol} 触及第一止盈，已抬高纸面跟踪止损。",
                price=_float(price),
                current_stop=_float(position.current_stop),
                pnl_pct=_pnl_pct(position, price),
            )
        )

    if position.current_stop is not None and low is not None and low <= position.current_stop:
        alerts.append(
            RealtimePaperAlert(
                symbol=position.symbol,
                alert_type="stop_loss_touched",
                severity="high",
                message=f"{position.symbol} 盘中触及纸面止损/跟踪止损。",
                price=_float(price),
                current_stop=_float(position.current_stop),
                pnl_pct=_pnl_pct(position, price),
            )
        )

    return changed, alerts


def monitor_paper_positions_realtime(
    trade_date: str | None = None,
    account_name: str = "default",
    quotes: list[RealtimeQuoteRow] | None = None,
    quote_time: datetime | None = None,
) -> RealtimePaperMonitorResult:
    current_time = (quote_time or now_local()).replace(tzinfo=None)
    current_date = date.fromisoformat(trade_date) if trade_date else current_time.date()

    with SessionLocal() as db:
        account = get_or_create_account(db, name=account_name)
        target_symbols = _target_symbols(db, account.id, current_date)
        quote_rows = quotes
        if quote_rows is None and target_symbols:
            try:
                quote_rows = fetch_sina_realtime_quotes(
                    symbols=target_symbols,
                    quote_time=current_time,
                )
            except Exception as exc:
                db.rollback()
                return RealtimePaperMonitorResult(
                    status="failed",
                    message=f"{type(exc).__name__}: {exc}",
                    quote_time=current_time.isoformat(timespec="seconds"),
                    target_symbols=len(target_symbols),
                    quotes=0,
                    updated_positions=0,
                    alerts=[],
                )
        quote_rows = quote_rows or []
        if quote_rows:
            upsert_realtime_quotes(db, quote_rows)

        by_symbol = _quote_map(quote_rows)
        updated_positions = 0
        alerts: list[RealtimePaperAlert] = []
        for position in load_open_positions(db, account.id):
            quote = by_symbol.get(position.symbol)
            if quote is None:
                continue
            changed, position_alerts = _update_position_from_quote(position, quote)
            if changed:
                updated_positions += 1
            alerts.extend(position_alerts)

        db.commit()

    return RealtimePaperMonitorResult(
        status="ok",
        message="realtime paper monitor completed",
        quote_time=current_time.isoformat(timespec="seconds"),
        target_symbols=len(target_symbols),
        quotes=len(quote_rows),
        updated_positions=updated_positions,
        alerts=alerts,
    )


def run_realtime_monitor_loop(
    *,
    interval_seconds: float = 30.0,
    max_ticks: int | None = None,
    trade_date: str | None = None,
    account_name: str = "default",
) -> list[RealtimePaperMonitorResult]:
    results: list[RealtimePaperMonitorResult] = []
    tick = 0
    while max_ticks is None or tick < max_ticks:
        results.append(
            monitor_paper_positions_realtime(
                trade_date=trade_date,
                account_name=account_name,
            )
        )
        tick += 1
        if max_ticks is not None and tick >= max_ticks:
            break
        sleep(max(1.0, interval_seconds))
    return results
