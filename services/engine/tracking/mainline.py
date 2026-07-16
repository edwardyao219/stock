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
    signal_date: str
    sector: str
    leader_symbol: str
    horizons: dict[int, MainlineHorizonOutcome]


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
        if not isinstance(cross_day, dict) or cross_day.get("checkpoint") != "10:30复核":
            continue
        if cross_day.get("status") != "观察确认":
            continue
        for item in cross_day.get("sectors") or []:
            if not isinstance(item, dict) or item.get("status") != "观察确认":
                continue
            sector = str(item.get("sector") or "").strip()
            leader_symbol = str(item.get("current_leader_symbol") or "").strip()
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
            outcomes.append(
                ConfirmedMainlineOutcome(
                    signal_date=row.trade_date.isoformat(),
                    sector=sector,
                    leader_symbol=leader_symbol,
                    horizons=_horizons(bars),
                )
            )
            if len(outcomes) >= limit:
                return outcomes
    return outcomes
