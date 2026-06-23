from celery import Celery

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
}
