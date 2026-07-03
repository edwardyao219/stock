from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import (
    DailyBar,
    PaperAccount,
    PaperPosition,
    PaperTrade,
    TradePlan,
)


def get_or_create_account(
    db: Session,
    name: str = "default",
    initial_cash: Decimal = Decimal("1000000"),
) -> PaperAccount:
    account = db.execute(select(PaperAccount).where(PaperAccount.name == name)).scalar_one_or_none()
    if account:
        return account
    account = PaperAccount(name=name, initial_cash=initial_cash, cash=initial_cash, status="active")
    db.add(account)
    db.flush()
    return account


def load_trade_plans_for_trade_date(
    db: Session,
    trade_date: date,
    symbols: list[str] | None = None,
) -> list[TradePlan]:
    stmt = (
        select(TradePlan)
        .where(TradePlan.trade_date == trade_date)
        .where(TradePlan.status == "planned")
        .order_by(TradePlan.confidence_score.desc())
    )
    if symbols:
        stmt = stmt.where(TradePlan.symbol.in_(symbols))
    return list(db.execute(stmt).scalars())


def load_bar(db: Session, symbol: str, trade_date: date) -> DailyBar | None:
    stmt = (
        select(DailyBar)
        .where(DailyBar.symbol == symbol)
        .where(DailyBar.trade_date == trade_date)
    )
    return db.execute(stmt).scalar_one_or_none()


def has_open_position(db: Session, account_id: int, symbol: str) -> bool:
    stmt = (
        select(PaperPosition.id)
        .where(PaperPosition.account_id == account_id)
        .where(PaperPosition.symbol == symbol)
        .where(PaperPosition.status == "open")
    )
    return db.execute(stmt).first() is not None


def load_open_positions(db: Session, account_id: int) -> list[PaperPosition]:
    stmt = (
        select(PaperPosition)
        .where(PaperPosition.account_id == account_id)
        .where(PaperPosition.status == "open")
        .order_by(PaperPosition.entry_date)
    )
    return list(db.execute(stmt).scalars())


def create_trade(
    db: Session,
    account_id: int,
    symbol: str,
    side: str,
    trade_date: date,
    price: Decimal,
    quantity: int,
    reason: str,
    order_id: int | None = None,
    position_id: int | None = None,
    fee_rate: Decimal = Decimal("0.0003"),
) -> PaperTrade:
    amount = (price * Decimal(quantity)).quantize(Decimal("0.01"))
    fee = (amount * fee_rate).quantize(Decimal("0.01"))
    trade = PaperTrade(
        account_id=account_id,
        order_id=order_id,
        position_id=position_id,
        symbol=symbol,
        side=side,
        trade_date=trade_date,
        price=price,
        quantity=quantity,
        amount=amount,
        fee=fee,
        reason=reason,
    )
    db.add(trade)
    return trade
