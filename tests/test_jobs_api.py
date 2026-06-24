from apps.api.app.main import create_app
from apps.api.app.routers import jobs
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
            force=True,
        )
    )

    assert payload.stage == "prepare_next_session"
    assert payload.steps[0].detail == "done"
    assert captured["limit"] == 20
    assert captured["use_learning_adjustments"] is False
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
