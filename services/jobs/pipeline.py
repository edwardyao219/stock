from __future__ import annotations

from dataclasses import dataclass, field

from services.collector.daily import sync_daily_market_data
from services.engine.review.mechanical import generate_daily_mechanical_review


@dataclass(frozen=True)
class PipelineStepResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DailyPipelineResult:
    trade_date: str
    next_trade_date: str
    steps: list[PipelineStepResult] = field(default_factory=list)


def run_daily_research_pipeline(trade_date: str, next_trade_date: str) -> DailyPipelineResult:
    steps: list[PipelineStepResult] = []

    try:
        collection_results = sync_daily_market_data(trade_date)
        failed_collections = [item for item in collection_results if item.status not in {"ok", "pending"}]
        status = "failed" if failed_collections else "pending"
        steps.append(
            PipelineStepResult(
                name="sync_daily_market_data",
                status=status,
                detail=f"{len(collection_results)} datasets processed or queued",
            )
        )
    except Exception as exc:
        steps.append(
            PipelineStepResult(
                name="sync_daily_market_data",
                status="failed",
                detail=f"{type(exc).__name__}: {exc}",
            )
        )

    try:
        from services.engine.features.sync import compute_and_store_stock_features

        feature_result = compute_and_store_stock_features(limit=200)
        steps.append(
            PipelineStepResult(
                name="compute_daily_features",
                status="ok",
                detail=f"{feature_result['rows']} feature rows written for {feature_result['symbols']} symbols",
            )
        )
    except Exception as exc:
        steps.append(
            PipelineStepResult(
                name="compute_daily_features",
                status="failed",
                detail=f"{type(exc).__name__}: {exc}",
            )
        )

    try:
        from services.engine.plans.sync import generate_and_store_trade_plans

        plan_result = generate_and_store_trade_plans(
            plan_date=trade_date,
            trade_date=next_trade_date,
            limit=200,
        )
        steps.append(
            PipelineStepResult(
                name="generate_trade_plans",
                status="ok",
                detail=(
                    f"{plan_result['written']} plans written from "
                    f"{plan_result['contexts']} feature contexts"
                ),
            )
        )
    except Exception as exc:
        steps.append(
            PipelineStepResult(
                name="generate_trade_plans",
                status="failed",
                detail=f"{type(exc).__name__}: {exc}",
            )
        )

    steps.append(
        PipelineStepResult(
            name="run_rule_regression",
            status="pending",
            detail="Backtest engine is not implemented yet.",
        )
    )

    review = generate_daily_mechanical_review(trade_date)
    steps.append(
        PipelineStepResult(
            name="generate_daily_review",
            status="ok",
            detail=review.title,
        )
    )

    return DailyPipelineResult(trade_date=trade_date, next_trade_date=next_trade_date, steps=steps)
