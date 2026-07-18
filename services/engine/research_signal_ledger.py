from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import (
    DailyBar,
    PaperOrder,
    PaperPosition,
    ResearchSignalLedger,
    TradePlan,
    TradingCalendar,
)

HORIZONS = (1, 3, 5, 10)
MIN_SAMPLES_FOR_POLICY = 30
STARTUP_STAGES = {"starting", "accelerating"}


def _plain_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def record_research_signals(db: Session, signals: list[dict[str, Any]]) -> int:
    """Persist first-observed signal evidence; retries must never rewrite it."""
    created = 0
    for item in signals:
        source = str(item.get("source") or "").strip()
        signal_type = str(item.get("signal_type") or "").strip()
        symbol = str(item.get("symbol") or "").strip()
        signal_time = item.get("signal_time")
        signal_price = item.get("signal_price")
        if (
            not source
            or not signal_type
            or not symbol
            or not isinstance(signal_time, datetime)
            or signal_price is None
            or float(signal_price) <= 0
        ):
            continue
        signal_time = _plain_datetime(signal_time)
        identity = (
            ResearchSignalLedger.source == source,
            ResearchSignalLedger.signal_type == signal_type,
            ResearchSignalLedger.signal_time == signal_time,
            ResearchSignalLedger.symbol == symbol,
        )
        if db.execute(select(ResearchSignalLedger.id).where(*identity)).scalar_one_or_none():
            continue
        db.add(
            ResearchSignalLedger(
                source=source,
                signal_type=signal_type,
                signal_time=signal_time,
                signal_date=signal_time.date(),
                symbol=symbol,
                name=str(item["name"]).strip() if item.get("name") else None,
                sector=str(item["sector"]).strip() if item.get("sector") else None,
                signal_price=float(signal_price),
                market_regime=(
                    str(item["market_regime"]).strip() if item.get("market_regime") else None
                ),
                market_state=(
                    str(item["market_state"]).strip() if item.get("market_state") else None
                ),
                executable=bool(item.get("executable")),
                evidence_json=dict(item.get("evidence") or {}),
            )
        )
        created += 1
    if created:
        db.flush()
    return created


def build_intraday_market_turn_signals(
    *,
    snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    signal_time: datetime,
    market_regime: str | None,
) -> list[dict[str, Any]]:
    """Map a persisted market-turn snapshot to research-only ledger entries."""
    signals: list[dict[str, Any]] = []
    market_state = str(snapshot.get("key") or "unknown")
    for candidate in candidates:
        startup_stage = str(candidate.get("startup_stage") or "")
        price = candidate.get("price")
        symbol = str(candidate.get("symbol") or "").strip()
        if startup_stage not in STARTUP_STAGES or not symbol or not price or float(price) <= 0:
            continue
        signals.append(
            {
                "source": "intraday_market_turn",
                "signal_type": f"startup_{startup_stage}",
                "signal_time": signal_time,
                "symbol": symbol,
                "name": candidate.get("name"),
                "sector": candidate.get("sector"),
                "signal_price": float(price),
                "market_regime": market_regime,
                "market_state": market_state,
                "executable": False,
                "evidence": {
                    "startup_score": candidate.get("startup_score"),
                    "startup_label": candidate.get("startup_label"),
                    "selection_tier": candidate.get("selection_tier"),
                    "selection_reason": candidate.get("selection_reason"),
                    "intraday_state": candidate.get("intraday_state"),
                    "sector_signal": candidate.get("sector_signal"),
                },
            }
        )
    cross_day = snapshot.get("cross_day_mainline")
    if not isinstance(cross_day, dict) or cross_day.get("status") != "观察确认":
        return signals
    checkpoint = str(cross_day.get("checkpoint") or "")
    signal_type = "watch_mainline" if checkpoint == "9:45观察" else "confirmed_mainline"
    if checkpoint not in {"9:45观察", "10:30复核"}:
        return signals
    for sector_row in cross_day.get("sectors") or []:
        if not isinstance(sector_row, dict) or sector_row.get("status") != "观察确认":
            continue
        symbol = str(
            sector_row.get("current_leader_symbol") or sector_row.get("leader_symbol") or ""
        ).strip()
        if not symbol:
            continue
        price = sector_row.get("current_leader_price") or sector_row.get("leader_price")
        if not price or float(price) <= 0:
            # A sector signal is still useful research evidence, but cannot be outcome-scored
            # without the observed leader price and therefore is not written to the ledger.
            continue
        signals.append(
            {
                "source": "intraday_market_turn",
                "signal_type": signal_type,
                "signal_time": signal_time,
                "symbol": symbol,
                "sector": sector_row.get("sector"),
                "signal_price": float(price),
                "market_regime": market_regime,
                "market_state": market_state,
                "executable": False,
                "evidence": {"checkpoint": checkpoint, "sector": sector_row},
            }
        )
    return signals


def build_daily_candidate_signals(
    *,
    discovery: dict[str, Any],
    candidates: list[dict[str, Any]],
    signal_time: datetime,
    prices_by_symbol: dict[str, float],
) -> list[dict[str, Any]]:
    """Capture an after-close candidate batch only when it uses that day's features."""
    feature_date = str(discovery.get("feature_date") or "")
    requested_feature_date = str(discovery.get("requested_feature_date") or "")
    signal_date = _plain_datetime(signal_time).date().isoformat()
    if feature_date != signal_date or requested_feature_date != signal_date:
        return []
    market_turn = discovery.get("market_turn")
    market_state = (
        str(market_turn.get("key") or "unknown") if isinstance(market_turn, dict) else "unknown"
    )
    market_regime = str(discovery.get("market_regime") or "unknown")
    signals: list[dict[str, Any]] = []
    for rank, candidate in enumerate(candidates, start=1):
        symbol = str(candidate.get("symbol") or "").strip()
        selection_mode = str(candidate.get("selection_mode") or "").strip()
        price = prices_by_symbol.get(symbol)
        if not symbol or not selection_mode or price is None or price <= 0:
            continue
        signals.append(
            {
                "source": "daily_candidate_discovery",
                "signal_type": f"daily_{selection_mode}",
                "signal_time": signal_time,
                "symbol": symbol,
                "name": candidate.get("name"),
                "sector": candidate.get("sector"),
                "signal_price": price,
                "market_regime": market_regime,
                "market_state": market_state,
                "executable": False,
                "evidence": {
                    "candidate_rank": rank,
                    "candidate_score": candidate.get("score"),
                    "selected_rule_id": candidate.get("selected_rule_id"),
                    "selected_rule_name": candidate.get("selected_rule_name"),
                    "selected_strategy_type": candidate.get("selected_strategy_type"),
                    "startup_signal_score": candidate.get("startup_signal_score"),
                    "startup_signal_label": candidate.get("startup_signal_label"),
                    "reasons": list(candidate.get("reasons") or []),
                    "risk_flags": list(candidate.get("risk_flags") or []),
                    "next_trade_date": discovery.get("next_trade_date"),
                },
            }
        )
    return signals


def _daily_cutoff(current_time: datetime) -> date:
    if (current_time.hour, current_time.minute) >= (15, 5):
        return current_time.date()
    return current_time.date() - timedelta(days=1)


def _horizon_result(
    *,
    row: ResearchSignalLedger,
    horizon: int,
    open_dates: list[date],
    bars_by_key: dict[tuple[str, date], DailyBar],
    daily_cutoff: date,
    current_date: date,
) -> dict[str, Any]:
    future_dates = [item for item in open_dates if item > row.signal_date]
    target_date = future_dates[horizon - 1] if len(future_dates) >= horizon else None
    result: dict[str, Any] = {
        "horizon": horizon,
        "status": "waiting",
        "target_trade_date": target_date.isoformat() if target_date else None,
        "return_pct": None,
        "max_gain_pct": None,
        "max_drawdown_pct": None,
        "reason": "awaiting_trade_day",
    }
    if target_date is None:
        return result
    if target_date > daily_cutoff:
        return {
            **result,
            "reason": (
                "awaiting_closed_daily_bar"
                if target_date <= current_date
                else "awaiting_trade_day"
            ),
        }
    period_dates = future_dates[:horizon]
    period_bars = [bars_by_key.get((row.symbol, item)) for item in period_dates]
    if any(item is None for item in period_bars):
        return {**result, "status": "unavailable", "reason": "missing_daily_bar"}
    if any(item.is_suspended for item in period_bars if item is not None):
        return {**result, "status": "unavailable", "reason": "suspended"}
    if any(
        not item.close or not item.high or not item.low
        for item in period_bars
        if item is not None
    ):
        return {**result, "status": "unavailable", "reason": "incomplete_ohlc"}
    complete_bars = [item for item in period_bars if item is not None]
    gains = [float(item.high) / row.signal_price - 1 for item in complete_bars]
    drawdowns = [float(item.low) / row.signal_price - 1 for item in complete_bars]
    return {
        **result,
        "status": "completed",
        "reason": None,
        "return_pct": round(float(complete_bars[-1].close) / row.signal_price - 1, 6),
        "max_gain_pct": round(max(0.0, *gains), 6),
        "max_drawdown_pct": round(min(0.0, *drawdowns), 6),
    }


def _summary(signals: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    summary: dict[int, dict[str, Any]] = {}
    for horizon in HORIZONS:
        results = [item["horizons"][horizon] for item in signals]
        completed = [item for item in results if item["status"] == "completed"]
        returns = [float(item["return_pct"]) for item in completed]
        summary[horizon] = {
            "horizon": horizon,
            "sample_count": len(completed),
            "signal_count": len(results),
            "completed_count": len(completed),
            "waiting_count": sum(item["status"] == "waiting" for item in results),
            "unavailable_count": sum(item["status"] == "unavailable" for item in results),
            "waiting_reasons": dict(
                Counter(item["reason"] for item in results if item["status"] == "waiting")
            ),
            "unavailable_reasons": dict(
                Counter(item["reason"] for item in results if item["status"] == "unavailable")
            ),
            "minimum_sample_count": MIN_SAMPLES_FOR_POLICY,
            "eligible_for_policy": len(completed) >= MIN_SAMPLES_FOR_POLICY,
            "avg_return_pct": round(fmean(returns), 6) if returns else None,
            "win_rate": (
                round(sum(value > 0 for value in returns) / len(returns), 6)
                if returns
                else None
            ),
            "avg_max_gain_pct": (
                round(fmean(float(item["max_gain_pct"]) for item in completed), 6)
                if completed
                else None
            ),
            "avg_max_drawdown_pct": (
                round(fmean(float(item["max_drawdown_pct"]) for item in completed), 6)
                if completed
                else None
            ),
        }
    return summary


def _breakdowns(signals: list[dict[str, Any]], horizon: int = 3) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[str, list[float]]] = {
        "signal_types": defaultdict(list),
        "market_regimes": defaultdict(list),
        "market_states": defaultdict(list),
        "sectors": defaultdict(list),
    }
    keys = {
        "signal_types": "signal_type",
        "market_regimes": "market_regime",
        "market_states": "market_state",
        "sectors": "sector",
    }
    for signal in signals:
        result = signal["horizons"][horizon]
        if result["status"] != "completed" or result["return_pct"] is None:
            continue
        for group_name, field in keys.items():
            key = str(signal.get(field) or "未分类")
            grouped[group_name][key].append(float(result["return_pct"]))
    return {
        group_name: [
            {
                "key": key,
                "sample_count": len(values),
                "minimum_sample_count": MIN_SAMPLES_FOR_POLICY,
                "eligible_for_policy": len(values) >= MIN_SAMPLES_FOR_POLICY,
                "avg_return_pct": round(fmean(values), 6),
                "win_rate": round(sum(value > 0 for value in values) / len(values), 6),
            }
            for key, values in sorted(rows.items(), key=lambda item: (-len(item[1]), item[0]))
        ]
        for group_name, rows in grouped.items()
    }


def _execution_report(
    db: Session,
    rows: list[ResearchSignalLedger],
    *,
    current_time: datetime,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    signal_dates = {row.signal_date for row in rows}
    symbols = {row.symbol for row in rows}
    plans = list(
        db.execute(
            select(TradePlan)
            .where(TradePlan.plan_date.in_(signal_dates))
            .where(TradePlan.symbol.in_(symbols))
            .order_by(TradePlan.id)
        ).scalars()
    )
    plans_by_key: dict[tuple[date, str], list[TradePlan]] = defaultdict(list)
    for plan in plans:
        plans_by_key[(plan.plan_date, plan.symbol)].append(plan)
    plan_ids = {plan.id for plan in plans}
    positions = (
        list(
            db.execute(
                select(PaperPosition)
                .where(PaperPosition.trade_plan_id.in_(plan_ids))
                .order_by(PaperPosition.id.desc())
            ).scalars()
        )
        if plan_ids
        else []
    )
    orders = (
        list(
            db.execute(
                select(PaperOrder)
                .where(PaperOrder.trade_plan_id.in_(plan_ids))
                .where(PaperOrder.side == "buy")
                .order_by(PaperOrder.id.desc())
            ).scalars()
        )
        if plan_ids
        else []
    )
    position_by_plan = {
        position.trade_plan_id: position
        for position in reversed(positions)
        if position.trade_plan_id is not None
    }
    order_by_plan = {
        order.trade_plan_id: order
        for order in reversed(orders)
        if order.trade_plan_id is not None
    }
    executions: dict[int, dict[str, Any]] = {}
    for row in rows:
        is_formal_daily = row.signal_type == "daily_formal_strategy"
        matching_plans = plans_by_key.get((row.signal_date, row.symbol), [])
        selected_rule = str((row.evidence_json or {}).get("selected_rule_id") or "")
        plan = next(
            (item for item in matching_plans if item.rule_id == selected_rule),
            matching_plans[0] if matching_plans else None,
        )
        if not is_formal_daily or plan is None:
            executions[row.id] = {
                "status": "research_only",
                "plan_id": plan.id if plan else None,
                "trade_date": plan.trade_date.isoformat() if plan else None,
                "position_id": None,
                "entry_date": None,
                "entry_price": None,
                "entry_slippage_pct": None,
                "exit_date": None,
                "pnl_pct": None,
                "max_gain_pct": None,
                "max_drawdown_pct": None,
                "exit_reason": None,
                "order_reason": None,
            }
            continue
        position = position_by_plan.get(plan.id)
        order = order_by_plan.get(plan.id)
        if position is None:
            awaiting_entry = plan.trade_date > current_time.date() or (
                plan.trade_date == current_time.date()
                and (current_time.hour, current_time.minute) < (15, 5)
            )
            executions[row.id] = {
                "status": "waiting_entry" if awaiting_entry else "not_entered",
                "plan_id": plan.id,
                "trade_date": plan.trade_date.isoformat(),
                "position_id": None,
                "entry_date": None,
                "entry_price": None,
                "entry_slippage_pct": None,
                "exit_date": None,
                "pnl_pct": None,
                "max_gain_pct": None,
                "max_drawdown_pct": None,
                "exit_reason": None,
                "order_reason": order.reason if order else None,
            }
            continue
        entry_price = float(position.entry_price)
        executions[row.id] = {
            "status": "closed" if position.status == "closed" else "open",
            "plan_id": plan.id,
            "trade_date": plan.trade_date.isoformat(),
            "position_id": position.id,
            "entry_date": position.entry_date.isoformat(),
            "entry_price": entry_price,
            "entry_slippage_pct": round(entry_price / row.signal_price - 1, 6),
            "exit_date": position.exit_date.isoformat() if position.exit_date else None,
            "pnl_pct": float(position.pnl_pct) if position.pnl_pct is not None else None,
            "max_gain_pct": round(float(position.highest_price) / entry_price - 1, 6),
            "max_drawdown_pct": round(float(position.lowest_price) / entry_price - 1, 6),
            "exit_reason": position.exit_reason,
            "order_reason": order.reason if order else None,
        }
    values = list(executions.values())
    entered = [item for item in values if item["entry_slippage_pct"] is not None]
    closed = [item for item in values if item["status"] == "closed" and item["pnl_pct"] is not None]
    return executions, {
        "research_only_count": sum(item["status"] == "research_only" for item in values),
        "planned_count": sum(item["plan_id"] is not None for item in values),
        "waiting_entry_count": sum(item["status"] == "waiting_entry" for item in values),
        "not_entered_count": sum(item["status"] == "not_entered" for item in values),
        "open_count": sum(item["status"] == "open" for item in values),
        "closed_count": len(closed),
        "avg_entry_slippage_pct": (
            round(fmean(float(item["entry_slippage_pct"]) for item in entered), 6)
            if entered
            else None
        ),
        "closed_avg_pnl_pct": (
            round(fmean(float(item["pnl_pct"]) for item in closed), 6) if closed else None
        ),
        "closed_win_rate": (
            round(sum(float(item["pnl_pct"]) > 0 for item in closed) / len(closed), 6)
            if closed
            else None
        ),
    }


def _execution_outcomes(signals: list[dict[str, Any]]) -> dict[str, dict[int, dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "executed": [],
        "not_entered": [],
        "research_only": [],
    }
    for signal in signals:
        status = str((signal.get("execution") or {}).get("status") or "")
        if status in {"open", "closed"}:
            grouped["executed"].append(signal)
        elif status in grouped:
            grouped[status].append(signal)
    return {key: _summary(items) for key, items in grouped.items()}
def evaluate_research_signal_ledger(
    db: Session,
    *,
    current_time: datetime,
    limit: int = 500,
) -> dict[str, Any]:
    current_time = _plain_datetime(current_time)
    rows = list(
        db.execute(
            select(ResearchSignalLedger)
            .order_by(ResearchSignalLedger.signal_time.desc(), ResearchSignalLedger.id.desc())
            .limit(limit)
        ).scalars()
    )
    if not rows:
        empty_summary = _summary([])
        return {
            "signal_count": 0,
            "minimum_sample_count": MIN_SAMPLES_FOR_POLICY,
            "policy_status": "insufficient",
            "policy_label": "暂无真实信号，禁止调整策略",
            "horizons": empty_summary,
            "breakdown_horizon": 3,
            "signal_types": [],
            "market_regimes": [],
            "market_states": [],
            "sectors": [],
            "execution_funnel": {
                "research_only_count": 0,
                "planned_count": 0,
                "waiting_entry_count": 0,
                "not_entered_count": 0,
                "open_count": 0,
                "closed_count": 0,
                "avg_entry_slippage_pct": None,
                "closed_avg_pnl_pct": None,
                "closed_win_rate": None,
            },
            "execution_outcomes": _execution_outcomes([]),
            "signals": [],
        }
    first_signal_date = min(item.signal_date for item in rows)
    open_dates = list(
        db.execute(
            select(TradingCalendar.trade_date)
            .where(TradingCalendar.is_open.is_(True))
            .where(TradingCalendar.trade_date >= first_signal_date)
            .order_by(TradingCalendar.trade_date)
        ).scalars()
    )
    cutoff = _daily_cutoff(current_time)
    symbols = {item.symbol for item in rows}
    bars_by_key = {
        (item.symbol, item.trade_date): item
        for item in db.execute(
            select(DailyBar)
            .where(DailyBar.symbol.in_(symbols))
            .where(DailyBar.trade_date >= first_signal_date)
            .where(DailyBar.trade_date <= cutoff)
        ).scalars()
    }
    executions, execution_funnel = _execution_report(db, rows, current_time=current_time)
    signals = []
    for row in rows:
        signals.append(
            {
                "id": row.id,
                "source": row.source,
                "signal_type": row.signal_type,
                "signal_time": row.signal_time.isoformat(),
                "signal_date": row.signal_date.isoformat(),
                "symbol": row.symbol,
                "name": row.name,
                "sector": row.sector,
                "signal_price": row.signal_price,
                "market_regime": row.market_regime,
                "market_state": row.market_state,
                "executable": row.executable,
                "evidence": row.evidence_json or {},
                "execution": executions[row.id],
                "horizons": {
                    horizon: _horizon_result(
                        row=row,
                        horizon=horizon,
                        open_dates=open_dates,
                        bars_by_key=bars_by_key,
                        daily_cutoff=cutoff,
                        current_date=current_time.date(),
                    )
                    for horizon in HORIZONS
                },
            }
        )
    summary = _summary(signals)
    breakdowns = _breakdowns(signals)
    policy_usable = bool(summary[3]["eligible_for_policy"])
    return {
        "signal_count": len(signals),
        "minimum_sample_count": MIN_SAMPLES_FOR_POLICY,
        "policy_status": "usable" if policy_usable else "insufficient",
        "policy_label": "样本可用，仅供策略研究" if policy_usable else "样本不足，禁止调整策略",
        "horizons": summary,
        "breakdown_horizon": 3,
        **breakdowns,
        "execution_funnel": execution_funnel,
        "execution_outcomes": _execution_outcomes(signals),
        "signals": signals,
    }
