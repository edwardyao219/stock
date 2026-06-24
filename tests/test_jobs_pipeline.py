from services.collector.contracts import CollectionResult
from services.jobs import pipeline


def test_prepare_next_trade_session_runs_prepare_steps(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_is_open_trade_date", lambda db, trade_date: True)
    monkeypatch.setattr(pipeline, "_sync_daily_market_data_step", lambda trade_date: "synced")
    monkeypatch.setattr(
        pipeline,
        "_compute_features_step",
        lambda trade_date, limit: f"features:{limit}",
    )
    monkeypatch.setattr(
        pipeline,
        "_generate_trade_plans_step",
        lambda plan_date, trade_date, limit, use_learning_adjustments: (
            f"plans:{trade_date}:{use_learning_adjustments}"
        ),
    )

    result = pipeline.prepare_next_trade_session(
        "2026-06-24",
        "2026-06-25",
        limit=50,
        use_learning_adjustments=False,
    )

    assert result.stage == "prepare_next_session"
    assert [item.name for item in result.steps] == [
        "sync_daily_market_data",
        "compute_features",
        "generate_trade_plans",
    ]
    assert result.steps[2].detail == "plans:2026-06-25:False"


def test_sync_daily_market_data_step_returns_chinese_failure_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "sync_daily_market_data",
        lambda trade_date, *, full_refresh=False: [
            CollectionResult(
                source="akshare",
                dataset="trading_calendar_and_securities",
                trade_date=trade_date,
                rows=0,
                status="failed",
                message="ProxyError: unable to connect",
            ),
            CollectionResult(
                source="akshare",
                dataset="stock_daily",
                trade_date=trade_date,
                rows=0,
                status="pending",
                message="queued",
            ),
        ],
    )

    result = pipeline._sync_daily_market_data_step("2026-06-24")

    assert result.status == "failed"
    assert result.summary == "同步行情失败"
    assert "同步行情部分失败" in result.detail
    assert result.details[0].startswith("trading_calendar_and_securities")


def test_sync_daily_market_data_step_defaults_to_lightweight_mode(monkeypatch) -> None:
    captured = {}

    def fake_sync(trade_date, *, full_refresh=False):
        captured["full_refresh"] = full_refresh
        return [
            CollectionResult(
                source="local",
                dataset="daily_market_data",
                trade_date=trade_date,
                rows=0,
                status="skipped",
                message="local only",
            )
        ]

    monkeypatch.setattr(pipeline, "sync_daily_market_data", fake_sync)

    result = pipeline._sync_daily_market_data_step("2026-06-24")

    assert captured["full_refresh"] is False
    assert result.status == "skipped"
    assert result.summary == "已跳过全量同步"


def test_intraday_session_skips_outside_window(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "is_a_share_intraday_window", lambda: False)

    result = pipeline.run_intraday_trade_session("2026-06-24", force=False)

    assert result.stage == "intraday"
    assert result.steps[0].status == "ok"
    assert result.steps[0].detail == "当前不在 A 股盘中时段，已跳过实时监控。"


def test_after_close_session_runs_review_learning_steps(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "_run_daily_paper_simulation_step",
        lambda trade_date, account: f"paper:{account}",
    )
    monkeypatch.setattr(pipeline, "_generate_paper_reviews_step", lambda trade_date: "reviews")
    monkeypatch.setattr(pipeline, "_run_rule_regression_step", lambda trade_date, limit: "backtest")
    monkeypatch.setattr(pipeline, "_generate_daily_review_step", lambda trade_date: "daily")

    result = pipeline.run_after_close_session("2026-06-24", "2026-06-25", account="default")

    assert result.stage == "after_close"
    assert [item.name for item in result.steps] == [
        "run_daily_paper_simulation",
        "generate_paper_trading_review",
        "run_rule_regression",
        "generate_daily_review",
    ]
    assert result.steps[1].detail == "reviews"


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None
