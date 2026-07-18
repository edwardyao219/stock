from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, datetime
from statistics import fmean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.shared.models import (
    DailyBar,
    IntradayMarketTurnSnapshot,
    MarketRegimeDaily,
    TradingCalendar,
)

HORIZONS = (1, 3, 5)
STARTUP_STAGES = {"starting", "accelerating"}


def _plain_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _first_startup_signals(snapshot_days: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    seen: set[tuple[date, str]] = set()
    snapshots = sorted(
        (snapshot for day in snapshot_days for snapshot in day),
        key=lambda item: str(item.get("as_of") or ""),
    )
    for snapshot in snapshots:
        raw_time = str(snapshot.get("as_of") or "")
        if not raw_time:
            continue
        signal_time = datetime.fromisoformat(raw_time)
        signal_date = signal_time.date()
        for candidate in snapshot.get("candidates") or []:
            startup_stage = str(candidate.get("startup_stage") or "")
            symbol = str(candidate.get("symbol") or "")
            price = float(candidate.get("price") or 0)
            key = (signal_date, symbol)
            if startup_stage not in STARTUP_STAGES or not symbol or price <= 0 or key in seen:
                continue
            seen.add(key)
            signals.append(
                {
                    "signal_date": signal_date,
                    "signal_time": signal_time,
                    "signal_stage": str(snapshot.get("stage") or "latest"),
                    "signal_stage_label": str(snapshot.get("stage_label") or "最新快照"),
                    "symbol": symbol,
                    "name": candidate.get("name"),
                    "sector": candidate.get("sector"),
                    "startup_stage": startup_stage,
                    "startup_label": str(candidate.get("startup_label") or startup_stage),
                    "startup_score": float(candidate.get("startup_score") or 0),
                    "signal_price": price,
                }
            )
    return signals


def _market_context(
    snapshots: list[IntradayMarketTurnSnapshot],
    signal_time: datetime,
) -> dict[str, Any]:
    signal_clock = _plain_datetime(signal_time)
    eligible = [item for item in snapshots if item.snapshot_time <= signal_clock]
    snapshot = max(eligible, key=lambda item: item.snapshot_time) if eligible else None
    breadth = float(snapshot.breadth_ratio) if snapshot is not None else None
    index_change = (
        float(snapshot.index_change_pct)
        if snapshot is not None and snapshot.index_change_pct is not None
        else None
    )
    if (breadth is not None and breadth <= 0.25) or (
        index_change is not None and index_change <= -0.015
    ):
        key, label = "systemic_risk", "系统性风险"
    elif (breadth is not None and breadth <= 0.4) or (
        index_change is not None and index_change <= -0.008
    ):
        key, label = "weak_market", "弱市"
    elif snapshot is not None:
        key, label = "normal_market", "常态市场"
    else:
        key, label = "unknown", "环境待确认"
    return {
        "market_context": key,
        "market_context_label": label,
        "market_breadth_ratio": breadth,
        "market_index_change_pct": index_change,
    }


def _horizon_result(
    *,
    signal: dict[str, Any],
    horizon: int,
    open_dates: list[date],
    bars_by_key: dict[tuple[str, date], DailyBar],
    latest_daily_date: date | None,
) -> dict[str, Any]:
    first_target_index = bisect_right(open_dates, signal["signal_date"])
    target_index = first_target_index + horizon - 1
    target_date = open_dates[target_index] if target_index < len(open_dates) else None
    result = {
        "horizon": horizon,
        "status": "waiting",
        "target_trade_date": target_date.isoformat() if target_date else None,
        "return_pct": None,
        "max_gain_pct": None,
        "max_drawdown_pct": None,
    }
    if target_date is None or latest_daily_date is None or target_date > latest_daily_date:
        return result

    period_dates = open_dates[first_target_index : target_index + 1]
    period_bars = [bars_by_key.get((signal["symbol"], item)) for item in period_dates]
    if any(
        item is None or item.is_suspended or not item.close or not item.high or not item.low
        for item in period_bars
    ):
        result["status"] = "unavailable"
        return result

    complete_bars = [item for item in period_bars if item is not None]
    target_bar = complete_bars[-1]
    signal_price = float(signal["signal_price"])
    gains = [float(item.high) / signal_price - 1 for item in complete_bars]
    drawdowns = [float(item.low) / signal_price - 1 for item in complete_bars]
    result.update(
        {
            "status": "completed",
            "return_pct": round(float(target_bar.close) / signal_price - 1, 6),
            "max_gain_pct": round(max(0.0, *gains), 6),
            "max_drawdown_pct": round(min(0.0, *drawdowns), 6),
        }
    )
    return result


def _summary(outcomes: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    summary: dict[int, dict[str, Any]] = {}
    for horizon in HORIZONS:
        completed = [
            item["horizons"][horizon]
            for item in outcomes
            if item["horizons"][horizon]["status"] == "completed"
        ]
        returns = [float(item["return_pct"]) for item in completed]
        summary[horizon] = {
            "sample_count": len(completed),
            "win_rate": round(sum(value > 0 for value in returns) / len(returns), 4)
            if returns
            else None,
            "avg_return_pct": round(fmean(returns), 6) if returns else None,
            "avg_max_gain_pct": round(
                fmean(float(item["max_gain_pct"]) for item in completed),
                6,
            )
            if completed
            else None,
            "avg_max_drawdown_pct": round(
                fmean(float(item["max_drawdown_pct"]) for item in completed),
                6,
            )
            if completed
            else None,
        }
    return summary


def _regime_transition_summary(outcomes: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    summary: dict[int, list[dict[str, Any]]] = {}
    for horizon in HORIZONS:
        returns_by_transition: dict[str, list[float]] = {}
        for outcome in outcomes:
            transition = outcome.get("regime_transition")
            result = outcome["horizons"][horizon]
            if not transition or result["status"] != "completed":
                continue
            returns_by_transition.setdefault(str(transition), []).append(
                float(result["return_pct"])
            )
        summary[horizon] = [
            {
                "regime_transition": transition,
                "sample_count": len(returns),
                "win_rate": round(sum(value > 0 for value in returns) / len(returns), 4),
                "avg_return_pct": round(fmean(returns), 6),
                "is_sufficient_samples": len(returns) >= 3,
            }
            for transition, returns in sorted(
                returns_by_transition.items(), key=lambda item: (-len(item[1]), item[0])
            )
        ]
    return summary


def build_intraday_startup_outcomes(
    db: Session,
    snapshot_days: list[list[dict[str, Any]]],
    *,
    current_time: datetime,
) -> dict[str, Any]:
    signals = _first_startup_signals(snapshot_days)
    if not signals:
        return {
            "signal_count": 0,
            "completed_count": 0,
            "waiting_count": 0,
            "unavailable_count": 0,
            "context_counts": {},
            "summary": _summary([]),
            "regime_transition_summary": _regime_transition_summary([]),
            "outcomes": [],
        }

    signal_dates = {item["signal_date"] for item in signals}
    symbols = {item["symbol"] for item in signals}
    first_signal_date = min(signal_dates)
    open_dates = list(
        db.execute(
            select(TradingCalendar.trade_date)
            .where(TradingCalendar.is_open.is_(True))
            .where(TradingCalendar.trade_date >= first_signal_date)
            .order_by(TradingCalendar.trade_date)
        ).scalars()
    )
    daily_cutoff = (
        DailyBar.trade_date <= current_time.date()
        if (current_time.hour, current_time.minute) >= (15, 5)
        else DailyBar.trade_date < current_time.date()
    )
    daily_bars = list(
        db.execute(
            select(DailyBar)
            .where(DailyBar.symbol.in_(symbols))
            .where(DailyBar.trade_date >= first_signal_date)
            .where(daily_cutoff)
        ).scalars()
    )
    bars_by_key = {(item.symbol, item.trade_date): item for item in daily_bars}
    latest_daily_date = db.execute(
        select(func.max(DailyBar.trade_date)).where(daily_cutoff)
    ).scalar_one_or_none()
    market_snapshots = list(
        db.execute(
            select(IntradayMarketTurnSnapshot)
            .where(IntradayMarketTurnSnapshot.trade_date.in_(signal_dates))
            .order_by(IntradayMarketTurnSnapshot.snapshot_time)
        ).scalars()
    )
    market_by_date: dict[date, list[IntradayMarketTurnSnapshot]] = {}
    for item in market_snapshots:
        market_by_date.setdefault(item.trade_date, []).append(item)
    calendar_dates = list(
        db.execute(
            select(TradingCalendar.trade_date)
            .where(TradingCalendar.is_open.is_(True))
            .where(TradingCalendar.trade_date <= max(signal_dates))
            .order_by(TradingCalendar.trade_date)
        ).scalars()
    )
    previous_trade_dates = {}
    for signal_date in signal_dates:
        index = bisect_left(calendar_dates, signal_date)
        previous_trade_dates[signal_date] = calendar_dates[index - 1] if index else None
    regime_dates = signal_dates | {
        trade_date for trade_date in previous_trade_dates.values() if trade_date is not None
    }
    regimes_by_date = {
        item.trade_date: item.regime
        for item in db.execute(
            select(MarketRegimeDaily).where(MarketRegimeDaily.trade_date.in_(regime_dates))
        ).scalars()
    }

    outcomes: list[dict[str, Any]] = []
    for signal in signals:
        market_regime = regimes_by_date.get(signal["signal_date"])
        previous_market_regime = regimes_by_date.get(previous_trade_dates[signal["signal_date"]])
        outcome = {
            **{key: value for key, value in signal.items() if key != "signal_date"},
            "signal_date": signal["signal_date"].isoformat(),
            "signal_time": signal["signal_time"].isoformat(),
            **_market_context(
                market_by_date.get(signal["signal_date"], []),
                signal["signal_time"],
            ),
            "market_regime": market_regime,
            "previous_market_regime": previous_market_regime,
            "regime_transition": (
                f"{previous_market_regime} -> {market_regime}"
                if previous_market_regime and market_regime
                else None
            ),
        }
        outcome["horizons"] = {
            horizon: _horizon_result(
                signal=signal,
                horizon=horizon,
                open_dates=open_dates,
                bars_by_key=bars_by_key,
                latest_daily_date=latest_daily_date,
            )
            for horizon in HORIZONS
        }
        outcomes.append(outcome)

    outcomes.sort(key=lambda item: (item["signal_time"], item["startup_score"]), reverse=True)
    completed_count = sum(
        all(item["status"] == "completed" for item in outcome["horizons"].values())
        for outcome in outcomes
    )
    waiting_count = sum(
        any(item["status"] == "waiting" for item in outcome["horizons"].values())
        for outcome in outcomes
    )
    unavailable_count = len(outcomes) - completed_count - waiting_count
    context_counts: dict[str, int] = {}
    for outcome in outcomes:
        key = str(outcome["market_context"])
        context_counts[key] = context_counts.get(key, 0) + 1
    return {
        "signal_count": len(outcomes),
        "completed_count": completed_count,
        "waiting_count": waiting_count,
        "unavailable_count": unavailable_count,
        "context_counts": context_counts,
        "summary": _summary(outcomes),
        "regime_transition_summary": _regime_transition_summary(outcomes),
        "outcomes": outcomes,
    }
