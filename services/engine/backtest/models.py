from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestTrade:
    rule_id: str
    symbol: str
    signal_date: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    holding_days: int
    pnl_pct: float
    mfe_pct: float
    mae_pct: float
    exit_reason: str


@dataclass(frozen=True)
class RulePerformance:
    rule_id: str
    trade_count: int
    win_rate: float
    avg_return: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    avg_mfe: float
    avg_mae: float
    score: float
