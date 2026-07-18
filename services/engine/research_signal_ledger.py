from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import DailyBar, ResearchSignalLedger, TradingCalendar

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
        "signals": signals,
    }
