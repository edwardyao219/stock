from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select

from services.shared.database import SessionLocal
from services.shared.models import DailyBar, SectorFeatureDaily, Security, StockFeatureDaily

HOT_STRENGTH_MIN = 60.0
HOT_CONTINUITY_MIN = 65.0
HOT_RETURN_20D_MIN = 0.08
HOT_POSITIVE_20D_MIN = 55.0


@dataclass(frozen=True)
class SectorReplayEvent:
    trade_date: str
    coverage_ratio: float
    qualifies_hot: bool
    setup_label: str
    extension_risk: str
    strength_score: float
    continuity_score: float
    resilience_score: float
    avg_return_20d: float
    positive_20d_rate: float
    stock_count: int
    forward_returns: dict[int, float | None]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SectorReplayResult:
    month: str
    sector: str
    events: list[SectorReplayEvent]

    def to_dict(self) -> dict[str, Any]:
        return {
            "month": self.month,
            "sector": self.sector,
            "events": [item.to_dict() for item in self.events],
        }


def _month_bounds(month: str) -> tuple[date, date]:
    start = date.fromisoformat(f"{month}-01")
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start, end


def _float(features: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = features.get(key)
    return float(value) if value is not None else default


def _qualifies_hot(features: dict[str, Any]) -> bool:
    strength = _float(features, "sector_strength_score")
    continuity = _float(features, "sector_trend_continuity_score")
    avg_return_20d = _float(features, "sector_avg_return_20d")
    positive_20d_rate = _float(features, "sector_positive_20d_rate")
    return (
        strength >= HOT_STRENGTH_MIN
        and continuity >= HOT_CONTINUITY_MIN
        and (
            avg_return_20d >= HOT_RETURN_20D_MIN
            or positive_20d_rate >= HOT_POSITIVE_20D_MIN
        )
    )


def _extension_risk(features: dict[str, Any]) -> str:
    avg_return_20d = _float(features, "sector_avg_return_20d")
    positive_20d_rate = _float(features, "sector_positive_20d_rate")
    if avg_return_20d >= 0.24 or positive_20d_rate >= 85.0:
        return "high"
    if avg_return_20d >= 0.18 or positive_20d_rate >= 75.0:
        return "elevated"
    return "normal"


def _setup_label(features: dict[str, Any]) -> str:
    risk = _extension_risk(features)
    avg_return_20d = _float(features, "sector_avg_return_20d")
    if risk == "high":
        return "overextended"
    if 0.08 <= avg_return_20d <= 0.18:
        return "mainline_confirmed"
    return "watch"


def _forward_return(
    db,
    *,
    sector: str,
    signal_date: date,
    horizon: int,
) -> float | None:
    target_date = db.execute(
        select(DailyBar.trade_date)
        .where(DailyBar.trade_date > signal_date)
        .group_by(DailyBar.trade_date)
        .order_by(DailyBar.trade_date)
        .offset(max(0, horizon - 1))
        .limit(1)
    ).scalar_one_or_none()
    if target_date is None:
        return None

    rows = db.execute(
        select(DailyBar.symbol, DailyBar.close)
        .join(Security, Security.symbol == DailyBar.symbol)
        .where(Security.industry == sector)
        .where(Security.is_active.is_(True))
        .where(Security.is_st.is_(False))
        .where(DailyBar.trade_date == signal_date)
    ).all()
    start_close = {symbol: float(close) for symbol, close in rows if close and float(close) > 0}
    if not start_close:
        return None

    end_rows = db.execute(
        select(DailyBar.symbol, DailyBar.close)
        .where(DailyBar.symbol.in_(list(start_close)))
        .where(DailyBar.trade_date == target_date)
    ).all()
    returns = [
        float(close) / start_close[symbol] - 1.0
        for symbol, close in end_rows
        if symbol in start_close and close is not None
    ]
    if not returns:
        return None
    return round(sum(returns) / len(returns), 6)


def replay_sector_month(
    month: str,
    *,
    sector: str,
    horizons: tuple[int, ...] = (5, 10, 20),
) -> SectorReplayResult:
    start, end = _month_bounds(month)
    with SessionLocal() as db:
        active_total = int(
            db.execute(
                select(func.count())
                .select_from(Security)
                .where(Security.is_active.is_(True))
                .where(Security.is_st.is_(False))
            ).scalar_one()
            or 0
        )
        rows = list(
            db.execute(
                select(SectorFeatureDaily)
                .where(SectorFeatureDaily.sector_code == sector)
                .where(SectorFeatureDaily.trade_date >= start)
                .where(SectorFeatureDaily.trade_date < end)
                .order_by(SectorFeatureDaily.trade_date)
            ).scalars()
        )

        events: list[SectorReplayEvent] = []
        for row in rows:
            features = row.features or {}
            qualifies = _qualifies_hot(features)
            if not qualifies:
                continue
            feature_symbols = int(
                db.execute(
                    select(func.count(func.distinct(StockFeatureDaily.symbol))).where(
                        StockFeatureDaily.trade_date == row.trade_date
                    )
                ).scalar_one()
                or 0
            )
            coverage = round(feature_symbols / active_total, 4) if active_total else 0.0
            forward_returns = {
                horizon: _forward_return(
                    db,
                    sector=sector,
                    signal_date=row.trade_date,
                    horizon=horizon,
                )
                for horizon in horizons
            }
            events.append(
                SectorReplayEvent(
                    trade_date=row.trade_date.isoformat(),
                    coverage_ratio=coverage,
                    qualifies_hot=qualifies,
                    setup_label=_setup_label(features),
                    extension_risk=_extension_risk(features),
                    strength_score=round(_float(features, "sector_strength_score"), 4),
                    continuity_score=round(
                        _float(features, "sector_trend_continuity_score"),
                        4,
                    ),
                    resilience_score=round(
                        _float(features, "sector_trend_resilience_score"),
                        4,
                    ),
                    avg_return_20d=round(_float(features, "sector_avg_return_20d"), 6),
                    positive_20d_rate=round(_float(features, "sector_positive_20d_rate"), 4),
                    stock_count=int(_float(features, "sector_stock_count")),
                    forward_returns=forward_returns,
                )
            )
    return SectorReplayResult(month=month, sector=sector, events=events)
