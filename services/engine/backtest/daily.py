from __future__ import annotations

from services.engine.backtest.models import BacktestTrade, DailyBacktestInput
from services.engine.plans.generator import generate_trade_plans
from services.engine.rules.models import StrategyRule


def _index_by_date(items: list[object]) -> dict[str, object]:
    return {getattr(item, "trade_date"): item for item in items}


def _next_trade_date(dates: list[str], current: str) -> str | None:
    try:
        index = dates.index(current)
    except ValueError:
        return None
    if index + 1 >= len(dates):
        return None
    return dates[index + 1]


def _exit_trade(
    rule: StrategyRule,
    bars_by_date: dict[str, object],
    dates: list[str],
    entry_index: int,
    entry_price: float,
    initial_stop: float | None,
    take_profit_1: float | None,
) -> tuple[str, float, int, float, float, str]:
    max_holding_days = rule.time_exit.max_holding_days or 5
    highest = entry_price
    lowest = entry_price
    exit_date = dates[entry_index]
    exit_price = entry_price
    exit_reason = "time_exit"

    for holding_offset in range(max_holding_days):
        bar_index = entry_index + holding_offset
        if bar_index >= len(dates):
            break

        date = dates[bar_index]
        bar = bars_by_date[date]
        high = float(getattr(bar, "high"))
        low = float(getattr(bar, "low"))
        close = float(getattr(bar, "close"))

        highest = max(highest, high)
        lowest = min(lowest, low)
        exit_date = date
        exit_price = close

        if initial_stop is not None and low <= initial_stop:
            exit_price = initial_stop
            exit_reason = "stop_loss"
            break

        if take_profit_1 is not None and high >= take_profit_1:
            trailing_pct = float(rule.take_profit.params.get("drawdown_from_high_pct", 0.06))
            trailing_stop = highest * (1 - trailing_pct)
            if low <= trailing_stop:
                exit_price = trailing_stop
                exit_reason = "trailing_take_profit"
                break

        if holding_offset + 1 >= max_holding_days:
            exit_reason = "time_exit"
            exit_price = close
            break

    holding_days = dates.index(exit_date) - entry_index + 1
    mfe_pct = highest / entry_price - 1
    mae_pct = lowest / entry_price - 1
    return exit_date, exit_price, holding_days, mfe_pct, mae_pct, exit_reason


def run_daily_rule_backtest(
    data: DailyBacktestInput,
    rule: StrategyRule,
    fee_rate: float = 0.0003,
    slippage_rate: float = 0.001,
) -> list[BacktestTrade]:
    bars = sorted(data.bars, key=lambda item: item.trade_date)
    features = sorted(data.features, key=lambda item: item.trade_date)
    dates = [bar.trade_date for bar in bars]
    bars_by_date = _index_by_date(bars)
    trades: list[BacktestTrade] = []

    for snapshot in features:
        signal_date = snapshot.trade_date
        entry_date = _next_trade_date(dates, signal_date)
        if entry_date is None:
            continue

        context = dict(snapshot.context)
        context.setdefault("symbol", data.symbol)
        plans = generate_trade_plans(
            plan_date=signal_date,
            trade_date=entry_date,
            rules=[rule],
            feature_contexts=[context],
        )
        if not plans:
            continue

        entry_index = dates.index(entry_date)
        entry_bar = bars_by_date[entry_date]
        entry_open = float(getattr(entry_bar, "open"))
        entry_price = entry_open * (1 + slippage_rate)

        plan = plans[0]
        exit_date, exit_price, holding_days, mfe_pct, mae_pct, exit_reason = _exit_trade(
            rule=rule,
            bars_by_date=bars_by_date,
            dates=dates,
            entry_index=entry_index,
            entry_price=entry_price,
            initial_stop=plan.initial_stop,
            take_profit_1=plan.take_profit_1,
        )
        exit_price = exit_price * (1 - slippage_rate)
        pnl_pct = exit_price / entry_price - 1 - fee_rate * 2

        trades.append(
            BacktestTrade(
                rule_id=rule.id,
                symbol=data.symbol,
                signal_date=signal_date,
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=exit_date,
                exit_price=exit_price,
                holding_days=holding_days,
                pnl_pct=pnl_pct,
                mfe_pct=mfe_pct,
                mae_pct=mae_pct,
                exit_reason=exit_reason,
            )
        )

    return trades
