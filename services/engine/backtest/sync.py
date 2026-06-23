from __future__ import annotations

from datetime import date

from services.engine.backtest.daily import run_daily_rule_backtest
from services.engine.backtest.metrics import summarize_rule_performance
from services.engine.backtest.repository import load_many_backtest_inputs
from services.engine.rules.seed_rules import MVP_RULES
from services.shared.database import SessionLocal


def run_rules_backtest(
    symbols: list[str],
    rule_ids: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, object]:
    target_rules = [rule for rule in MVP_RULES if not rule_ids or rule.id in rule_ids]
    summaries = []
    trade_count = 0

    with SessionLocal() as db:
        inputs = load_many_backtest_inputs(db, symbols=symbols, start_date=start_date, end_date=end_date)

    for rule in target_rules:
        rule_trades = []
        for item in inputs:
            rule_trades.extend(run_daily_rule_backtest(item, rule))
        trade_count += len(rule_trades)
        summaries.append(summarize_rule_performance(rule.id, rule_trades).__dict__)

    return {
        "symbols": len(symbols),
        "rules": [rule.id for rule in target_rules],
        "trade_count": trade_count,
        "summaries": summaries,
    }
