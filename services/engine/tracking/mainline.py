from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import DailyBar, IntradayMarketTurnSnapshot

MAINLINE_HORIZONS = (1, 3, 5)


@dataclass(frozen=True)
class MainlineHorizonOutcome:
    horizon: int
    status: str
    return_pct: float | None


@dataclass(frozen=True)
class ConfirmedMainlineOutcome:
    signal_type: str
    signal_date: str
    sector: str
    leader_symbol: str
    horizons: dict[int, MainlineHorizonOutcome]
    candidate_bindings: list[ConfirmedCandidateOutcome]


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


def _horizons(bars: list[DailyBar]) -> dict[int, MainlineHorizonOutcome]:
    if not bars or not bars[0].close:
        return {
            horizon: MainlineHorizonOutcome(horizon=horizon, status="waiting", return_pct=None)
            for horizon in MAINLINE_HORIZONS
        }
    base_close = float(bars[0].close)
    return {
        horizon: MainlineHorizonOutcome(
            horizon=horizon,
            status="completed" if len(bars) > horizon and bars[horizon].close else "waiting",
            return_pct=(round(float(bars[horizon].close) / base_close - 1, 6)
            if len(bars) > horizon and bars[horizon].close
            else None),
        )
        for horizon in MAINLINE_HORIZONS
    }


def list_confirmed_mainline_outcomes(
    db: Session,
    *,
    limit: int = 60,
) -> list[ConfirmedMainlineOutcome]:
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
                        horizons=_horizons(candidate_bars),
                    )
                )
            outcomes.append(
                ConfirmedMainlineOutcome(
                    signal_type=signal_type,
                    signal_date=row.trade_date.isoformat(),
                    sector=sector,
                    leader_symbol=leader_symbol,
                    horizons=_horizons(bars),
                    candidate_bindings=candidate_bindings,
                )
            )
            if len(outcomes) >= limit:
                return outcomes
    return outcomes
