from services.engine.backtest.run_long_replay_baseline import summarize_replay_baseline
from services.engine.backtest.walk_forward import (
    WalkForwardCandidate,
    WalkForwardDay,
    WalkForwardReplayResult,
)


def _candidate(symbol: str, value: float | None, *, guarded: float | None = None) -> WalkForwardCandidate:
    return WalkForwardCandidate(
        symbol=symbol,
        name=symbol,
        sector="半导体",
        selection_mode="observation",
        score=60.0,
        entry_date="2026-01-05",
        forward_returns={5: value},
        guarded_forward_returns={5: guarded},
    )


def _day(signal_date: str, candidates: list[WalkForwardCandidate]) -> WalkForwardDay:
    return WalkForwardDay(
        signal_date=signal_date,
        next_trade_date="2026-01-05",
        universe_size=100,
        feature_rows=90,
        active_symbols=100,
        feature_coverage_ratio=0.9,
        candidates=candidates,
    )


def test_summarize_replay_baseline_uses_monthly_average_without_compounding() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-02-28",
        processed_days=3,
        days=[
            _day("2026-01-02", [_candidate("600001", 0.10), _candidate("600002", -0.02)]),
            _day("2026-01-03", [_candidate("000001", 0.50)]),
            _day("2026-02-03", [_candidate("600003", -0.05)]),
        ],
    )

    summary = summarize_replay_baseline(result, horizon=5)

    assert summary["total_return"] == -0.01
    assert summary["max_drawdown"] == -0.05
    assert summary["months"] == [
        {
            "month": "2026-01",
            "signal_days": 1,
            "candidate_count": 2,
            "win_rate": 0.5,
            "month_return": 0.04,
        },
        {
            "month": "2026-02",
            "signal_days": 1,
            "candidate_count": 1,
            "win_rate": 0.0,
            "month_return": -0.05,
        },
    ]


def test_summarize_replay_baseline_can_use_guarded_returns() -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-01-31",
        processed_days=1,
        days=[_day("2026-01-02", [_candidate("600001", 0.10, guarded=0.03)])],
    )

    summary = summarize_replay_baseline(result, horizon=5, guarded=True)

    assert summary["total_return"] == 0.03
    assert summary["months"][0]["month_return"] == 0.03
