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
    summary: str | None = None
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
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


def _run_step(name: str, fn: Callable[[], str | PipelineStepResult]) -> PipelineStepResult:
    try:
        result = fn()
        if isinstance(result, PipelineStepResult):
            return result
        return PipelineStepResult(name=name, status="ok", detail=result, summary=result)
    except Exception as exc:
        return PipelineStepResult(
            name=name,
            status="failed",
            detail="任务执行失败，请点开详情查看原因。",
            summary="任务执行失败",
            details=[f"{type(exc).__name__}: {exc}"],
        )


def _is_open_trade_date(db: Session, trade_date: str) -> bool:
    row = db.execute(
        select(TradingCalendar).where(TradingCalendar.trade_date == date.fromisoformat(trade_date))
    ).scalar_one_or_none()
    return True if row is None else bool(row.is_open)


def is_a_share_intraday_window() -> bool:
    current = now_local().time()
    return time(9, 25) <= current <= time(11, 30) or time(13, 0) <= current <= time(15, 5)


def _sync_daily_market_data_step(
    trade_date: str,
    *,
    full_refresh: bool = False,
) -> PipelineStepResult:
    collection_results = sync_daily_market_data(trade_date, full_refresh=full_refresh)
    failed_collections = [item for item in collection_results if item.status == "failed"]
    pending_collections = [item for item in collection_results if item.status == "pending"]
    ok_collections = [item for item in collection_results if item.status == "ok"]
    skipped_collections = [item for item in collection_results if item.status == "skipped"]
    details = [
        f"{item.dataset}: {item.status}, rows={item.rows}"
        + (f", {item.message}" if item.message else "")
        for item in collection_results
    ]
    if failed_collections:
        return PipelineStepResult(
            name="sync_daily_market_data",
            status="failed",
            detail=(
                f"同步行情部分失败：{len(failed_collections)} 个数据源失败，"
                f"{len(ok_collections)} 个成功，{len(pending_collections)} 个待处理。"
            ),
            summary="同步行情失败",
            details=details,
        )
    if skipped_collections:
        return PipelineStepResult(
            name="sync_daily_market_data",
            status="skipped",
            detail="轻量试运行：已跳过全市场行情同步，直接使用本地已有数据。",
            summary="已跳过全量同步",
            details=details,
        )
    if pending_collections:
        return PipelineStepResult(
            name="sync_daily_market_data",
            status="warning",
            detail=(
                f"同步行情部分完成：{len(ok_collections)} 个成功，"
                f"{len(pending_collections)} 个待处理。"
            ),
            summary="同步行情部分完成",
            details=details,
        )
    return PipelineStepResult(
        name="sync_daily_market_data",
        status="ok",
        detail=f"同步行情完成：{len(collection_results)} 个数据集已处理。",
        summary="同步行情完成",
        details=details,
    )


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
        f"计算完成：{feature_result['symbols']} 只股票、"
        f"{feature_result['rows']} 条股票特征；"
        f"{sector_feature_result['sectors']} 个板块、"
        f"{sector_feature_result['rows']} 条板块特征。"
    )


def _sync_fundamentals_step(pool_name: str) -> PipelineStepResult:
    from services.engine.fundamental.sync import sync_fundamentals_from_akshare

    result = sync_fundamentals_from_akshare(pool_name=pool_name, include_valuation=True)
    details = [
        (
            f"{item['symbol']}: {item['status']}, "
            f"financial={item['financial_snapshots']}, valuation={item['valuation_snapshots']}"
            + (f", {item['message']}" if item.get("message") else "")
        )
        for item in result["results"]
    ]
    status = "warning" if result["failed"] else "ok"
    summary = f"财务同步完成：成功 {result['ok']}，失败 {result['failed']}。"
    return PipelineStepResult(
        name="sync_fundamentals",
        status=status,
        detail=summary,
        summary=summary,
        details=details,
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
    return (
        f"生成完成：从 {plan_result['contexts']} 个特征上下文"
        f"写入 {plan_result['written']} 条计划。"
    )


def _run_daily_paper_simulation_step(trade_date: str, account: str) -> str:
    from services.engine.paper.simulator import run_daily_paper_simulation

    paper_result = run_daily_paper_simulation(trade_date=trade_date, account_name=account)
    return (
        f"模拟完成：买入 {paper_result.opened} 笔，卖出 {paper_result.closed} 笔，"
        f"跳过 {paper_result.skipped} 笔。"
    )


def _run_realtime_monitor_step(
    trade_date: str,
    account: str,
    execute_entries: bool,
    execute_exits: bool,
    force: bool,
) -> str:
    if not force and not is_a_share_intraday_window():
        return "当前不在 A 股盘中时段，已跳过实时监控。"

    from services.engine.paper.realtime import monitor_paper_positions_realtime

    result = monitor_paper_positions_realtime(
        trade_date=trade_date,
        account_name=account,
        execute_entries=execute_entries,
        execute_exits=execute_exits,
    )
    return (
        f"实时监控完成：获取 {result.quotes} 条快照，"
        f"纸面买入 {result.executed_entries} 笔，"
        f"产生 {len(result.alerts)} 条预警，执行 {result.executed_exits} 次卖出。"
    )


def _generate_paper_reviews_step(trade_date: str) -> str:
    from services.engine.paper.diagnostics import generate_paper_trading_review
    from services.engine.paper.learning import generate_paper_learning_report
    from services.engine.paper.review import generate_paper_trade_reviews

    review_samples = generate_paper_trade_reviews(trade_date)
    changed = generate_paper_trading_review(trade_date)
    learning_changed = generate_paper_learning_report(trade_date)
    return (
        f"复盘完成：生成 {review_samples} 条交易样本、"
        f"{changed} 条纸面交易建议、{learning_changed} 条学习建议。"
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
        f"回归完成：{backtest_result['trade_count']} 笔交易样本，"
        f"{backtest_result['written_performance']} 条表现记录。"
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
    full_market_sync: bool = False,
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
                        detail=f"{trade_date} 不是交易日，已跳过准备流程。",
                        summary="非交易日跳过",
                    )
                ],
            )

    steps = [
        _run_step(
            "sync_daily_market_data",
            lambda: _sync_daily_market_data_step(
                trade_date,
                full_refresh=full_market_sync,
            ),
        ),
        _run_step("sync_fundamentals", lambda: _sync_fundamentals_step("experiment")),
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
    execute_entries: bool = True,
    execute_exits: bool = True,
    force: bool = False,
) -> DailyPipelineResult:
    steps = [
        _run_step(
            "monitor_paper_positions_realtime",
            lambda: _run_realtime_monitor_step(
                trade_date,
                account,
                execute_entries,
                execute_exits,
                force,
            ),
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
    prepare_result = prepare_next_trade_session(
        trade_date,
        next_trade_date,
        full_market_sync=True,
    )
    after_close_result = run_after_close_session(trade_date, next_trade_date)
    return DailyPipelineResult(
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        stage="daily",
        steps=[*prepare_result.steps, *after_close_result.steps],
    )
