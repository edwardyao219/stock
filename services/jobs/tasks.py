from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import select

from services.collector.external_market import sync_korea_semiconductor_signal
from services.collector.realtime import sync_realtime_quotes
from services.engine.features.health import (
    DAILY_CANDIDATE_MIN_COVERAGE_RATIO,
    inspect_tushare_evidence_health,
)
from services.engine.features.intraday_market_turn_snapshot import (
    build_intraday_market_turn_snapshot,
)
from services.engine.intraday.candidates import early_sector_scan_symbols
from services.engine.review.mechanical import generate_daily_mechanical_review
from services.engine.review.monthly_summary import generate_monthly_trade_summary
from services.engine.tracking.mainline import build_confirmed_mainline_candidate_bindings
from services.jobs.celery_app import celery_app
from services.jobs.pipeline import (
    _is_open_trade_date,
    _sync_daily_market_data_step,
    _sync_sector_moneyflow_step,
    prepare_next_trade_session,
    resolve_next_trade_date,
    run_after_close_session,
    run_daily_research_pipeline,
    run_intraday_trade_session,
)
from services.jobs.status import read_after_close_status, write_after_close_status
from services.notifications.dispatcher import dispatch_monthly_trade_summary, dispatch_text
from services.shared.database import SessionLocal
from services.shared.models import IntradayMarketTurnSnapshot, Security
from services.shared.time import now_local

_DAILY_TASK_LOCK_TTL_SECONDS = 6 * 60 * 60
_AFTER_CLOSE_RECOVERY_LOCK_TTL_SECONDS = 30 * 60
_AFTER_CLOSE_RECOVERY_MAX_ATTEMPTS = 2


def _is_after_close_push_window(value: datetime) -> bool:
    return value.hour > 17 or (value.hour == 17 and value.minute >= 55)


def _acquire_daily_task_lock(task_name: str, trade_date: date) -> tuple[bool, str]:
    key = f"stock:daily-task:{task_name}:{trade_date.isoformat()}"
    try:
        acquired = celery_app.backend.client.set(
            key,
            "1",
            ex=_DAILY_TASK_LOCK_TTL_SECONDS,
            nx=True,
        )
    except Exception:
        return True, key
    return bool(acquired), key


def _release_daily_task_lock(key: str) -> None:
    try:
        celery_app.backend.client.delete(key)
    except Exception:
        return


def _acquire_after_close_recovery_lock(trade_date: str) -> tuple[str | None, str]:
    key = f"stock:after-close-recovery:{trade_date}"
    token = uuid4().hex
    try:
        acquired = celery_app.backend.client.set(
            key,
            token,
            ex=_AFTER_CLOSE_RECOVERY_LOCK_TTL_SECONDS,
            nx=True,
        )
    except Exception:
        return token, key
    return (token if acquired else None), key


def _release_after_close_recovery_lock(key: str, token: str) -> None:
    try:
        celery_app.backend.client.eval(
            """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
            """,
            1,
            key,
            token,
        )
    except Exception:
        return


def _claim_after_close_recovery_slot(trade_date: str) -> tuple[bool, str]:
    return _acquire_daily_task_lock("after-close", date.fromisoformat(trade_date))


def _is_after_close_task_active() -> bool:
    try:
        active = celery_app.control.inspect(timeout=1.0).active()
    except Exception:
        return True
    if active is None:
        return True
    return any(
        task.get("name") == "services.jobs.tasks.run_after_close_session_task"
        for worker_tasks in active.values()
        for task in worker_tasks or []
        if isinstance(task, dict)
    )


def _dispatch_after_close_failure_alert(trade_date: str, stage: str, error: str) -> None:
    acquired, _ = _acquire_daily_task_lock(
        f"after-close-failure-alert:{stage}",
        date.fromisoformat(trade_date),
    )
    if acquired:
        title = "盘后恢复失败" if stage == "safe-recovery" else "盘后任务失败"
        dispatch_text(f"【{title}】{trade_date}：{error}")


@celery_app.task(name="services.jobs.tasks.pre_market_check")
def pre_market_check() -> dict[str, str]:
    today = now_local().date().isoformat()
    result = prepare_next_trade_session(today, resolve_next_trade_date(today))
    return result.to_dict()


@celery_app.task(name="services.jobs.tasks.capture_korea_semiconductor_signal_task")
def capture_korea_semiconductor_signal_task() -> dict[str, object]:
    with SessionLocal() as db:
        signal = sync_korea_semiconductor_signal(db)
        db.commit()
        signal_id = signal.id if signal is not None else None
        observed_at = signal.observed_at.isoformat() if signal is not None else None
    if signal is None:
        return {
            "status": "skipped",
            "message": "韩国半导体信号未达到观察阈值。",
        }
    return {
        "status": "ok",
        "message": "韩国半导体观察信号已记录，等待A股盘中确认。",
        "signal_id": signal_id,
        "observed_at": observed_at,
    }


@celery_app.task(name="services.jobs.tasks.sync_daily_market_data_task")
def sync_daily_market_data_task() -> dict[str, str]:
    today = now_local().date()
    trade_date = today.isoformat()
    with SessionLocal() as db:
        if not _is_open_trade_date(db, trade_date):
            return {
                "trade_date": trade_date,
                "status": "skipped",
                "message": "非交易日，已跳过全市场收盘同步。",
            }

    acquired, lock_key = _acquire_daily_task_lock("daily-market-sync", today)
    if not acquired:
        return {
            "trade_date": trade_date,
            "status": "skipped",
            "message": "当日全市场收盘同步已运行或正在运行。",
            "lock_key": lock_key,
        }

    step = _sync_daily_market_data_step(
        trade_date,
        full_refresh=True,
        force=True,
    )
    return {"trade_date": trade_date, **step.to_dict()}


@celery_app.task(name="services.jobs.tasks.capture_full_market_snapshot_task")
def capture_full_market_snapshot_task() -> dict[str, object]:
    current_time = now_local()
    today = current_time.date()
    trade_date = today.isoformat()
    with SessionLocal() as db:
        if not _is_open_trade_date(db, trade_date):
            return {
                "trade_date": trade_date,
                "status": "skipped",
                "message": "非交易日，已跳过全市场收盘快照。",
            }
        active_symbols = {
            item.symbol
            for item in db.query(Security).filter_by(is_active=True, is_st=False).all()
        }
        active_security_count = len(active_symbols)

    acquired, lock_key = _acquire_daily_task_lock("full-market-snapshot", today)
    if not acquired:
        return {
            "trade_date": trade_date,
            "status": "skipped",
            "message": "当日全市场收盘快照已采集或正在采集。",
            "lock_key": lock_key,
        }

    try:
        quotes = sync_realtime_quotes(symbols=active_symbols, quote_time=current_time)
    except Exception as exc:
        _release_daily_task_lock(lock_key)
        return {
            "trade_date": trade_date,
            "status": "failed",
            "message": f"全市场收盘快照采集失败：{type(exc).__name__}: {exc}",
        }
    valid_quote_count = sum(
        1
        for quote in quotes
        if quote.symbol in active_symbols
        and quote.price is not None
        and quote.pre_close is not None
        and quote.pre_close > 0
    )
    coverage_ratio = valid_quote_count / active_security_count if active_security_count else 0.0
    status = "ok" if coverage_ratio >= DAILY_CANDIDATE_MIN_COVERAGE_RATIO else "warning"
    if status == "warning":
        _release_daily_task_lock(lock_key)
    return {
        "trade_date": trade_date,
        "status": status,
        "message": (
            f"全市场收盘快照：有效报价 {valid_quote_count}/{active_security_count}，"
            f"覆盖率 {coverage_ratio:.1%}。"
        ),
        "quote_count": len(quotes),
        "valid_quote_count": valid_quote_count,
        "coverage_ratio": round(coverage_ratio, 6),
    }


@celery_app.task(name="services.jobs.tasks.capture_intraday_market_turn_snapshot_task")
def capture_intraday_market_turn_snapshot_task() -> dict[str, object]:
    current_time = now_local().replace(tzinfo=None)
    trade_date = current_time.date()
    with SessionLocal() as db:
        if not _is_open_trade_date(db, trade_date.isoformat()):
            return {
                "trade_date": trade_date.isoformat(),
                "status": "skipped",
                "message": "非交易日，已跳过盘中市场修复快照。",
            }
        securities = list(
            db.query(Security)
            .filter_by(is_active=True, is_st=False)
            .all()
        )

    try:
        quotes = sync_realtime_quotes(
            symbols={item.symbol for item in securities},
            quote_time=current_time,
        )
        from apps.api.app.routers.market import _safe_live_market_indexes

        index_change_pct = next(
            (
                item.change_pct
                for item in _safe_live_market_indexes()
                if item.code == "sh000001"
            ),
            None,
        )
    except Exception as exc:
        return {
            "trade_date": trade_date.isoformat(),
            "status": "failed",
            "message": f"盘中市场修复快照采集失败：{type(exc).__name__}: {exc}",
        }

    with SessionLocal() as db:
        prior_snapshots = list(
            db.execute(
                select(IntradayMarketTurnSnapshot)
                .where(IntradayMarketTurnSnapshot.trade_date == trade_date)
                .where(IntradayMarketTurnSnapshot.snapshot_time < current_time)
                .order_by(IntradayMarketTurnSnapshot.snapshot_time)
            ).scalars()
        )
        cross_day_baseline_snapshot = db.execute(
            select(IntradayMarketTurnSnapshot)
            .where(IntradayMarketTurnSnapshot.trade_date < trade_date)
            .order_by(
                IntradayMarketTurnSnapshot.trade_date.desc(),
                IntradayMarketTurnSnapshot.snapshot_time.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()
        snapshot = build_intraday_market_turn_snapshot(
            quotes=quotes,
            active_security_count=len(securities),
            active_symbols={item.symbol for item in securities},
            sector_by_symbol={item.symbol: item.industry for item in securities},
            index_change_pct=index_change_pct,
            prior_snapshots=prior_snapshots,
            cross_day_baseline_snapshot=cross_day_baseline_snapshot,
            snapshot_time=current_time,
        )
        source_counts = Counter(str(getattr(quote, "source", "unknown")) for quote in quotes)
        snapshot["quote_integrity"] = {
            "expected_symbol_count": len(securities),
            "valid_quote_count": snapshot["valid_quote_count"],
            "coverage_ratio": snapshot["coverage_ratio"],
            "source_counts": dict(sorted(source_counts.items())),
            "retry_applied": any(source.endswith(".retry") for source in source_counts),
        }
        cross_day_mainline = snapshot.get("cross_day_mainline")
        if (
            isinstance(cross_day_mainline, dict)
            and cross_day_mainline.get("status") == "观察确认"
            and cross_day_mainline.get("checkpoint") == "10:30复核"
        ):
            confirmed_sectors = {
                str(sector).strip()
                for sector in cross_day_mainline.get("confirmed_sectors") or []
                if str(sector).strip()
            }
            from services.engine.intraday.candidates import discover_intraday_candidates

            candidate_result = discover_intraday_candidates(
                db,
                trade_date=trade_date,
                pool_name="experiment",
                limit=50,
                include_growth_board=False,
                as_of=current_time,
                sustained_startup_sectors=confirmed_sectors,
            )
            snapshot["confirmed_candidate_bindings"] = build_confirmed_mainline_candidate_bindings(
                candidates=list(candidate_result.get("candidates") or []),
                confirmed_sectors=confirmed_sectors,
            )
        db.add(
            IntradayMarketTurnSnapshot(
                trade_date=trade_date,
                snapshot_time=current_time,
                coverage_ratio=float(snapshot["coverage_ratio"]),
                breadth_ratio=float(snapshot["breadth_ratio"]),
                total_amount=float(snapshot["total_amount"]),
                index_change_pct=snapshot["index_change_pct"],
                sector_expansion_count=int(snapshot["sector_expansion_count"]),
                state_json=snapshot,
            )
        )
        db.commit()

    return {
        "trade_date": trade_date.isoformat(),
        "status": "ok" if snapshot["data_ready"] else "warning",
        "message": f"盘中市场修复：{snapshot['label']}。{snapshot['summary']}",
        "snapshot": snapshot,
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
    result = generate_and_store_trade_plans(
        plan_date=today,
        trade_date=today,
        pool_name="experiment",
        limit=200,
    )
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
def run_after_close_session_task(force: bool = False) -> dict[str, object]:
    current_time = now_local()
    today = current_time.date()
    if not force and not _is_after_close_push_window(current_time):
        return {
            "trade_date": today.isoformat(),
            "status": "skipped",
            "message": f"outside after-close window: {current_time.isoformat()}",
        }
    if not force:
        acquired, lock_key = _acquire_daily_task_lock("after-close", today)
        if not acquired:
            return {
                "trade_date": today.isoformat(),
                "status": "skipped",
                "message": f"after-close task already running or sent for {today.isoformat()}",
                "lock_key": lock_key,
            }
    next_trade_date = resolve_next_trade_date(today.isoformat())
    write_after_close_status(
        {
            "trade_date": today.isoformat(),
            "next_trade_date": next_trade_date,
            "status": "running",
            "message": "盘后任务正在执行",
            "scheduler_health": {
                "state": "running",
                "last_heartbeat_at": current_time.isoformat(),
                "completed_steps": [],
                "missing_steps": [],
                "recovery_attempts": 0,
            },
        }
    )
    result: dict[str, object] | None = None
    try:
        result = run_after_close_session(
            today.isoformat(),
            next_trade_date,
            full_market_sync=True,
        ).to_dict()
        sync_statuses: dict[str, str] = {}
        for step in result.get("steps") or []:
            if step.get("name") != "sync_daily_market_data":
                continue
            for detail in step.get("details") or []:
                match = re.match(
                    r"^(moneyflow_dc|limit_list_d|cyq_perf): (ok|skipped|failed), rows=(\d+)",
                    str(detail),
                )
                if match:
                    sync_statuses[match.group(1)] = match.group(2)
        with SessionLocal() as db:
            result["tushare_evidence_health"] = inspect_tushare_evidence_health(
                db,
                today,
                sync_statuses,
            )
        failed_steps = [
            str(step.get("name") or "unknown")
            for step in result.get("steps") or []
            if step.get("status") == "failed"
        ]
        result["scheduler_health"] = {
            "state": "failed" if failed_steps else "completed",
            "last_heartbeat_at": now_local().isoformat(),
            "completed_steps": [
                str(step.get("name") or "unknown")
                for step in result.get("steps") or []
                if step.get("status") != "failed"
            ],
            "missing_steps": failed_steps,
            "recovery_attempts": 0,
        }
        if failed_steps:
            _dispatch_after_close_failure_alert(
                today.isoformat(),
                "normal",
                f"failed steps: {', '.join(failed_steps)}",
            )
        write_after_close_status(result)
        return result
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        failed_result = result or {
            "trade_date": today.isoformat(),
            "next_trade_date": next_trade_date,
            "steps": [],
        }
        failed_result["status"] = "failed"
        failed_result["message"] = "盘后任务失败"
        failed_result["scheduler_health"] = {
            "state": "failed",
            "last_heartbeat_at": now_local().isoformat(),
            "completed_steps": [
                str(step.get("name") or "unknown")
                for step in failed_result.get("steps") or []
                if step.get("status") != "failed"
            ],
            "missing_steps": ["after_close_session"],
            "recovery_attempts": 0,
            "error": error,
            "safe_recovery_url": f"/jobs/after-close/recover?trade_date={today.isoformat()}",
        }
        write_after_close_status(failed_result)
        _dispatch_after_close_failure_alert(today.isoformat(), "normal", error)
        raise


@celery_app.task(name="services.jobs.tasks.run_after_close_safe_recovery_task")
def run_after_close_safe_recovery_task() -> dict[str, object]:
    current_time = now_local()
    trade_date = current_time.date().isoformat()
    existing = read_after_close_status(trade_date)
    if existing and existing.get("status") in {"ok", "warning"}:
        return {
            "trade_date": trade_date,
            "status": "skipped",
            "message": "after-close status already completed",
        }
    if (
        existing
        and existing.get("status") in {"scheduled", "running"}
        and _is_after_close_task_active()
    ):
        return {
            "trade_date": trade_date,
            "status": "skipped",
            "message": "after-close task is still running",
        }
    if not existing:
        claimed, slot_key = _claim_after_close_recovery_slot(trade_date)
        if not claimed:
            return {
                "trade_date": trade_date,
                "status": "skipped",
                "message": "normal after-close task is pending or running",
                "lock_key": slot_key,
            }
    scheduler_health = existing.get("scheduler_health") if isinstance(existing, dict) else {}
    prior_attempts = 0
    if isinstance(scheduler_health, dict):
        try:
            prior_attempts = int(scheduler_health.get("recovery_attempts") or 0)
        except (TypeError, ValueError):
            prior_attempts = 0
    if prior_attempts >= _AFTER_CLOSE_RECOVERY_MAX_ATTEMPTS:
        return {
            "trade_date": trade_date,
            "status": "skipped",
            "message": "after-close recovery attempt limit reached",
        }
    token, lock_key = _acquire_after_close_recovery_lock(trade_date)
    if not token:
        return {
            "trade_date": trade_date,
            "status": "skipped",
            "message": "after-close recovery already running",
            "lock_key": lock_key,
        }
    recovery_attempts = prior_attempts + 1
    try:
        result = run_after_close_session(
            trade_date,
            resolve_next_trade_date(trade_date),
            full_market_sync=True,
            safe_recovery=True,
            suppress_candidate_notification=bool(
                isinstance(existing, dict) and existing.get("dingtalk_statuses")
            ),
        ).to_dict()
        failed_steps = [
            str(step.get("name") or "unknown")
            for step in result.get("steps") or []
            if step.get("status") == "failed"
        ]
        result["scheduler_health"] = {
            "state": "failed" if failed_steps else "completed",
            "last_heartbeat_at": current_time.isoformat(),
            "completed_steps": [
                str(step.get("name") or "unknown")
                for step in result.get("steps") or []
                if step.get("status") != "failed"
            ],
            "missing_steps": failed_steps,
            "recovery_attempts": recovery_attempts,
            "safe_recovery_url": f"/jobs/after-close/recover?trade_date={trade_date}",
        }
        if failed_steps:
            error = f"failed steps: {', '.join(failed_steps)}"
            result["scheduler_health"]["error"] = error
            _dispatch_after_close_failure_alert(trade_date, "safe-recovery", error)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        result = {
            "trade_date": trade_date,
            "status": "failed",
            "message": "盘后安全恢复失败",
            "steps": [],
            "scheduler_health": {
                "state": "failed",
                "last_heartbeat_at": current_time.isoformat(),
                "completed_steps": [],
                "missing_steps": ["safe_recovery"],
                "recovery_attempts": recovery_attempts,
                "error": error,
                "safe_recovery_url": f"/jobs/after-close/recover?trade_date={trade_date}",
            },
        }
        _dispatch_after_close_failure_alert(trade_date, "safe-recovery", error)
    finally:
        if isinstance(token, str):
            _release_after_close_recovery_lock(lock_key, token)
    write_after_close_status(result)
    return result


@celery_app.task(name="services.jobs.tasks.run_daily_research_pipeline_task")
def run_daily_research_pipeline_task(trade_date: str, next_trade_date: str) -> dict[str, object]:
    result = run_daily_research_pipeline(trade_date, next_trade_date)
    return result.to_dict()
