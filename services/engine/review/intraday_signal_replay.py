from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy import select

from services.shared.database import SessionLocal
from services.shared.models import DailyBar, RealtimeQuote, SectorFeatureDaily, Security

STRONG_SECTOR_STRENGTH_MIN = 60.0
STRONG_SECTOR_CONTINUITY_MIN = 65.0
STRONG_SECTOR_RETURN_20D_MIN = 0.08
STRONG_SECTOR_POSITIVE_20D_MIN = 55.0


@dataclass(frozen=True)
class IntradaySignalReplayEvent:
    symbol: str
    name: str | None
    trade_date: str
    quote_time: str
    sector: str | None
    sector_strength_group: str
    trigger_price: float
    open_gap_pct: float
    change_from_open_pct: float
    session_change_pct: float
    range_position: float
    forward_returns: dict[int, float | None]
    support_flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntradaySignalReplayResult:
    start_date: str
    end_date: str
    event_count: int
    groups: dict[str, dict[str, Any]]
    events: list[IntradaySignalReplayEvent]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "event_count": self.event_count,
            "groups": self.groups,
            "events": [event.to_dict() for event in self.events],
        }


def _parse(value: str) -> date:
    return date.fromisoformat(value)


def _float(value) -> float | None:
    return float(value) if value is not None else None


def _range_position(price, high, low) -> float | None:
    if price is None or high is None or low is None or high <= low:
        return None
    return max(0.0, min(1.0, float((price - low) / (high - low))))


def _pct(current, previous) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return float(current / previous - 1)


def _is_gap_down_repair(quote: RealtimeQuote) -> tuple[bool, dict[str, float]]:
    open_gap_pct = _pct(quote.open, quote.pre_close)
    change_from_open_pct = _pct(quote.price, quote.open)
    session_change_pct = _pct(quote.price, quote.pre_close)
    range_position = _range_position(quote.price, quote.high, quote.low)
    metrics = {
        "open_gap_pct": round(open_gap_pct or 0.0, 6),
        "change_from_open_pct": round(change_from_open_pct or 0.0, 6),
        "session_change_pct": round(session_change_pct or 0.0, 6),
        "range_position": round(range_position or 0.0, 6),
    }
    return (
        open_gap_pct is not None
        and open_gap_pct <= -0.015
        and change_from_open_pct is not None
        and change_from_open_pct >= 0.018
        and session_change_pct is not None
        and session_change_pct >= -0.003
        and range_position is not None
        and range_position >= 0.65,
        metrics,
    )


def _is_daily_gap_down_repair(bar: DailyBar) -> tuple[bool, dict[str, float]]:
    open_gap_pct = _pct(bar.open, bar.pre_close)
    change_from_open_pct = _pct(bar.close, bar.open)
    session_change_pct = _pct(bar.close, bar.pre_close)
    range_position = _range_position(bar.close, bar.high, bar.low)
    metrics = {
        "open_gap_pct": round(open_gap_pct or 0.0, 6),
        "change_from_open_pct": round(change_from_open_pct or 0.0, 6),
        "session_change_pct": round(session_change_pct or 0.0, 6),
        "range_position": round(range_position or 0.0, 6),
    }
    return (
        open_gap_pct is not None
        and open_gap_pct <= -0.015
        and change_from_open_pct is not None
        and change_from_open_pct >= 0.018
        and session_change_pct is not None
        and session_change_pct >= -0.003
        and range_position is not None
        and range_position >= 0.65,
        metrics,
    )


def _sector_group(features: dict[str, Any] | None) -> str:
    if features is None:
        return "unknown_sector"
    features = features or {}
    strength = float(features.get("sector_strength_score") or 0)
    continuity = float(features.get("sector_trend_continuity_score") or 0)
    avg_return_20d = float(features.get("sector_avg_return_20d") or 0)
    positive_20d_rate = float(features.get("sector_positive_20d_rate") or 0)
    if (
        strength >= STRONG_SECTOR_STRENGTH_MIN
        and continuity >= STRONG_SECTOR_CONTINUITY_MIN
        and (
            avg_return_20d >= STRONG_SECTOR_RETURN_20D_MIN
            or positive_20d_rate >= STRONG_SECTOR_POSITIVE_20D_MIN
        )
    ):
        return "strong_sector"
    return "weak_sector"


def _nth_trade_date_after(db, signal_date: date, horizon: int) -> date | None:
    return db.execute(
        select(DailyBar.trade_date)
        .where(DailyBar.trade_date > signal_date)
        .group_by(DailyBar.trade_date)
        .order_by(DailyBar.trade_date)
        .offset(max(0, horizon - 1))
        .limit(1)
    ).scalar_one_or_none()


def _forward_returns(
    db,
    *,
    symbol: str,
    trigger_price: float,
    signal_date: date,
    horizons: tuple[int, ...],
) -> dict[int, float | None]:
    if trigger_price <= 0:
        return {horizon: None for horizon in horizons}
    returns: dict[int, float | None] = {}
    for horizon in horizons:
        target_date = _nth_trade_date_after(db, signal_date, horizon)
        if target_date is None:
            returns[horizon] = None
            continue
        close = db.execute(
            select(DailyBar.close)
            .where(DailyBar.symbol == symbol)
            .where(DailyBar.trade_date == target_date)
        ).scalar_one_or_none()
        returns[horizon] = round(float(close) / trigger_price - 1.0, 6) if close else None
    return returns


def _return_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"sample_count": 0, "avg_return": None, "win_rate": None}
    return {
        "sample_count": len(values),
        "avg_return": round(sum(values) / len(values), 6),
        "win_rate": round(sum(1 for value in values if value > 0) / len(values), 6),
    }


def _group_summary(
    events: list[IntradaySignalReplayEvent],
    *,
    horizons: tuple[int, ...],
) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for group in ("strong_sector", "weak_sector", "unknown_sector"):
        group_events = [event for event in events if event.sector_strength_group == group]
        groups[group] = {
            "sample_count": len(group_events),
            "horizons": {
                horizon: _return_summary(
                    [
                        value
                        for event in group_events
                        if (value := event.forward_returns.get(horizon)) is not None
                    ]
                )
                for horizon in horizons
            },
        }
    return groups


def replay_gap_down_repair(
    *,
    start_date: str,
    end_date: str,
    horizons: tuple[int, ...] = (1, 3, 5, 10),
) -> IntradaySignalReplayResult:
    start = _parse(start_date)
    end = _parse(end_date)
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(RealtimeQuote, Security)
                .join(Security, Security.symbol == RealtimeQuote.symbol)
                .where(RealtimeQuote.trade_date >= start)
                .where(RealtimeQuote.trade_date <= end)
                .where(Security.is_active.is_(True))
                .where(Security.is_st.is_(False))
                .order_by(RealtimeQuote.trade_date, RealtimeQuote.symbol, RealtimeQuote.quote_time)
            ).all()
        )
        seen: set[tuple[str, date]] = set()
        events: list[IntradaySignalReplayEvent] = []
        for quote, security in rows:
            if (quote.symbol, quote.trade_date) in seen:
                continue
            matched, metrics = _is_gap_down_repair(quote)
            if not matched:
                continue
            seen.add((quote.symbol, quote.trade_date))
            sector_features = None
            if security.industry:
                sector_features = db.execute(
                    select(SectorFeatureDaily.features)
                    .where(SectorFeatureDaily.sector_code == security.industry)
                    .where(SectorFeatureDaily.trade_date == quote.trade_date)
                ).scalar_one_or_none()
            trigger_price = float(quote.price)
            events.append(
                IntradaySignalReplayEvent(
                    symbol=quote.symbol,
                    name=security.name,
                    trade_date=quote.trade_date.isoformat(),
                    quote_time=quote.quote_time.isoformat(timespec="seconds"),
                    sector=security.industry,
                    sector_strength_group=_sector_group(sector_features),
                    trigger_price=round(trigger_price, 4),
                    open_gap_pct=metrics["open_gap_pct"],
                    change_from_open_pct=metrics["change_from_open_pct"],
                    session_change_pct=metrics["session_change_pct"],
                    range_position=metrics["range_position"],
                    forward_returns=_forward_returns(
                        db,
                        symbol=quote.symbol,
                        trigger_price=trigger_price,
                        signal_date=quote.trade_date,
                        horizons=horizons,
                    ),
                    support_flags=["intraday_gap_down_repair"],
                )
            )
    events = sorted(
        events,
        key=lambda event: (
            event.trade_date,
            0 if event.sector_strength_group == "strong_sector" else 1,
            event.quote_time,
            event.symbol,
        ),
    )
    return IntradaySignalReplayResult(
        start_date=start_date,
        end_date=end_date,
        event_count=len(events),
        groups=_group_summary(events, horizons=horizons),
        events=events,
    )


def replay_daily_gap_down_repair_proxy(
    *,
    start_date: str,
    end_date: str,
    horizons: tuple[int, ...] = (1, 3, 5, 10),
) -> IntradaySignalReplayResult:
    start = _parse(start_date)
    end = _parse(end_date)
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(DailyBar, Security)
                .join(Security, Security.symbol == DailyBar.symbol)
                .where(DailyBar.trade_date >= start)
                .where(DailyBar.trade_date <= end)
                .where(Security.is_active.is_(True))
                .where(Security.is_st.is_(False))
                .order_by(DailyBar.trade_date, DailyBar.symbol)
            ).all()
        )
        events: list[IntradaySignalReplayEvent] = []
        for bar, security in rows:
            matched, metrics = _is_daily_gap_down_repair(bar)
            if not matched:
                continue
            sector_features = None
            if security.industry:
                sector_features = db.execute(
                    select(SectorFeatureDaily.features)
                    .where(SectorFeatureDaily.sector_code == security.industry)
                    .where(SectorFeatureDaily.trade_date == bar.trade_date)
                ).scalar_one_or_none()
            trigger_price = float(bar.close)
            events.append(
                IntradaySignalReplayEvent(
                    symbol=bar.symbol,
                    name=security.name,
                    trade_date=bar.trade_date.isoformat(),
                    quote_time=f"{bar.trade_date.isoformat()}T15:00:00",
                    sector=security.industry,
                    sector_strength_group=_sector_group(sector_features),
                    trigger_price=round(trigger_price, 4),
                    open_gap_pct=metrics["open_gap_pct"],
                    change_from_open_pct=metrics["change_from_open_pct"],
                    session_change_pct=metrics["session_change_pct"],
                    range_position=metrics["range_position"],
                    forward_returns=_forward_returns(
                        db,
                        symbol=bar.symbol,
                        trigger_price=trigger_price,
                        signal_date=bar.trade_date,
                        horizons=horizons,
                    ),
                    support_flags=["daily_gap_down_repair_proxy"],
                )
            )
    events = sorted(
        events,
        key=lambda event: (
            event.trade_date,
            0 if event.sector_strength_group == "strong_sector" else 1,
            event.quote_time,
            event.symbol,
        ),
    )
    return IntradaySignalReplayResult(
        start_date=start_date,
        end_date=end_date,
        event_count=len(events),
        groups=_group_summary(events, horizons=horizons),
        events=events,
    )
