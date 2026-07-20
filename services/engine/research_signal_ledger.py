from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from services.shared.models import (
    CandidateDiscoverySnapshot,
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
HISTORICAL_REPLAY_CACHE_VERSION = "candidate-v5-startup-signal"
HISTORICAL_REPLAY_CANDIDATE_LIMIT = 15
HISTORICAL_REPLAY_SNAPSHOT_LIMIT = 120
MIN_SIGNAL_DAYS_FOR_STABILITY = 10


def _plain_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _parse_iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).split("T", maxsplit=1)[0])
    except (TypeError, ValueError):
        return None


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
    symbol: str,
    signal_date: date,
    signal_price: float,
    horizon: int,
    open_dates: list[date],
    bars_by_key: dict[tuple[str, date], Any],
    daily_cutoff: date,
    current_date: date,
) -> dict[str, Any]:
    future_dates = [item for item in open_dates if item > signal_date]
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
    period_bars = [bars_by_key.get((symbol, item)) for item in period_dates]
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
    gains = [float(item.high) / signal_price - 1 for item in complete_bars]
    drawdowns = [float(item.low) / signal_price - 1 for item in complete_bars]
    return {
        **result,
        "status": "completed",
        "reason": None,
        "return_pct": round(float(complete_bars[-1].close) / signal_price - 1, 6),
        "max_gain_pct": round(max(0.0, *gains), 6),
        "max_drawdown_pct": round(min(0.0, *drawdowns), 6),
    }


def _historical_replay_breakdown(
    signals: list[dict[str, Any]],
    field: str,
    *,
    horizon: int = 3,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for signal in signals:
        result = signal["horizons"][horizon]
        if result["status"] == "completed" and result["return_pct"] is not None:
            grouped[str(signal.get(field) or "未分类")].append(float(result["return_pct"]))
    return [
        {
            "key": key,
            "sample_count": len(values),
            "minimum_sample_count": MIN_SAMPLES_FOR_POLICY,
            "eligible_for_policy": False,
            "avg_return_pct": round(fmean(values), 6),
            "win_rate": round(sum(value > 0 for value in values) / len(values), 6),
        }
        for key, values in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _historical_research_metrics(
    signals: list[dict[str, Any]],
    *,
    horizon: int,
) -> dict[str, Any]:
    completed = [
        signal
        for signal in signals
        if signal["horizons"][horizon]["status"] == "completed"
        and signal["horizons"][horizon]["return_pct"] is not None
    ]
    returns = [float(signal["horizons"][horizon]["return_pct"]) for signal in completed]
    signal_day_count = len({str(signal["signal_date"]) for signal in completed})
    return {
        "sample_count": len(completed),
        "signal_day_count": signal_day_count,
        "minimum_sample_count": MIN_SAMPLES_FOR_POLICY,
        "minimum_signal_day_count": MIN_SIGNAL_DAYS_FOR_STABILITY,
        "research_sample_sufficient": (
            len(completed) >= MIN_SAMPLES_FOR_POLICY
            and signal_day_count >= MIN_SIGNAL_DAYS_FOR_STABILITY
        ),
        "avg_return_pct": round(fmean(returns), 6) if returns else None,
        "win_rate": (
            round(sum(value > 0 for value in returns) / len(returns), 6)
            if returns
            else None
        ),
    }


def _historical_stability_cohorts(
    train_signals: list[dict[str, Any]],
    validation_signals: list[dict[str, Any]],
    *,
    fields: tuple[str, ...],
    horizon: int,
) -> list[dict[str, Any]]:
    def group(signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for signal in signals:
            key = "|".join(str(signal.get(field) or "未分类") for field in fields)
            grouped[key].append(signal)
        return grouped

    train_groups = group(train_signals)
    validation_groups = group(validation_signals)
    rows = []
    for key in sorted(set(train_groups) | set(validation_groups)):
        train = _historical_research_metrics(train_groups.get(key, []), horizon=horizon)
        validation = _historical_research_metrics(
            validation_groups.get(key, []),
            horizon=horizon,
        )
        comparable = bool(
            train["research_sample_sufficient"]
            and validation["research_sample_sufficient"]
        )
        train_return = train["avg_return_pct"]
        validation_return = validation["avg_return_pct"]
        stable_positive = bool(
            comparable
            and train_return is not None
            and validation_return is not None
            and train_return > 0
            and validation_return > 0
        )
        rows.append(
            {
                "key": key,
                "train": train,
                "validation": validation,
                "comparable": comparable,
                "stable_positive": stable_positive,
                "validation_delta_pct": (
                    round(float(validation_return) - float(train_return), 6)
                    if train_return is not None and validation_return is not None
                    else None
                ),
            }
        )
    def sort_key(item: dict[str, Any]) -> tuple[bool, bool, float, str]:
        validation_return = item["validation"]["avg_return_pct"]
        return (
            not bool(item["stable_positive"]),
            not bool(item["comparable"]),
            -float(validation_return) if validation_return is not None else float("inf"),
            str(item["key"]),
        )

    return sorted(rows, key=sort_key)


def summarize_historical_replay_stability(
    signals: list[dict[str, Any]],
    *,
    horizon: int = 3,
) -> dict[str, Any]:
    signal_dates = sorted({str(signal["signal_date"]) for signal in signals})
    if len(signal_dates) >= 2:
        split_index = max(1, min(len(signal_dates) - 1, int(len(signal_dates) * 0.7)))
    else:
        split_index = len(signal_dates)
    train_dates = set(signal_dates[:split_index])
    validation_dates = set(signal_dates[split_index:])
    train_signals = [signal for signal in signals if str(signal["signal_date"]) in train_dates]
    validation_signals = [
        signal for signal in signals if str(signal["signal_date"]) in validation_dates
    ]
    monthly_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        monthly_groups[str(signal["signal_date"])[:7]].append(signal)
    return {
        "horizon": horizon,
        "split_method": "chronological_70_30",
        "train_end_date": signal_dates[split_index - 1] if split_index else None,
        "validation_start_date": signal_dates[split_index] if validation_dates else None,
        "train": _historical_research_metrics(train_signals, horizon=horizon),
        "validation": _historical_research_metrics(validation_signals, horizon=horizon),
        "selection_modes": _historical_stability_cohorts(
            train_signals,
            validation_signals,
            fields=("selection_mode",),
            horizon=horizon,
        ),
        "market_regimes": _historical_stability_cohorts(
            train_signals,
            validation_signals,
            fields=("market_regime",),
            horizon=horizon,
        ),
        "market_states": _historical_stability_cohorts(
            train_signals,
            validation_signals,
            fields=("market_state",),
            horizon=horizon,
        ),
        "sectors": _historical_stability_cohorts(
            train_signals,
            validation_signals,
            fields=("sector",),
            horizon=horizon,
        ),
        "combinations": _historical_stability_cohorts(
            train_signals,
            validation_signals,
            fields=("selection_mode", "market_regime"),
            horizon=horizon,
        ),
        "monthly": [
            {
                "month": month,
                **_historical_research_metrics(monthly_groups[month], horizon=horizon),
            }
            for month in sorted(monthly_groups)
        ],
    }


def evaluate_historical_signal_replay(
    db: Session,
    *,
    current_time: datetime,
    snapshot_limit: int = HISTORICAL_REPLAY_SNAPSHOT_LIMIT,
    recent_signal_limit: int = 25,
) -> dict[str, Any]:
    """Evaluate cached walk-forward discoveries without writing to the real signal ledger."""
    current_time = _plain_datetime(current_time)
    available_snapshot_count = int(
        db.scalar(
            select(func.count())
            .select_from(CandidateDiscoverySnapshot)
            .where(CandidateDiscoverySnapshot.cache_version == HISTORICAL_REPLAY_CACHE_VERSION)
            .where(CandidateDiscoverySnapshot.candidate_limit == HISTORICAL_REPLAY_CANDIDATE_LIMIT)
            .where(CandidateDiscoverySnapshot.include_fundamentals.is_(False))
        )
        or 0
    )
    snapshots = list(
        db.execute(
            select(CandidateDiscoverySnapshot)
            .where(CandidateDiscoverySnapshot.cache_version == HISTORICAL_REPLAY_CACHE_VERSION)
            .where(CandidateDiscoverySnapshot.candidate_limit == HISTORICAL_REPLAY_CANDIDATE_LIMIT)
            .where(CandidateDiscoverySnapshot.include_fundamentals.is_(False))
            .order_by(CandidateDiscoverySnapshot.signal_date.desc())
            .limit(snapshot_limit)
        ).scalars()
    )
    snapshot_open_dates = (
        list(
            db.execute(
                select(TradingCalendar.trade_date)
                .where(TradingCalendar.is_open.is_(True))
                .where(
                    TradingCalendar.trade_date >= min(row.signal_date for row in snapshots),
                    TradingCalendar.trade_date <= max(row.next_trade_date for row in snapshots),
                )
                .order_by(TradingCalendar.trade_date)
            ).scalars()
        )
        if snapshots
        else []
    )
    next_open_date = dict(zip(snapshot_open_dates, snapshot_open_dates[1:], strict=False))
    exclusion_reasons: Counter[str] = Counter()
    accepted: list[tuple[CandidateDiscoverySnapshot, dict[str, Any]]] = []
    for snapshot in snapshots:
        discovery = snapshot.discovery_json
        if not isinstance(discovery, dict):
            exclusion_reasons["invalid_discovery"] += 1
            continue
        feature_date = _parse_iso_date(discovery.get("feature_date"))
        requested_feature_date = _parse_iso_date(discovery.get("requested_feature_date"))
        if next_open_date.get(snapshot.signal_date) != snapshot.next_trade_date:
            exclusion_reasons["invalid_next_trade_date"] += 1
            continue
        if feature_date != snapshot.signal_date:
            exclusion_reasons["feature_date_mismatch"] += 1
            continue
        if (
            "requested_feature_date" in discovery
            and requested_feature_date != snapshot.signal_date
        ):
            exclusion_reasons["requested_feature_date_mismatch"] += 1
            continue
        accepted.append((snapshot, discovery))

    cutoff = _daily_cutoff(current_time)
    first_signal_date = min((row.signal_date for row, _ in accepted), default=None)
    open_dates = (
        list(
            db.execute(
                select(TradingCalendar.trade_date)
                .where(TradingCalendar.is_open.is_(True))
                .where(TradingCalendar.trade_date >= first_signal_date)
                .order_by(TradingCalendar.trade_date)
            ).scalars()
        )
        if first_signal_date
        else []
    )
    candidates: list[dict[str, Any]] = []
    needed_bar_keys: set[tuple[str, date]] = set()
    for snapshot, discovery in accepted:
        future_dates = [item for item in open_dates if item > snapshot.signal_date][: max(HORIZONS)]
        seen_symbols: set[str] = set()
        for rank, item in enumerate(discovery.get("candidates") or [], start=1):
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip()
            selection_mode = str(item.get("selection_mode") or "").strip()
            if not symbol or not selection_mode or symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            candidate = {
                "source_type": "historical_replay",
                "signal_date": snapshot.signal_date,
                "symbol": symbol,
                "name": str(item.get("name") or "").strip() or None,
                "sector": str(item.get("sector") or "").strip() or None,
                "selection_mode": selection_mode,
                "score": float(item.get("score") or 0.0),
                "rank": rank,
                "market_regime": str(discovery.get("market_regime") or "unknown"),
                "market_state": (
                    str(discovery["market_turn"].get("key") or "unknown")
                    if isinstance(discovery.get("market_turn"), dict)
                    else "unknown"
                ),
            }
            candidates.append(candidate)
            needed_bar_keys.add((symbol, snapshot.signal_date))
            needed_bar_keys.update(
                (symbol, item_date) for item_date in future_dates if item_date <= cutoff
            )

    bars_by_key: dict[tuple[str, date], Any] = {}
    symbols_by_date: dict[date, set[str]] = defaultdict(set)
    for symbol, trade_date in needed_bar_keys:
        symbols_by_date[trade_date].add(symbol)
    bar_dates = sorted(symbols_by_date)
    for start in range(0, len(bar_dates), 100):
        date_batch = bar_dates[start : start + 100]
        bar_rows = db.execute(
            select(
                DailyBar.symbol,
                DailyBar.trade_date,
                DailyBar.high,
                DailyBar.low,
                DailyBar.close,
                DailyBar.is_suspended,
            )
            .where(
                or_(
                    *(
                        and_(
                            DailyBar.trade_date == trade_date,
                            DailyBar.symbol.in_(symbols_by_date[trade_date]),
                        )
                        for trade_date in date_batch
                    )
                )
            )
            .execution_options(stream_results=True, yield_per=2000)
        )
        bars_by_key.update(
            {(bar.symbol, bar.trade_date): bar for bar in bar_rows}
        )

    candidate_exclusion_reasons: Counter[str] = Counter()
    signals: list[dict[str, Any]] = []
    for candidate in candidates:
        signal_date = candidate["signal_date"]
        if signal_date > cutoff:
            candidate_exclusion_reasons["unclosed_signal_date"] += 1
            continue
        signal_bar = bars_by_key.get((candidate["symbol"], signal_date))
        if signal_bar is None or not signal_bar.close or float(signal_bar.close) <= 0:
            candidate_exclusion_reasons["missing_signal_close"] += 1
            continue
        if signal_bar.is_suspended:
            candidate_exclusion_reasons["suspended_signal_date"] += 1
            continue
        signal_price = float(signal_bar.close)
        signals.append(
            {
                **candidate,
                "signal_date": signal_date.isoformat(),
                "signal_price": signal_price,
                "horizons": {
                    horizon: _horizon_result(
                        symbol=candidate["symbol"],
                        signal_date=signal_date,
                        signal_price=signal_price,
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
    research_sample_sufficient = bool(summary[3]["eligible_for_policy"])
    for item in summary.values():
        item["eligible_for_policy"] = False
    accepted_dates = sorted({row.signal_date for row, _ in accepted})
    covered_month_count = len({item.strftime("%Y-%m") for item in accepted_dates})
    return {
        "source_type": "historical_replay",
        "cache_version": HISTORICAL_REPLAY_CACHE_VERSION,
        "policy_eligible": False,
        "research_sample_sufficient": research_sample_sufficient,
        "policy_label": (
            "历史回放达到研究门槛，仍禁止替代真实信号结论"
            if research_sample_sufficient
            else "历史回放样本不足，仅用于研究参考"
        ),
        "available_snapshot_count": available_snapshot_count,
        "source_snapshot_count": len(snapshots),
        "evaluated_snapshot_count": len(accepted),
        "excluded_snapshot_count": len(snapshots) - len(accepted),
        "exclusion_reasons": dict(exclusion_reasons),
        "candidate_exclusion_reasons": dict(candidate_exclusion_reasons),
        "signal_count": len(signals),
        "start_date": accepted_dates[0].isoformat() if accepted_dates else None,
        "end_date": accepted_dates[-1].isoformat() if accepted_dates else None,
        "covered_month_count": covered_month_count,
        "minimum_sample_count": MIN_SAMPLES_FOR_POLICY,
        "horizons": summary,
        "breakdown_horizon": 3,
        "selection_modes": _historical_replay_breakdown(signals, "selection_mode"),
        "market_regimes": _historical_replay_breakdown(signals, "market_regime"),
        "market_states": _historical_replay_breakdown(signals, "market_state"),
        "sectors": _historical_replay_breakdown(signals, "sector"),
        "stability": summarize_historical_replay_stability(signals),
        "recent_signals": sorted(
            signals,
            key=lambda item: (item["signal_date"], -int(item["rank"])),
            reverse=True,
        )[:recent_signal_limit],
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


def _execution_group_key(signal: dict[str, Any]) -> str | None:
    status = str((signal.get("execution") or {}).get("status") or "")
    if status in {"open", "closed"}:
        return "executed"
    return status if status in {"not_entered", "research_only"} else None


def _execution_outcomes(signals: list[dict[str, Any]]) -> dict[str, dict[int, dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "executed": [],
        "not_entered": [],
        "research_only": [],
    }
    for signal in signals:
        key = _execution_group_key(signal)
        if key:
            grouped[key].append(signal)
    return {key: _summary(items) for key, items in grouped.items()}


def _execution_cohorts(signals: list[dict[str, Any]], horizon: int = 3) -> list[dict[str, Any]]:
    cohorts: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        cohorts[
            (
                str(signal.get("signal_type") or "unknown"),
                str(signal.get("market_regime") or "unknown"),
            )
        ].append(signal)
    rows = []
    for (signal_type, market_regime), cohort_signals in cohorts.items():
        grouped = {key: [] for key in ("executed", "not_entered", "research_only")}
        for signal in cohort_signals:
            key = _execution_group_key(signal)
            if key:
                grouped[key].append(signal)
        summaries = {key: _summary(items)[horizon] for key, items in grouped.items()}
        eligible_group_count = sum(
            bool(summary["eligible_for_policy"]) for summary in summaries.values()
        )
        rows.append(
            {
                "signal_type": signal_type,
                "market_regime": market_regime,
                "horizon": horizon,
                "signal_count": len(cohort_signals),
                "eligible_group_count": eligible_group_count,
                "comparable": eligible_group_count >= 2,
                "fully_comparable": eligible_group_count == len(summaries),
                "groups": summaries,
            }
        )
    return sorted(rows, key=lambda item: (-int(item["signal_count"]), item["signal_type"]))


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
            "execution_cohorts": [],
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
                        symbol=row.symbol,
                        signal_date=row.signal_date,
                        signal_price=row.signal_price,
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
        "execution_cohorts": _execution_cohorts(signals),
        "signals": signals,
    }
