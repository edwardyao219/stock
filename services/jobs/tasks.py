from __future__ import annotations

from services.jobs.celery_app import celery_app
from services.jobs.pipeline import run_daily_research_pipeline
from services.shared.time import now_local


@celery_app.task(name="services.jobs.tasks.pre_market_check")
def pre_market_check() -> dict[str, str]:
    today = now_local().date().isoformat()
    return {
        "trade_date": today,
        "status": "pending",
        "message": "Pre-market check is not implemented yet.",
    }


@celery_app.task(name="services.jobs.tasks.sync_daily_market_data_task")
def sync_daily_market_data_task() -> dict[str, str]:
    today = now_local().date().isoformat()
    return {
        "trade_date": today,
        "status": "pending",
        "message": "Data sync connector is not implemented yet.",
    }


@celery_app.task(name="services.jobs.tasks.compute_daily_features_task")
def compute_daily_features_task() -> dict[str, str]:
    from services.engine.features.sync import compute_and_store_stock_features

    today = now_local().date().isoformat()
    result = compute_and_store_stock_features(limit=500)
    return {
        "trade_date": today,
        "status": "ok",
        "message": f"{result['rows']} feature rows written for {result['symbols']} symbols.",
    }


@celery_app.task(name="services.jobs.tasks.generate_trade_plans_task")
def generate_trade_plans_task() -> dict[str, str]:
    from services.engine.plans.sync import generate_and_store_trade_plans

    today = now_local().date().isoformat()
    result = generate_and_store_trade_plans(plan_date=today, trade_date=today, limit=500)
    return {
        "trade_date": today,
        "status": "ok",
        "message": f"{result['written']} plans written from {result['contexts']} feature contexts.",
    }


@celery_app.task(name="services.jobs.tasks.run_paper_simulation_task")
def run_paper_simulation_task() -> dict[str, str]:
    from services.engine.paper.simulator import run_daily_paper_simulation

    today = now_local().date().isoformat()
    result = run_daily_paper_simulation(trade_date=today)
    return {
        "trade_date": today,
        "status": "ok",
        "message": f"opened {result.opened}, closed {result.closed}, skipped {result.skipped}",
    }


@celery_app.task(name="services.jobs.tasks.monitor_paper_positions_realtime_task")
def monitor_paper_positions_realtime_task() -> dict[str, object]:
    from services.engine.paper.realtime import monitor_paper_positions_realtime

    result = monitor_paper_positions_realtime()
    return result.to_dict()


@celery_app.task(name="services.jobs.tasks.run_rule_regression_task")
def run_rule_regression_task() -> dict[str, str]:
    from datetime import date

    from services.engine.backtest.sync import run_rules_backtest

    today = now_local().date().isoformat()
    result = run_rules_backtest(
        end_date=date.fromisoformat(today),
        run_date=date.fromisoformat(today),
        persist=True,
        limit=500,
    )
    return {
        "trade_date": today,
        "status": "ok",
        "message": (
            f"{result['trade_count']} trades, "
            f"{result['written_performance']} performance rows written."
        ),
    }


@celery_app.task(name="services.jobs.tasks.generate_daily_review_task")
def generate_daily_review_task() -> dict[str, str]:
    today = now_local().date().isoformat()
    return {
        "trade_date": today,
        "status": "pending",
        "message": "Daily review is not implemented yet.",
    }


@celery_app.task(name="services.jobs.tasks.run_daily_research_pipeline_task")
def run_daily_research_pipeline_task(trade_date: str, next_trade_date: str) -> dict[str, object]:
    result = run_daily_research_pipeline(trade_date, next_trade_date)
    return {
        "trade_date": result.trade_date,
        "next_trade_date": result.next_trade_date,
        "steps": [step.__dict__ for step in result.steps],
    }
