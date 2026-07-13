from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from services.engine.paper.entry_quality import (
    HIGH_QUALITY_CONFIDENCE_MIN,
    HIGH_QUALITY_RANK_MAX,
    HIGH_QUALITY_RELATIVE_MIN,
    HIGH_QUALITY_RISK_MAX,
    HIGH_QUALITY_SECTOR_MIN,
    HIGH_QUALITY_TREND_MIN,
    evaluate_plan_entry_quality,
)
from services.engine.paper.position_sizing import adjusted_position_size_pct
from services.engine.paper.repository import (
    create_trade,
    get_or_create_account,
    has_open_position,
    load_bar,
    load_open_positions,
    load_trade_plans_for_trade_date,
)
from services.shared.database import SessionLocal
from services.shared.models import PaperOrder, PaperPosition, TradePlan

PAPER_SIM_DAILY_ENTRY_CAP = 2
PAPER_SIM_HIGH_QUALITY_RANK_MAX = HIGH_QUALITY_RANK_MAX
PAPER_SIM_HIGH_QUALITY_CONFIDENCE_MIN = HIGH_QUALITY_CONFIDENCE_MIN
PAPER_SIM_HIGH_QUALITY_TREND_MIN = HIGH_QUALITY_TREND_MIN
PAPER_SIM_HIGH_QUALITY_RELATIVE_MIN = HIGH_QUALITY_RELATIVE_MIN
PAPER_SIM_HIGH_QUALITY_SECTOR_MIN = HIGH_QUALITY_SECTOR_MIN
PAPER_SIM_HIGH_QUALITY_RISK_MAX = HIGH_QUALITY_RISK_MAX


@dataclass(frozen=True)
class PaperSimulationResult:
    trade_date: str
    account: str
    opened: int
    closed: int
    skipped: int
    messages: list[str]


def _decimal(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _holding_days(entry_date: date, current_date: date) -> int:
    return (current_date - entry_date).days + 1


def _entry_quantity(cash: Decimal, price: Decimal, position_pct: Decimal) -> int:
    budget = cash * position_pct
    raw_quantity = int(budget / price)
    return raw_quantity - raw_quantity % 100


def _plan_is_high_quality(
    db,
    plan: TradePlan,
    *,
    candidate_pool_name: str | None = "experiment",
    feature_date: date | None = None,
) -> bool:
    return evaluate_plan_entry_quality(
        db,
        plan,
        pool_name=candidate_pool_name,
        feature_date=feature_date,
    ).accepted


def _should_exit(position: PaperPosition, bar, trade_date: date) -> tuple[bool, Decimal, str]:
    high = _decimal(bar.high)
    low = _decimal(bar.low)
    close = _decimal(bar.close)
    baseline_stop = (
        position.initial_stop if position.initial_stop is not None else position.entry_price
    )
    trailing_active = (
        position.take_profit_1 is not None
        and position.current_stop is not None
        and baseline_stop is not None
        and position.current_stop > baseline_stop
    )

    current_stop = position.current_stop
    if current_stop is not None and low <= current_stop:
        if trailing_active:
            return True, current_stop, "trailing_take_profit"
        return True, current_stop, "stop_loss"

    if high > position.highest_price:
        position.highest_price = high
    if low < position.lowest_price:
        position.lowest_price = low

    if position.take_profit_1 is not None and high >= position.take_profit_1:
        trailing_stop = (position.highest_price * Decimal("0.94")).quantize(Decimal("0.0001"))
        if position.current_stop is None or trailing_stop > position.current_stop:
            position.current_stop = trailing_stop

    if (
        position.max_holding_days
        and _holding_days(position.entry_date, trade_date) >= position.max_holding_days
    ):
        return True, close, "time_exit"

    return False, close, ""


def _open_position_from_plan(
    db,
    account,
    plan: TradePlan,
    trade_date: date,
    bar,
    *,
    open_positions_count: int,
) -> tuple[bool, str]:
    if has_open_position(db, account.id, plan.symbol):
        return False, f"{plan.symbol} skipped: open position exists"
    if bar.is_suspended:
        return False, f"{plan.symbol} skipped: suspended"

    open_price = _decimal(bar.open)
    high_price = _decimal(bar.high)
    previous_close = _decimal(bar.pre_close) if bar.pre_close is not None else None
    trigger_price = (
        _decimal(plan.entry_trigger_price) if plan.entry_trigger_price is not None else open_price
    )
    max_gap_up_pct = (
        Decimal(str(plan.max_gap_up_pct))
        if plan.max_gap_up_pct is not None
        else Decimal("0.06")
    )

    if previous_close is not None and previous_close > 0:
        gap_up_pct = open_price / previous_close - Decimal("1")
        if gap_up_pct > max_gap_up_pct:
            plan.status = "cancelled"
            return False, f"{plan.symbol} cancelled: gap_up {gap_up_pct:.2%} > {max_gap_up_pct:.2%}"

    if high_price < trigger_price:
        return False, f"{plan.symbol} pending: trigger {trigger_price} not touched"

    entry_price = max(open_price, trigger_price)
    effective_position_size = adjusted_position_size_pct(
        plan.position_size,
        open_positions_count,
        plan.strategy_type,
    )
    quantity = _entry_quantity(account.cash, entry_price, effective_position_size)
    if quantity <= 0:
        return False, f"{plan.symbol} skipped: insufficient cash"

    order = PaperOrder(
        account_id=account.id,
        trade_plan_id=plan.id,
        symbol=plan.symbol,
        side="buy",
        order_date=trade_date,
        planned_price=entry_price,
        quantity=quantity,
        status="filled",
        reason=f"trade_plan:{plan.rule_id}",
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
        price=entry_price,
        quantity=quantity,
        reason=f"open_by_plan:{plan.rule_id}",
    )
    cost = trade.amount + trade.fee
    if cost > account.cash:
        order.status = "rejected"
        return False, f"{plan.symbol} skipped: cost exceeds cash"

    account.cash -= cost
    position = PaperPosition(
        account_id=account.id,
        trade_plan_id=plan.id,
        symbol=plan.symbol,
        rule_id=plan.rule_id,
        strategy_type=plan.strategy_type,
        entry_date=trade_date,
        entry_price=entry_price,
        quantity=quantity,
        initial_stop=plan.initial_stop,
        current_stop=plan.initial_stop,
        take_profit_1=plan.take_profit_1,
        take_profit_2=plan.take_profit_2,
        highest_price=entry_price,
        lowest_price=entry_price,
        max_holding_days=plan.max_holding_days,
        status="open",
    )
    db.add(position)
    db.flush()
    trade.position_id = position.id
    plan.status = "executed"
    concentration_note = ""
    if effective_position_size < Decimal(str(plan.position_size)):
        concentration_note = (
            f" current open positions {open_positions_count}, "
            f"size adjusted to {effective_position_size:.2%}"
        )
    return True, f"{plan.symbol} opened: {quantity} @ {entry_price}{concentration_note}"


def run_daily_paper_simulation(
    trade_date: str,
    account_name: str = "default",
    initial_cash: Decimal = Decimal("1000000"),
    symbols: list[str] | None = None,
    candidate_pool_name: str | None = "experiment",
    allowed_strategy_types: set[str] | None = None,
    execute_entries: bool = True,
) -> PaperSimulationResult:
    current_date = date.fromisoformat(trade_date)
    opened = 0
    closed = 0
    skipped = 0
    messages: list[str] = []

    with SessionLocal() as db:
        account = get_or_create_account(db, name=account_name, initial_cash=initial_cash)
        existing_daily_entries = (
            db.query(PaperOrder)
            .filter(PaperOrder.account_id == account.id)
            .filter(PaperOrder.side == "buy")
            .filter(PaperOrder.order_date == current_date)
            .filter(PaperOrder.status == "filled")
            .count()
        )

        for position in load_open_positions(db, account.id):
            bar = load_bar(db, position.symbol, current_date)
            if bar is None:
                skipped += 1
                messages.append(f"{position.symbol} position skipped: no bar")
                continue
            should_exit, exit_price, reason = _should_exit(position, bar, current_date)
            if not should_exit:
                continue

            order = PaperOrder(
                account_id=account.id,
                trade_plan_id=position.trade_plan_id,
                symbol=position.symbol,
                side="sell",
                order_date=current_date,
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
                trade_date=current_date,
                price=exit_price,
                quantity=position.quantity,
                reason=reason,
            )
            account.cash += trade.amount - trade.fee
            position.status = "closed"
            position.exit_date = current_date
            position.exit_price = exit_price
            position.exit_reason = reason
            position.pnl = (
                (exit_price - position.entry_price) * Decimal(position.quantity) - trade.fee
            )
            position.pnl_pct = (exit_price / position.entry_price - Decimal("1")).quantize(
                Decimal("0.000001")
            )
            closed += 1
            messages.append(f"{position.symbol} closed: {reason} @ {exit_price}")

        open_positions_count = len(load_open_positions(db, account.id))
        plans = (
            load_trade_plans_for_trade_date(db, current_date, symbols=symbols)
            if execute_entries
            else []
        )
        for plan in plans:
            if plan.rule_id == "OBS001":
                skipped += 1
                messages.append(f"{plan.symbol} plan skipped: OBS001 requires realtime monitor")
                continue
            if (
                allowed_strategy_types is not None
                and plan.strategy_type not in allowed_strategy_types
            ):
                skipped += 1
                messages.append(f"{plan.symbol} plan skipped: short-term plan stays in observation")
                continue
            remaining_slots = PAPER_SIM_DAILY_ENTRY_CAP - existing_daily_entries - opened
            if remaining_slots <= 0:
                skipped += 1
                messages.append(f"{plan.symbol} plan skipped: daily entry cap reached")
                continue
            if not _plan_is_high_quality(
                db,
                plan,
                candidate_pool_name=candidate_pool_name,
                feature_date=plan.plan_date,
            ):
                skipped += 1
                messages.append(f"{plan.symbol} plan skipped: quality too weak")
                continue
            bar = load_bar(db, plan.symbol, current_date)
            if bar is None:
                skipped += 1
                messages.append(f"{plan.symbol} plan skipped: no bar")
                continue
            ok, message = _open_position_from_plan(
                db,
                account,
                plan,
                current_date,
                bar,
                open_positions_count=open_positions_count,
            )
            if ok:
                opened += 1
                open_positions_count += 1
            else:
                skipped += 1
            messages.append(message)

        db.commit()

    return PaperSimulationResult(
        trade_date=trade_date,
        account=account_name,
        opened=opened,
        closed=closed,
        skipped=skipped,
        messages=messages,
    )
