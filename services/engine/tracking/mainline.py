from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import DailyBar, IntradayMarketTurnSnapshot

MAINLINE_HORIZONS = (1, 3, 5)
MIN_OUTCOME_SAMPLES_FOR_POLICY = 20


@dataclass(frozen=True)
class MainlineHorizonOutcome:
    horizon: int
    status: str
    return_pct: float | None
    reason: str | None = None


@dataclass(frozen=True)
class ConfirmedMainlineOutcome:
    signal_type: str
    signal_date: str
    sector: str
    leader_symbol: str
    horizons: dict[int, MainlineHorizonOutcome]
    candidate_bindings: list[ConfirmedCandidateOutcome]
    market_state: str | None = None


@dataclass(frozen=True)
class ConfirmedCandidateOutcome:
    symbol: str
    sector: str
    horizons: dict[int, MainlineHorizonOutcome]


def build_confirmed_mainline_candidate_bindings(
    *,
    candidates: list[dict[str, object]],
    confirmed_sectors: set[str],
) -> list[dict[str, object]]:
    return [
        candidate
        for candidate in candidates
        if candidate.get("selection_tier") == "formal"
        and str(candidate.get("sector") or "").strip() in confirmed_sectors
    ]


def _horizons(
    *,
    bars: list[DailyBar],
    market_dates: list[date],
    signal_date: date,
) -> dict[int, MainlineHorizonOutcome]:
    bars_by_date = {bar.trade_date: bar for bar in bars}
    signal_bar = bars_by_date.get(signal_date)
    if signal_bar is None or not signal_bar.close:
        awaiting_close = not market_dates or signal_date > market_dates[-1]
        return {
            horizon: MainlineHorizonOutcome(
                horizon=horizon,
                status="waiting" if awaiting_close else "unavailable",
                return_pct=None,
                reason="awaiting_signal_close" if awaiting_close else "missing_signal_close",
            )
            for horizon in MAINLINE_HORIZONS
        }
    base_close = float(signal_bar.close)
    future_dates = [item for item in market_dates if item > signal_date]
    outcomes: dict[int, MainlineHorizonOutcome] = {}
    for horizon in MAINLINE_HORIZONS:
        if len(future_dates) < horizon:
            outcomes[horizon] = MainlineHorizonOutcome(
                horizon=horizon,
                status="waiting",
                return_pct=None,
                reason="awaiting_trade_day",
            )
            continue
        target_bar = bars_by_date.get(future_dates[horizon - 1])
        if target_bar is None or not target_bar.close:
            outcomes[horizon] = MainlineHorizonOutcome(
                horizon=horizon,
                status="unavailable",
                return_pct=None,
                reason="missing_target_close",
            )
            continue
        outcomes[horizon] = MainlineHorizonOutcome(
            horizon=horizon,
            status="completed",
            return_pct=round(float(target_bar.close) / base_close - 1, 6),
        )
    return outcomes


def summarize_mainline_outcomes(
    outcomes: list[ConfirmedMainlineOutcome],
    *,
    signal_type: str = "strong_benchmark",
) -> dict[int, dict[str, object]]:
    summary: dict[int, dict[str, object]] = {}
    signal_outcomes = [item for item in outcomes if item.signal_type == signal_type]
    for horizon in MAINLINE_HORIZONS:
        horizon_rows = [item.horizons.get(horizon) for item in signal_outcomes]
        completed = [item for item in horizon_rows if item and item.status == "completed"]
        values = [
            item.return_pct
            for item in completed
            if item.return_pct is not None
        ]
        unavailable = [
            item for item in horizon_rows if item and item.status == "unavailable"
        ]
        waiting = [item for item in horizon_rows if item and item.status == "waiting"]
        count = len(values)
        summary[horizon] = {
            "horizon": horizon,
            "sample_count": count,
            "total_signal_count": len(signal_outcomes),
            "completed_count": len(completed),
            "waiting_count": sum(
                item is None or item.status == "waiting" for item in horizon_rows
            ),
            "waiting_reasons": dict(
                Counter(item.reason for item in waiting if item.reason)
            ),
            "unavailable_count": len(unavailable),
            "unavailable_reasons": dict(
                Counter(item.reason for item in unavailable if item.reason)
            ),
            "minimum_sample_count": MIN_OUTCOME_SAMPLES_FOR_POLICY,
            "eligible_for_policy": count >= MIN_OUTCOME_SAMPLES_FOR_POLICY,
            "avg_return_pct": round(sum(values) / count, 6) if count else None,
            "win_rate": round(sum(value > 0 for value in values) / count, 6) if count else None,
            "failure_rate": round(sum(value <= 0 for value in values) / count, 6)
            if count
            else None,
        }
    return summary


def summarize_mainline_outcome_breakdowns(
    outcomes: list[ConfirmedMainlineOutcome],
    *,
    horizon: int = 3,
) -> dict[str, object]:
    def grouped(key_name: str) -> list[dict[str, bool | int | float | str]]:
        groups: dict[str, list[float]] = {}
        for item in outcomes:
            value = item.horizons.get(horizon)
            key = item.sector if key_name == "sector" else item.market_state
            if (
                item.signal_type != "strong_benchmark"
                or not key
                or value is None
                or value.status != "completed"
                or value.return_pct is None
            ):
                continue
            groups.setdefault(key, []).append(value.return_pct)
        return sorted(
            [
                {
                    "key": key,
                    "sample_count": len(values),
                    "minimum_sample_count": MIN_OUTCOME_SAMPLES_FOR_POLICY,
                    "eligible_for_policy": len(values) >= MIN_OUTCOME_SAMPLES_FOR_POLICY,
                    "avg_return_pct": round(sum(values) / len(values), 6),
                    "win_rate": round(sum(value > 0 for value in values) / len(values), 6),
                    "failure_rate": round(sum(value <= 0 for value in values) / len(values), 6),
                }
                for key, values in groups.items()
            ],
            key=lambda item: (-int(item["sample_count"]), str(item["key"])),
        )

    return {
        "horizon": horizon,
        "sectors": grouped("sector"),
        "market_states": grouped("market_state"),
    }


def list_confirmed_mainline_outcomes(
    db: Session,
    *,
    limit: int = 60,
) -> list[ConfirmedMainlineOutcome]:
    market_dates = list(
        db.execute(
            select(DailyBar.trade_date).distinct().order_by(DailyBar.trade_date)
        ).scalars()
    )
    rows = db.execute(
        select(IntradayMarketTurnSnapshot).order_by(
            IntradayMarketTurnSnapshot.trade_date.desc(),
            IntradayMarketTurnSnapshot.snapshot_time.desc(),
        )
    ).scalars()
    outcomes: list[ConfirmedMainlineOutcome] = []
    seen: set[tuple[object, str]] = set()
    for row in rows:
        cross_day = (row.state_json or {}).get("cross_day_mainline")
        signals: list[tuple[str, dict[str, object]]] = []
        if (
            isinstance(cross_day, dict)
            and cross_day.get("checkpoint") == "10:30复核"
            and cross_day.get("status") == "观察确认"
        ):
            signals.extend(
                ("confirmed_mainline", item)
                for item in cross_day.get("sectors") or []
                if isinstance(item, dict) and item.get("status") == "观察确认"
            )
        signals.extend(
            ("strong_benchmark", item)
            for item in (row.state_json or {}).get("leading_sustained_sectors") or []
            if isinstance(item, dict)
            and float(item.get("up_ratio") or 0) >= 0.7
            and float(item.get("avg_change_pct") or 0) >= 0.015
            and float(item.get("leader_change_pct") or 0) >= 0.03
        )
        for signal_type, item in signals:
            sector = str(item.get("sector") or "").strip()
            leader_symbol = str(
                item.get("current_leader_symbol") or item.get("leader_symbol") or ""
            ).strip()
            key = (row.trade_date, sector)
            if not sector or not leader_symbol or key in seen:
                continue
            seen.add(key)
            bars = list(
                db.execute(
                    select(DailyBar)
                    .where(DailyBar.symbol == leader_symbol)
                    .where(DailyBar.trade_date >= row.trade_date)
                    .order_by(DailyBar.trade_date)
                ).scalars()
            )
            candidate_bindings = []
            for candidate in (row.state_json or {}).get("confirmed_candidate_bindings") or []:
                if not isinstance(candidate, dict) or str(candidate.get("sector") or "") != sector:
                    continue
                symbol = str(candidate.get("symbol") or "").strip()
                if not symbol:
                    continue
                candidate_bars = list(
                    db.execute(
                        select(DailyBar)
                        .where(DailyBar.symbol == symbol)
                        .where(DailyBar.trade_date >= row.trade_date)
                        .order_by(DailyBar.trade_date)
                    ).scalars()
                )
                candidate_bindings.append(
                    ConfirmedCandidateOutcome(
                        symbol=symbol,
                        sector=sector,
                        horizons=_horizons(
                            bars=candidate_bars,
                            market_dates=market_dates,
                            signal_date=row.trade_date,
                        ),
                    )
                )
            outcomes.append(
                ConfirmedMainlineOutcome(
                    signal_type=signal_type,
                    signal_date=row.trade_date.isoformat(),
                    sector=sector,
                    leader_symbol=leader_symbol,
                    horizons=_horizons(
                        bars=bars,
                        market_dates=market_dates,
                        signal_date=row.trade_date,
                    ),
                    candidate_bindings=candidate_bindings,
                    market_state=str((row.state_json or {}).get("key") or "unknown"),
                )
            )
            if len(outcomes) >= limit:
                return outcomes
    return outcomes
