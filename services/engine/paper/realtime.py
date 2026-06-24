from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from time import sleep

from services.collector.akshare_client import RealtimeQuoteRow, fetch_sina_realtime_quotes
from services.collector.repository import upsert_realtime_quotes
from services.engine.paper.repository import (
    create_trade,
    get_or_create_account,
    has_open_position,
    load_open_positions,
    load_trade_plans_for_trade_date,
)
from services.engine.paper.review import upsert_paper_trade_review_for_position
from services.notifications.dispatcher import dispatch_paper_alerts
from services.shared.database import SessionLocal
from services.shared.models import PaperAlert, PaperOrder, PaperPosition, TradePlan
from services.shared.time import now_local
from services.shared.upsert import upsert_rows


@dataclass(frozen=True)
class RealtimePaperAlert:
    account_id: int
    position_id: int | None
    symbol: str
    alert_type: str
    severity: str
    message: str
    alert_time: str
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
    executed_entries: int
    executed_exits: int
    alerts: list[RealtimePaperAlert]
    notifications: list[dict[str, str]]

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


def _entry_quantity(cash: Decimal, price: Decimal, position_pct: Decimal) -> int:
    budget = cash * position_pct
    raw_quantity = int(budget / price)
    return raw_quantity - raw_quantity % 100


def _limit_ratio(symbol: str) -> Decimal:
    if symbol.startswith(("4", "8")):
        return Decimal("1.30")
    if symbol.startswith(("3", "688", "689")):
        return Decimal("1.20")
    return Decimal("1.10")


def _alert(
    *,
    position: PaperPosition,
    quote: RealtimeQuoteRow,
    alert_type: str,
    severity: str,
    message: str,
    price: Decimal | None,
) -> RealtimePaperAlert:
    return RealtimePaperAlert(
        account_id=position.account_id,
        position_id=position.id,
        symbol=position.symbol,
        alert_type=alert_type,
        severity=severity,
        message=message,
        alert_time=quote.quote_time.isoformat(timespec="seconds"),
        price=_float(price),
        current_stop=_float(position.current_stop),
        pnl_pct=_pnl_pct(position, price),
    )


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
    if position.entry_date.isoformat() == quote.trade_date:
        high = price
        low = price
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
            _alert(
                position=position,
                quote=quote,
                alert_type="take_profit_touched",
                severity="medium",
                message=f"{position.symbol} 触及第一止盈，已抬高纸面跟踪止损。",
                price=price,
            )
        )

    if position.current_stop is not None and low is not None and low <= position.current_stop:
        alerts.append(
            _alert(
                position=position,
                quote=quote,
                alert_type="stop_loss_touched",
                severity="high",
                message=f"{position.symbol} 盘中触及纸面止损/跟踪止损。",
                price=price,
            )
        )

    if quote.pre_close is not None:
        limit_ratio = _limit_ratio(position.symbol)
        limit_up = (_decimal(quote.pre_close) * limit_ratio).quantize(Decimal("0.0001"))
        limit_down = (_decimal(quote.pre_close) * (Decimal("2") - limit_ratio)).quantize(
            Decimal("0.0001")
        )
        if high is not None and high >= limit_up:
            alerts.append(
                _alert(
                    position=position,
                    quote=quote,
                    alert_type="limit_up_touched",
                    severity="medium",
                    message=f"{position.symbol} 盘中触及或接近涨停价。",
                    price=price,
                )
            )
        if low is not None and low <= limit_down:
            alerts.append(
                _alert(
                    position=position,
                    quote=quote,
                    alert_type="limit_down_touched",
                    severity="high",
                    message=f"{position.symbol} 盘中触及或接近跌停价。",
                    price=price,
                )
            )

    return changed, alerts


def _persist_alerts(db, alerts: list[RealtimePaperAlert]) -> int:
    if not alerts:
        return 0
    rows = [
        {
            "account_id": alert.account_id,
            "position_id": alert.position_id,
            "symbol": alert.symbol,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "alert_time": datetime.fromisoformat(alert.alert_time),
            "price": Decimal(str(alert.price)) if alert.price is not None else None,
            "current_stop": (
                Decimal(str(alert.current_stop)) if alert.current_stop is not None else None
            ),
            "pnl_pct": Decimal(str(alert.pnl_pct)) if alert.pnl_pct is not None else None,
            "message": alert.message,
            "status": "open",
        }
        for alert in alerts
    ]
    return upsert_rows(
        db,
        PaperAlert,
        rows,
        update_columns=["severity", "price", "current_stop", "pnl_pct", "message"],
        constraint="uq_paper_alert_event",
    )


def _realtime_exit_signal(
    position: PaperPosition,
    quote: RealtimeQuoteRow,
) -> tuple[bool, Decimal | None, str]:
    low = _decimal(quote.price) if position.entry_date.isoformat() == quote.trade_date else (
        _decimal(quote.low) or _decimal(quote.price)
    )
    if position.current_stop is None or low is None or low > position.current_stop:
        return False, None, ""
    if position.take_profit_1 is not None and position.highest_price >= position.take_profit_1:
        return True, position.current_stop, "trailing_take_profit"
    return True, position.current_stop, "stop_loss"


def _execute_realtime_exit(
    db,
    account,
    position: PaperPosition,
    exit_price: Decimal,
    reason: str,
    trade_date: date,
) -> None:
    order = PaperOrder(
        account_id=account.id,
        trade_plan_id=position.trade_plan_id,
        symbol=position.symbol,
        side="sell",
        order_date=trade_date,
        planned_price=exit_price,
        quantity=position.quantity,
        status="filled",
        reason=reason,
    )
    db.add(order)
    db.flush()
    trade = create_trade(
        db,
        account_id=account.id,
        order_id=order.id,
        position_id=position.id,
        symbol=position.symbol,
        side="sell",
        trade_date=trade_date,
        price=exit_price,
        quantity=position.quantity,
        reason=f"realtime:{reason}",
    )
    account.cash += trade.amount - trade.fee
    position.status = "closed"
    position.exit_date = trade_date
    position.exit_price = exit_price
    position.exit_reason = reason
    position.pnl = (exit_price - position.entry_price) * Decimal(position.quantity) - trade.fee
    position.pnl_pct = (exit_price / position.entry_price - Decimal("1")).quantize(
        Decimal("0.000001")
    )


def _execute_realtime_entry(
    db,
    account,
    plan: TradePlan,
    quote: RealtimeQuoteRow,
    trade_date: date,
) -> tuple[bool, RealtimePaperAlert | None]:
    if has_open_position(db, account.id, plan.symbol):
        return False, None

    price = _decimal(quote.price)
    open_price = _decimal(quote.open)
    pre_close = _decimal(quote.pre_close)
    if price is None:
        return False, None

    trigger_price = (
        _decimal(plan.entry_trigger_price) if plan.entry_trigger_price is not None else price
    )
    max_gap_up_pct = (
        Decimal(str(plan.max_gap_up_pct)) if plan.max_gap_up_pct is not None else Decimal("0.06")
    )
    if open_price is not None and pre_close is not None and pre_close > 0:
        gap_up_pct = open_price / pre_close - Decimal("1")
        if gap_up_pct > max_gap_up_pct:
            plan.status = "cancelled"
            return False, None

    if price < trigger_price:
        return False, None

    initial_stop = _decimal(plan.initial_stop)
    if initial_stop is not None and initial_stop >= price:
        plan.status = "cancelled"
        return False, None

    quantity = _entry_quantity(account.cash, price, Decimal(plan.position_size))
    if quantity <= 0:
        return False, None

    order = PaperOrder(
        account_id=account.id,
        trade_plan_id=plan.id,
        symbol=plan.symbol,
        side="buy",
        order_date=trade_date,
        planned_price=price,
        quantity=quantity,
        status="filled",
        reason=f"realtime_entry:{plan.rule_id}",
    )
    db.add(order)
    db.flush()

    trade = create_trade(
        db,
        account_id=account.id,
        order_id=order.id,
        position_id=None,
        symbol=plan.symbol,
        side="buy",
        trade_date=trade_date,
        price=price,
        quantity=quantity,
        reason=f"realtime_open_by_plan:{plan.rule_id}",
    )
    cost = trade.amount + trade.fee
    if cost > account.cash:
        order.status = "rejected"
        return False, None

    account.cash -= cost
    position = PaperPosition(
        account_id=account.id,
        trade_plan_id=plan.id,
        symbol=plan.symbol,
        rule_id=plan.rule_id,
        strategy_type=plan.strategy_type,
        entry_date=trade_date,
        entry_price=price,
        quantity=quantity,
        initial_stop=plan.initial_stop,
        current_stop=plan.initial_stop,
        take_profit_1=plan.take_profit_1,
        take_profit_2=plan.take_profit_2,
        highest_price=price,
        lowest_price=price,
        max_holding_days=plan.max_holding_days,
        status="open",
    )
    db.add(position)
    db.flush()
    trade.position_id = position.id
    plan.status = "executed"

    return True, _alert(
        position=position,
        quote=quote,
        alert_type="paper_entry_filled",
        severity="medium",
        message=f"{plan.symbol} 纸面买入已触发，价格 {price}，数量 {quantity}。",
        price=price,
    )


def monitor_paper_positions_realtime(
    trade_date: str | None = None,
    account_name: str = "default",
    quotes: list[RealtimeQuoteRow] | None = None,
    quote_time: datetime | None = None,
    execute_entries: bool = True,
    execute_exits: bool = False,
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
                    executed_entries=0,
                    executed_exits=0,
                    alerts=[],
                    notifications=[],
                )
        quote_rows = quote_rows or []
        if quote_rows:
            upsert_realtime_quotes(db, quote_rows)

        by_symbol = _quote_map(quote_rows)
        updated_positions = 0
        executed_entries = 0
        executed_exits = 0
        alerts: list[RealtimePaperAlert] = []
        if execute_entries:
            for plan in load_trade_plans_for_trade_date(db, current_date):
                quote = by_symbol.get(plan.symbol)
                if quote is None:
                    continue
                opened, entry_alert = _execute_realtime_entry(
                    db,
                    account,
                    plan,
                    quote,
                    current_date,
                )
                if opened:
                    executed_entries += 1
                if entry_alert is not None:
                    alerts.append(entry_alert)

        for position in load_open_positions(db, account.id):
            quote = by_symbol.get(position.symbol)
            if quote is None:
                continue
            changed, position_alerts = _update_position_from_quote(position, quote)
            if changed:
                updated_positions += 1
            alerts.extend(position_alerts)
            if execute_exits:
                should_exit, exit_price, reason = _realtime_exit_signal(position, quote)
                if should_exit and exit_price is not None:
                    _execute_realtime_exit(db, account, position, exit_price, reason, current_date)
                    upsert_paper_trade_review_for_position(db, position)
                    executed_exits += 1

        _persist_alerts(db, alerts)
        db.commit()

    notifications = dispatch_paper_alerts([alert.to_dict() for alert in alerts])

    return RealtimePaperMonitorResult(
        status="ok",
        message="realtime paper monitor completed",
        quote_time=current_time.isoformat(timespec="seconds"),
        target_symbols=len(target_symbols),
        quotes=len(quote_rows),
        updated_positions=updated_positions,
        executed_entries=executed_entries,
        executed_exits=executed_exits,
        alerts=alerts,
        notifications=[item.to_dict() for item in notifications],
    )


def run_realtime_monitor_loop(
    *,
    interval_seconds: float = 30.0,
    max_ticks: int | None = None,
    trade_date: str | None = None,
    account_name: str = "default",
    execute_entries: bool = True,
    execute_exits: bool = False,
) -> list[RealtimePaperMonitorResult]:
    results: list[RealtimePaperMonitorResult] = []
    tick = 0
    while max_ticks is None or tick < max_ticks:
        results.append(
            monitor_paper_positions_realtime(
                trade_date=trade_date,
                account_name=account_name,
                execute_entries=execute_entries,
                execute_exits=execute_exits,
            )
        )
        tick += 1
        if max_ticks is not None and tick >= max_ticks:
            break
        sleep(max(1.0, interval_seconds))
    return results
