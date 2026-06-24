from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.collector.daily import sync_daily_market_data
from services.engine.review.mechanical import generate_daily_mechanical_review
from services.shared.database import SessionLocal
from services.shared.models import TradingCalendar
from services.shared.time import now_local


@dataclass(frozen=True)
class PipelineStepResult:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DailyPipelineResult:
    trade_date: str
    next_trade_date: str
    stage: str = "daily"
    steps: list[PipelineStepResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "next_trade_date": self.next_trade_date,
            "stage": self.stage,
            "steps": [step.to_dict() for step in self.steps],
        }


def _run_step(name: str, fn: Callable[[], str]) -> PipelineStepResult:
    try:
        return PipelineStepResult(name=name, status="ok", detail=fn())
    except Exception as exc:
        return PipelineStepResult(
            name=name,
            status="failed",
            detail=f"{type(exc).__name__}: {exc}",
        )


def _is_open_trade_date(db: Session, trade_date: str) -> bool:
    row = db.execute(
        select(TradingCalendar).where(TradingCalendar.trade_date == date.fromisoformat(trade_date))
    ).scalar_one_or_none()
    return True if row is None else bool(row.is_open)


def is_a_share_intraday_window() -> bool:
    current = now_local().time()
    return time(9, 25) <= current <= time(11, 30) or time(13, 0) <= current <= time(15, 5)


def _sync_daily_market_data_step(trade_date: str) -> str:
    collection_results = sync_daily_market_data(trade_date)
    failed_collections = [item for item in collection_results if item.status == "failed"]
    if failed_collections:
        failed_names = ", ".join(item.dataset for item in failed_collections)
        raise RuntimeError(f"failed datasets: {failed_names}")
    return f"{len(collection_results)} datasets processed or queued"


def _compute_features_step(trade_date: str, limit: int) -> str:
    from services.engine.features.sync import (
        compute_and_store_sector_features,
        compute_and_store_stock_features,
    )

    pipeline_date = date.fromisoformat(trade_date)
    feature_result = compute_and_store_stock_features(
        start_date=pipeline_date,
        end_date=pipeline_date,
        limit=limit,
    )
    sector_feature_result = compute_and_store_sector_features(
        start_date=pipeline_date,
        end_date=pipeline_date,
    )
    return (
        f"{feature_result['rows']} stock feature rows for {feature_result['symbols']} symbols; "
        f"{sector_feature_result['rows']} sector rows for "
        f"{sector_feature_result['sectors']} sectors"
    )


def _generate_trade_plans_step(
    plan_date: str,
    trade_date: str,
    limit: int,
    use_learning_adjustments: bool,
) -> str:
    from services.engine.plans.sync import generate_and_store_trade_plans

    plan_result = generate_and_store_trade_plans(
        plan_date=plan_date,
        trade_date=trade_date,
        limit=limit,
        use_learning_adjustments=use_learning_adjustments,
    )
    return f"{plan_result['written']} plans written from {plan_result['contexts']} contexts"


def _run_daily_paper_simulation_step(trade_date: str, account: str) -> str:
    from services.engine.paper.simulator import run_daily_paper_simulation

    paper_result = run_daily_paper_simulation(trade_date=trade_date, account_name=account)
    return (
        f"opened {paper_result.opened}, closed {paper_result.closed}, "
        f"skipped {paper_result.skipped}"
    )


def _run_realtime_monitor_step(
    trade_date: str,
    account: str,
    execute_exits: bool,
    force: bool,
) -> str:
    if not force and not is_a_share_intraday_window():
        return "skipped: outside A-share intraday window"

    from services.engine.paper.realtime import monitor_paper_positions_realtime

    result = monitor_paper_positions_realtime(
        trade_date=trade_date,
        account_name=account,
        execute_exits=execute_exits,
    )
    return (
        f"{result.quotes} quotes, {len(result.alerts)} alerts, "
        f"{result.executed_exits} executed exits"
    )


def _generate_paper_reviews_step(trade_date: str) -> str:
    from services.engine.paper.diagnostics import generate_paper_trading_review
    from services.engine.paper.learning import generate_paper_learning_report
    from services.engine.paper.review import generate_paper_trade_reviews

    review_samples = generate_paper_trade_reviews(trade_date)
    changed = generate_paper_trading_review(trade_date)
    learning_changed = generate_paper_learning_report(trade_date)
    return (
        f"{review_samples} trade review samples, "
        f"{changed} paper-trading suggestions, "
        f"{learning_changed} learning suggestions written"
    )


def _run_rule_regression_step(trade_date: str, limit: int) -> str:
    from services.engine.backtest.sync import run_rules_backtest

    backtest_result = run_rules_backtest(
        end_date=date.fromisoformat(trade_date),
        run_date=date.fromisoformat(trade_date),
        persist=True,
        limit=limit,
    )
    return (
        f"{backtest_result['trade_count']} trades, "
        f"{backtest_result['written_performance']} performance rows"
    )


def _generate_daily_review_step(trade_date: str) -> str:
    review = generate_daily_mechanical_review(trade_date)
    return review.title


def prepare_next_trade_session(
    trade_date: str,
    next_trade_date: str,
    *,
    limit: int = 200,
    use_learning_adjustments: bool = True,
    force: bool = False,
) -> DailyPipelineResult:
    with SessionLocal() as db:
        if not force and not _is_open_trade_date(db, trade_date):
            return DailyPipelineResult(
                trade_date=trade_date,
                next_trade_date=next_trade_date,
                stage="prepare_next_session",
                steps=[
                    PipelineStepResult(
                        name="trading_calendar_guard",
                        status="skipped",
                        detail=f"{trade_date} is not an open trading day",
                    )
                ],
            )

    steps = [
        _run_step("sync_daily_market_data", lambda: _sync_daily_market_data_step(trade_date)),
        _run_step("compute_features", lambda: _compute_features_step(trade_date, limit)),
        _run_step(
            "generate_trade_plans",
            lambda: _generate_trade_plans_step(
                trade_date,
                next_trade_date,
                limit,
                use_learning_adjustments,
            ),
        ),
    ]
    return DailyPipelineResult(
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        stage="prepare_next_session",
        steps=steps,
    )


def run_intraday_trade_session(
    trade_date: str,
    *,
    account: str = "default",
    execute_exits: bool = True,
    force: bool = False,
) -> DailyPipelineResult:
    steps = [
        _run_step(
            "monitor_paper_positions_realtime",
            lambda: _run_realtime_monitor_step(trade_date, account, execute_exits, force),
        )
    ]
    return DailyPipelineResult(
        trade_date=trade_date,
        next_trade_date=trade_date,
        stage="intraday",
        steps=steps,
    )


def run_after_close_session(
    trade_date: str,
    next_trade_date: str,
    *,
    limit: int = 200,
    account: str = "default",
) -> DailyPipelineResult:
    steps = [
        _run_step(
            "run_daily_paper_simulation",
            lambda: _run_daily_paper_simulation_step(trade_date, account),
        ),
        _run_step(
            "generate_paper_trading_review",
            lambda: _generate_paper_reviews_step(trade_date),
        ),
        _run_step("run_rule_regression", lambda: _run_rule_regression_step(trade_date, limit)),
        _run_step("generate_daily_review", lambda: _generate_daily_review_step(trade_date)),
    ]
    return DailyPipelineResult(
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        stage="after_close",
        steps=steps,
    )


def run_daily_research_pipeline(trade_date: str, next_trade_date: str) -> DailyPipelineResult:
    prepare_result = prepare_next_trade_session(trade_date, next_trade_date)
    after_close_result = run_after_close_session(trade_date, next_trade_date)
    return DailyPipelineResult(
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        stage="daily",
        steps=[*prepare_result.steps, *after_close_result.steps],
    )
