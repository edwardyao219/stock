from services.engine.backtest import run_long_replay_baseline as baseline
from services.engine.backtest.run_long_replay_baseline import (
    diagnose_ranked_replay_losses,
    annotate_drawdown_limit,
    format_ranked_replay_market_context,
    format_ranked_replay_months,
    format_ranked_replay_baselines,
    format_replay_loss_diagnostics,
    summarize_market_context_by_month,
    rank_replay_baselines,
    resolve_guard_parameters,
    run_replay_baseline,
    summarize_replay_baseline,
)
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
            "signal_dates": ["2026-01-02"],
        },
        {
            "month": "2026-02",
            "signal_days": 1,
            "candidate_count": 1,
            "win_rate": 0.0,
            "month_return": -0.05,
            "signal_dates": ["2026-02-03"],
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


def test_run_replay_baseline_passes_guard_parameters(monkeypatch) -> None:
    captured = {}
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-01-31",
        processed_days=1,
        days=[_day("2026-01-02", [_candidate("600001", 0.10, guarded=0.03)])],
    )

    def fake_run_candidate_walk_forward_replay(**kwargs):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(
        baseline,
        "run_candidate_walk_forward_replay",
        fake_run_candidate_walk_forward_replay,
    )

    summary = run_replay_baseline(
        start_date="2026-01-01",
        end_date="2026-01-31",
        horizon=5,
        limit=3,
        candidate_scope="sector_watch",
        guarded=True,
        min_coverage_ratio=0.8,
        include_fundamentals=False,
        stop_loss_pct=0.04,
        trailing_drawdown_pct=0.08,
    )

    assert summary["total_return"] == 0.03
    assert summary["stop_loss_pct"] == 0.04
    assert summary["trailing_drawdown_pct"] == 0.08
    assert captured["stop_loss_pct"] == 0.04
    assert captured["trailing_drawdown_pct"] == 0.08
    assert captured["candidate_scope"] == "sector_watch"


def test_resolve_guard_parameters_can_adapt_by_candidate_scope() -> None:
    assert resolve_guard_parameters(
        candidate_scope="action",
        guard_preset="adaptive",
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
    ) == (0.04, 0.06)
    assert resolve_guard_parameters(
        candidate_scope="sector_watch",
        guard_preset="adaptive",
        stop_loss_pct=0.04,
        trailing_drawdown_pct=0.06,
    ) == (0.06, 0.08)
    assert resolve_guard_parameters(
        candidate_scope="unknown",
        guard_preset="fixed",
        stop_loss_pct=0.05,
        trailing_drawdown_pct=0.07,
    ) == (0.05, 0.07)


def test_resolve_guard_parameters_can_use_drawdown15_preset() -> None:
    assert resolve_guard_parameters(
        candidate_scope="sector_watch",
        guard_preset="drawdown15",
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
    ) == (0.05, 0.05)
    assert resolve_guard_parameters(
        candidate_scope="action",
        guard_preset="drawdown15",
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
    ) == (0.04, 0.05)
    assert resolve_guard_parameters(
        candidate_scope="startup_confirmed",
        guard_preset="drawdown15",
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
    ) == (0.03, 0.06)


def test_annotate_drawdown_limit_marks_pass_or_fail() -> None:
    passed = annotate_drawdown_limit({"max_drawdown": -0.12}, max_drawdown_limit_pct=0.15)
    failed = annotate_drawdown_limit({"max_drawdown": -0.18}, max_drawdown_limit_pct=0.15)

    assert passed["max_drawdown_limit_pct"] == 0.15
    assert passed["max_drawdown_passed"] is True
    assert failed["max_drawdown_passed"] is False


def test_run_replay_baseline_uses_adaptive_guard_parameters(monkeypatch) -> None:
    captured = {}
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-01-31",
        processed_days=1,
        days=[_day("2026-01-02", [_candidate("600001", 0.10, guarded=0.03)])],
    )

    def fake_run_candidate_walk_forward_replay(**kwargs):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(
        baseline,
        "run_candidate_walk_forward_replay",
        fake_run_candidate_walk_forward_replay,
    )

    summary = run_replay_baseline(
        start_date="2026-01-01",
        end_date="2026-01-31",
        horizon=5,
        limit=3,
        candidate_scope="action",
        guarded=True,
        min_coverage_ratio=0.8,
        include_fundamentals=False,
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
        guard_preset="adaptive",
    )

    assert summary["guard_preset"] == "adaptive"
    assert summary["stop_loss_pct"] == 0.04
    assert summary["trailing_drawdown_pct"] == 0.06
    assert captured["stop_loss_pct"] == 0.04
    assert captured["trailing_drawdown_pct"] == 0.06


def test_run_replay_baseline_reports_drawdown_limit(monkeypatch) -> None:
    result = WalkForwardReplayResult(
        start_date="2026-01-01",
        end_date="2026-02-28",
        processed_days=2,
        days=[
            _day("2026-01-02", [_candidate("600001", 0.10, guarded=0.03)]),
            _day("2026-02-02", [_candidate("600002", -0.20, guarded=-0.16)]),
        ],
    )

    def fake_run_candidate_walk_forward_replay(**kwargs):
        return result

    monkeypatch.setattr(
        baseline,
        "run_candidate_walk_forward_replay",
        fake_run_candidate_walk_forward_replay,
    )

    summary = run_replay_baseline(
        start_date="2026-01-01",
        end_date="2026-02-28",
        horizon=5,
        limit=3,
        candidate_scope="sector_watch",
        guarded=True,
        min_coverage_ratio=0.8,
        include_fundamentals=False,
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
        guard_preset="drawdown15",
        max_drawdown_limit_pct=0.15,
    )

    assert summary["guard_preset"] == "drawdown15"
    assert summary["stop_loss_pct"] == 0.05
    assert summary["trailing_drawdown_pct"] == 0.05
    assert summary["max_drawdown"] == -0.16
    assert summary["max_drawdown_passed"] is False


def test_rank_replay_baselines_prioritizes_drawdown_passes(monkeypatch) -> None:
    summaries = {
        ("sector_watch", "adaptive"): {
            "total_return": 0.50,
            "max_drawdown": -0.18,
            "max_drawdown_passed": False,
        },
        ("sector_watch", "drawdown15"): {
            "total_return": 0.35,
            "max_drawdown": -0.09,
            "max_drawdown_passed": True,
        },
        ("action", "drawdown15"): {
            "total_return": 0.20,
            "max_drawdown": -0.07,
            "max_drawdown_passed": True,
        },
        ("action", "adaptive"): {
            "total_return": 0.10,
            "max_drawdown": -0.06,
            "max_drawdown_passed": True,
        },
    }

    def fake_run_replay_baseline(**kwargs):
        return {
            "candidate_scope": kwargs["candidate_scope"],
            "guard_preset": kwargs["guard_preset"],
            "stop_loss_pct": 0.05,
            "trailing_drawdown_pct": 0.05,
            "candidate_count": 10,
            "month_count": 3,
            **summaries[(kwargs["candidate_scope"], kwargs["guard_preset"])],
        }

    monkeypatch.setattr(baseline, "run_replay_baseline", fake_run_replay_baseline)

    ranked = rank_replay_baselines(
        start_date="2026-01-01",
        end_date="2026-03-31",
        horizon=20,
        limit=15,
        candidate_scopes=["sector_watch", "action"],
        guard_presets=["adaptive", "drawdown15"],
        guarded=True,
        min_coverage_ratio=0.8,
        include_fundamentals=False,
        stop_loss_pct=0.06,
        trailing_drawdown_pct=0.08,
        max_drawdown_limit_pct=0.15,
    )

    assert [(item["candidate_scope"], item["guard_preset"]) for item in ranked] == [
        ("sector_watch", "drawdown15"),
        ("action", "drawdown15"),
        ("action", "adaptive"),
        ("sector_watch", "adaptive"),
    ]


def test_format_ranked_replay_baselines_uses_compact_chinese_table() -> None:
    text = format_ranked_replay_baselines(
        [
            {
                "candidate_scope": "sector_watch",
                "guard_preset": "drawdown15",
                "stop_loss_pct": 0.05,
                "trailing_drawdown_pct": 0.05,
                "total_return": 0.3556,
                "max_drawdown": -0.0884,
                "max_drawdown_passed": True,
                "candidate_count": 54,
                "month_count": 14,
            }
        ]
    )

    assert "回撤约束排名" in text
    assert "sector_watch | drawdown15 | 达标 | 35.56% | -8.84%" in text


def test_format_ranked_replay_months_shows_top_month_breakdown() -> None:
    text = format_ranked_replay_months(
        [
            {
                "candidate_scope": "sector_watch",
                "guard_preset": "drawdown15",
                "total_return": 0.3556,
                "max_drawdown": -0.0884,
                "months": [
                    {
                        "month": "2025-06",
                        "signal_days": 1,
                        "candidate_count": 2,
                        "win_rate": 1.0,
                        "month_return": 0.2013,
                    },
                    {
                        "month": "2025-09",
                        "signal_days": 5,
                        "candidate_count": 11,
                        "win_rate": 0.3636,
                        "month_return": -0.0086,
                    },
                ],
            },
            {
                "candidate_scope": "action",
                "guard_preset": "drawdown15",
                "total_return": 0.198,
                "max_drawdown": -0.0716,
                "months": [],
            },
        ],
        top_n=1,
    )

    assert "月度拆解 Top 1" in text
    assert "sector_watch/drawdown15 总收益35.56% 最大回撤-8.84%" in text
    assert "2025-06 | 1 | 2 | 100.00% | 20.13%" in text
    assert "action/drawdown15" not in text


def test_diagnose_ranked_replay_losses_flags_streaks_and_drawdown_failures() -> None:
    diagnostics = diagnose_ranked_replay_losses(
        [
            {
                "candidate_scope": "action",
                "guard_preset": "drawdown15",
                "max_drawdown_passed": True,
                "months": [
                    {"month": "2024-04", "month_return": -0.01},
                    {"month": "2024-05", "month_return": -0.02},
                    {"month": "2024-06", "month_return": -0.0573},
                    {"month": "2024-07", "month_return": 0.02},
                ],
            },
            {
                "candidate_scope": "sector_watch",
                "guard_preset": "drawdown15",
                "max_drawdown_passed": False,
                "months": [
                    {"month": "2024-06", "month_return": -0.12},
                    {"month": "2024-07", "month_return": 0.05},
                ],
            },
        ]
    )

    assert diagnostics[0] == {
        "candidate_scope": "action",
        "guard_preset": "drawdown15",
        "negative_month_count": 3,
        "worst_month": "2024-06",
        "worst_month_return": -0.0573,
        "max_loss_streak": 3,
        "recommendation": "需要行情门控",
    }
    assert diagnostics[1]["recommendation"] == "降级观察"


def test_format_replay_loss_diagnostics_uses_compact_chinese_table() -> None:
    text = format_replay_loss_diagnostics(
        [
            {
                "candidate_scope": "action",
                "guard_preset": "drawdown15",
                "negative_month_count": 3,
                "worst_month": "2024-06",
                "worst_month_return": -0.0573,
                "max_loss_streak": 3,
                "recommendation": "需要行情门控",
            }
        ]
    )

    assert "亏损月诊断" in text
    assert "action | drawdown15 | 3 | 2024-06 -5.73% | 3 | 需要行情门控" in text


def test_summarize_market_context_by_month_uses_signal_day_rows() -> None:
    summary = summarize_market_context_by_month(
        [
            {
                "trade_date": "2024-06-03",
                "trend_score": 40.0,
                "breadth_score": 35.0,
                "emotion_score": 25.0,
            },
            {
                "trade_date": "2024-06-04",
                "trend_score": 50.0,
                "breadth_score": 45.0,
                "emotion_score": 55.0,
            },
        ]
    )

    assert summary["2024-06"] == {
        "trend_score": 45.0,
        "breadth_score": 40.0,
        "emotion_score": 40.0,
        "market_state": "risk_off",
    }


def test_format_ranked_replay_market_context_marks_loss_month_state() -> None:
    text = format_ranked_replay_market_context(
        [
            {
                "candidate_scope": "action",
                "guard_preset": "drawdown15",
                "months": [
                    {
                        "month": "2024-06",
                        "month_return": -0.0573,
                        "signal_dates": ["2024-06-03"],
                    }
                ],
            }
        ],
        {"2024-06": {"trend_score": 45.0, "breadth_score": 40.0, "emotion_score": 40.0, "market_state": "risk_off"}},
        top_n=1,
    )

    assert "行情状态诊断 Top 1" in text
    assert "action/drawdown15" in text
    assert "2024-06 | -5.73% | risk_off | 趋势45.0 | 宽度40.0 | 情绪40.0" in text


def test_format_ranked_replay_market_context_marks_missing_context() -> None:
    text = format_ranked_replay_market_context(
        [
            {
                "candidate_scope": "action",
                "guard_preset": "drawdown15",
                "months": [{"month": "2024-02", "month_return": -0.0149}],
            }
        ],
        {},
        top_n=1,
    )

    assert "2024-02 | -1.49% | 缺数据 | 趋势- | 宽度- | 情绪-" in text
