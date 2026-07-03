from apps.api.app.main import create_app
from apps.api.app.routers import jobs
from services.jobs import run_pipeline as run_pipeline_cli
from services.jobs.pipeline import DailyPipelineResult, PipelineStepResult


def _result(stage: str) -> DailyPipelineResult:
    return DailyPipelineResult(
        trade_date="2026-06-24",
        next_trade_date="2026-06-25",
        stage=stage,
        steps=[PipelineStepResult(name="sample", status="ok", detail="done")],
    )


def test_jobs_routes_are_registered() -> None:
    schema = create_app().openapi()

    assert "/jobs/pipeline/run" in schema["paths"]
    assert "/jobs/historical-replay/run" in schema["paths"]


def test_run_prepare_pipeline_stage(monkeypatch) -> None:
    captured = {}

    def fake_prepare(trade_date, next_trade_date, **kwargs):
        captured.update(
            {
                "trade_date": trade_date,
                "next_trade_date": next_trade_date,
                **kwargs,
            }
        )
        return _result("prepare_next_session")

    monkeypatch.setattr(jobs, "prepare_next_trade_session", fake_prepare)

    payload = jobs.run_pipeline_stage(
        jobs.PipelineRunRequest(
            stage="prepare",
            trade_date="2026-06-24",
            next_trade_date="2026-06-25",
            limit=20,
            disable_learning_adjustments=True,
            full_market_sync=True,
            force=True,
        )
    )

    assert payload.stage == "prepare_next_session"
    assert payload.steps[0].detail == "done"
    assert captured["limit"] == 20
    assert captured["use_learning_adjustments"] is False
    assert captured["full_market_sync"] is True
    assert captured["force"] is True


def test_run_intraday_pipeline_stage(monkeypatch) -> None:
    captured = {}

    def fake_intraday(trade_date, **kwargs):
        captured.update({"trade_date": trade_date, **kwargs})
        return _result("intraday")

    monkeypatch.setattr(jobs, "run_intraday_trade_session", fake_intraday)

    payload = jobs.run_pipeline_stage(
        jobs.PipelineRunRequest(
            stage="intraday",
            trade_date="2026-06-24",
            account="paper",
            dry_run_exits=True,
        )
    )

    assert payload.stage == "intraday"
    assert captured["account"] == "paper"
    assert captured["execute_exits"] is False


def test_run_after_close_pipeline_stage(monkeypatch) -> None:
    captured = {}

    def fake_after_close(trade_date, next_trade_date, **kwargs):
        captured.update(
            {
                "trade_date": trade_date,
                "next_trade_date": next_trade_date,
                **kwargs,
            }
        )
        return _result("after_close")

    monkeypatch.setattr(jobs, "run_after_close_session", fake_after_close)

    payload = jobs.run_pipeline_stage(
        jobs.PipelineRunRequest(
            stage="after-close",
            trade_date="2026-06-24",
            next_trade_date="2026-06-25",
            full_market_sync=True,
        )
    )

    assert payload.stage == "after_close"
    assert captured["full_market_sync"] is True


def test_run_historical_replay_job(monkeypatch) -> None:
    captured = {}

    class _ReplayResult:
        def to_dict(self):
            return {
                "start_date": "2026-01-02",
                "end_date": "2026-01-03",
                "account": "历史回放",
                "symbols": ["002837"],
                "processed_days": 2,
                "generated_plans": 1,
                "opened": 0,
                "closed": 0,
                "skipped": 0,
                "account_summary": {
                    "initial_cash": 500000.0,
                    "cash": 500000.0,
                    "market_value": 0.0,
                    "equity": 500000.0,
                    "total_return_pct": 0.0,
                    "realized_pnl": 0.0,
                    "open_positions": 0,
                    "closed_positions": 0,
                    "win_rate": None,
                    "avg_closed_return_pct": None,
                },
                "days": [],
            }

    def fake_replay(**kwargs):
        captured.update(kwargs)
        return _ReplayResult()

    monkeypatch.setattr(jobs, "run_historical_replay", fake_replay)

    payload = jobs.run_historical_replay_job(
        jobs.HistoricalReplayRunRequest(
            preset="june_hot_sectors",
            symbols=["600183", "603083", "002837", "600519"],
            initial_cash=500000,
            dry_run=True,
        )
    )

    assert payload.processed_days == 2
    assert captured["preset"] == "june_hot_sectors"
    assert captured["symbols"] == ["600183", "603083", "002837", "600519"]
    assert str(captured["initial_cash"]) == "500000.0"
    assert captured["dry_run"] is True


def test_run_pipeline_cli_uses_resolved_next_trade_date(monkeypatch, capsys) -> None:
    captured = {}

    def fake_daily(trade_date, next_trade_date):
        captured["trade_date"] = trade_date
        captured["next_trade_date"] = next_trade_date
        return _result("daily")

    monkeypatch.setattr(
        run_pipeline_cli,
        "resolve_next_trade_date",
        lambda trade_date: "2026-06-29",
    )
    monkeypatch.setattr(run_pipeline_cli, "run_daily_research_pipeline", fake_daily)
    monkeypatch.setattr(run_pipeline_cli, "argparse", __import__("argparse"))

    class _Args:
        stage = "daily"
        trade_date = "2026-06-26"
        next_trade_date = None
        limit = 200
        account = "default"
        force = False
        full_market_sync = False
        disable_learning_adjustments = False
        dry_run_entries = False
        dry_run_exits = False

    monkeypatch.setattr(
        run_pipeline_cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: _Args(),
    )
    run_pipeline_cli.main()

    assert captured["next_trade_date"] == "2026-06-29"
