import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.collector.contracts import CollectionResult
from services.jobs import pipeline, tasks
from services.jobs.celery_app import celery_app
from services.shared.database import Base
from services.shared.models import ResearchPoolItem


def test_prepare_next_trade_session_runs_prepare_steps(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_is_open_trade_date", lambda db, trade_date: True)
    monkeypatch.setattr(
        pipeline,
        "_sync_daily_market_data_step",
        lambda trade_date, full_refresh=False: "synced",
    )
    monkeypatch.setattr(
        pipeline,
        "_sync_sector_moneyflow_step",
        lambda trade_date, lookback_open_days=8: pipeline.PipelineStepResult(
            name="sync_sector_moneyflow",
            status="ok",
            detail=f"sector-flow:{trade_date}:{lookback_open_days}",
            summary="sector-flow",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_compute_features_step",
        lambda trade_date, limit: f"features:{limit}",
    )
    monkeypatch.setattr(
        pipeline,
        "_sync_fundamentals_step",
        lambda pool_name: pipeline.PipelineStepResult(
            name="sync_fundamentals",
            status="ok",
            detail=f"fundamentals:{pool_name}",
            summary=f"fundamentals:{pool_name}",
        ),
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
        "sync_sector_moneyflow",
        "sync_fundamentals",
        "compute_features",
        "generate_trade_plans",
    ]
    assert result.steps[4].detail == "plans:2026-06-25:False"


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


def test_sync_daily_market_data_task_runs_forced_full_market_sync(monkeypatch) -> None:
    from datetime import datetime
    from types import SimpleNamespace

    captured = {}
    outcome_health = {
        "horizons": [
            {
                "horizon": 1,
                "total_signal_count": 12,
                "completed_count": 6,
                "waiting_count": 6,
                "unavailable_count": 0,
            }
        ]
    }

    def fake_sync_step(trade_date, *, full_refresh=False, force=False):
        captured.update(
            trade_date=trade_date,
            full_refresh=full_refresh,
            force=force,
        )
        return pipeline.PipelineStepResult(
            name="sync_daily_market_data",
            status="ok",
            detail="同步行情完成",
            summary="同步行情完成",
        )

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 13, 15, 30))
    monkeypatch.setattr(tasks, "_is_open_trade_date", lambda db, trade_date: True, raising=False)
    monkeypatch.setattr(tasks, "_sync_daily_market_data_step", fake_sync_step, raising=False)
    monkeypatch.setattr(
        tasks,
        "_acquire_daily_task_lock",
        lambda task_name, trade_date: (True, "stock:daily-task:daily-market-sync:2026-07-13"),
    )
    monkeypatch.setattr(
        tasks,
        "_mainline_outcome_health",
        lambda db: outcome_health,
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "inspect_daily_data_health",
        lambda db, trade_date: SimpleNamespace(
            daily_coverage_ratio=0.99,
            eligible_daily_bar_count=5264,
            expected_security_count=5317,
        ),
        raising=False,
    )

    result = tasks.sync_daily_market_data_task()

    assert captured == {
        "trade_date": "2026-07-13",
        "full_refresh": True,
        "force": True,
    }
    assert result["status"] == "ok"
    assert result["detail"] == "同步行情完成"
    assert result["mainline_outcome_health"] == outcome_health


def test_sync_daily_market_data_task_retries_when_daily_bars_are_not_ready(monkeypatch) -> None:
    from datetime import datetime
    from types import SimpleNamespace

    released = []
    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 16, 15, 30))
    monkeypatch.setattr(tasks, "_is_open_trade_date", lambda db, trade_date: True)
    monkeypatch.setattr(
        tasks,
        "_acquire_daily_task_lock",
        lambda task_name, trade_date: (True, "daily-sync-lock"),
    )
    monkeypatch.setattr(tasks, "_release_daily_task_lock", released.append)
    monkeypatch.setattr(
        tasks,
        "_sync_daily_market_data_step",
        lambda *args, **kwargs: pipeline.PipelineStepResult(
            name="sync_daily_market_data",
            status="ok",
            detail="同步行情完成",
            summary="同步行情完成",
        ),
    )
    monkeypatch.setattr(tasks, "_mainline_outcome_health", lambda db: {"horizons": []})
    monkeypatch.setattr(
        tasks,
        "inspect_daily_data_health",
        lambda db, trade_date: SimpleNamespace(
            daily_coverage_ratio=0.0,
            eligible_daily_bar_count=0,
            expected_security_count=5317,
        ),
        raising=False,
    )

    result = tasks.sync_daily_market_data_task()

    assert result["status"] == "warning"
    assert "16:00" in result["detail"]
    assert result["daily_data_health"]["coverage_ratio"] == 0.0
    assert released == ["daily-sync-lock"]


def test_sync_daily_market_data_task_skips_non_trading_day(monkeypatch) -> None:
    from datetime import datetime

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 12, 15, 30))
    monkeypatch.setattr(tasks, "_is_open_trade_date", lambda db, trade_date: False, raising=False)
    monkeypatch.setattr(
        tasks,
        "_sync_daily_market_data_step",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sync should not run")),
        raising=False,
    )

    result = tasks.sync_daily_market_data_task()

    assert result["status"] == "skipped"
    assert "非交易日" in result["message"]


def test_compute_daily_features_task_only_computes_today_and_includes_sectors(
    monkeypatch,
) -> None:
    from datetime import date, datetime

    from services.engine.backtest import walk_forward
    from services.engine.features import sync as feature_sync

    calls = []
    target_date = date(2026, 7, 16)
    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 16, 16, 30))
    monkeypatch.setattr(
        feature_sync,
        "compute_and_store_stock_features",
        lambda **kwargs: calls.append(("stock", kwargs)) or {"symbols": 500, "rows": 500},
    )
    monkeypatch.setattr(
        feature_sync,
        "compute_and_store_sector_features",
        lambda **kwargs: calls.append(("sector", kwargs)) or {"sectors": 32, "rows": 32},
    )
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        walk_forward,
        "sync_low_dimensional_feature_snapshots",
        lambda db, *, start, end: calls.append(("cache", start, end)) or 500,
    )

    result = tasks.compute_daily_features_task()

    assert calls == [
        (
            "stock",
            {"start_date": target_date, "end_date": target_date, "limit": 500},
        ),
        ("sector", {"start_date": target_date, "end_date": target_date}),
        ("cache", target_date, target_date),
    ]
    assert result == {
        "trade_date": "2026-07-16",
        "status": "ok",
        "message": "500 条股票特征，32 条板块特征，500 条低维缓存。",
        "stock_symbols": 500,
        "stock_feature_rows": 500,
        "sectors": 32,
        "sector_feature_rows": 32,
        "snapshot_rows": 500,
    }


def test_sync_late_tushare_moneyflow_task_reports_pending_release(monkeypatch) -> None:
    from datetime import datetime

    from services.collector import sync as collector_sync

    captured = {}
    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 16, 19, 30))
    monkeypatch.setattr(tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(tasks, "_is_open_trade_date", lambda db, trade_date: True)

    def fake_sync(trade_date, *, datasets, force=False):
        captured.update(
            trade_date=trade_date,
            datasets=tuple(datasets),
            force=force,
        )
        return [
            CollectionResult(
                source="tushare_proxy",
                dataset="moneyflow",
                trade_date=trade_date,
                rows=0,
                status="pending",
                message="dataset not published yet",
            )
        ]

    monkeypatch.setattr(collector_sync, "sync_tushare_market_data_resumable", fake_sync)

    result = tasks.sync_late_tushare_moneyflow_task()

    assert captured == {
        "trade_date": "20260716",
        "datasets": ("moneyflow",),
        "force": False,
    }
    assert result == {
        "trade_date": "2026-07-16",
        "status": "warning",
        "message": "基础资金流尚未发布，本次未写入。",
        "sync_status": "pending",
        "moneyflow_rows": 0,
    }


def test_compute_features_step_refreshes_low_dimensional_snapshot_cache(monkeypatch) -> None:
    from datetime import date

    from services.engine.backtest import walk_forward
    from services.engine.features import sync as feature_sync

    calls = []

    monkeypatch.setattr(
        feature_sync,
        "compute_and_store_stock_features",
        lambda **kwargs: calls.append(("stock", kwargs)) or {"symbols": 2, "rows": 2},
    )
    monkeypatch.setattr(
        feature_sync,
        "compute_and_store_sector_features",
        lambda **kwargs: calls.append(("sector", kwargs)) or {"sectors": 1, "rows": 1},
    )
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        walk_forward,
        "sync_low_dimensional_feature_snapshots",
        lambda db, *, start, end: calls.append(("cache", start, end)) or 2,
    )

    result = pipeline._compute_features_step("2026-06-24", limit=50)

    assert calls == [
        (
            "stock",
            {"start_date": date(2026, 6, 24), "end_date": date(2026, 6, 24), "limit": 50},
        ),
        ("sector", {"start_date": date(2026, 6, 24), "end_date": date(2026, 6, 24)}),
        ("cache", date(2026, 6, 24), date(2026, 6, 24)),
    ]
    assert "2 条低维缓存" in result


def test_generate_trade_plans_step_uses_latest_candidate_pool(monkeypatch) -> None:
    captured = {}

    def fake_generate_and_store_trade_plans(**kwargs):
        captured.update(kwargs)
        return {"contexts": 3, "written": 2}

    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )

    detail = pipeline._generate_trade_plans_step(
        "2026-07-07",
        "2026-07-08",
        limit=200,
        use_learning_adjustments=True,
    )

    assert captured["pool_name"] == "experiment"
    assert "symbols" not in captured
    assert "写入 2 条计划" in detail


def test_celery_after_close_screening_runs_at_six_pm() -> None:
    schedule = celery_app.conf.beat_schedule["paper-after-close-screening"]["schedule"]

    assert schedule.hour == {18}
    assert schedule.minute == {0}


def test_celery_retries_late_tushare_moneyflow_twice() -> None:
    entry = celery_app.conf.beat_schedule["retry-late-tushare-moneyflow"]

    assert entry["task"] == "services.jobs.tasks.sync_late_tushare_moneyflow_task"
    assert entry["schedule"].hour == {19, 20}
    assert entry["schedule"].minute == {30}


def test_celery_captures_full_market_snapshot_after_close() -> None:
    schedule = celery_app.conf.beat_schedule["capture-full-market-snapshot"]["schedule"]

    assert schedule.hour == {15}
    assert schedule.minute == {5}


def test_celery_retries_full_market_snapshot_after_first_capture() -> None:
    schedule = celery_app.conf.beat_schedule["retry-full-market-snapshot"]["schedule"]

    assert schedule.hour == {15}
    assert schedule.minute == {20}


def test_full_market_snapshot_task_records_source_failure(monkeypatch) -> None:
    from datetime import datetime

    released = []

    class _Query:
        def filter_by(self, **kwargs):
            return self

        def count(self):
            return 100

        def all(self):
            return []

    class _Db:
        def query(self, model):
            return _Query()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 15, 5))
    monkeypatch.setattr(tasks, "SessionLocal", _Db)
    monkeypatch.setattr(tasks, "_is_open_trade_date", lambda db, trade_date: True)
    monkeypatch.setattr(tasks, "_acquire_daily_task_lock", lambda *args: (True, "lock"))
    monkeypatch.setattr(tasks, "_release_daily_task_lock", released.append, raising=False)
    monkeypatch.setattr(
        tasks,
        "sync_realtime_quotes",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("source unavailable")),
    )

    result = tasks.capture_full_market_snapshot_task()

    assert result["status"] == "failed"
    assert "source unavailable" in result["message"]
    assert released == ["lock"]


def test_full_market_snapshot_task_releases_lock_when_coverage_is_low(monkeypatch) -> None:
    from datetime import datetime

    released = []

    class _Query:
        def filter_by(self, **kwargs):
            return self

        def count(self):
            return 100

        def all(self):
            return []

    class _Db:
        def query(self, model):
            return _Query()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 15, 5))
    monkeypatch.setattr(tasks, "SessionLocal", _Db)
    monkeypatch.setattr(tasks, "_is_open_trade_date", lambda db, trade_date: True)
    monkeypatch.setattr(tasks, "_acquire_daily_task_lock", lambda *args: (True, "lock"))
    monkeypatch.setattr(tasks, "_release_daily_task_lock", released.append, raising=False)
    monkeypatch.setattr(tasks, "sync_realtime_quotes", lambda **kwargs: [])

    result = tasks.capture_full_market_snapshot_task()

    assert result["status"] == "warning"
    assert released == ["lock"]


def test_full_market_snapshot_coverage_excludes_inactive_symbols(monkeypatch) -> None:
    from datetime import datetime
    from types import SimpleNamespace

    released = []

    class _Query:
        def filter_by(self, **kwargs):
            return self

        def count(self):
            return 2

        def all(self):
            return [SimpleNamespace(symbol="000001"), SimpleNamespace(symbol="000002")]

    class _Db:
        def query(self, model):
            return _Query()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    quotes = [
        SimpleNamespace(symbol="000001", price=10, pre_close=9),
        SimpleNamespace(symbol="600000", price=10, pre_close=9),
    ]
    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 15, 5))
    monkeypatch.setattr(tasks, "SessionLocal", _Db)
    monkeypatch.setattr(tasks, "_is_open_trade_date", lambda db, trade_date: True)
    monkeypatch.setattr(tasks, "_acquire_daily_task_lock", lambda *args: (True, "lock"))
    monkeypatch.setattr(tasks, "_release_daily_task_lock", released.append, raising=False)
    monkeypatch.setattr(tasks, "sync_realtime_quotes", lambda **kwargs: quotes)

    result = tasks.capture_full_market_snapshot_task()

    assert result["status"] == "warning"
    assert result["coverage_ratio"] == 0.5
    assert released == ["lock"]


def test_celery_after_close_recovery_checks_run_after_session(monkeypatch) -> None:
    schedules = [
        celery_app.conf.beat_schedule["after-close-safe-recovery-1820"]["schedule"],
        celery_app.conf.beat_schedule["after-close-safe-recovery-1840"]["schedule"],
    ]

    assert [(item.hour, item.minute) for item in schedules] == [({18}, {20}), ({18}, {40})]


def test_after_close_recovery_skips_completed_status(monkeypatch) -> None:
    from datetime import datetime

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(tasks, "read_after_close_status", lambda trade_date: {"status": "ok"})

    result = tasks.run_after_close_safe_recovery_task()

    assert result["status"] == "skipped"


def test_after_close_recovery_skips_active_normal_task(monkeypatch) -> None:
    from datetime import datetime

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(
        tasks,
        "read_after_close_status",
        lambda trade_date: {
            "status": "running",
            "scheduler_health": {"state": "running"},
        },
    )
    monkeypatch.setattr(
        tasks,
        "run_after_close_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recovery must not overlap an active normal task")
        ),
    )
    monkeypatch.setattr(tasks, "_is_after_close_task_active", lambda: True, raising=False)

    result = tasks.run_after_close_safe_recovery_task()

    assert result["status"] == "skipped"
    assert "still running" in result["message"]


def test_after_close_recovery_resumes_stale_running_task(monkeypatch) -> None:
    from datetime import datetime

    class _Result:
        def to_dict(self):
            return {"trade_date": "2026-07-14", "steps": []}

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(
        tasks,
        "read_after_close_status",
        lambda trade_date: {"status": "running", "scheduler_health": {"state": "running"}},
    )
    monkeypatch.setattr(tasks, "_is_after_close_task_active", lambda: False, raising=False)
    monkeypatch.setattr(
        tasks,
        "_acquire_after_close_recovery_lock",
        lambda trade_date: (True, "lock"),
    )
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-15")
    monkeypatch.setattr(tasks, "run_after_close_session", lambda *args, **kwargs: _Result())
    monkeypatch.setattr(tasks, "write_after_close_status", lambda result: None)

    result = tasks.run_after_close_safe_recovery_task()

    assert result["scheduler_health"]["state"] == "completed"


def test_after_close_recovery_runs_safe_pipeline_when_status_is_missing(monkeypatch) -> None:
    from datetime import datetime

    captured = {}

    class _Result:
        def to_dict(self):
            return {"trade_date": "2026-07-14", "next_trade_date": "2026-07-15", "steps": []}

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(tasks, "read_after_close_status", lambda trade_date: None)
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-15")
    monkeypatch.setattr(
        tasks,
        "_acquire_after_close_recovery_lock",
        lambda trade_date: (True, "lock"),
    )
    monkeypatch.setattr(
        tasks,
        "_claim_after_close_recovery_slot",
        lambda trade_date: (True, "after-close-lock"),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "run_after_close_session",
        lambda trade_date, next_trade_date, **kwargs: captured.update(kwargs) or _Result(),
    )
    monkeypatch.setattr(
        tasks,
        "write_after_close_status",
        lambda result: captured.update(result=result),
    )

    result = tasks.run_after_close_safe_recovery_task()

    assert captured["safe_recovery"] is True
    assert captured["suppress_candidate_notification"] is False
    assert result["scheduler_health"]["state"] == "completed"
    assert captured["result"] == result


def test_after_close_recovery_skips_candidate_notification_already_delivered(monkeypatch) -> None:
    from datetime import datetime

    captured = {}

    class _Result:
        def to_dict(self):
            return {"trade_date": "2026-07-14", "steps": []}

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(
        tasks,
        "read_after_close_status",
        lambda trade_date: {"status": "failed", "dingtalk_statuses": ["dingtalk:ok"]},
    )
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-15")
    monkeypatch.setattr(
        tasks,
        "_acquire_after_close_recovery_lock",
        lambda trade_date: (True, "lock"),
    )
    monkeypatch.setattr(
        tasks,
        "run_after_close_session",
        lambda *args, **kwargs: captured.update(kwargs) or _Result(),
    )
    monkeypatch.setattr(tasks, "write_after_close_status", lambda result: None)

    tasks.run_after_close_safe_recovery_task()

    assert captured["suppress_candidate_notification"] is True


def test_after_close_recovery_releases_its_lock_after_completion(monkeypatch) -> None:
    from datetime import datetime

    released = []

    class _Result:
        def to_dict(self):
            return {"trade_date": "2026-07-14", "steps": []}

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(tasks, "read_after_close_status", lambda trade_date: None)
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-15")
    monkeypatch.setattr(
        tasks,
        "_acquire_after_close_recovery_lock",
        lambda trade_date: ("recovery-token", "recovery-lock"),
    )
    monkeypatch.setattr(
        tasks,
        "_claim_after_close_recovery_slot",
        lambda trade_date: (True, "after-close-lock"),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "_release_after_close_recovery_lock",
        lambda *args: released.append(args),
        raising=False,
    )
    monkeypatch.setattr(tasks, "run_after_close_session", lambda *args, **kwargs: _Result())
    monkeypatch.setattr(tasks, "write_after_close_status", lambda result: None)

    tasks.run_after_close_safe_recovery_task()

    assert released == [("recovery-lock", "recovery-token")]


def test_after_close_recovery_skips_when_another_recovery_holds_the_lock(monkeypatch) -> None:
    from datetime import datetime

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(tasks, "read_after_close_status", lambda trade_date: None)
    monkeypatch.setattr(
        tasks,
        "_acquire_after_close_recovery_lock",
        lambda trade_date: (False, "stock:after-close-recovery:2026-07-14"),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "_claim_after_close_recovery_slot",
        lambda trade_date: (True, "after-close-lock"),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "run_after_close_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recovery must not overlap another recovery")
        ),
    )

    result = tasks.run_after_close_safe_recovery_task()

    assert result["status"] == "skipped"
    assert "recovery already running" in result["message"]


def test_after_close_recovery_claims_missing_normal_task_slot(monkeypatch) -> None:
    from datetime import datetime

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(tasks, "read_after_close_status", lambda trade_date: None)
    monkeypatch.setattr(
        tasks,
        "_claim_after_close_recovery_slot",
        lambda trade_date: (False, "stock:daily-task:after-close:2026-07-14"),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "run_after_close_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("normal task reservation must prevent recovery overlap")
        ),
    )

    result = tasks.run_after_close_safe_recovery_task()

    assert result["status"] == "skipped"
    assert "normal after-close task" in result["message"]


def test_after_close_recovery_stops_after_two_attempts(monkeypatch) -> None:
    from datetime import datetime

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 40))
    monkeypatch.setattr(
        tasks,
        "read_after_close_status",
        lambda trade_date: {
            "status": "failed",
            "scheduler_health": {"recovery_attempts": 2},
        },
    )
    monkeypatch.setattr(
        tasks,
        "run_after_close_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recovery attempt limit must prevent another run")
        ),
    )

    result = tasks.run_after_close_safe_recovery_task()

    assert result["status"] == "skipped"
    assert "attempt limit" in result["message"]


def test_after_close_recovery_records_and_alerts_failure(monkeypatch) -> None:
    from datetime import datetime

    captured = {}
    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(tasks, "read_after_close_status", lambda trade_date: None)
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-15")
    monkeypatch.setattr(
        tasks,
        "_claim_after_close_recovery_slot",
        lambda trade_date: (True, "after-close-lock"),
    )
    monkeypatch.setattr(
        tasks,
        "_acquire_after_close_recovery_lock",
        lambda trade_date: (True, "lock"),
    )
    monkeypatch.setattr(
        tasks,
        "_acquire_daily_task_lock",
        lambda task_name, trade_date: (True, "alert-lock"),
    )
    monkeypatch.setattr(
        tasks,
        "run_after_close_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("sync unavailable")),
    )
    monkeypatch.setattr(
        tasks,
        "write_after_close_status",
        lambda result: captured.update(result=result),
    )
    monkeypatch.setattr(
        tasks,
        "dispatch_text",
        lambda content: captured.update(alert=content) or [],
    )

    result = tasks.run_after_close_safe_recovery_task()

    assert result["scheduler_health"]["state"] == "failed"
    assert "sync unavailable" in result["scheduler_health"]["error"]
    assert "2026-07-14" in captured["alert"]


def test_after_close_recovery_alerts_each_failed_stage_once(monkeypatch) -> None:
    from datetime import datetime

    alerts = []
    alert_locks = iter([(True, "alert-lock"), (False, "alert-lock")])
    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 7, 14, 18, 20))
    monkeypatch.setattr(tasks, "read_after_close_status", lambda trade_date: None)
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-15")
    monkeypatch.setattr(
        tasks,
        "_acquire_after_close_recovery_lock",
        lambda trade_date: (True, "lock"),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "_claim_after_close_recovery_slot",
        lambda trade_date: (True, "after-close-lock"),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "_acquire_daily_task_lock",
        lambda task_name, trade_date: next(alert_locks),
    )
    monkeypatch.setattr(
        tasks,
        "run_after_close_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("sync unavailable")),
    )
    monkeypatch.setattr(tasks, "write_after_close_status", lambda result: None)
    monkeypatch.setattr(tasks, "dispatch_text", alerts.append)

    tasks.run_after_close_safe_recovery_task()
    tasks.run_after_close_safe_recovery_task()

    assert len(alerts) == 1
    assert "盘后恢复失败" in alerts[0]


def test_celery_daily_jobs_use_documented_wall_clock_times() -> None:
    expected = {
        "pre-market-check": ({8}, {30}),
        "sync-daily-market-data": ({15}, {30}),
        "retry-sync-daily-market-data": ({16}, {0}),
        "compute-daily-features": ({16}, {30}),
        "run-rule-regression": ({21}, {0}),
        "generate-daily-review": ({22}, {30}),
    }

    for job_name, (hour, minute) in expected.items():
        schedule = celery_app.conf.beat_schedule[job_name]["schedule"]
        assert schedule.hour == hour
        assert schedule.minute == minute


def test_celery_does_not_auto_run_legacy_trade_plan_task() -> None:
    assert "generate-trade-plans" not in celery_app.conf.beat_schedule


def test_celery_beat_does_not_catch_up_stale_cron_tasks() -> None:
    assert celery_app.conf.beat_cron_starting_deadline == 120


def test_after_close_task_uses_full_market_sync_before_screening(monkeypatch) -> None:
    from datetime import datetime

    captured = {}
    written = []

    class _Result:
        def to_dict(self):
            return {
                "trade_date": "2026-06-30",
                "next_trade_date": "2026-07-01",
                "stage": "after_close",
                "steps": [
                    {
                        "name": "sync_daily_market_data",
                        "status": "ok",
                        "detail": "同步行情完成",
                        "details": [
                            "moneyflow_dc: ok, rows=5907",
                            "limit_list_d: ok, rows=187",
                            "cyq_perf: ok, rows=5521",
                        ],
                    },
                    {
                        "name": "discover_next_session_candidates",
                        "status": "ok",
                        "detail": (
                            "明日候选完成：扫描 3000 只股票，"
                            "写入 12 只股票，生成 1 条交易计划。"
                        ),
                        "details": ["钉钉提醒：dingtalk:ok"],
                    }
                ],
            }

    def fake_run_after_close_session(trade_date, next_trade_date, **kwargs):
        captured.update(
            {
                "trade_date": trade_date,
                "next_trade_date": next_trade_date,
                **kwargs,
            }
        )
        return _Result()

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 6, 30, 18, 0))
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-01")
    monkeypatch.setattr(tasks, "run_after_close_session", fake_run_after_close_session)
    monkeypatch.setattr(
        tasks,
        "inspect_tushare_evidence_health",
        lambda db, trade_date, sync_statuses: {
            "trade_date": trade_date.isoformat(),
            "daily_symbol_count": 100,
            "datasets": [],
            "sync_statuses": sync_statuses,
        },
    )

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks, "SessionLocal", _Db)
    monkeypatch.setattr(
        tasks,
        "write_after_close_status",
        lambda result: written.append(result),
    )
    monkeypatch.setattr(
        tasks,
        "_acquire_daily_task_lock",
        lambda task_name, trade_date: (True, "stock:daily-task:after-close:2026-06-30"),
    )

    result = tasks.run_after_close_session_task()

    assert result["stage"] == "after_close"
    assert written[0]["status"] == "running"
    assert written[-1] == result
    assert captured["trade_date"] == "2026-06-30"
    assert captured["next_trade_date"] == "2026-07-01"
    assert captured["full_market_sync"] is True
    assert result["tushare_evidence_health"]["sync_statuses"] == {
        "moneyflow_dc": "ok",
        "limit_list_d": "ok",
        "cyq_perf": "ok",
    }


def test_after_close_task_writes_running_heartbeat_before_pipeline(monkeypatch) -> None:
    from datetime import datetime

    writes = []

    class _Result:
        def to_dict(self):
            return {
                "trade_date": "2026-06-30",
                "next_trade_date": "2026-07-01",
                "stage": "after_close",
                "steps": [{"name": "sync_daily_market_data", "status": "ok"}],
            }

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 6, 30, 18, 0))
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-01")
    monkeypatch.setattr(tasks, "run_after_close_session", lambda *args, **kwargs: _Result())
    monkeypatch.setattr(tasks, "SessionLocal", _Db)
    monkeypatch.setattr(tasks, "inspect_tushare_evidence_health", lambda *args: {})
    monkeypatch.setattr(tasks, "write_after_close_status", writes.append)
    monkeypatch.setattr(tasks, "_acquire_daily_task_lock", lambda *args: (True, "lock"))

    tasks.run_after_close_session_task()

    assert writes[0]["status"] == "running"
    assert writes[0]["scheduler_health"]["state"] == "running"
    assert writes[-1]["scheduler_health"]["state"] == "completed"


def test_after_close_task_records_failure_when_pipeline_raises(monkeypatch) -> None:
    from datetime import datetime

    writes = []
    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 6, 30, 18, 0))
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-01")
    monkeypatch.setattr(tasks, "_acquire_daily_task_lock", lambda *args: (True, "lock"))
    monkeypatch.setattr(tasks, "write_after_close_status", writes.append)
    monkeypatch.setattr(tasks, "_dispatch_after_close_failure_alert", lambda *args: None)
    monkeypatch.setattr(
        tasks,
        "run_after_close_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("sync unavailable")),
    )

    with pytest.raises(RuntimeError, match="sync unavailable"):
        tasks.run_after_close_session_task()

    assert writes[-1]["status"] == "failed"
    assert writes[-1]["scheduler_health"]["state"] == "failed"


def test_after_close_task_skips_duplicate_daily_push(monkeypatch) -> None:
    from datetime import datetime

    calls = []

    def fake_run_after_close_session(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("duplicate after-close push should not run")

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 6, 30, 18, 0))
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-01")
    monkeypatch.setattr(tasks, "run_after_close_session", fake_run_after_close_session)
    monkeypatch.setattr(
        tasks,
        "_acquire_daily_task_lock",
        lambda task_name, trade_date: (False, "stock:daily-task:after-close:2026-06-30"),
    )

    result = tasks.run_after_close_session_task()

    assert result["status"] == "skipped"
    assert "already running" in result["message"]
    assert calls == []


def test_after_close_task_ignores_stale_catchup_before_after_close_window(monkeypatch) -> None:
    from datetime import datetime

    calls = []

    def fake_run_after_close_session(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("stale catch-up should not run after-close session")

    def fake_lock(*args, **kwargs):
        raise AssertionError("stale catch-up should not occupy the after-close lock")

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 6, 30, 8, 46))
    monkeypatch.setattr(tasks, "resolve_next_trade_date", lambda trade_date: "2026-07-01")
    monkeypatch.setattr(tasks, "run_after_close_session", fake_run_after_close_session)
    monkeypatch.setattr(tasks, "_acquire_daily_task_lock", fake_lock)

    result = tasks.run_after_close_session_task()

    assert result["status"] == "skipped"
    assert "outside after-close window" in result["message"]
    assert calls == []


def test_celery_intraday_schedule_matches_trading_windows() -> None:
    schedule = celery_app.conf.beat_schedule["paper-intraday-screening"]["schedule"]

    assert schedule.hour == {9, 10, 11, 13, 14}
    assert schedule.minute == {0, 5, 10, 15, 20, 25, 30, 40, 45, 55}


def test_celery_has_early_midday_and_late_session_snapshot_jobs() -> None:
    early_job = celery_app.conf.beat_schedule["paper-early-divergence-snapshot"]
    midday_job = celery_app.conf.beat_schedule["paper-midday-snapshot"]
    late_job = celery_app.conf.beat_schedule["paper-late-session-snapshot"]
    early = early_job["schedule"]
    midday = midday_job["schedule"]
    late = late_job["schedule"]

    assert early.hour == {9}
    assert early.minute == {45}
    assert early_job["task"] == "services.jobs.tasks.paper_early_divergence_snapshot_task"
    assert midday.hour == {11}
    assert midday.minute == {35}
    assert midday_job["task"] == "services.jobs.tasks.paper_midday_snapshot_task"
    assert late.hour == {14}
    assert late.minute == {50}
    assert late_job["task"] == "services.jobs.tasks.paper_late_session_snapshot_task"


def test_celery_captures_early_market_repair_snapshots() -> None:
    expected_times = {
        "capture-intraday-market-turn-0935": (9, 35),
        "capture-intraday-market-turn-0945": (9, 45),
        "capture-intraday-market-turn-1030": (10, 30),
    }

    for job_name, (hour, minute) in expected_times.items():
        job = celery_app.conf.beat_schedule[job_name]
        schedule = job["schedule"]
        assert job["task"] == "services.jobs.tasks.capture_intraday_market_turn_snapshot_task"
        assert schedule.hour == {hour}
        assert schedule.minute == {minute}


def test_celery_captures_korea_semiconductor_signal_before_a_share_open() -> None:
    job = celery_app.conf.beat_schedule["capture-korea-semiconductor-signal"]
    schedule = job["schedule"]

    assert job["task"] == "services.jobs.tasks.capture_korea_semiconductor_signal_task"
    assert schedule.hour == {8}
    assert schedule.minute == {55}


def test_intraday_session_passes_stage_and_as_of_to_monitor(monkeypatch) -> None:
    from datetime import datetime

    captured = {}

    class _Result:
        quotes = 3
        executed_entries = 1
        alerts = []
        executed_exits = 0

    def fake_monitor(**kwargs):
        captured.update(kwargs)
        return _Result()

    monkeypatch.setattr(pipeline, "is_a_share_intraday_window", lambda: False)
    monkeypatch.setattr(
        "services.engine.paper.realtime.monitor_paper_positions_realtime",
        fake_monitor,
    )

    result = pipeline.run_intraday_trade_session(
        "2026-06-24",
        force=True,
        stage="midday_snapshot",
        as_of=datetime(2026, 6, 24, 11, 35),
    )

    assert result.stage == "midday_snapshot"
    assert result.steps[0].summary == "midday_snapshot @ 2026-06-24T11:35:00"
    assert captured["quote_time"] == datetime(2026, 6, 24, 11, 35)
    assert captured["snapshot_stage"] == "midday_snapshot"


def test_early_midday_and_late_snapshot_tasks_use_current_as_of(monkeypatch) -> None:
    from datetime import date, datetime

    captured = []

    class _Result:
        def __init__(self, stage: str) -> None:
            self.stage = stage

        def to_dict(self):
            return {"stage": self.stage}

    def fake_run(trade_date, **kwargs):
        captured.append({"trade_date": trade_date, **kwargs})
        return _Result(kwargs["stage"])

    monkeypatch.setattr(
        tasks,
        "early_sector_scan_symbols",
        lambda db, *, trade_date, include_growth_board=False: captured.append(
            {
                "step": "early_symbols",
                "trade_date": trade_date,
                "include_growth_board": include_growth_board,
            }
        )
        or ["600212", "600214"],
    )
    monkeypatch.setattr(
        tasks,
        "sync_realtime_quotes",
        lambda *, symbols, quote_time: captured.append(
            {"step": "early_sync", "symbols": list(symbols), "quote_time": quote_time}
        )
        or [object(), object()],
    )
    monkeypatch.setattr(tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 6, 24, 14, 50))
    monkeypatch.setattr(tasks, "run_intraday_trade_session", fake_run)

    early = tasks.paper_early_divergence_snapshot_task()
    midday = tasks.paper_midday_snapshot_task()
    late = tasks.paper_late_session_snapshot_task()

    assert early["stage"] == "early_divergence_snapshot"
    assert early["early_sector_quote_symbol_count"] == 2
    assert early["early_sector_quote_rows"] == 2
    assert midday["stage"] == "midday_snapshot"
    assert late["stage"] == "late_session_snapshot"
    assert captured == [
        {
            "step": "early_symbols",
            "trade_date": date(2026, 6, 24),
            "include_growth_board": False,
        },
        {
            "step": "early_sync",
            "symbols": ["600212", "600214"],
            "quote_time": datetime(2026, 6, 24, 14, 50),
        },
        {
            "trade_date": "2026-06-24",
            "stage": "early_divergence_snapshot",
            "as_of": datetime(2026, 6, 24, 14, 50),
            "force": True,
        },
        {
            "trade_date": "2026-06-24",
            "stage": "midday_snapshot",
            "as_of": datetime(2026, 6, 24, 14, 50),
            "force": True,
        },
        {
            "trade_date": "2026-06-24",
            "stage": "late_session_snapshot",
            "as_of": datetime(2026, 6, 24, 14, 50),
            "force": True,
        },
    ]


def test_early_divergence_snapshot_keeps_running_when_quote_refresh_fails(monkeypatch) -> None:
    from datetime import datetime

    calls = []

    class _Result:
        def to_dict(self):
            return {"stage": "early_divergence_snapshot"}

    def fake_sync_realtime_quotes(*, symbols, quote_time):
        calls.append(("sync", list(symbols), quote_time))
        raise ConnectionError("quote source closed")

    def fake_run(trade_date, **kwargs):
        calls.append(("run", trade_date, kwargs["stage"]))
        return _Result()

    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 6, 24, 9, 45))
    monkeypatch.setattr(
        tasks,
        "early_sector_scan_symbols",
        lambda db, *, trade_date, include_growth_board=False: ["600212"],
    )
    monkeypatch.setattr(tasks, "sync_realtime_quotes", fake_sync_realtime_quotes)
    monkeypatch.setattr(tasks, "run_intraday_trade_session", fake_run)
    monkeypatch.setattr(tasks, "SessionLocal", lambda: _Session())

    result = tasks.paper_early_divergence_snapshot_task()

    assert result["stage"] == "early_divergence_snapshot"
    assert result["early_sector_quote_symbol_count"] == 1
    assert result["early_sector_quote_rows"] == 0
    assert "quote source closed" in result["early_sector_quote_warning"]
    assert calls == [
        ("sync", ["600212"], datetime(2026, 6, 24, 9, 45)),
        ("run", "2026-06-24", "early_divergence_snapshot"),
    ]


def test_resolve_next_trade_date_prefers_calendar_next_trade(monkeypatch) -> None:
    class _CalendarItem:
        next_trade_date = None

    class _Db:
        def get(self, model, current):
            item = _CalendarItem()
            item.next_trade_date = __import__("datetime").date(2026, 6, 29)
            return item

    assert pipeline.resolve_next_trade_date("2026-06-26", db=_Db()) == "2026-06-29"


def test_resolve_next_trade_date_falls_back_to_next_weekday(monkeypatch) -> None:
    class _Db:
        def get(self, model, current):
            return None

        def execute(self, stmt):
            class _Result:
                def scalar_one_or_none(self):
                    return None

            return _Result()

    assert pipeline.resolve_next_trade_date("2026-06-26", db=_Db()) == "2026-06-29"


def test_intraday_session_skips_outside_window(monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "is_a_share_intraday_window", lambda: False)

    result = pipeline.run_intraday_trade_session("2026-06-24", force=False)

    assert result.stage == "intraday"
    assert result.steps[0].status == "ok"
    assert result.steps[0].detail == "当前不在 A 股盘中时段，已跳过实时监控。"


def test_after_close_session_sends_candidates_before_heavy_regression(monkeypatch) -> None:
    captured = {}

    def fake_sync_daily(trade_date, *, full_refresh=False, force=False):
        captured["full_sync"] = (trade_date, full_refresh, force)
        return pipeline.PipelineStepResult(
            name="sync_daily_market_data",
            status="ok",
            detail="market-synced",
        )

    def fake_prepare_market_universe(trade_date, limit, sync_daily=False):
        captured["sync_daily"] = sync_daily
        return pipeline.PipelineStepResult(
            name="prepare_market_feature_universe",
            status="ok",
            detail=f"universe:{limit}",
        )

    def fake_paper_simulation(trade_date, account, *, execute_entries=True):
        captured["execute_entries"] = execute_entries
        return f"paper:{account}"

    monkeypatch.setattr(pipeline, "_run_daily_paper_simulation_step", fake_paper_simulation)
    monkeypatch.setattr(pipeline, "_sync_daily_market_data_step", fake_sync_daily)
    monkeypatch.setattr(
        pipeline,
        "_sync_sector_moneyflow_step",
        lambda trade_date, lookback_open_days=8: pipeline.PipelineStepResult(
            name="sync_sector_moneyflow",
            status="ok",
            detail=f"sector-flow:{trade_date}:{lookback_open_days}",
            summary="sector-flow",
        ),
    )
    monkeypatch.setattr(pipeline, "_generate_paper_reviews_step", lambda trade_date: "reviews")
    monkeypatch.setattr(pipeline, "_run_rule_regression_step", lambda trade_date, limit: "backtest")
    monkeypatch.setattr(
        pipeline,
        "_generate_backtest_learning_step",
        lambda trade_date: "backtest-learning",
    )
    monkeypatch.setattr(
        pipeline,
        "_prewarm_candidate_replay_effect_step",
        lambda trade_date: pipeline.PipelineStepResult(
            name="prewarm_candidate_replay_effect",
            status="ok",
            detail=f"prewarm:{trade_date}",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_record_tracking_snapshots_step",
        lambda trade_date, limit: pipeline.PipelineStepResult(
            name="record_tracking_snapshots",
            status="ok",
            detail=f"tracking:{trade_date}:{limit}",
        ),
    )
    monkeypatch.setattr(pipeline, "_generate_daily_review_step", lambda trade_date: "daily")
    monkeypatch.setattr(
        pipeline,
        "_prepare_market_feature_universe_step",
        fake_prepare_market_universe,
    )
    monkeypatch.setattr(
        pipeline,
        "_daily_candidate_data_gate_step",
        lambda trade_date: pipeline.PipelineStepResult(
            name="validate_daily_candidate_data",
            status="ok",
            detail="候选数据门禁通过",
        ),
        raising=False,
    )
    monkeypatch.setattr(
        pipeline,
        "_discover_next_session_candidates_step",
        lambda trade_date, next_trade_date, limit, use_learning_adjustments: (
            pipeline.PipelineStepResult(
                name="discover_next_session_candidates",
                status="ok",
                detail=f"candidates:{next_trade_date}:{use_learning_adjustments}",
            )
        ),
    )

    result = pipeline.run_after_close_session(
        "2026-06-24",
        "2026-06-25",
        account="default",
        use_learning_adjustments=False,
        full_market_sync=True,
    )

    assert result.stage == "after_close"
    assert [item.name for item in result.steps] == [
        "sync_daily_market_data",
        "sync_sector_moneyflow",
        "prepare_market_feature_universe",
        "validate_daily_candidate_data",
        "discover_next_session_candidates",
        "record_tracking_snapshots",
        "run_daily_paper_simulation",
        "generate_paper_trading_review",
        "run_rule_regression",
        "generate_backtest_learning_review",
        "prewarm_candidate_replay_effect",
        "generate_daily_review",
    ]
    assert result.steps[4].detail == "candidates:2026-06-25:False"
    assert result.steps[5].detail == "tracking:2026-06-24:200"
    assert captured["full_sync"] == ("2026-06-24", True, True)
    assert captured["sync_daily"] is False
    assert captured["execute_entries"] is True
    assert result.steps[7].detail == "reviews"
    assert result.steps[-1].detail == "daily"
    assert result.steps[-2].detail == "prewarm:2026-06-24"


def test_after_close_session_blocks_candidates_when_daily_data_gate_fails(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(
        pipeline,
        "_sync_daily_market_data_step",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("lightweight after-close session should not run full sync")
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_sync_sector_moneyflow_step",
        lambda trade_date, lookback_open_days=8: pipeline.PipelineStepResult(
            name="sync_sector_moneyflow",
            status="ok",
            detail="sector-flow",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_prepare_market_feature_universe_step",
        lambda trade_date, limit, sync_daily=False: pipeline.PipelineStepResult(
            name="prepare_market_feature_universe",
            status="ok",
            detail="universe",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_daily_candidate_data_gate_step",
        lambda trade_date: pipeline.PipelineStepResult(
            name="validate_daily_candidate_data",
            status="warning",
            detail="候选数据门禁未通过：日线覆盖不足",
            summary="数据完整性不足",
            details=["日线覆盖不足"],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        pipeline,
        "_discover_next_session_candidates_step",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("candidates should not run")),
    )
    monkeypatch.setattr(
        pipeline,
        "_record_tracking_snapshots_step",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("tracking should not run")),
    )

    def fake_paper_simulation(trade_date, account, *, execute_entries=True):
        captured["execute_entries"] = execute_entries
        return "paper"

    monkeypatch.setattr(pipeline, "_run_daily_paper_simulation_step", fake_paper_simulation)
    monkeypatch.setattr(pipeline, "_generate_paper_reviews_step", lambda trade_date: "reviews")
    monkeypatch.setattr(pipeline, "_run_rule_regression_step", lambda trade_date, limit: "backtest")
    monkeypatch.setattr(
        pipeline,
        "_generate_backtest_learning_step",
        lambda trade_date: "backtest-learning",
    )
    monkeypatch.setattr(
        pipeline,
        "_prewarm_candidate_replay_effect_step",
        lambda trade_date: "prewarm",
    )
    monkeypatch.setattr(pipeline, "_generate_daily_review_step", lambda trade_date: "daily")

    result = pipeline.run_after_close_session("2026-06-24", "2026-06-25")

    blocked = next(
        step for step in result.steps if step.name == "discover_next_session_candidates"
    )
    assert blocked.status == "warning"
    assert "数据完整性不足" in blocked.detail
    assert captured["execute_entries"] is False


def test_after_close_safe_recovery_skips_paper_and_regression_steps(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "_sync_daily_market_data_step",
        lambda *args, **kwargs: pipeline.PipelineStepResult(
            "sync_daily_market_data", "ok", "sync"
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_sync_sector_moneyflow_step",
        lambda *args, **kwargs: pipeline.PipelineStepResult(
            "sync_sector_moneyflow", "ok", "sector"
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_prepare_market_feature_universe_step",
        lambda *args, **kwargs: pipeline.PipelineStepResult(
            "prepare_market_feature_universe", "ok", "features"
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_daily_candidate_data_gate_step",
        lambda *args, **kwargs: pipeline.PipelineStepResult(
            "validate_daily_candidate_data", "warning", "blocked"
        ),
    )
    for name in (
        "_run_daily_paper_simulation_step",
        "_generate_paper_reviews_step",
        "_run_rule_regression_step",
        "_generate_backtest_learning_step",
        "_prewarm_candidate_replay_effect_step",
        "_generate_daily_review_step",
    ):
        monkeypatch.setattr(
            pipeline,
            name,
            lambda *args, _name=name, **kwargs: (_ for _ in ()).throw(AssertionError(_name)),
        )

    result = pipeline.run_after_close_session(
        "2026-07-13",
        "2026-07-14",
        full_market_sync=True,
        safe_recovery=True,
    )

    assert [step.name for step in result.steps] == [
        "sync_daily_market_data",
        "sync_sector_moneyflow",
        "prepare_market_feature_universe",
        "validate_daily_candidate_data",
        "discover_next_session_candidates",
    ]


def test_record_tracking_snapshots_keeps_symbols_before_session_closes(monkeypatch) -> None:
    class _Db:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.closed = True

        def commit(self):
            return None

    class _Item:
        def __init__(self, symbol: str):
            self.symbol = symbol

    class _Row:
        def __init__(self, db: _Db, symbol: str):
            self._db = db
            self._symbol = symbol

        @property
        def symbol(self) -> str:
            if self._db.closed:
                raise RuntimeError("detached row")
            return self._symbol

    monkeypatch.setattr(pipeline, "SessionLocal", _Db)
    monkeypatch.setattr(
        pipeline,
        "load_stock_workspace_items",
        lambda db, pool_name, limit, include_growth_board: [_Item("002550"), _Item("603087")],
    )
    monkeypatch.setattr(
        pipeline,
        "build_tracking_snapshot_payload",
        lambda item, snapshot_date: item,
    )
    monkeypatch.setattr(
        pipeline,
        "upsert_tracking_snapshot",
        lambda db, payload: _Row(db, payload.symbol),
    )

    result = pipeline._record_tracking_snapshots_step("2026-07-10", limit=20)

    assert result.status == "ok"
    assert result.details == ["002550", "603087"]


def test_sync_sector_moneyflow_step_summarizes_recent_backfill(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "sync_recent_tushare_sector_moneyflow",
        lambda trade_date, lookback_open_days=8: [
            CollectionResult(
                source="tushare_proxy",
                dataset="moneyflow_ind_dc",
                trade_date="2026-06-23",
                rows=88,
                status="ok",
            ),
            CollectionResult(
                source="tushare_proxy",
                dataset="moneyflow_ind_dc",
                trade_date="2026-06-24",
                rows=89,
                status="ok",
            ),
        ],
    )

    result = pipeline._sync_sector_moneyflow_step("2026-06-24")

    assert result.status == "ok"
    assert result.summary == "板块资金流补齐完成"
    assert "更新 2 个交易日" in result.detail


def test_generate_daily_review_task_uses_mechanical_review(monkeypatch) -> None:
    from datetime import datetime

    calls = []

    class _Review:
        title = "2026-06-24 每日机械复盘"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_after_close_session should not be called here")

    def fake_sync_moneyflow(trade_date):
        calls.append(("sync_moneyflow", trade_date))
        return pipeline.PipelineStepResult(
            name="sync_sector_moneyflow",
            status="ok",
            detail="sector-flow",
            summary="板块资金流已最新",
        )

    def fake_review(report_date):
        calls.append(("review", report_date))
        return _Review()

    monkeypatch.setattr(tasks, "_sync_sector_moneyflow_step", fake_sync_moneyflow)
    monkeypatch.setattr(tasks, "generate_daily_mechanical_review", fake_review)
    monkeypatch.setattr(tasks, "run_after_close_session", fail_if_called)
    monkeypatch.setattr(tasks, "now_local", lambda: datetime(2026, 6, 24, 18, 30))

    result = tasks.generate_daily_review_task()

    assert calls == [("sync_moneyflow", "2026-06-24"), ("review", "2026-06-24")]
    assert result["trade_date"] == "2026-06-24"
    assert result["status"] == "ok"
    assert result["message"] == "2026-06-24 每日机械复盘"
    assert result["moneyflow_status"] == "ok"


def test_discover_next_session_candidates_step_dispatches_screening_summary(monkeypatch) -> None:
    captured = {}

    def fake_discovery(db, **kwargs):
        captured["discovery_kwargs"] = kwargs
        return {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "universe_warning": "",
            "candidate_diagnostics": {
                "summary": "候选偏少：3只，先解释原因再考虑调参。",
                "reasons": ["市场状态把候选上限从15只收缩到3只。"],
            },
            "sector_focus": [
                {
                    "sector": "通信设备",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "candidates": [
                {
                    "symbol": "603083",
                    "name": "剑桥科技",
                    "sector": "通信设备",
                    "selection_mode": "formal_strategy",
                    "score": 82.5,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "reasons": ["板块20日主线扩散较好", "趋势强度领先"],
                    "risk_flags": [],
                }
            ],
            "written": 1,
            "retired": 0,
        }

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": 1}

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return [type("R", (), {"channel": "dingtalk", "status": "ok"})()]

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_load_candidate_gate_policies", lambda trade_date: {})
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )

    result = pipeline._discover_next_session_candidates_step(
        "2026-06-24",
        "2026-06-25",
        limit=10,
        use_learning_adjustments=False,
    )

    assert result.name == "discover_next_session_candidates"
    assert captured["discovery"]["candidates"][0]["symbol"] == "603083"
    assert captured["plan_args"]["symbols"] == ["603083"]
    assert result.details[0] == "钉钉提醒：dingtalk:ok"
    assert any("候选诊断：候选偏少" in item for item in result.details)


def test_discover_next_session_candidates_step_plans_action_candidates_only(monkeypatch) -> None:
    captured = {}

    def fake_discovery(db, **kwargs):
        return {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "candidates": [
                {
                    "symbol": "002156",
                    "name": "通富微电",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 84.9,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                },
                {
                    "symbol": "600900",
                    "name": "高位观察",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 92.0,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "selected_strategy_type": "swing",
                    "reasons": ["板块20日主线扩散较好"],
                    "risk_flags": ["距离MA20偏远17.00%"],
                },
            ],
            "written": 2,
            "retired": 0,
        }

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": len(kwargs["symbols"])}

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return [type("R", (), {"channel": "dingtalk", "status": "ok"})()]

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_load_candidate_gate_policies", lambda trade_date: {})
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )

    pipeline._discover_next_session_candidates_step(
        "2026-06-24",
        "2026-06-25",
        limit=10,
        use_learning_adjustments=False,
    )

    assert [item["symbol"] for item in captured["discovery"]["action_candidates"]] == ["002156"]
    assert captured["plan_args"]["symbols"] == ["002156"]


def test_discover_next_session_candidates_step_reports_empty_core_reason(monkeypatch) -> None:
    captured = {}

    def fake_discovery(db, **kwargs):
        return {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [],
            "candidates": [
                {
                    "symbol": "002669",
                    "name": "潜力票",
                    "sector": "化工原料",
                    "selection_mode": "potential_watch",
                    "selected_strategy_type": "watch_breakout",
                    "score": 66.9,
                    "reasons": ["潜力观察：个股启动但板块未确认，只观察不行动"],
                    "risk_flags": [],
                }
            ],
            "written": 1,
            "retired": 0,
        }

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": 0}

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_load_candidate_gate_policies", lambda trade_date: {})
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        lambda discovery: [],
    )

    result = pipeline._discover_next_session_candidates_step(
        "2026-06-24",
        "2026-06-25",
        limit=10,
        use_learning_adjustments=False,
    )

    assert any("没有核心行动：当前候选都是潜力观察" in item for item in result.details)
    assert captured["plan_args"]["symbols"] == []


def test_discover_next_session_candidates_step_plans_long_action_candidates_first(
    monkeypatch,
) -> None:
    captured = {}

    def fake_discovery(db, **kwargs):
        return {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "candidates": [
                {
                    "symbol": "002156",
                    "name": "普通行动",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 84.9,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "selected_strategy_type": "short_term",
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                },
                {
                    "symbol": "600002",
                    "name": "中期强者",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 82.0,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["中期强者：相对强度或板块扩散足够强"],
                    "risk_flags": [],
                },
            ],
            "written": 2,
            "retired": 0,
        }

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": len(kwargs["symbols"])}

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return [type("R", (), {"channel": "dingtalk", "status": "ok"})()]

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_load_candidate_gate_policies", lambda trade_date: {})
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )

    pipeline._discover_next_session_candidates_step(
        "2026-06-24",
        "2026-06-25",
        limit=10,
        use_learning_adjustments=False,
    )

    assert [item["symbol"] for item in captured["discovery"]["action_candidates"]] == [
        "002156",
        "600002",
    ]
    assert [item["symbol"] for item in captured["discovery"]["long_action_candidates"]] == [
        "600002"
    ]
    assert [item["symbol"] for item in captured["discovery"]["candidate_tiers"]["core_action"]] == [
        "600002"
    ]
    assert captured["plan_args"]["symbols"] == ["600002"]


def test_discover_next_session_candidates_step_does_not_plan_blocked_core(
    monkeypatch,
) -> None:
    captured = {}

    def fake_discovery(db, **kwargs):
        return {
            "feature_date": "2026-07-06",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [
                {
                    "sector": "保险",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "market_regime": "weak_trend",
            "market_regime_snapshot": {
                "breadth_score": 34.0,
                "emotion_gate": "risk_off",
            },
            "market_participation_snapshot": {
                "participation_score": 41.0,
                "liquidity_score": 31.0,
            },
            "candidates": [
                {
                    "symbol": "601336",
                    "name": "新华保险",
                    "sector": "保险",
                    "sector_style": "market_beta",
                    "suggested_horizon_days": 5,
                    "horizon_reason": "风格周期：market_beta偏5日观察，需结合指数和成交额",
                    "selection_mode": "formal_strategy",
                    "score": 86.8,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "swing",
                    "reasons": ["趋势强度领先", "相对强度领先市场"],
                    "risk_flags": [],
                    "day_change_pct": -0.0231,
                    "total_score": 86.8,
                    "selected_rule_score": 86.8,
                }
            ],
            "written": 1,
            "retired": 0,
        }

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": len(kwargs["symbols"])}

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return [type("R", (), {"channel": "dingtalk", "status": "ok"})()]

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_load_candidate_gate_policies", lambda trade_date: {})
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )

    result = pipeline._discover_next_session_candidates_step(
        "2026-07-06",
        "2026-07-07",
        limit=10,
        use_learning_adjustments=False,
    )

    assert captured["discovery"]["candidate_tiers"]["core_action"] == []
    assert [item["symbol"] for item in captured["discovery"]["candidate_tiers"]["watch_wait"]] == [
        "601336"
    ]
    assert captured["plan_args"]["symbols"] == []
    assert "生成 0 条交易计划" in result.summary
    assert any("大盘压力大" in item for item in result.details)


def test_discover_next_session_candidates_step_blocks_growth_core_on_market_stress(
    monkeypatch,
) -> None:
    captured = {}

    def fake_discovery(db, **kwargs):
        if kwargs.get("include_growth_board"):
            return {
                "feature_date": "2026-07-06",
                "universe_size": 100,
                "sector_focus": [],
                "candidates": [],
                "written": 0,
                "retired": 0,
            }
        return {
            "feature_date": "2026-07-06",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "market_regime": "weak_trend",
            "market_regime_snapshot": {
                "breadth_score": 34.0,
                "emotion_gate": "risk_off",
            },
            "market_participation_snapshot": {
                "participation_score": 41.0,
                "liquidity_score": 31.0,
            },
            "candidates": [
                {
                    "symbol": "603061",
                    "name": "金海通",
                    "sector": "半导体",
                    "sector_style": "growth_cycle",
                    "suggested_horizon_days": 10,
                    "horizon_reason": "风格周期：growth_cycle偏10日观察，科技成长先看承接延续",
                    "selection_mode": "formal_strategy",
                    "score": 88.0,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                    "day_change_pct": -0.012,
                }
            ],
            "written": 1,
            "retired": 0,
        }

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": len(kwargs["symbols"])}

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return []

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )

    result = pipeline._discover_next_session_candidates_step(
        "2026-07-06",
        "2026-07-07",
        limit=10,
        use_learning_adjustments=False,
    )

    assert captured["discovery"]["market_stress"]["stress_status"] == "risk_off"
    assert captured["discovery"]["candidate_tiers"]["core_action"] == []
    assert [item["symbol"] for item in captured["discovery"]["candidate_tiers"]["watch_wait"]] == [
        "603061"
    ]
    assert captured["plan_args"]["symbols"] == []
    assert "生成 0 条交易计划" in result.summary
    assert any("大盘压力大" in item for item in result.details)


def test_discover_next_session_candidates_step_uses_live_market_stress_for_today(
    monkeypatch,
) -> None:
    captured = {}

    def fake_discovery(db, **kwargs):
        if kwargs.get("include_growth_board"):
            return {
                "feature_date": "2026-07-07",
                "universe_size": 100,
                "sector_focus": [],
                "candidates": [],
                "written": 0,
                "retired": 0,
            }
        return {
            "feature_date": "2026-07-07",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [],
            "market_regime": "range",
            "market_regime_snapshot": {
                "breadth_score": 52.0,
                "emotion_gate": "neutral",
            },
            "market_participation_snapshot": {
                "participation_score": 55.0,
                "liquidity_score": 51.0,
            },
            "candidates": [
                {
                    "symbol": "603061",
                    "name": "金海通",
                    "sector": "半导体",
                    "sector_style": "growth_cycle",
                    "selection_mode": "formal_strategy",
                    "score": 88.0,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                    "day_change_pct": -0.012,
                },
                {
                    "symbol": "002558",
                    "name": "巨人网络",
                    "sector": "互联网",
                    "sector_style": "growth_cycle",
                    "selection_mode": "potential_watch",
                    "score": 82.0,
                    "selected_rule_id": "POT001",
                    "selected_rule_name": "潜力启动观察",
                    "selected_strategy_type": "watch_breakout",
                    "reasons": ["潜力观察：个股启动但板块未确认"],
                    "risk_flags": [],
                    "day_change_pct": 0.02,
                },
            ],
            "written": 2,
            "retired": 0,
        }

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": len(kwargs["symbols"])}

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return []

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )
    monkeypatch.setattr(
        pipeline,
        "_candidate_live_market_stress_for_trade_date",
        lambda trade_date, db=None: {
            "stress_status": "risk_off",
            "stress_label": "压力大",
            "stress_score": 86.0,
            "stress_reasons": ["上涨占比仅12%，市场宽度明显不足"],
            "risk_action_label": "停止扩散，只做观察和风控",
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_load_candidate_gate_policies",
        lambda trade_date: {
            "style_gate_policy": {
                "rows": [
                    {
                        "style": "growth_cycle",
                        "label": "科技成长",
                        "status": "upgrade_allowed",
                        "status_label": "允许潜力升级",
                        "summary": "科技成长近期回放占优，可放网页端重点观察。",
                    }
                ]
            }
        },
    )

    result = pipeline._discover_next_session_candidates_step(
        "2026-07-07",
        "2026-07-08",
        limit=10,
        use_learning_adjustments=False,
    )

    tiers = captured["discovery"]["candidate_tiers"]
    assert captured["discovery"]["market_stress"]["stress_status"] == "risk_off"
    assert tiers["core_action"] == []
    assert [item["symbol"] for item in tiers["sector_watch"]] == ["002558"]
    assert captured["plan_args"]["symbols"] == []
    assert result.summary is not None
    assert "压力大" in result.summary
    assert "生成 0 条交易计划" in result.summary


def test_load_candidate_gate_policies_adds_replay_phase_policy(monkeypatch) -> None:
    captured = {}

    def fake_compare(**kwargs):
        captured["compare"] = kwargs
        return {"scopes": {}}

    def fake_style_gate(comparison, **kwargs):
        return {
            "scope": kwargs["scope"],
            "horizon": kwargs["horizon"],
            "rows": [],
        }

    def fake_diagnosis(comparison, **kwargs):
        captured["diagnosis"] = kwargs
        return {
            "market_phase_policy": {
                "status": "risk_off",
                "max_core_positions": 1,
            },
            "dual_line_policy": {
                "active_line": "cash_defense",
                "max_core_positions": 0,
                "summary": "两条线都没有足够确认，优先防守和复盘。",
            },
            "strategy_pk": {
                "return_mode": "simple_sum_no_compounding",
                "rows": [],
            },
        }

    monkeypatch.setattr(
        "services.engine.backtest.walk_forward.compare_candidate_walk_forward_scopes",
        fake_compare,
    )
    monkeypatch.setattr(
        "apps.api.app.routers.rules.diagnose_style_gate_policy",
        fake_style_gate,
    )
    monkeypatch.setattr(
        "apps.api.app.routers.rules.diagnose_candidate_replay_effect",
        fake_diagnosis,
    )

    policies = pipeline._load_candidate_gate_policies("2026-07-08")

    assert captured["compare"]["scopes"] == (
        "all",
        "action",
        "action_long",
        "potential_watch",
        "startup_preheat",
        "sector_watch",
    )
    assert captured["compare"]["horizons"] == (5, 10, 20)
    assert captured["diagnosis"]["horizon"] == 20
    assert policies["style_gate_policy"]["scope"] == "potential_watch"
    assert policies["startup_preheat_policy"]["scope"] == "startup_preheat"
    assert policies["dual_line_policy"]["max_core_positions"] == 0
    assert policies["market_phase_policy"]["status"] == "risk_off"
    assert policies["strategy_pk"]["return_mode"] == "simple_sum_no_compounding"


def test_load_candidate_gate_policies_does_not_block_when_replay_data_is_insufficient(
    monkeypatch,
) -> None:
    def fake_compare(**kwargs):
        return {"scopes": {}}

    def fake_style_gate(comparison, **kwargs):
        return {
            "scope": kwargs["scope"],
            "horizon": kwargs["horizon"],
            "rows": [],
        }

    def fake_diagnosis(comparison, **kwargs):
        return {
            "market_phase_policy": {
                "status": "insufficient_data",
                "max_core_positions": 1,
            },
            "dual_line_policy": {
                "active_line": "cash_defense",
                "max_core_positions": 0,
                "summary": "两条线都没有足够确认，优先防守和复盘。",
            },
            "strategy_pk": {
                "return_mode": "simple_sum_no_compounding",
                "rows": [],
            },
        }

    monkeypatch.setattr(
        "services.engine.backtest.walk_forward.compare_candidate_walk_forward_scopes",
        fake_compare,
    )
    monkeypatch.setattr(
        "apps.api.app.routers.rules.diagnose_style_gate_policy",
        fake_style_gate,
    )
    monkeypatch.setattr(
        "apps.api.app.routers.rules.diagnose_candidate_replay_effect",
        fake_diagnosis,
    )

    policies = pipeline._load_candidate_gate_policies("2026-07-08")

    assert "dual_line_policy" not in policies
    assert "market_phase_policy" not in policies
    assert "strategy_pk" not in policies
    assert policies["style_gate_policy"]["rows"] == []


def test_candidate_live_market_stress_falls_back_to_sina_symbol_snapshot(
    monkeypatch,
) -> None:
    from datetime import date, datetime

    from apps.api.app.routers import market

    class FakeOverview:
        trade_date = date(2026, 7, 7)
        snapshot_scope_label = "盘中实时"
        stress_status = "risk_off"
        stress_label = "压力大"
        stress_score = 80.0
        stress_reasons = ["上涨占比仅12%，市场宽度明显不足"]
        risk_action_label = "停止扩散，只做观察和风控"

    fake_db = object()
    fake_overview = FakeOverview()
    fallback_calls = []
    cached_overviews = []

    monkeypatch.setattr(pipeline, "now_local", lambda: datetime(2026, 7, 7, 14, 30))
    monkeypatch.setattr(market, "_try_cached_live_a_share_overview", lambda timeout: None)
    monkeypatch.setattr(
        market,
        "_try_sina_symbol_live_a_share_overview",
        lambda db: fallback_calls.append(db) or fake_overview,
    )
    monkeypatch.setattr(
        market,
        "_store_live_market_cache",
        lambda overview: cached_overviews.append(overview),
    )

    stress = pipeline._candidate_live_market_stress_for_trade_date("2026-07-07", fake_db)

    assert fallback_calls == [fake_db]
    assert cached_overviews == [fake_overview]
    assert stress == {
        "trade_date": "2026-07-07",
        "snapshot_scope_label": "盘中实时",
        "stress_status": "risk_off",
        "stress_label": "压力大",
        "stress_score": 80.0,
        "stress_reasons": ["上涨占比仅12%，市场宽度明显不足"],
        "risk_action_label": "停止扩散，只做观察和风控",
    }


def test_apply_candidate_tier_tags_updates_research_pool_items() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add_all(
            [
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="603005",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "rank:1",
                            "candidate_summary:旧原因",
                            "candidate_pool:旧池",
                        ]
                    },
                    status="active",
                ),
                ResearchPoolItem(
                    pool_name="experiment_star",
                    symbol="688003",
                    tags_json={"tags": ["after_close_candidate", "rank:2"]},
                    status="active",
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="002558",
                    tags_json={"tags": ["after_close_candidate", "rank:3"]},
                    status="active",
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="600111",
                    tags_json={"tags": ["after_close_candidate", "rank:4"]},
                    status="active",
                ),
            ]
        )
        db.commit()

        pipeline._apply_candidate_tier_tags(
            db,
            pool_names=("experiment", "experiment_star"),
            candidate_tiers={
                "core_action": [
                    {
                        "symbol": "603005",
                        "tier_reason": "板块和个股趋势同时在线，盘中仍看承接。",
                    }
                ],
                "sector_watch": [
                    {
                        "symbol": "600111",
                        "selection_mode": "potential_watch",
                        "score": 81.0,
                        "tier_reason": (
                            "防守阶段板块观察：周期资源方向保留代表票，"
                            "交给人盘中判断，非买点。"
                        ),
                        "reasons": ["潜力观察：个股启动但板块未确认"],
                        "risk_flags": [],
                    }
                ],
                "watch_wait": [
                    {
                        "symbol": "688003",
                        "selection_mode": "potential_watch",
                        "score": 72.0,
                        "tier_reason": "趋势仍可跟踪，但还需要买点确认。",
                        "style_gate_status": "observe_only",
                        "style_gate_label": "只观察",
                        "style_gate_reason": "科技成长潜力观察近期有修复，只做网页端观察。",
                        "reasons": [
                            "潜力启动：20日涨幅仍低，今日向上启动，后续看承接确认",
                            "板块20日主线扩散较好",
                            "量能温和确认",
                        ],
                        "risk_flags": [],
                    },
                    {
                        "symbol": "002558",
                        "selection_mode": "potential_watch",
                        "score": 70.0,
                        "tier_reason": "启动前夜只观察次日承接。",
                        "style_gate_status": "upgrade_allowed",
                        "style_gate_label": "允许潜力升级",
                        "style_gate_reason": "科技成长启动前夜可盘中重点观察，不代表买点。",
                        "reasons": [
                            "启动前夜：T-1量价修复，20日涨幅仍不高，只观察次日承接",
                            "成交量开始确认：温和放量配合价格修复，但未进入核心行动",
                        ],
                        "risk_flags": [],
                    }
                ],
                "risk_reject": [],
                "summary": {
                    "core_block_reason": "没有核心行动：当前候选都是潜力观察，板块或买点还没确认。"
                },
            },
        )
        rows = {
            item.symbol: item
            for item in db.query(ResearchPoolItem).order_by(ResearchPoolItem.symbol).all()
        }

    assert "tier:core_action" in rows["603005"].tags_json["tags"]
    assert "tier:watch_wait" in rows["688003"].tags_json["tags"]
    assert any(
        tag.startswith("tier_reason:板块和个股趋势同时在线")
        for tag in rows["603005"].tags_json["tags"]
    )
    assert "candidate_summary:旧原因" not in rows["603005"].tags_json["tags"]
    assert "candidate_pool:旧池" not in rows["603005"].tags_json["tags"]
    assert (
        "candidate_summary:没有核心行动：当前候选都是潜力观察，板块或买点还没确认。"
        in rows["603005"].tags_json["tags"]
    )
    assert (
        "candidate_summary:没有核心行动：当前候选都是潜力观察，板块或买点还没确认。"
        in rows["688003"].tags_json["tags"]
    )
    assert "candidate_pool:expansion_confirm" in rows["688003"].tags_json["tags"]
    assert any(
        tag.startswith("candidate_pool_reason:扩散确认")
        for tag in rows["688003"].tags_json["tags"]
    )
    assert "style_gate:observe_only" in rows["688003"].tags_json["tags"]
    assert any(
        tag.startswith("style_gate_reason:科技成长潜力观察")
        for tag in rows["688003"].tags_json["tags"]
    )
    assert "candidate_pool:startup_preheat" in rows["002558"].tags_json["tags"]
    assert any(
        tag.startswith("candidate_pool_reason:启动前夜")
        for tag in rows["002558"].tags_json["tags"]
    )
    assert "style_gate:upgrade_allowed" in rows["002558"].tags_json["tags"]
    assert any(
        tag.startswith("style_gate_reason:科技成长启动前夜")
        for tag in rows["002558"].tags_json["tags"]
    )
    assert "tier:sector_watch" in rows["600111"].tags_json["tags"]
    assert any(
        tag.startswith("tier_reason:防守阶段板块观察")
        for tag in rows["600111"].tags_json["tags"]
    )


def test_discover_next_session_candidates_step_keeps_long_term_notifications(monkeypatch) -> None:
    captured = {}

    def fake_discovery(db, **kwargs):
        return {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [
                {
                    "sector": "通信设备",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "candidates": [
                {
                    "symbol": "603083",
                    "name": "长期回调票",
                    "sector": "通信设备",
                    "selection_mode": "formal_strategy",
                    "score": 86.4,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["先看板块主线", "板块20日主线扩散较好"],
                    "risk_flags": [],
                },
                {
                    "symbol": "000001",
                    "name": "历史噪音候选",
                    "sector": "银行",
                    "selection_mode": "formal_strategy",
                    "score": 82.5,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "selected_strategy_type": "short_term",
                    "reasons": ["趋势强度领先"],
                    "risk_flags": [],
                },
            ],
            "written": 2,
            "retired": 0,
        }

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": 1}

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return [type("R", (), {"channel": "dingtalk", "status": "ok"})()]

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_load_candidate_gate_policies", lambda trade_date: {})
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )

    result = pipeline._discover_next_session_candidates_step(
        "2026-06-24",
        "2026-06-25",
        limit=10,
        use_learning_adjustments=False,
    )

    assert captured["plan_args"]["symbols"] == ["603083"]
    assert result.details[0].startswith("钉钉提醒：")
    assert captured["discovery"]["candidates"][0]["symbol"] == "603083"


def test_discover_next_session_candidates_step_attaches_style_gate_policies(
    monkeypatch,
) -> None:
    captured = {}

    def fake_discovery(db, **kwargs):
        if kwargs.get("include_growth_board"):
            return {
                "feature_date": "2026-06-24",
                "universe_size": 100,
                "sector_focus": [],
                "candidates": [],
                "written": 0,
                "retired": 0,
            }
        return {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "sector_focus": [],
            "candidates": [
                {
                    "symbol": "002558",
                    "name": "启动前夜",
                    "sector": "互联网",
                    "sector_style": "growth_cycle",
                    "selection_mode": "potential_watch",
                    "selected_strategy_type": "watch_breakout",
                    "score": 70.0,
                    "day_change_pct": 0.012,
                    "selected_rule_id": "WATCH",
                    "selected_rule_name": "启动观察",
                    "reasons": [
                        "启动前夜：T-1量价修复，20日涨幅仍不高，只观察次日承接",
                        "成交量开始确认：温和放量配合价格修复，但未进入核心行动",
                    ],
                    "risk_flags": [],
                }
            ],
            "written": 1,
            "retired": 0,
        }

    def fake_gate_policies(trade_date):
        assert trade_date == "2026-06-24"
        return {
            "startup_preheat_policy": {
                "scope": "startup_preheat",
                "horizon": 5,
                "rows": [
                    {
                        "style": "growth_cycle",
                        "label": "科技成长",
                        "status": "upgrade_allowed",
                        "status_label": "允许潜力升级",
                        "summary": "科技成长启动前夜可盘中重点观察，不代表买点。",
                    }
                ],
            }
        }

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return []

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(pipeline, "_load_candidate_gate_policies", fake_gate_policies)
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )

    pipeline._discover_next_session_candidates_step(
        "2026-06-24",
        "2026-06-25",
        limit=10,
        use_learning_adjustments=False,
    )

    watch_wait = captured["discovery"]["candidate_tiers"]["watch_wait"]
    assert watch_wait[0]["symbol"] == "002558"
    assert watch_wait[0]["style_gate_status"] == "upgrade_allowed"
    assert "不代表买点" in watch_wait[0]["tier_reason"]


def test_discover_next_session_candidates_step_caps_limit_to_fifteen(monkeypatch) -> None:
    calls = []

    def fake_discovery(db, **kwargs):
        calls.append(kwargs)
        return {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [
                {
                    "sector": "通信设备",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "candidates": [
                {
                    "symbol": "603083",
                    "name": "剑桥科技",
                    "sector": "通信设备",
                    "selection_mode": "formal_strategy",
                    "score": 82.5,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "reasons": ["板块20日主线扩散较好", "趋势强度领先"],
                    "risk_flags": [],
                }
            ],
            "written": 1,
            "retired": 0,
        }

    def fake_generate_and_store_trade_plans(**kwargs):
        return {"written": 1}

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        lambda discovery: [],
    )

    result = pipeline._discover_next_session_candidates_step(
        "2026-06-24",
        "2026-06-25",
        limit=99,
        use_learning_adjustments=False,
    )

    assert calls[0]["limit"] == 15
    assert calls[1]["limit"] == 10
    assert result.summary is not None
    assert "有效上限 15" in result.summary


def test_discover_next_session_candidates_step_skips_dingtalk_when_feature_date_falls_back(
    monkeypatch,
) -> None:
    def fake_discovery(db, **kwargs):
        return {
            "feature_date": "2026-06-29",
            "requested_feature_date": "2026-06-30",
            "feature_coverage_ratio": 0.0004,
            "universe_size": 3510,
            "universe_warning": "",
            "sector_focus": [],
            "candidates": [
                {
                    "symbol": "600360",
                    "name": "华微电子",
                    "sector": "半导体",
                    "selection_mode": "observation",
                    "score": 77.06,
                    "day_change_pct": 0.0707,
                    "selected_rule_id": "OBS001",
                    "selected_rule_name": "观察候选",
                    "reasons": ["回退旧特征日"],
                    "risk_flags": [],
                }
            ],
            "written": 1,
            "retired": 0,
        }

    def fail_dispatch(discovery):
        raise AssertionError("stale feature-date candidates must not be pushed to DingTalk")

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_load_star_symbols", lambda db: [])
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fail_dispatch,
    )

    result = pipeline._discover_next_session_candidates_step(
        "2026-06-30",
        "2026-07-01",
        limit=99,
        use_learning_adjustments=False,
    )

    assert result.status == "warning"
    assert result.details[0] == (
        "数据未补齐：请求特征日 2026-06-30，实际使用 2026-06-29，"
        "覆盖率 0.0%。已跳过钉钉推送，避免重复发送旧盘面候选。"
    )


def test_discover_next_session_candidates_step_filters_star_candidates_with_star_focus(
    monkeypatch,
) -> None:
    captured = {}
    calls = []

    def _candidate(symbol: str, sector: str) -> dict:
        return {
            "symbol": symbol,
            "name": f"{symbol}候选",
            "sector": sector,
            "selection_mode": "formal_strategy",
            "score": 82.5,
            "selected_rule_id": "R004",
            "selected_rule_name": "板块中期趋势跟随",
            "selected_strategy_type": "long_term",
            "reasons": ["板块20日主线扩散较好", "趋势强度领先"],
            "risk_flags": [],
        }

    def fake_discovery(db, **kwargs):
        calls.append(kwargs)
        if kwargs.get("include_growth_board"):
            return {
                "feature_date": "2026-06-24",
                "universe_size": 20,
                "universe_warning": "",
                "sector_focus": [
                    {
                        "sector": "半导体",
                        "focus_score": 75,
                        "continuity_score": 72,
                        "avg_return_20d_pct": 10,
                        "positive_ratio": 0.66,
                    }
                ],
                "candidates": [
                    _candidate("688001", "半导体"),
                    _candidate("688002", "医药"),
                ],
                "written": 2,
                "retired": 0,
            }
        return {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [
                {
                    "sector": "通信设备",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "candidates": [
                _candidate("603083", "通信设备"),
                _candidate("688003", "半导体"),
            ],
            "written": 2,
            "retired": 0,
        }

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return [type("R", (), {"channel": "dingtalk", "status": "ok"})()]

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": len(kwargs["symbols"])}

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_load_star_symbols", lambda db: ["688001", "688002"])
    monkeypatch.setattr(pipeline, "_load_candidate_gate_policies", lambda trade_date: {})
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )

    result = pipeline._discover_next_session_candidates_step(
        "2026-06-24",
        "2026-06-25",
        limit=99,
        use_learning_adjustments=False,
    )

    assert calls[0]["limit"] == 15
    assert calls[1]["limit"] == 10
    assert calls[1]["include_growth_board"] is True
    assert [item["symbol"] for item in captured["discovery"]["candidates"]] == [
        "603083",
        "688001",
    ]
    assert captured["discovery"]["star_candidates"][0]["symbol"] == "688001"
    assert captured["plan_args"]["symbols"] == ["603083"]
    assert "写入 4 只股票" in result.summary
    assert result.details[0].startswith("钉钉提醒：")


def test_discover_next_session_candidates_step_scans_growth_board_without_star_focus(
    monkeypatch,
) -> None:
    captured = {}
    calls = []

    def _candidate(symbol: str, sector: str) -> dict:
        return {
            "symbol": symbol,
            "name": f"{symbol}候选",
            "sector": sector,
            "selection_mode": "formal_strategy",
            "score": 82.5,
            "selected_rule_id": "R004",
            "selected_rule_name": "板块中期趋势跟随",
            "selected_strategy_type": "long_term",
            "reasons": ["板块20日主线扩散较好", "趋势强度领先"],
            "risk_flags": [],
        }

    def fake_discovery(db, **kwargs):
        calls.append(kwargs)
        if kwargs.get("include_growth_board"):
            return {
                "feature_date": "2026-06-24",
                "universe_size": 300,
                "universe_warning": "",
                "sector_focus": [],
                "candidates": [
                    _candidate("688001", "半导体"),
                    _candidate("300001", "元器件"),
                ],
                "written": 2,
                "retired": 0,
            }
        return {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "universe_warning": "",
            "sector_focus": [],
            "candidates": [
                _candidate("603083", "通信设备"),
                _candidate("688003", "半导体"),
            ],
            "written": 2,
            "retired": 0,
        }

    def fake_dispatch(discovery):
        captured["discovery"] = discovery
        return [type("R", (), {"channel": "dingtalk", "status": "ok"})()]

    def fake_generate_and_store_trade_plans(**kwargs):
        captured["plan_args"] = kwargs
        return {"written": len(kwargs["symbols"])}

    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(pipeline, "_load_star_symbols", lambda db: [])
    monkeypatch.setattr(pipeline, "_load_candidate_gate_policies", lambda trade_date: {})
    monkeypatch.setattr(
        "services.engine.research_pool.candidates.discover_next_session_candidates",
        fake_discovery,
    )
    monkeypatch.setattr(
        "services.engine.plans.sync.generate_and_store_trade_plans",
        fake_generate_and_store_trade_plans,
    )
    monkeypatch.setattr(
        "services.notifications.dispatcher.dispatch_candidate_screening",
        fake_dispatch,
    )

    pipeline._discover_next_session_candidates_step(
        "2026-06-24",
        "2026-06-25",
        limit=99,
        use_learning_adjustments=False,
    )

    assert calls[1]["include_growth_board"] is True
    assert "symbols" not in calls[1]
    assert [item["symbol"] for item in captured["discovery"]["candidates"]] == [
        "603083",
        "688001",
    ]
    assert captured["discovery"]["star_candidates"][0]["symbol"] == "688001"
    assert captured["plan_args"]["symbols"] == ["603083"]


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def commit(self):
        return None
