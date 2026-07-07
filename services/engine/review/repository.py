from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from services.engine.research_pool.repository import list_pool_items
from services.engine.rules.seed_rules import MVP_RULES
from services.engine.sector.names import canonical_sector_name
from services.shared.models import (
    DailyBar,
    ParameterRecommendation,
    ReviewReport,
    RulePerformanceDaily,
    Security,
    TradePlan,
    TradingCalendar,
    TushareMoneyflowIndDc,
)

ACTIVE_RULE_IDS = tuple(rule.id for rule in MVP_RULES)
PARAMETER_RECOMMENDATION_STATUSES = {"pending", "approved", "rejected", "applied"}
INDEX_DAILY_BAR_SYMBOLS = {"399001", "399006", "sh000001", "sz399001", "sz399006"}
MARKET_INDEX_SYMBOLS = (
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
)


def _recommendation_rule_id(item: dict) -> str | None:
    proposed = item.get("proposed") or {}
    current = item.get("current") or {}
    if item.get("rule_id"):
        return item["rule_id"]
    if proposed.get("source_rule_id"):
        return proposed["source_rule_id"]
    if current.get("rule_id"):
        return current["rule_id"]
    return item.get("scope_value") if item.get("scope_type", "rule") == "rule" else None


def load_rule_performance_for_date(db: Session, report_date: str) -> list[RulePerformanceDaily]:
    stmt = (
        select(RulePerformanceDaily)
        .where(RulePerformanceDaily.trade_date == date.fromisoformat(report_date))
        .order_by(desc(RulePerformanceDaily.score))
    )
    return list(db.execute(stmt).scalars())


def load_trade_plans_for_date(db: Session, plan_date: str, limit: int = 20) -> list[TradePlan]:
    stmt = (
        select(TradePlan)
        .where(TradePlan.plan_date == date.fromisoformat(plan_date))
        .where(TradePlan.rule_id.in_(ACTIVE_RULE_IDS))
        .order_by(desc(TradePlan.confidence_score))
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def load_latest_review_report(
    db: Session,
    report_type: str,
    *,
    before_report_date: str | None = None,
) -> ReviewReport | None:
    stmt = select(ReviewReport).where(ReviewReport.report_type == report_type)
    if before_report_date:
        stmt = stmt.where(ReviewReport.report_date < date.fromisoformat(before_report_date))
    stmt = stmt.order_by(desc(ReviewReport.report_date), desc(ReviewReport.id)).limit(1)
    return db.execute(stmt).scalar_one_or_none()


def previous_trade_date(db: Session, report_date: str) -> date:
    current = date.fromisoformat(report_date)
    previous = db.execute(
        select(TradingCalendar.previous_trade_date).where(TradingCalendar.trade_date == current)
    ).scalar_one_or_none()
    if previous is not None:
        return previous

    fallback = db.execute(
        select(func.max(TradingCalendar.trade_date))
        .where(TradingCalendar.trade_date < current)
        .where(TradingCalendar.is_open.is_(True))
    ).scalar_one_or_none()
    if fallback is not None:
        return fallback
    return current - timedelta(days=1)


def load_candidate_pool_items_for_review(
    db: Session,
    report_date: str,
    pool_name: str = "experiment",
) -> list[dict]:
    feature_tag = previous_trade_date(db, report_date).isoformat()
    items = list_pool_items(db, pool_name=pool_name)
    return [
        item
        for item in items
        if feature_tag in (item.get("tags") or [])
        and "after_close_candidate" in (item.get("tags") or [])
    ]


def load_daily_bars_for_symbols(
    db: Session,
    trade_date: str,
    symbols: list[str],
) -> dict[str, DailyBar]:
    if not symbols:
        return {}
    stmt = (
        select(DailyBar)
        .where(DailyBar.trade_date == date.fromisoformat(trade_date))
        .where(DailyBar.symbol.in_(symbols))
    )
    return {item.symbol: item for item in db.execute(stmt).scalars()}


def load_market_summary_for_report_date(db: Session, report_date: str) -> dict[str, object]:
    target_date = date.fromisoformat(report_date)
    latest_date = db.execute(
        select(func.max(DailyBar.trade_date)).where(DailyBar.trade_date <= target_date)
    ).scalar_one_or_none()
    if latest_date is None:
        return {
            "requested_date": target_date.isoformat(),
            "trade_date": "",
            "stale": True,
            "stock_count": 0,
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "up_ratio": None,
            "avg_change_pct": None,
            "total_amount": None,
            "amount_change_pct": None,
            "amount_change_note": "",
            "active_security_count": 0,
            "coverage_ratio": None,
            "is_full_market": False,
        }

    bars = [
        item
        for item in db.execute(select(DailyBar).where(DailyBar.trade_date == latest_date)).scalars()
        if item.symbol not in INDEX_DAILY_BAR_SYMBOLS
    ]
    changes = [
        float(item.close) / float(item.pre_close) - 1
        for item in bars
        if item.pre_close is not None and float(item.pre_close) > 0
    ]
    up_count = sum(1 for value in changes if value > 0)
    down_count = sum(1 for value in changes if value < 0)
    flat_count = len(changes) - up_count - down_count
    total_amount = sum(float(item.amount or 0) for item in bars)
    amount_missing_ratio = sum(1 for item in bars if item.amount is None) / len(bars) if bars else 1

    previous_date = db.execute(
        select(func.max(DailyBar.trade_date)).where(DailyBar.trade_date < latest_date)
    ).scalar_one_or_none()
    previous_amount = 0.0
    previous_amount_missing_ratio = 1.0
    if previous_date is not None:
        previous_bars = [
            item
            for item in db.execute(
                select(DailyBar).where(DailyBar.trade_date == previous_date)
            ).scalars()
            if item.symbol not in INDEX_DAILY_BAR_SYMBOLS
        ]
        previous_amount = sum(float(item.amount or 0) for item in previous_bars)
        previous_amount_missing_ratio = (
            sum(1 for item in previous_bars if item.amount is None) / len(previous_bars)
            if previous_bars
            else 1.0
        )

    active_security_count = int(
        db.execute(
            select(func.count())
            .select_from(Security)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).scalar_one()
    )
    stock_count = len(changes)
    coverage_ratio = (
        round(stock_count / active_security_count, 6) if active_security_count else None
    )
    amount_change_note = ""
    amount_change_pct = None
    if amount_missing_ratio >= 0.2:
        amount_change_note = "当日成交额覆盖不足，暂不计算成交额变化。"
    elif previous_amount_missing_ratio >= 0.2:
        amount_change_note = "前一交易日成交额覆盖不足，暂不计算成交额变化。"
    elif previous_amount > 0:
        amount_change_pct = round(total_amount / previous_amount - 1, 6)
    return {
        "requested_date": target_date.isoformat(),
        "trade_date": latest_date.isoformat(),
        "stale": latest_date < target_date,
        "stock_count": stock_count,
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "up_ratio": round(up_count / stock_count, 6) if stock_count else None,
        "avg_change_pct": round(sum(changes) / stock_count, 6) if stock_count else None,
        "total_amount": total_amount,
        "amount_change_pct": amount_change_pct,
        "amount_change_note": amount_change_note,
        "active_security_count": active_security_count,
        "coverage_ratio": coverage_ratio,
        "is_full_market": bool(coverage_ratio is not None and coverage_ratio >= 0.80),
    }


def load_market_indexes_for_report_date(db: Session, report_date: str) -> list[dict[str, object]]:
    target_date = date.fromisoformat(report_date)
    indexes: list[dict[str, object]] = []
    for symbol, name in MARKET_INDEX_SYMBOLS:
        latest_date = db.execute(
            select(func.max(DailyBar.trade_date))
            .where(DailyBar.symbol == symbol)
            .where(DailyBar.trade_date <= target_date)
        ).scalar_one_or_none()
        if latest_date is None:
            indexes.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "trade_date": "",
                    "close": None,
                    "change_pct": None,
                    "amount": None,
                    "stale": True,
                }
            )
            continue

        bar = db.execute(
            select(DailyBar)
            .where(DailyBar.symbol == symbol)
            .where(DailyBar.trade_date == latest_date)
        ).scalar_one_or_none()
        if bar is None:
            continue
        previous_close = float(bar.pre_close) if bar.pre_close is not None else None
        if previous_close is None or previous_close <= 0:
            previous_close = db.execute(
                select(DailyBar.close)
                .where(DailyBar.symbol == symbol)
                .where(DailyBar.trade_date < latest_date)
                .order_by(desc(DailyBar.trade_date))
                .limit(1)
            ).scalar_one_or_none()
            previous_close = float(previous_close) if previous_close is not None else None
        change_pct = (
            round(float(bar.close) / previous_close - 1, 6)
            if previous_close is not None and previous_close > 0
            else None
        )
        indexes.append(
            {
                "symbol": symbol,
                "name": name,
                "trade_date": latest_date.isoformat(),
                "close": float(bar.close),
                "change_pct": change_pct,
                "amount": float(bar.amount) if bar.amount is not None else None,
                "stale": latest_date < target_date,
            }
        )
    return indexes


def _add_moneyflow_snapshot(
    snapshots: dict[str, dict[str, object]],
    sector_name: str,
    row: TushareMoneyflowIndDc,
) -> None:
    snapshot = snapshots.setdefault(
        sector_name,
        {
            "trade_date": row.trade_date,
            "amount_sum": 0.0,
            "amount_count": 0,
            "rate_sum": 0.0,
            "rate_count": 0,
            "source_names": set(),
        },
    )
    if row.net_amount is not None:
        snapshot["amount_sum"] = float(snapshot["amount_sum"]) + float(row.net_amount)
        snapshot["amount_count"] = int(snapshot["amount_count"]) + 1
    if row.net_amount_rate is not None:
        snapshot["rate_sum"] = float(snapshot["rate_sum"]) + float(row.net_amount_rate)
        snapshot["rate_count"] = int(snapshot["rate_count"]) + 1
    source_names = snapshot["source_names"]
    if isinstance(source_names, set):
        source_names.add(str(row.name or sector_name))


def load_market_cross_section_for_report_date(
    db: Session,
    report_date: str,
    *,
    limit: int = 5,
    min_sector_count: int = 3,
) -> dict[str, object]:
    target_date = date.fromisoformat(report_date)
    latest_date = db.execute(
        select(func.max(DailyBar.trade_date)).where(DailyBar.trade_date <= target_date)
    ).scalar_one_or_none()
    if latest_date is None:
        return {
            "trade_date": "",
            "sector_moneyflow_trade_date": "",
            "sector_moneyflow_stale": False,
            "sector_moneyflow_missing_count": 0,
            "strong_sectors": [],
            "weak_sectors": [],
            "top_gainers": [],
            "top_losers": [],
        }

    moneyflow_date = db.execute(
        select(func.max(TushareMoneyflowIndDc.trade_date))
        .where(TushareMoneyflowIndDc.trade_date <= latest_date)
        .where(TushareMoneyflowIndDc.content_type == "行业")
    ).scalar_one_or_none()
    moneyflow_by_name: dict[str, dict[str, object]] = {}
    if moneyflow_date is not None:
        moneyflow_rows = db.execute(
            select(TushareMoneyflowIndDc)
            .where(TushareMoneyflowIndDc.trade_date == moneyflow_date)
            .where(TushareMoneyflowIndDc.content_type == "行业")
            .order_by(
                TushareMoneyflowIndDc.name.asc(),
                func.coalesce(TushareMoneyflowIndDc.net_amount_rate, -999999999).desc(),
                func.coalesce(TushareMoneyflowIndDc.net_amount, -999999999).desc(),
                TushareMoneyflowIndDc.id.desc(),
            )
        ).scalars()
        for row in moneyflow_rows:
            if not row.name:
                continue
            raw_name = str(row.name)
            for sector_name in {raw_name, canonical_sector_name(raw_name)}:
                _add_moneyflow_snapshot(moneyflow_by_name, sector_name, row)

    rows = db.execute(
        select(DailyBar, Security)
        .join(Security, Security.symbol == DailyBar.symbol, isouter=True)
        .where(DailyBar.trade_date == latest_date)
    ).all()
    movers: list[dict[str, object]] = []
    sectors: dict[str, dict[str, object]] = {}
    for bar, security in rows:
        if bar.symbol in INDEX_DAILY_BAR_SYMBOLS:
            continue
        pre_close = float(bar.pre_close or 0)
        if pre_close <= 0:
            continue
        change_pct = float(bar.close) / pre_close - 1
        sector = (security.industry if security else None) or "未分行业"
        amount = float(bar.amount or 0)
        name = security.name if security else ""
        movers.append(
            {
                "symbol": bar.symbol,
                "name": name,
                "sector": sector,
                "change_pct": round(change_pct, 6),
                "amount": amount,
            }
        )
        bucket = sectors.setdefault(
            sector,
            {
                "sector": sector,
                "stock_count": 0,
                "up_count": 0,
                "change_sum": 0.0,
                "total_amount": 0.0,
            },
        )
        bucket["stock_count"] = int(bucket["stock_count"]) + 1
        bucket["up_count"] = int(bucket["up_count"]) + (1 if change_pct > 0 else 0)
        bucket["change_sum"] = float(bucket["change_sum"]) + change_pct
        bucket["total_amount"] = float(bucket["total_amount"]) + amount

    sector_rows = []
    for item in sectors.values():
        stock_count = int(item["stock_count"])
        if stock_count <= 0:
            continue
        sector_name = str(item["sector"])
        moneyflow = moneyflow_by_name.get(sector_name)
        source_names = (
            moneyflow.get("source_names") if moneyflow is not None else set()
        )
        source_count = len(source_names) if isinstance(source_names, set) else 0
        rate_count = int(moneyflow.get("rate_count") or 0) if moneyflow is not None else 0
        sector_rows.append(
            {
                "sector": sector_name,
                "stock_count": stock_count,
                "up_ratio": round(int(item["up_count"]) / stock_count, 6),
                "avg_change_pct": round(float(item["change_sum"]) / stock_count, 6),
                "total_amount": float(item["total_amount"]),
                "fund_flow_net_amount": (
                    float(moneyflow["amount_sum"])
                    if moneyflow is not None and int(moneyflow["amount_count"]) > 0
                    else None
                ),
                "fund_flow_rate": (
                    float(moneyflow["rate_sum"])
                    if moneyflow is not None and source_count == 1 and rate_count == 1
                    else None
                ),
                "fund_flow_trade_date": (
                    moneyflow["trade_date"].isoformat() if moneyflow is not None else ""
                ),
                "fund_flow_stale": (
                    moneyflow["trade_date"] < latest_date if moneyflow is not None else False
                ),
                "fund_flow_source_count": source_count,
                "fund_flow_source_names": sorted(source_names)
                if isinstance(source_names, set)
                else [],
            }
        )
    eligible_sectors = [
        item for item in sector_rows if int(item["stock_count"]) >= min_sector_count
    ]
    ranked_sectors = eligible_sectors or sector_rows
    return {
        "trade_date": latest_date.isoformat(),
        "sector_moneyflow_trade_date": moneyflow_date.isoformat() if moneyflow_date else "",
        "sector_moneyflow_stale": bool(moneyflow_date and moneyflow_date < latest_date),
        "sector_moneyflow_missing_count": sum(
            1 for item in sector_rows if item.get("fund_flow_trade_date") == ""
        ),
        "strong_sectors": sorted(
            ranked_sectors,
            key=lambda item: (float(item["avg_change_pct"]), float(item["total_amount"])),
            reverse=True,
        )[:limit],
        "weak_sectors": sorted(
            ranked_sectors,
            key=lambda item: (float(item["avg_change_pct"]), -float(item["total_amount"])),
        )[:limit],
        "top_gainers": sorted(
            movers,
            key=lambda item: (float(item["change_pct"]), float(item["amount"])),
            reverse=True,
        )[:limit],
        "top_losers": sorted(
            movers,
            key=lambda item: (float(item["change_pct"]), -float(item["amount"])),
        )[:limit],
    }


def insert_review_report(
    db: Session,
    report_date: str,
    report_type: str,
    content_md: str,
    metrics_json: dict | None = None,
    scope: str = "market",
    generator: str = "mechanical",
) -> int:
    parsed_date = date.fromisoformat(report_date)
    existing = db.execute(
        select(ReviewReport)
        .where(ReviewReport.report_date == parsed_date)
        .where(ReviewReport.report_type == report_type)
        .order_by(desc(ReviewReport.id))
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        existing.scope = scope
        existing.generator = generator
        existing.content_md = content_md
        existing.metrics_json = metrics_json or {}
        return 1

    db.add(
        ReviewReport(
            report_date=parsed_date,
            report_type=report_type,
            scope=scope,
            generator=generator,
            content_md=content_md,
            metrics_json=metrics_json or {},
        )
    )
    return 1


def upsert_parameter_recommendations(
    db: Session,
    report_date: str,
    suggestions: list[dict],
    source_report_type: str = "daily_mechanical",
) -> int:
    parsed_report_date = date.fromisoformat(report_date)
    changed = 0

    for item in suggestions:
        rule_id = _recommendation_rule_id(item)
        stmt = select(ParameterRecommendation).where(
            ParameterRecommendation.report_date == parsed_report_date,
            ParameterRecommendation.source_report_type == source_report_type,
            ParameterRecommendation.rule_id == rule_id,
            ParameterRecommendation.scope_type == item.get("scope_type", "rule"),
            ParameterRecommendation.scope_value == item.get("scope_value"),
            ParameterRecommendation.target_type == item["target_type"],
            ParameterRecommendation.target_name == item["target_name"],
            ParameterRecommendation.action == item["action"],
        )
        existing = db.execute(stmt).scalar_one_or_none()
        payload = {
            "rule_id": rule_id,
            "scope_type": item.get("scope_type", "rule"),
            "scope_value": item.get("scope_value"),
            "priority": item.get("priority", "medium"),
            "rationale": item.get("rationale", ""),
            "current_json": item.get("current", {}),
            "proposed_json": item.get("proposed", {}),
            "guardrails_json": {"items": item.get("guardrails", [])},
            "source_report_type": source_report_type,
        }

        if existing is None:
            db.add(
                ParameterRecommendation(
                    report_date=parsed_report_date,
                    target_type=item["target_type"],
                    target_name=item["target_name"],
                    action=item["action"],
                    status="pending",
                    **payload,
                )
            )
            changed += 1
            continue

        if existing.status != "pending":
            continue

        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = datetime.utcnow()
        changed += 1

    return changed


def list_parameter_recommendations(
    db: Session,
    *,
    status: str | None = None,
    report_date: str | None = None,
    rule_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ParameterRecommendation]:
    stmt = select(ParameterRecommendation)
    if status:
        stmt = stmt.where(ParameterRecommendation.status == status)
    if report_date:
        stmt = stmt.where(ParameterRecommendation.report_date == date.fromisoformat(report_date))
    if rule_id:
        stmt = stmt.where(ParameterRecommendation.rule_id == rule_id)
    stmt = (
        stmt.order_by(desc(ParameterRecommendation.report_date), desc(ParameterRecommendation.id))
        .offset(offset)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def count_parameter_recommendations_by_status(db: Session) -> dict[str, int]:
    stmt = select(ParameterRecommendation.status, func.count(ParameterRecommendation.id)).group_by(
        ParameterRecommendation.status
    )
    return {status: count for status, count in db.execute(stmt).all()}


def load_parameter_recommendation(
    db: Session,
    recommendation_id: int,
) -> ParameterRecommendation | None:
    stmt = select(ParameterRecommendation).where(ParameterRecommendation.id == recommendation_id)
    return db.execute(stmt).scalar_one_or_none()


def update_parameter_recommendation_decision(
    db: Session,
    recommendation_id: int,
    *,
    status: str,
    decision_reason: str | None = None,
) -> ParameterRecommendation | None:
    if status not in PARAMETER_RECOMMENDATION_STATUSES:
        raise ValueError(f"Unsupported parameter recommendation status: {status}")

    item = load_parameter_recommendation(db, recommendation_id)
    if item is None:
        return None

    item.status = status
    item.decision_reason = decision_reason
    item.updated_at = datetime.utcnow()
    return item
