from __future__ import annotations

from datetime import date, datetime

from services.collector.realtime import sync_realtime_quotes
from services.engine.intraday.candidates import early_sector_scan_symbols
from services.engine.review.mechanical import generate_daily_mechanical_review
from services.engine.review.monthly_summary import generate_monthly_trade_summary
from services.jobs.celery_app import celery_app
from services.jobs.pipeline import (
    _sync_sector_moneyflow_step,
    prepare_next_trade_session,
    resolve_next_trade_date,
    run_after_close_session,
    run_daily_research_pipeline,
    run_intraday_trade_session,
)
from services.notifications.dispatcher import dispatch_monthly_trade_summary
from services.shared.database import SessionLocal
from services.shared.time import now_local


@celery_app.task(name="services.jobs.tasks.pre_market_check")
def pre_market_check() -> dict[str, str]:
    today = now_local().date().isoformat()
    result = prepare_next_trade_session(today, resolve_next_trade_date(today))
    return result.to_dict()


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
    current_time = now_local()
    today = current_time.date().isoformat()
    return run_intraday_trade_session(today, as_of=current_time).to_dict()


def _refresh_early_sector_quotes(trade_date: date, quote_time: datetime) -> dict[str, object]:
    symbols: list[str] = []
    rows = 0
    warning = ""
    try:
        with SessionLocal() as db:
            symbols = early_sector_scan_symbols(db, trade_date=trade_date)
        if symbols:
            rows = len(sync_realtime_quotes(symbols=symbols, quote_time=quote_time))
    except Exception as exc:
        warning = f"早盘热门板块行情刷新失败：{type(exc).__name__}: {exc}"

    result: dict[str, object] = {
        "early_sector_quote_symbol_count": len(symbols),
        "early_sector_quote_rows": rows,
    }
    if warning:
        result["early_sector_quote_warning"] = warning
    return result


@celery_app.task(name="services.jobs.tasks.paper_early_divergence_snapshot_task")
def paper_early_divergence_snapshot_task() -> dict[str, object]:
    current_time = now_local()
    trade_date = current_time.date()
    today = trade_date.isoformat()
    refresh = _refresh_early_sector_quotes(trade_date, current_time)
    result = run_intraday_trade_session(
        today,
        stage="early_divergence_snapshot",
        as_of=current_time,
        force=True,
    ).to_dict()
    result.update(refresh)
    return result


@celery_app.task(name="services.jobs.tasks.paper_midday_snapshot_task")
def paper_midday_snapshot_task() -> dict[str, object]:
    current_time = now_local()
    today = current_time.date().isoformat()
    return run_intraday_trade_session(
        today,
        stage="midday_snapshot",
        as_of=current_time,
        force=True,
    ).to_dict()


@celery_app.task(name="services.jobs.tasks.paper_late_session_snapshot_task")
def paper_late_session_snapshot_task() -> dict[str, object]:
    current_time = now_local()
    today = current_time.date().isoformat()
    return run_intraday_trade_session(
        today,
        stage="late_session_snapshot",
        as_of=current_time,
        force=True,
    ).to_dict()


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
    moneyflow_step = _sync_sector_moneyflow_step(today)
    review = generate_daily_mechanical_review(today)
    return {
        "trade_date": today,
        "status": "warning" if moneyflow_step.status == "failed" else "ok",
        "message": review.title,
        "moneyflow_status": moneyflow_step.status,
        "moneyflow_message": moneyflow_step.summary or moneyflow_step.detail,
    }


@celery_app.task(name="services.jobs.tasks.send_monthly_trade_summary_task")
def send_monthly_trade_summary_task(month: str = "2026-06") -> dict[str, str]:
    summary = generate_monthly_trade_summary(month)
    results = dispatch_monthly_trade_summary(summary.content_md)
    status = "ok" if results else "skipped"
    return {
        "month": month,
        "status": status,
        "message": f"{month} 交易总结",
    }


@celery_app.task(name="services.jobs.tasks.run_after_close_session_task")
def run_after_close_session_task() -> dict[str, object]:
    today = now_local().date()
    next_trade_date = resolve_next_trade_date(today.isoformat())
    return run_after_close_session(
        today.isoformat(),
        next_trade_date,
        full_market_sync=True,
    ).to_dict()


@celery_app.task(name="services.jobs.tasks.run_daily_research_pipeline_task")
def run_daily_research_pipeline_task(trade_date: str, next_trade_date: str) -> dict[str, object]:
    result = run_daily_research_pipeline(trade_date, next_trade_date)
    return result.to_dict()
