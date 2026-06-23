from __future__ import annotations

from datetime import date

from services.engine.backtest.daily import run_daily_rule_backtest
from services.engine.backtest.metrics import summarize_rule_performance
from services.engine.backtest.persistence import upsert_backtest_trades, upsert_rule_performance
from services.engine.backtest.repository import load_many_backtest_inputs
from services.engine.features.repository import list_active_symbols
from services.engine.rules.seed_rules import MVP_RULES
from services.shared.database import SessionLocal


def run_rules_backtest(
    symbols: list[str] | None = None,
    rule_ids: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    run_date: date | None = None,
    persist: bool = False,
    limit: int | None = None,
) -> dict[str, object]:
    target_rules = [rule for rule in MVP_RULES if not rule_ids or rule.id in rule_ids]
    summaries = []
    trade_count = 0
    written_trades = 0
    written_performance = 0

    with SessionLocal() as db:
        target_symbols = symbols if symbols is not None else list_active_symbols(db, limit=limit)
        inputs = load_many_backtest_inputs(db, symbols=target_symbols, start_date=start_date, end_date=end_date)

        for rule in target_rules:
            rule_trades = []
            for item in inputs:
                rule_trades.extend(run_daily_rule_backtest(item, rule))
            performance = summarize_rule_performance(rule.id, rule_trades)
            trade_count += len(rule_trades)
            summaries.append(performance.__dict__)

            if persist:
                effective_run_date = run_date or end_date or date.today()
                written_trades += upsert_backtest_trades(db, effective_run_date, rule_trades)
                written_performance += upsert_rule_performance(db, effective_run_date, performance)

        if persist:
            db.commit()

    return {
        "symbols": len(target_symbols),
        "rules": [rule.id for rule in target_rules],
        "trade_count": trade_count,
        "written_trades": written_trades,
        "written_performance": written_performance,
        "summaries": summaries,
    }
