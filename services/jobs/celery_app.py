from celery import Celery
from celery.schedules import crontab

from services.shared.config import get_settings

settings = get_settings()

celery_app = Celery(
    "stock_research_jobs",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.timezone = settings.timezone
celery_app.conf.beat_schedule = {
    "pre-market-check": {
        "task": "services.jobs.tasks.pre_market_check",
        "schedule": 60 * 60 * 24,
    },
    "sync-daily-market-data": {
        "task": "services.jobs.tasks.sync_daily_market_data_task",
        "schedule": 60 * 60 * 24,
    },
    "compute-daily-features": {
        "task": "services.jobs.tasks.compute_daily_features_task",
        "schedule": 60 * 60 * 24,
    },
    "generate-trade-plans": {
        "task": "services.jobs.tasks.generate_trade_plans_task",
        "schedule": 60 * 60 * 24,
    },
    "run-rule-regression": {
        "task": "services.jobs.tasks.run_rule_regression_task",
        "schedule": 60 * 60 * 24,
    },
    "generate-daily-review": {
        "task": "services.jobs.tasks.generate_daily_review_task",
        "schedule": 60 * 60 * 24,
    },
    "paper-intraday-screening": {
        "task": "services.jobs.tasks.monitor_paper_positions_realtime_task",
        "schedule": crontab(minute="0,5,10,15,20,25,30,40,45,55", hour="9-11,13-14"),
    },
    "paper-early-divergence-snapshot": {
        "task": "services.jobs.tasks.paper_early_divergence_snapshot_task",
        "schedule": crontab(minute=45, hour=9),
    },
    "paper-midday-snapshot": {
        "task": "services.jobs.tasks.paper_midday_snapshot_task",
        "schedule": crontab(minute=35, hour=11),
    },
    "paper-late-session-snapshot": {
        "task": "services.jobs.tasks.paper_late_session_snapshot_task",
        "schedule": crontab(minute=50, hour=14),
    },
    "paper-after-close-screening": {
        "task": "services.jobs.tasks.run_after_close_session_task",
        "schedule": crontab(minute=0, hour=18),
    },
}

celery_app.conf.imports = ("services.jobs.tasks",)

# Import task module so worker/beat register tasks immediately.
from services.jobs import tasks as _tasks  # noqa: F401,E402
