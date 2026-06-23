from services.engine.backtest.daily import run_daily_rule_backtest
from services.engine.backtest.models import DailyBacktestInput, FeatureSnapshot
from services.engine.features.daily import BarInput
from services.engine.rules.seed_rules import MVP_RULES


def test_run_daily_rule_backtest_generates_t_plus_one_trade() -> None:
    bars = [
        BarInput("000001", "2026-01-01", 10.0, 10.4, 9.8, 10.0, None, 1000),
        BarInput("000001", "2026-01-02", 10.2, 10.8, 10.1, 10.6, 10.0, 2000),
        BarInput("000001", "2026-01-03", 10.7, 11.4, 10.6, 11.2, 10.6, 3000),
        BarInput("000001", "2026-01-04", 11.1, 11.2, 10.4, 10.5, 11.2, 2500),
    ]
    features = [
        FeatureSnapshot(
            symbol="000001",
            trade_date="2026-01-01",
            context={
                "symbol": "000001",
                "close": 10.0,
                "atr_14": 0.3,
                "sector_strength_score": 80,
                "relative_strength_score": 75,
                "amount_percentile_60d": 90,
                "distance_to_20d_high": -0.01,
                "trend_score": 80,
                "volume_score": 90,
                "risk_score": 20,
                "is_st": False,
                "is_suspended": False,
            },
        )
    ]

    trades = run_daily_rule_backtest(
        DailyBacktestInput(symbol="000001", bars=bars, features=features),
        MVP_RULES[0],
        fee_rate=0,
        slippage_rate=0,
    )

    assert len(trades) == 1
    assert trades[0].signal_date == "2026-01-01"
    assert trades[0].entry_date == "2026-01-02"
    assert trades[0].entry_price == 10.2
    assert trades[0].exit_reason in {"trailing_take_profit", "time_exit", "stop_loss"}
    assert trades[0].mfe_pct > 0
