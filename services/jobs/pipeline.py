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
        from apps.api.app.routers.rules import diagnose_style_gate_policy
        from services.engine.backtest.walk_forward import compare_candidate_walk_forward_scopes

        end_date = date.fromisoformat(trade_date)
        start_date = (end_date - timedelta(days=240)).isoformat()
        comparison = compare_candidate_walk_forward_scopes(
            start_date=start_date,
            end_date=trade_date,
            scopes=("potential_watch", "startup_preheat"),
            limit=15,
            horizons=(5, 10),
            min_coverage_ratio=0.70,
            include_fundamentals=False,
        )
        return {
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
    except Exception:
        return {}


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
    for tier in ("core_action", "watch_wait", "risk_reject"):
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
        star_discovery = discover_next_session_candidates(
            db,
            feature_date=trade_date,
            next_trade_date=next_trade_date,
            pool_name="experiment_star",
            limit=10,
            include_growth_board=True,
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
    plan_candidates = (
        candidate_tiers.get("core_action")
        or discovery.get("long_action_candidates")
        or action_candidates
    )
    formal_symbols = [
        item["symbol"]
        for item in plan_candidates
        if item.get("selection_mode") == "formal_strategy"
    ]
    plan_result = {"written": 0}
    if formal_symbols:
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
    details.insert(
        0,
        f"市场环境 {discovery.get('market_regime') or '-'} / "
        f"有效上限 {discovery.get('effective_limit', candidate_limit)} / "
        f"趋势 {float(market_snapshot.get('trend_score') or 0):.1f} / "
        f"上升信号 {float(market_snapshot.get('up_signal_rate') or 0):.1f}%",
    )
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
        f"市场 {discovery.get('market_regime') or '-'}，"
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
    steps = [
        _run_step("sync_sector_moneyflow", lambda: _sync_sector_moneyflow_step(trade_date)),
        _run_step(
            "prepare_market_feature_universe",
            lambda: _prepare_market_feature_universe_step(
                trade_date,
                None,
                sync_daily=full_market_sync,
            ),
        ),
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
            "run_daily_paper_simulation",
            lambda: _run_daily_paper_simulation_step(trade_date, account),
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
