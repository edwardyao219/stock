from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.main import create_app
from apps.api.app.routers import jobs
from services.jobs import run_pipeline as run_pipeline_cli
from services.jobs import status as job_status
from services.jobs.pipeline import DailyPipelineResult, PipelineStepResult
from services.shared.database import Base
from services.shared.models import (
    BacktestTradeRecord,
    IntradayMarketTurnSnapshot,
    MarketRegimeDaily,
    ReviewReport,
    RulePerformanceDaily,
)


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
    assert "/jobs/rule-regression/status" in schema["paths"]
    assert "/jobs/after-close/status" in schema["paths"]


def test_after_close_status_reads_cached_status(monkeypatch) -> None:
    monkeypatch.setattr(
        jobs,
        "read_after_close_status",
        lambda trade_date: {
            "trade_date": trade_date,
            "next_trade_date": "2026-07-10",
            "status": "ok",
            "message": "收盘推送已完成：写入 12 只股票，生成 0 条交易计划。",
            "updated_at": "2026-07-09T18:24:22+08:00",
            "candidate_count": 12,
            "plan_count": 0,
            "dingtalk_statuses": ["dingtalk:ok", "dingtalk:ok"],
            "moneyflow_status": "ok",
            "moneyflow_rows": 5197,
            "moneyflow_updated_at": "2026-07-09T19:30:00+08:00",
            "plan_refresh_status": "ok",
            "existing_plans": 2,
            "plan_rows_refreshed": 2,
            "candidate_recovery_status": "ok",
            "candidate_recovery_summary": "候选恢复完成：写入 3 只股票，生成 1 条交易计划。",
            "market_summary": "市场 weak_trend / 压力大",
            "tushare_evidence_health": {
                "trade_date": trade_date,
                "daily_symbol_count": 100,
                "datasets": [],
            },
            "source": "cache",
        },
    )

    payload = jobs.get_after_close_status(db=None, trade_date="2026-07-09")

    assert payload.status == "ok"
    assert payload.candidate_count == 12
    assert payload.dingtalk_statuses == ["dingtalk:ok", "dingtalk:ok"]
    assert payload.moneyflow_status == "ok"
    assert payload.moneyflow_rows == 5197
    assert payload.moneyflow_updated_at == "2026-07-09T19:30:00+08:00"
    assert payload.plan_refresh_status == "ok"
    assert payload.existing_plans == 2
    assert payload.plan_rows_refreshed == 2
    assert payload.candidate_recovery_status == "ok"
    assert payload.candidate_recovery_summary == "候选恢复完成：写入 3 只股票，生成 1 条交易计划。"
    assert payload.market_summary == "市场 weak_trend / 压力大"
    assert payload.tushare_evidence_health["daily_symbol_count"] == 100


def test_after_close_status_refreshes_cached_tushare_health_from_database(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(
        jobs,
        "read_after_close_status",
        lambda trade_date: {
            "trade_date": trade_date,
            "status": "warning",
            "message": "等待补采。",
            "tushare_evidence_health": {"trade_date": trade_date, "datasets": []},
        },
    )
    monkeypatch.setattr(
        jobs,
        "inspect_tushare_evidence_health",
        lambda db, trade_date: {
            "trade_date": trade_date.isoformat(),
            "daily_symbol_count": 99,
            "datasets": [{"name": "limit_list_d", "status": "ok"}],
        },
    )

    with session() as db:
        payload = jobs.get_after_close_status(db=db, trade_date="2026-07-09")

    assert payload.tushare_evidence_health["daily_symbol_count"] == 99
    assert payload.tushare_evidence_health["datasets"][0]["status"] == "ok"


def test_after_close_status_explains_trade_plan_data_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        jobs,
        "read_after_close_status",
        lambda trade_date: {
            "trade_date": trade_date,
            "status": "warning",
            "message": "数据等待补齐。",
            "tushare_evidence_health": {
                "trade_date": trade_date,
                "daily_symbol_count": 100,
                "datasets": [{"name": "cyq_perf", "status": "partial"}],
            },
        },
    )

    payload = jobs.get_after_close_status(db=None, trade_date="2026-07-09")

    assert payload.data_evidence_risk["status"] == "blocked"
    assert "尾盘行情" in payload.data_evidence_risk["reasons"][0]
    assert "筹码分布：数据覆盖不完整" in payload.data_evidence_risk["reasons"]


def test_after_close_status_returns_unknown_without_cache(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "read_after_close_status", lambda trade_date: None)

    payload = jobs.get_after_close_status(db=None, trade_date="2026-07-09")

    assert payload.status == "unknown"
    assert payload.trade_date == "2026-07-09"
    assert "还没有收盘推送记录" in payload.message


def test_after_close_status_exposes_late_market_index_evidence(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(
        jobs,
        "read_after_close_status",
        lambda trade_date: {"trade_date": trade_date, "status": "ok", "message": "已完成"},
    )

    with session() as db:
        db.add(
            IntradayMarketTurnSnapshot(
                trade_date=date(2026, 7, 17),
                snapshot_time=datetime(2026, 7, 17, 14, 50),
                coverage_ratio=0.998,
                breadth_ratio=0.42,
                total_amount=123.0,
                index_change_pct=-0.0123,
                sector_expansion_count=2,
                state_json={
                    "data_ready": True,
                    "index_evidence": {
                        "code": "sh000001",
                        "name": "上证指数",
                        "change_pct": -0.0123,
                        "source": "akshare.stock_zh_index_spot_sina",
                        "captured_at": "2026-07-17T14:50:00",
                    },
                },
            )
        )
        db.commit()
        payload = jobs.get_after_close_status(db=db, trade_date="2026-07-17")

    assert payload.late_market_index_evidence["code"] == "sh000001"
    assert payload.late_market_index_evidence["change_pct"] == -0.0123
    assert payload.late_market_index_evidence["source"] == "akshare.stock_zh_index_spot_sina"


def test_after_close_status_backfills_market_regime_from_daily_record(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(
        jobs,
        "read_after_close_status",
        lambda trade_date: {
            "trade_date": trade_date,
            "status": "ok",
            "message": "已完成",
            "market_regime": "weak_trend",
            "market_regime_risk_level": "high",
        },
    )

    with session() as db:
        db.add(
            MarketRegimeDaily(
                trade_date=date(2026, 7, 17),
                regime="panic",
                trend_score=22.0,
                breadth_score=18.0,
                emotion_score=20.0,
                volatility_score=74.0,
                risk_level="high",
                source="test",
            )
        )
        db.commit()
        payload = jobs.get_after_close_status(db=db, trade_date="2026-07-17")

    assert payload.market_regime == "panic"
    assert payload.market_regime_risk_level == "high"


def test_after_close_status_marks_delayed_review_complete_when_report_exists(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(
        jobs,
        "read_after_close_status",
        lambda trade_date: {
            "trade_date": trade_date,
            "status": "warning",
            "message": "候选已推送，复盘任务延后。",
            "review_status": "skipped",
            "source": "cache",
        },
    )

    with session() as db:
        db.add(
            ReviewReport(
                report_date=date(2026, 7, 14),
                report_type="daily_mechanical",
                content_md="复盘内容",
            )
        )
        db.commit()

        payload = jobs.get_after_close_status(trade_date="2026-07-14", db=db)

    assert payload.review_status == "ok"


def test_after_close_recovery_endpoint_enqueues_safe_task(monkeypatch) -> None:
    captured = {}

    class _Task:
        def delay(self):
            captured["called"] = True

    monkeypatch.setattr(jobs, "now_local", lambda: datetime(2026, 7, 14, 18, 30))
    monkeypatch.setattr(jobs, "run_after_close_safe_recovery_task", _Task())

    payload = jobs.recover_after_close(trade_date="2026-07-14")

    assert captured["called"] is True
    assert payload["status"] == "queued"


def test_build_after_close_status_keeps_scheduler_health() -> None:
    payload = job_status.build_after_close_status(
        {
            "trade_date": "2026-07-14",
            "scheduler_health": {
                "state": "failed",
                "last_heartbeat_at": "2026-07-14T18:20:00+08:00",
                "completed_steps": ["sync_daily_market_data"],
                "missing_steps": ["discover_next_session_candidates"],
                "recovery_attempts": 1,
                "safe_recovery_url": "/jobs/after-close/recover?trade_date=2026-07-14",
            },
        }
    )

    assert payload["scheduler_health"]["state"] == "failed"
    assert payload["scheduler_health"]["recovery_attempts"] == 1


def test_build_after_close_status_preserves_active_and_failed_states() -> None:
    running = job_status.build_after_close_status(
        {
            "trade_date": "2026-07-14",
            "status": "running",
            "message": "盘后任务正在执行",
        }
    )
    failed = job_status.build_after_close_status(
        {
            "trade_date": "2026-07-14",
            "status": "failed",
            "message": "盘后任务失败",
        }
    )

    assert running["status"] == "running"
    assert failed["status"] == "failed"


def test_rule_regression_status_reads_latest_persisted_run(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(
        jobs,
        "_rule_regression_celery_counts",
        lambda: {"active": 0, "reserved": 0, "scheduled": 0},
    )

    with session() as db:
        db.add_all(
            [
                BacktestTradeRecord(
                    run_date=date(2026, 7, 8),
                    rule_id="R001",
                    symbol="600183",
                    signal_date=date(2026, 6, 1),
                    entry_date=date(2026, 6, 2),
                    entry_price=Decimal("10"),
                    exit_date=date(2026, 6, 5),
                    exit_price=Decimal("10.5"),
                    holding_days=3,
                    pnl_pct=Decimal("0.05"),
                    mfe_pct=Decimal("0.08"),
                    mae_pct=Decimal("-0.02"),
                    exit_reason="time_exit",
                ),
                BacktestTradeRecord(
                    run_date=date(2026, 7, 8),
                    rule_id="R002",
                    symbol="603083",
                    signal_date=date(2026, 6, 3),
                    entry_date=date(2026, 6, 4),
                    entry_price=Decimal("20"),
                    exit_date=date(2026, 6, 8),
                    exit_price=Decimal("19.8"),
                    holding_days=4,
                    pnl_pct=Decimal("-0.01"),
                    mfe_pct=Decimal("0.03"),
                    mae_pct=Decimal("-0.04"),
                    exit_reason="time_exit",
                ),
                RulePerformanceDaily(
                    rule_id="R001",
                    trade_date=date(2026, 7, 8),
                    window_days=0,
                    trade_count=2,
                    win_rate=Decimal("0.5"),
                    avg_return=Decimal("0.02"),
                    expectancy=Decimal("0.02"),
                    profit_factor=Decimal("1.5"),
                    max_drawdown=Decimal("-0.04"),
                    avg_mfe=Decimal("0.05"),
                    avg_mae=Decimal("-0.03"),
                    score=Decimal("1.0"),
                ),
            ]
        )
        db.commit()

        payload = jobs.get_rule_regression_status(db=db)

    assert payload.status == "idle"
    assert payload.is_running is False
    assert payload.latest_run_date == "2026-07-08"
    assert payload.latest_trade_count == 2
    assert payload.latest_performance_rows == 1
    assert "空闲" in payload.message


def test_rule_regression_status_reports_running_when_celery_has_active_task(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(
        jobs,
        "_rule_regression_celery_counts",
        lambda: {"active": 1, "reserved": 0, "scheduled": 0},
    )

    with session() as db:
        payload = jobs.get_rule_regression_status(db=db)

    assert payload.status == "running"
    assert payload.is_running is True
    assert payload.latest_run_date is None
    assert "运行中" in payload.message


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
    monkeypatch.setattr(run_pipeline_cli, "require_primary_database", lambda reason: None)

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
