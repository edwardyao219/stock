from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from services.engine.backtest.models import BacktestTrade, RulePerformance
from services.shared.models import BacktestTradeRecord, RulePerformanceDaily
from services.shared.upsert import upsert_rows


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


def upsert_backtest_trades(db: Session, run_date: date, trades: list[BacktestTrade]) -> int:
    rows = [
        {
            "run_date": run_date,
            "rule_id": trade.rule_id,
            "symbol": trade.symbol,
            "signal_date": _date(trade.signal_date),
            "entry_date": _date(trade.entry_date),
            "entry_price": _decimal(trade.entry_price),
            "exit_date": _date(trade.exit_date),
            "exit_price": _decimal(trade.exit_price),
            "holding_days": trade.holding_days,
            "pnl_pct": _decimal(trade.pnl_pct),
            "mfe_pct": _decimal(trade.mfe_pct),
            "mae_pct": _decimal(trade.mae_pct),
            "exit_reason": trade.exit_reason,
        }
        for trade in trades
    ]
    if not rows:
        return 0

    return upsert_rows(
        db,
        BacktestTradeRecord,
        rows,
        update_columns=[
            "entry_date",
            "entry_price",
            "exit_date",
            "exit_price",
            "holding_days",
            "pnl_pct",
            "mfe_pct",
            "mae_pct",
            "exit_reason",
        ],
        constraint="uq_backtest_trades_run_rule_symbol_signal",
    )


def upsert_rule_performance(
    db: Session,
    trade_date: date,
    performance: RulePerformance,
    window_days: int = 0,
) -> int:
    row = {
        "rule_id": performance.rule_id,
        "trade_date": trade_date,
        "window_days": window_days,
        "trade_count": performance.trade_count,
        "win_rate": _decimal(performance.win_rate),
        "avg_return": _decimal(performance.avg_return),
        "expectancy": _decimal(performance.expectancy),
        "profit_factor": _decimal(performance.profit_factor),
        "max_drawdown": _decimal(performance.max_drawdown),
        "avg_mfe": _decimal(performance.avg_mfe),
        "avg_mae": _decimal(performance.avg_mae),
        "score": _decimal(performance.score),
        "notes": None,
    }
    return upsert_rows(
        db,
        RulePerformanceDaily,
        [row],
        update_columns=[
            "trade_count",
            "win_rate",
            "avg_return",
            "expectancy",
            "profit_factor",
            "max_drawdown",
            "avg_mfe",
            "avg_mae",
            "score",
            "notes",
        ],
        constraint="uq_rule_perf_daily",
    )
