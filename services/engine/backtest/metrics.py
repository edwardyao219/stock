from services.engine.backtest.models import BacktestTrade, RulePerformance


def summarize_rule_performance(rule_id: str, trades: list[BacktestTrade]) -> RulePerformance:
    if not trades:
        return RulePerformance(
            rule_id=rule_id,
            trade_count=0,
            win_rate=0.0,
            avg_return=0.0,
            expectancy=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            avg_mfe=0.0,
            avg_mae=0.0,
            score=0.0,
        )

    wins = [trade.pnl_pct for trade in trades if trade.pnl_pct > 0]
    losses = [trade.pnl_pct for trade in trades if trade.pnl_pct <= 0]
    avg_return = sum(trade.pnl_pct for trade in trades) / len(trades)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss else gross_profit
    win_rate = len(wins) / len(trades)
    avg_mfe = sum(trade.mfe_pct for trade in trades) / len(trades)
    avg_mae = sum(trade.mae_pct for trade in trades) / len(trades)

    score = avg_return * 100 + profit_factor * 3 - abs(avg_mae) * 20

    return RulePerformance(
        rule_id=rule_id,
        trade_count=len(trades),
        win_rate=win_rate,
        avg_return=avg_return,
        expectancy=avg_return,
        profit_factor=profit_factor,
        max_drawdown=0.0,
        avg_mfe=avg_mfe,
        avg_mae=avg_mae,
        score=score,
    )
