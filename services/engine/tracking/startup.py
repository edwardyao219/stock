from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import DailyBar

STARTUP_TAGS = {
    "candidate_pool:startup_preheat": ("startup_preheat", "启动观察"),
    "candidate_pool:expansion_confirm": ("startup_confirmed", "启动确认"),
}
HORIZONS = (5, 10, 20)
HistoricalEvidence = dict[str, dict[int, dict[str, float | int | None]]]


@dataclass(frozen=True)
class StartupCandidate:
    symbol: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class StartupHorizonProgress:
    horizon: int
    status: str


@dataclass(frozen=True)
class StartupTrackingRow:
    symbol: str
    signal_type: str
    signal_label: str
    signal_date: date | None
    signal_score: float | None
    signal_reasons: list[str]
    realised_return: float | None
    horizons: dict[int, StartupHorizonProgress]


def _signal_date(tags: tuple[str, ...]) -> date | None:
    dates: list[date] = []
    for tag in tags:
        try:
            dates.append(date.fromisoformat(tag))
        except ValueError:
            continue
    return max(dates) if dates else None


def _signal_score(tags: tuple[str, ...]) -> float | None:
    for tag in tags:
        if tag.startswith("startup_signal_score:"):
            try:
                return float(tag.removeprefix("startup_signal_score:"))
            except ValueError:
                return None
    return None


def _signal_reasons(tags: tuple[str, ...]) -> list[str]:
    return [
        tag.removeprefix("startup_signal_reason:")
        for tag in tags
        if tag.startswith("startup_signal_reason:")
    ]


def _startup_signal(tags: tuple[str, ...]) -> tuple[str, str] | None:
    for tag in tags:
        if tag in STARTUP_TAGS:
            return STARTUP_TAGS[tag]
    return None


def build_startup_tracking_rows(
    db: Session,
    candidates: list[StartupCandidate],
) -> list[StartupTrackingRow]:
    rows: list[StartupTrackingRow] = []
    for candidate in candidates:
        signal = _startup_signal(candidate.tags)
        if signal is None:
            continue
        signal_type, signal_label = signal
        signal_date = _signal_date(candidate.tags)
        bars = []
        if signal_date is not None:
            bars = list(
                db.execute(
                    select(DailyBar)
                    .where(DailyBar.symbol == candidate.symbol)
                    .where(DailyBar.trade_date >= signal_date)
                    .order_by(DailyBar.trade_date)
                ).scalars()
            )
        realised_return = None
        if bars and bars[0].trade_date == signal_date and bars[0].close:
            realised_return = round(float(bars[-1].close / bars[0].close - 1), 6)
        completed_days = max(0, len(bars) - 1)
        status = "data_pending" if not bars or bars[0].trade_date != signal_date else "in_progress"
        horizons = {
            horizon: StartupHorizonProgress(
                horizon=horizon,
                status="completed" if completed_days >= horizon else status,
            )
            for horizon in HORIZONS
        }
        rows.append(
            StartupTrackingRow(
                symbol=candidate.symbol,
                signal_type=signal_type,
                signal_label=signal_label,
                signal_date=signal_date,
                signal_score=_signal_score(candidate.tags),
                signal_reasons=_signal_reasons(candidate.tags),
                realised_return=realised_return,
                horizons=horizons,
            )
        )
    return rows


def build_startup_historical_evidence(payload: dict) -> HistoricalEvidence:
    evidence: HistoricalEvidence = {}
    scopes = payload.get("scopes") if isinstance(payload.get("scopes"), dict) else {}
    for signal_type in ("startup_preheat", "startup_confirmed"):
        scope = scopes.get(signal_type) if isinstance(scopes.get(signal_type), dict) else {}
        horizon_metrics: dict[int, dict[str, float | int | None]] = {}
        for horizon in HORIZONS:
            horizons = scope.get("horizons") if isinstance(scope.get("horizons"), dict) else {}
            values = horizons.get(horizon) or horizons.get(str(horizon)) or {}
            raw = values.get("raw") if isinstance(values.get("raw"), dict) else {}
            guarded = values.get("guarded") if isinstance(values.get("guarded"), dict) else {}
            horizon_metrics[horizon] = {
                "sample_count": raw.get("sample_count", 0),
                "win_rate": raw.get("win_rate"),
                "raw_return": raw.get("avg_return"),
                "guarded_return": guarded.get("avg_return"),
            }
        evidence[signal_type] = horizon_metrics
    return evidence
