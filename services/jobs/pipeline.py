from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.collector.daily import sync_daily_market_data
from services.collector.sync import sync_recent_tushare_sector_moneyflow
from services.engine.review.mechanical import generate_daily_mechanical_review
from services.engine.tracking.repository import (
    build_tracking_snapshot_payload,
    upsert_tracking_snapshot,
)
from services.engine.workspace.repository import load_stock_workspace_items
from services.shared.database import SessionLocal
from services.shared.models import ResearchPoolItem, Security, TradingCalendar
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


def _candidate_diagnostic_detail(discovery: dict[str, Any]) -> str | None:
    diagnostics = discovery.get("candidate_diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    summary = str(diagnostics.get("summary") or "").strip()
    reasons = [str(item).strip() for item in diagnostics.get("reasons") or [] if str(item).strip()]
    if not summary and not reasons:
        return None
    detail = f"候选诊断：{summary}" if summary else "候选诊断："
    if reasons:
        detail += f" 原因：{'；'.join(reasons[:2])}"
    return detail


def _is_open_trade_date(db: Session, trade_date: str) -> bool:
    row = db.execute(
        select(TradingCalendar).where(TradingCalendar.trade_date == date.fromisoformat(trade_date))
    ).scalar_one_or_none()
    return True if row is None else bool(row.is_open)


def _next_weekday(value: date) -> date:
    candidate = value + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def resolve_next_trade_date(trade_date: str, db: Session | None = None) -> str:
    current = date.fromisoformat(trade_date)

    def _resolve(active_db: Session) -> str | None:
        calendar_item = active_db.get(TradingCalendar, current)
        if calendar_item and calendar_item.next_trade_date:
            return calendar_item.next_trade_date.isoformat()
        next_open = active_db.execute(
            select(TradingCalendar.trade_date)
            .where(TradingCalendar.trade_date > current)
            .where(TradingCalendar.is_open.is_(True))
            .order_by(TradingCalendar.trade_date)
            .limit(1)
        ).scalar_one_or_none()
        return next_open.isoformat() if next_open else None

    if db is not None:
        return _resolve(db) or _next_weekday(current).isoformat()

    with SessionLocal() as active_db:
        return _resolve(active_db) or _next_weekday(current).isoformat()


def is_a_share_intraday_window() -> bool:
    current = now_local().time()
    return time(9, 25) <= current <= time(11, 30) or time(13, 0) <= current <= time(15, 5)


def _sync_daily_market_data_step(
    trade_date: str,
    *,
    full_refresh: bool = False,
    force: bool = False,
) -> PipelineStepResult:
    sync_kwargs: dict[str, bool] = {"full_refresh": full_refresh}
    if force:
        sync_kwargs["force"] = True
    collection_results = sync_daily_market_data(trade_date, **sync_kwargs)
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
    from services.engine.backtest.walk_forward import sync_low_dimensional_feature_snapshots
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
    with SessionLocal() as db:
        cache_rows = sync_low_dimensional_feature_snapshots(
            db,
            start=pipeline_date,
            end=pipeline_date,
        )
        db.commit()
    return (
        f"计算完成：{feature_result['symbols']} 只股票、"
        f"{feature_result['rows']} 条股票特征；"
        f"{sector_feature_result['sectors']} 个板块、"
        f"{sector_feature_result['rows']} 条板块特征；"
        f"{cache_rows} 条低维缓存。"
    )


def _sync_sector_moneyflow_step(
    trade_date: str,
    *,
    lookback_open_days: int = 8,
) -> PipelineStepResult:
    collection_results = sync_recent_tushare_sector_moneyflow(
        trade_date,
        lookback_open_days=lookback_open_days,
    )
    failed = [item for item in collection_results if item.status == "failed"]
    ok = [item for item in collection_results if item.status == "ok"]
    details = [
        f"{item.trade_date} / {item.dataset}: {item.status}, rows={item.rows}"
        + (f", {item.message}" if item.message else "")
        for item in collection_results
    ]
    if failed:
        return PipelineStepResult(
            name="sync_sector_moneyflow",
            status="failed",
            detail=f"板块资金流补齐失败：{len(failed)} 个交易日失败，{len(ok)} 个成功。",
            summary="板块资金流补齐失败",
            details=details,
        )
    if ok:
        return PipelineStepResult(
            name="sync_sector_moneyflow",
            status="ok",
            detail=f"板块资金流补齐完成：更新 {len(ok)} 个交易日。",
            summary="板块资金流补齐完成",
            details=details,
        )
    return PipelineStepResult(
        name="sync_sector_moneyflow",
        status="skipped",
        detail="板块资金流已经是最近交易日，未执行补齐。",
        summary="板块资金流已最新",
        details=details,
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
        pool_name="experiment",
        limit=limit,
        use_learning_adjustments=use_learning_adjustments,
    )
    return (
        f"生成完成：从 {plan_result['contexts']} 个特征上下文"
        f"写入 {plan_result['written']} 条计划。"
    )


def _run_daily_paper_simulation_step(
    trade_date: str,
    account: str,
    *,
    execute_entries: bool = True,
) -> str:
    from services.engine.paper.simulator import run_daily_paper_simulation

    paper_result = run_daily_paper_simulation(
        trade_date=trade_date,
        account_name=account,
        execute_entries=execute_entries,
    )
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
    *,
    stage: str = "intraday",
    as_of: datetime | None = None,
) -> PipelineStepResult:
    if not force and not is_a_share_intraday_window():
        return PipelineStepResult(
            name="monitor_paper_positions_realtime",
            status="ok",
            detail="当前不在 A 股盘中时段，已跳过实时监控。",
            summary="盘中窗口外跳过",
        )

    from services.engine.paper.realtime import monitor_paper_positions_realtime

    analysis_time = (as_of or now_local()).replace(tzinfo=None)
    market_overview = None
    try:
        from apps.api.app.routers.market import _cached_live_a_share_overview

        overview = _cached_live_a_share_overview()
        market_overview = {
            "up_ratio": overview.up_ratio,
            "avg_change_pct": overview.avg_change_pct,
        }
    except Exception:
        market_overview = None

    result = monitor_paper_positions_realtime(
        trade_date=trade_date,
        account_name=account,
        quote_time=analysis_time,
        snapshot_stage=stage,
        execute_entries=execute_entries,
        execute_exits=execute_exits,
        market_overview=market_overview,
    )
    detail = (
        f"实时监控完成：获取 {result.quotes} 条快照，"
        f"纸面买入 {result.executed_entries} 笔，"
        f"产生 {len(result.alerts)} 条预警，执行 {result.executed_exits} 次卖出。"
    )
    return PipelineStepResult(
        name="monitor_paper_positions_realtime",
        status="ok",
        detail=detail,
        summary=f"{stage} @ {analysis_time.isoformat(timespec='seconds')}",
        details=[f"analysis_time={analysis_time.isoformat(timespec='seconds')}"],
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


def _generate_backtest_learning_step(trade_date: str) -> str:
    from services.engine.backtest.learning import generate_backtest_learning_report

    changed = generate_backtest_learning_report(trade_date)
    return f"回归学习完成：生成或更新 {changed} 条策略适配建议。"


def _prewarm_candidate_replay_effect_step(trade_date: str) -> PipelineStepResult:
    from apps.api.app.routers.rules import prewarm_candidate_replay_effect_cache

    result = prewarm_candidate_replay_effect_cache(end_date=trade_date)
    detail = (
        f"候选回放缓存预热：{result['start_date']} ~ {result['end_date']}，"
        f"{result.get('cache_mode') or 'range_cache'}，"
        f"分片 {result.get('shard_count') or 0} 个。"
    )
    return PipelineStepResult(
        name="prewarm_candidate_replay_effect",
        status=str(result.get("status") or "ok"),
        detail=detail,
        summary=detail,
        details=[
            f"缓存命中：{'是' if result.get('cache_hit') else '否'}",
            f"分片命中：{result.get('shard_hits') or 0}",
            f"分片重算：{result.get('shard_misses') or 0}",
        ],
    )


def _record_tracking_snapshots_step(trade_date: str, limit: int = 200) -> PipelineStepResult:
    target_date = date.fromisoformat(trade_date)
    with SessionLocal() as db:
        items = load_stock_workspace_items(
            db,
            pool_name="experiment",
            limit=limit,
            include_growth_board=False,
        )
        rows = [
            upsert_tracking_snapshot(
                db,
                build_tracking_snapshot_payload(item, snapshot_date=target_date),
            )
            for item in items
        ]
        symbols = [row.symbol for row in rows[:20]]
        db.commit()
    return PipelineStepResult(
        name="record_tracking_snapshots",
        status="ok",
        detail=f"追踪快照已记录：{trade_date}，写入 {len(rows)} 只股票。",
        summary=f"追踪快照 {len(rows)} 只",
        details=symbols,
    )


def _generate_daily_review_step(trade_date: str) -> str:
    review = generate_daily_mechanical_review(trade_date)
    return review.title


def _prepare_market_feature_universe_step(
    trade_date: str,
    limit: int | None = None,
    *,
    sync_daily: bool = False,
) -> PipelineStepResult:
    from services.engine.research_pool.market_universe import prepare_market_feature_universe

    result = prepare_market_feature_universe(
        feature_date=trade_date,
        limit=limit,
        sync_daily=sync_daily,
    )
    details = [
        f"证券宇宙 {result.symbols} 只",
        f"同步日线 {result.synced_daily_rows} 行",
        f"写入特征 {result.feature_rows} 行",
        f"本地可扫描特征股票 {result.feature_symbols} 只",
        f"特征覆盖率 {result.coverage_ratio:.1%}",
    ]
    details.extend(result.warnings[:20])
    status = "warning" if result.warnings else "ok"
    summary = (
        f"市场候选宇宙完成：可扫描 {result.feature_symbols} 只股票，"
        f"覆盖率 {result.coverage_ratio:.1%}。"
    )
    return PipelineStepResult(
        name="prepare_market_feature_universe",
        status=status,
        detail=summary,
        summary=summary,
        details=details,
    )


def _daily_candidate_data_gate_step(trade_date: str) -> PipelineStepResult:
    from services.engine.features.health import inspect_daily_data_health

    with SessionLocal() as db:
        report = inspect_daily_data_health(db, trade_date=date.fromisoformat(trade_date))

    if report.candidate_generation_allowed:
        detail = (
            f"候选数据门禁通过：日线 {report.eligible_daily_bar_count}/"
            f"{report.expected_security_count}，覆盖 {report.daily_coverage_ratio:.1%}。"
        )
        return PipelineStepResult(
            name="validate_daily_candidate_data",
            status="ok",
            detail=detail,
            summary="候选数据可用",
        )

    return PipelineStepResult(
        name="validate_daily_candidate_data",
        status="warning",
        detail="候选数据门禁未通过：" + "；".join(report.candidate_block_reasons),
        summary="数据完整性不足",
        details=report.candidate_block_reasons,
    )


def _load_star_symbols(db: Session) -> list[str]:
    try:
        rows = db.execute(
            select(Security.symbol)
            .where(Security.is_active.is_(True))
            .where(Security.symbol.like("688%"))
        ).all()
    except Exception:
        return []
    return [str(item[0]) for item in rows]


def _filter_star_focus_candidates(
    star_discovery: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    focus_sectors = {
        str(item.get("sector") or "").strip()
        for item in star_discovery.get("sector_focus") or []
        if str(item.get("sector") or "").strip()
    }
    if not focus_sectors:
        return candidates
    return [
        item
        for item in candidates
        if str(item.get("sector") or "").strip() in focus_sectors
    ]


def _is_expansion_confirm_candidate(item: dict[str, Any]) -> bool:
    mode = str(item.get("selection_mode") or "").strip()
    if mode not in {"potential_watch", "exploration"}:
        return False
    if float(item.get("score") or 0.0) < 60.0:
        return False

    risk_text = " ".join(str(flag) for flag in item.get("risk_flags") or [])
    heavy_risk_keywords = ("放量诱多风险", "放量回落", "冲高翻绿", "近涨停未封")
    if any(keyword in risk_text for keyword in heavy_risk_keywords):
        return False

    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    has_expansion_context = any(
        keyword in reasons_text
        for keyword in (
            "潜力启动：20日涨幅仍低",
            "板块20日主线扩散较好",
            "板块中期趋势延续性较好",
        )
    )
    has_confirmation = any(
        keyword in reasons_text
        for keyword in (
            "量能温和确认",
            "量能未明显失速",
            "趋势强度领先",
            "趋势和资金都在同一方向",
        )
    )
    return has_expansion_context and has_confirmation


def _is_startup_preheat_candidate(item: dict[str, Any]) -> bool:
    mode = str(item.get("selection_mode") or "").strip()
    if mode != "potential_watch":
        return False
    if float(item.get("score") or 0.0) < 58.0:
        return False

    risk_text = " ".join(str(flag) for flag in item.get("risk_flags") or [])
    heavy_risk_keywords = ("放量诱多风险", "放量回落", "冲高翻绿", "近涨停未封", "20日涨幅偏高")
    if any(keyword in risk_text for keyword in heavy_risk_keywords):
        return False

    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    return "启动前夜：T-1量价修复" in reasons_text and "成交量开始确认" in reasons_text


def _load_candidate_gate_policies(trade_date: str) -> dict[str, Any]:
    try:
        from apps.api.app.routers.rules import (
            diagnose_candidate_replay_effect,
            diagnose_style_gate_policy,
        )
        from services.engine.backtest.walk_forward import compare_candidate_walk_forward_scopes

        end_date = date.fromisoformat(trade_date)
        start_date = (end_date - timedelta(days=240)).isoformat()
        comparison = compare_candidate_walk_forward_scopes(
            start_date=start_date,
            end_date=trade_date,
            scopes=(
                "all",
                "action",
                "action_long",
                "potential_watch",
                "startup_preheat",
                "sector_watch",
            ),
            limit=15,
            horizons=(5, 10, 20),
            min_coverage_ratio=0.70,
            include_fundamentals=False,
        )
        diagnosis = diagnose_candidate_replay_effect(comparison, horizon=20)
        policies = {
            "style_gate_policy": diagnose_style_gate_policy(
                comparison,
                scope="potential_watch",
                horizon=10,
            ),
            "startup_preheat_policy": diagnose_style_gate_policy(
                comparison,
                scope="startup_preheat",
                horizon=5,
                min_latest_samples=3,
                min_recent_samples=5,
                min_upgrade_avg_return=0.02,
            ),
        }
        market_phase = diagnosis.get("market_phase_policy") if isinstance(diagnosis, dict) else None
        phase_status = (
            str(market_phase.get("status") or "") if isinstance(market_phase, dict) else ""
        )
        if phase_status and phase_status != "insufficient_data":
            for key in ("market_phase_policy", "dual_line_policy", "strategy_pk"):
                value = diagnosis.get(key) if isinstance(diagnosis, dict) else None
                if isinstance(value, dict):
                    policies[key] = value
        return policies
    except Exception:
        return {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_market_stress_from_discovery(discovery: dict[str, Any]) -> dict[str, Any]:
    existing = discovery.get("market_stress")
    if isinstance(existing, dict):
        return existing

    regime_snapshot = discovery.get("market_regime_snapshot") or {}
    participation_snapshot = discovery.get("market_participation_snapshot") or {}
    regime = str(discovery.get("market_regime") or regime_snapshot.get("regime") or "")
    gate_state = str(regime_snapshot.get("emotion_gate") or "")
    emotion_gate = discovery.get("emotion_gate") or {}
    if not gate_state and isinstance(emotion_gate, dict):
        gate_state = str(emotion_gate.get("state") or "")
    breadth_score = _safe_float(regime_snapshot.get("breadth_score"), 50.0)
    participation_score = _safe_float(participation_snapshot.get("participation_score"), 50.0)
    liquidity_score = _safe_float(participation_snapshot.get("liquidity_score"), 50.0)

    score = 0.0
    reasons: list[str] = []
    if regime == "panic" or gate_state == "risk_off":
        score += 45.0
        reasons.append("情绪阀门risk_off，先按弱市处理")
    if breadth_score <= 35.0:
        score += 35.0
        reasons.append(f"市场宽度{breadth_score:.1f}，多数股票承压")
    elif breadth_score <= 45.0:
        score += 20.0
        reasons.append(f"市场宽度{breadth_score:.1f}，赚钱效应偏弱")
    if participation_score < 45.0 or liquidity_score < 35.0:
        score += 15.0
        reasons.append("参与度或流动性不足，候选需要二次确认")

    if score >= 70.0:
        status = "risk_off"
        label = "压力大"
        action = "停止扩散，只做观察和风控"
    elif score >= 40.0:
        status = "caution"
        label = "谨慎"
        action = "降低频率，等盘中确认"
    else:
        status = "neutral"
        label = "中性"
        action = "按原计划精选"

    return {
        "stress_status": status,
        "stress_label": label,
        "stress_score": round(score, 2),
        "stress_reasons": reasons or ["候选发现阶段没有明显市场压力"],
        "risk_action_label": action,
    }


def _candidate_live_market_stress_for_trade_date(
    trade_date: str,
    db: Session | None = None,
) -> dict[str, Any] | None:
    if trade_date != now_local().date().isoformat():
        return None
    try:
        from apps.api.app.routers.market import (
            _store_live_market_cache,
            _try_cached_live_a_share_overview,
            _try_sina_symbol_live_a_share_overview,
        )

        overview = _try_cached_live_a_share_overview(8.0)
        if overview is None and db is not None:
            overview = _try_sina_symbol_live_a_share_overview(db)
            if overview is not None:
                _store_live_market_cache(overview)
    except Exception:
        return None
    if overview is None:
        return None
    overview_date = getattr(overview, "trade_date", None)
    if overview_date is not None and overview_date.isoformat() != trade_date:
        return None
    status = str(getattr(overview, "stress_status", "") or "")
    if status not in {"caution", "risk_off"}:
        return None
    return {
        "trade_date": overview_date.isoformat() if overview_date else trade_date,
        "snapshot_scope_label": getattr(overview, "snapshot_scope_label", "盘中实时"),
        "stress_status": status,
        "stress_label": getattr(overview, "stress_label", "压力大"),
        "stress_score": getattr(overview, "stress_score", None),
        "stress_reasons": list(getattr(overview, "stress_reasons", []) or []),
        "risk_action_label": getattr(overview, "risk_action_label", None),
    }


def _apply_candidate_tier_tags(
    db: Session,
    *,
    pool_names: tuple[str, ...],
    candidate_tiers: dict,
) -> None:
    tier_by_symbol: dict[str, tuple[str, str]] = {}
    tier_item_by_symbol: dict[str, dict[str, Any]] = {}
    tier_summary = (
        candidate_tiers.get("summary") if isinstance(candidate_tiers, dict) else {}
    ) or {}
    core_block_reason = str(tier_summary.get("core_block_reason") or "").replace("\n", " ").strip()
    for tier in ("core_action", "sector_watch", "watch_wait", "risk_reject"):
        for item in candidate_tiers.get(tier) or []:
            symbol = str(item.get("symbol") or "")
            if not symbol:
                continue
            reason = str(item.get("tier_reason") or "").replace("\n", " ").strip()
            tier_by_symbol[symbol] = (tier, reason)
            tier_item_by_symbol[symbol] = item
    if not tier_by_symbol:
        return
    if not hasattr(db, "execute"):
        return

    rows = db.execute(
        select(ResearchPoolItem)
        .where(ResearchPoolItem.pool_name.in_(pool_names))
        .where(ResearchPoolItem.status == "active")
        .where(ResearchPoolItem.symbol.in_(tier_by_symbol))
    ).scalars()
    for row in rows:
        tier, reason = tier_by_symbol.get(row.symbol, ("", ""))
        if not tier:
            continue
        current_tags = [str(tag) for tag in (row.tags_json or {}).get("tags", [])]
        cleaned_tags = [
            tag
            for tag in current_tags
            if not (
                tag.startswith("tier:")
                or tag.startswith("tier_reason:")
                or tag.startswith("candidate_summary:")
                or tag.startswith("candidate_pool:")
                or tag.startswith("candidate_pool_reason:")
                or tag.startswith("style_gate:")
                or tag.startswith("style_gate_reason:")
            )
        ]
        cleaned_tags.append(f"tier:{tier}")
        if reason:
            cleaned_tags.append(f"tier_reason:{reason}")
        if core_block_reason:
            cleaned_tags.append(f"candidate_summary:{core_block_reason}")
        tier_item = tier_item_by_symbol.get(row.symbol) or {}
        if tier == "watch_wait" and _is_startup_preheat_candidate(tier_item):
            cleaned_tags.append("candidate_pool:startup_preheat")
            cleaned_tags.append(
                "candidate_pool_reason:启动前夜：T-1量价修复但还没确认，先盯次日承接，不进核心。"
            )
        elif tier == "watch_wait" and _is_expansion_confirm_candidate(tier_item):
            cleaned_tags.append("candidate_pool:expansion_confirm")
            cleaned_tags.append(
                "candidate_pool_reason:扩散确认：板块扩散和个股启动同步，先观察承接，不进核心。"
            )
        gate_status = str(tier_item.get("style_gate_status") or "").strip()
        gate_reason = str(tier_item.get("style_gate_reason") or "").replace("\n", " ").strip()
        if gate_status:
            cleaned_tags.append(f"style_gate:{gate_status}")
        if gate_reason:
            cleaned_tags.append(f"style_gate_reason:{gate_reason}")
        row.tags_json = {"tags": list(dict.fromkeys(cleaned_tags))}


def _discover_next_session_candidates_step(
    trade_date: str,
    next_trade_date: str,
    limit: int,
    use_learning_adjustments: bool,
) -> PipelineStepResult:
    from services.engine.plans.sync import generate_and_store_trade_plans
    from services.engine.research_pool.candidates import (
        CANDIDATE_DEFAULT_LIMIT,
        discover_next_session_candidates,
    )
    from services.notifications.dispatcher import (
        build_candidate_tiers,
        dispatch_candidate_screening,
        filter_hot_sector_candidates,
        select_action_candidates,
        select_long_action_candidates,
    )

    candidate_limit = max(1, min(limit, CANDIDATE_DEFAULT_LIMIT))
    with SessionLocal() as db:
        discovery = discover_next_session_candidates(
            db,
            feature_date=trade_date,
            next_trade_date=next_trade_date,
            pool_name="experiment",
            limit=candidate_limit,
        )
        star_symbols = _load_star_symbols(db)
        star_scan_kwargs: dict[str, Any] = {"symbols": star_symbols} if star_symbols else {}
        star_discovery = discover_next_session_candidates(
            db,
            feature_date=trade_date,
            next_trade_date=next_trade_date,
            pool_name="experiment_star",
            limit=10,
            include_growth_board=True,
            **star_scan_kwargs,
        )
        normal_candidates = filter_hot_sector_candidates(
            discovery,
            [
                item
                for item in discovery.get("candidates", [])
                if not str(item.get("symbol") or "").startswith("688")
            ],
        )[:candidate_limit]
        star_candidates = filter_hot_sector_candidates(
            star_discovery,
            [
                item
                for item in star_discovery.get("candidates", [])
                if str(item.get("symbol") or "").startswith("688")
            ],
        )[:10]
        star_candidates = _filter_star_focus_candidates(star_discovery, star_candidates)[:10]
        action_candidates = select_action_candidates(
            discovery,
            normal_candidates,
            max_items=3,
        )
        long_action_candidates = select_long_action_candidates(
            discovery,
            normal_candidates,
            max_items=3,
        )
        discovery["candidates"] = normal_candidates + star_candidates
        discovery["action_candidates"] = action_candidates
        discovery["long_action_candidates"] = long_action_candidates
        discovery["market_stress"] = (
            _candidate_live_market_stress_for_trade_date(trade_date, db)
            or _candidate_market_stress_from_discovery(discovery)
        )
        discovery.update(_load_candidate_gate_policies(trade_date))
        discovery["candidate_tiers"] = build_candidate_tiers(
            discovery,
            discovery["candidates"],
            max_core_items=3,
        )
        discovery["star_candidates"] = star_candidates
        _apply_candidate_tier_tags(
            db,
            pool_names=("experiment", "experiment_star"),
            candidate_tiers=discovery["candidate_tiers"],
        )
        db.commit()
    requested_feature_date = discovery.get("requested_feature_date") or trade_date
    effective_feature_date = discovery.get("feature_date") or ""
    feature_date_fell_back = bool(
        requested_feature_date
        and effective_feature_date
        and str(effective_feature_date) != str(requested_feature_date)
    )
    notification_results = [] if feature_date_fell_back else dispatch_candidate_screening(discovery)

    candidates = discovery["candidates"]
    action_candidates = discovery.get("action_candidates") or []
    candidate_tiers = discovery.get("candidate_tiers") or {}
    if isinstance(candidate_tiers, dict) and "core_action" in candidate_tiers:
        plan_candidates = candidate_tiers.get("core_action") or []
    else:
        plan_candidates = discovery.get("long_action_candidates") or action_candidates
    formal_symbols = [
        item["symbol"]
        for item in plan_candidates
        if item.get("selection_mode") == "formal_strategy"
    ]
    plan_result = generate_and_store_trade_plans(
        plan_date=trade_date,
        trade_date=next_trade_date,
        feature_date=discovery["feature_date"] or None,
        symbols=formal_symbols,
        limit=len(formal_symbols),
        use_learning_adjustments=use_learning_adjustments,
    )

    details = [
        f"{item['symbol']} {item.get('name') or ''} / {item.get('sector') or '-'} / "
        f"{item.get('selected_rule_id') or '-'} {item.get('selected_rule_name') or ''} / "
        f"{item.get('selection_mode') or '-'} / "
        f"今日 {float(item['day_change_pct']) * 100:.2f}% / "
        f"分数 {item['score']:.2f} / {'，'.join(item['reasons'])}"
        for item in candidates[:20]
        if item.get("day_change_pct") is not None
    ]
    details.extend(
        [
            f"{item['symbol']} {item.get('name') or ''} / {item.get('sector') or '-'} / "
            f"{item.get('selected_rule_id') or '-'} {item.get('selected_rule_name') or ''} / "
            f"{item.get('selection_mode') or '-'} / "
            f"今日 - / 分数 {item['score']:.2f} / {'，'.join(item['reasons'])}"
            for item in candidates[:20]
            if item.get("day_change_pct") is None
        ]
    )
    market_snapshot = discovery.get("market_regime_snapshot") or {}
    market_stress = discovery.get("market_stress") if isinstance(discovery, dict) else {}
    if not isinstance(market_stress, dict):
        market_stress = {}
    stress_status = str(market_stress.get("stress_status") or "")
    stress_label = str(market_stress.get("stress_label") or "")
    stress_suffix = (
        f" / {stress_label}"
        if stress_label and stress_status in {"caution", "risk_off"}
        else ""
    )
    details.insert(
        0,
        f"市场环境 {discovery.get('market_regime') or '-'}{stress_suffix} / "
        f"有效上限 {discovery.get('effective_limit', candidate_limit)} / "
        f"趋势 {float(market_snapshot.get('trend_score') or 0):.1f} / "
        f"上升信号 {float(market_snapshot.get('up_signal_rate') or 0):.1f}%",
    )
    candidate_diagnostic_detail = _candidate_diagnostic_detail(discovery)
    if candidate_diagnostic_detail:
        details.insert(1, candidate_diagnostic_detail)
    tier_summary = (
        candidate_tiers.get("summary") if isinstance(candidate_tiers, dict) else {}
    ) or {}
    core_block_reason = tier_summary.get("core_block_reason")
    if core_block_reason:
        details.insert(1, str(core_block_reason))
    if discovery.get("universe_warning"):
        details.insert(0, str(discovery["universe_warning"]))
    if notification_results:
        details.insert(
            0,
            "钉钉提醒："
            + "；".join(
                f"{item.channel}:{item.status}"
                for item in notification_results
            ),
        )
    if feature_date_fell_back:
        details.insert(
            0,
            (
                f"数据未补齐：请求特征日 {requested_feature_date}，"
                f"实际使用 {effective_feature_date}，"
                f"覆盖率 {float(discovery.get('feature_coverage_ratio') or 0):.1%}。"
                "已跳过钉钉推送，避免重复发送旧盘面候选。"
            ),
        )
    written_count = int(discovery.get("written") or 0) + int(star_discovery.get("written") or 0)
    retired_count = int(discovery.get("retired") or 0) + int(star_discovery.get("retired") or 0)
    summary = (
        f"明日候选完成：扫描 {discovery.get('universe_size', 0)} 只股票，"
        f"市场 {discovery.get('market_regime') or '-'}{stress_suffix}，"
        f"有效上限 {discovery.get('effective_limit', candidate_limit)}，"
        f"写入 {written_count} 只股票，"
        f"淘汰 {retired_count} 只旧候选，"
        f"生成 {plan_result['written']} 条交易计划。"
    )
    return PipelineStepResult(
        name="discover_next_session_candidates",
        status="warning" if discovery.get("universe_warning") or feature_date_fell_back else "ok",
        detail=summary,
        summary=summary,
        details=details,
    )


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
        _run_step("sync_sector_moneyflow", lambda: _sync_sector_moneyflow_step(trade_date)),
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
    stage: str = "intraday",
    as_of: datetime | None = None,
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
                stage=stage,
                as_of=as_of,
            ),
        )
    ]
    return DailyPipelineResult(
        trade_date=trade_date,
        next_trade_date=trade_date,
        stage=stage,
        steps=steps,
    )


def run_after_close_session(
    trade_date: str,
    next_trade_date: str,
    *,
    limit: int = 200,
    account: str = "default",
    use_learning_adjustments: bool = True,
    full_market_sync: bool = False,
) -> DailyPipelineResult:
    steps = []
    if full_market_sync:
        steps.append(
            _run_step(
                "sync_daily_market_data",
                lambda: _sync_daily_market_data_step(
                    trade_date,
                    full_refresh=True,
                    force=True,
                ),
            )
        )
    steps.extend(
        [
            _run_step(
                "sync_sector_moneyflow",
                lambda: _sync_sector_moneyflow_step(trade_date),
            ),
            _run_step(
                "prepare_market_feature_universe",
                lambda: _prepare_market_feature_universe_step(
                    trade_date,
                    None,
                    sync_daily=False,
                ),
            ),
        ]
    )
    candidate_gate = _run_step(
        "validate_daily_candidate_data",
        lambda: _daily_candidate_data_gate_step(trade_date),
    )
    steps.append(candidate_gate)
    candidate_data_ready = candidate_gate.status == "ok"
    if candidate_data_ready:
        steps.extend(
            [
                _run_step(
                    "discover_next_session_candidates",
                    lambda: _discover_next_session_candidates_step(
                        trade_date,
                        next_trade_date,
                        limit,
                        use_learning_adjustments,
                    ),
                ),
                _run_step(
                    "record_tracking_snapshots",
                    lambda: _record_tracking_snapshots_step(trade_date, limit),
                ),
            ]
        )
    else:
        steps.append(
            PipelineStepResult(
                name="discover_next_session_candidates",
                status="warning",
                detail="数据完整性不足，已跳过明日候选和交易计划。",
                summary="数据完整性不足",
                details=candidate_gate.details,
            )
        )

    steps.extend(
        [
        _run_step(
            "run_daily_paper_simulation",
            lambda: _run_daily_paper_simulation_step(
                trade_date,
                account,
                execute_entries=candidate_data_ready,
            ),
        ),
        _run_step(
            "generate_paper_trading_review",
            lambda: _generate_paper_reviews_step(trade_date),
        ),
        _run_step("run_rule_regression", lambda: _run_rule_regression_step(trade_date, limit)),
        _run_step(
            "generate_backtest_learning_review",
            lambda: _generate_backtest_learning_step(trade_date),
        ),
        _run_step(
            "prewarm_candidate_replay_effect",
            lambda: _prewarm_candidate_replay_effect_step(trade_date),
        ),
        _run_step("generate_daily_review", lambda: _generate_daily_review_step(trade_date)),
        ]
    )
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
    after_close_result = run_after_close_session(
        trade_date,
        next_trade_date,
        full_market_sync=True,
    )
    return DailyPipelineResult(
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        stage="daily",
        steps=[*prepare_result.steps, *after_close_result.steps],
    )
