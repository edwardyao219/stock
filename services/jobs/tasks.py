from __future__ import annotations

from services.jobs.celery_app import celery_app
from services.jobs.pipeline import run_daily_research_pipeline
from services.shared.time import now_local


@celery_app.task(name="services.jobs.tasks.pre_market_check")
def pre_market_check() -> dict[str, str]:
    today = now_local().date().isoformat()
    return {"trade_date": today, "status": "pending", "message": "Pre-market check is not implemented yet."}


@celery_app.task(name="services.jobs.tasks.sync_daily_market_data_task")
def sync_daily_market_data_task() -> dict[str, str]:
    today = now_local().date().isoformat()
    return {"trade_date": today, "status": "pending", "message": "Data sync connector is not implemented yet."}


@celery_app.task(name="services.jobs.tasks.compute_daily_features_task")
def compute_daily_features_task() -> dict[str, str]:
    today = now_local().date().isoformat()
    return {"trade_date": today, "status": "pending", "message": "Feature computation is not implemented yet."}


@celery_app.task(name="services.jobs.tasks.generate_trade_plans_task")
def generate_trade_plans_task() -> dict[str, str]:
    today = now_local().date().isoformat()
    return {"trade_date": today, "status": "pending", "message": "Trade plan generation is not implemented yet."}


@celery_app.task(name="services.jobs.tasks.run_rule_regression_task")
def run_rule_regression_task() -> dict[str, str]:
    today = now_local().date().isoformat()
    return {"trade_date": today, "status": "pending", "message": "Rule regression is not implemented yet."}


@celery_app.task(name="services.jobs.tasks.generate_daily_review_task")
def generate_daily_review_task() -> dict[str, str]:
    today = now_local().date().isoformat()
    return {"trade_date": today, "status": "pending", "message": "Daily review is not implemented yet."}


@celery_app.task(name="services.jobs.tasks.run_daily_research_pipeline_task")
def run_daily_research_pipeline_task(trade_date: str, next_trade_date: str) -> dict[str, object]:
    result = run_daily_research_pipeline(trade_date, next_trade_date)
    return {
        "trade_date": result.trade_date,
        "next_trade_date": result.next_trade_date,
        "steps": [step.__dict__ for step in result.steps],
    }
