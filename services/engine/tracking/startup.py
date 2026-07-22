from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.intraday.startup_state import STARTUP_LABELS
from services.shared.models import DailyBar, ResearchSignalLedger, TradePlan

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
    state: str
    state_label: str
    state_time: datetime | None
    signal_type: str
    signal_label: str
    signal_date: date | None
    signal_score: float | None
    signal_reasons: list[str]
    confirmation_evidence: list[str]
    invalidation_reasons: list[str]
    next_conditions: list[str]
    plan_available: bool
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
        if not tag.startswith("startup_state:"):
            continue
        state = tag.removeprefix("startup_state:")
        if state in STARTUP_LABELS:
            return f"startup_{state}", STARTUP_LABELS[state]
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
        state = signal_type.removeprefix("startup_")
        state_time = None
        confirmation_evidence: list[str] = []
        invalidation_reasons: list[str] = []
        next_conditions: list[str] = []
        event_stmt = (
            select(ResearchSignalLedger)
            .where(ResearchSignalLedger.source == "startup_state")
            .where(ResearchSignalLedger.symbol == candidate.symbol)
            .order_by(ResearchSignalLedger.signal_time.desc())
            .limit(1)
        )
        if signal_date is not None:
            event_stmt = event_stmt.where(ResearchSignalLedger.signal_date == signal_date)
        event = db.execute(event_stmt).scalar_one_or_none()
        if event is not None:
            event_state = event.signal_type.removeprefix("startup_")
            if event_state in STARTUP_LABELS:
                state = event_state
                signal_type = f"startup_{state}"
                signal_label = STARTUP_LABELS[state]
                signal_date = event.signal_date
                state_time = event.signal_time
                evidence = dict(event.evidence_json or {})
                confirmation_evidence = list(
                    evidence.get("confirmation_evidence") or []
                )
                invalidation_reasons = list(
                    evidence.get("invalidation_reasons") or []
                )
                next_conditions = list(evidence.get("next_conditions") or [])
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
        plan_available = bool(
            state == "confirmed"
            and signal_date is not None
            and db.execute(
                select(TradePlan.id)
                .where(TradePlan.symbol == candidate.symbol)
                .where(TradePlan.trade_date == signal_date)
                .where(TradePlan.status == "planned")
                .limit(1)
            ).scalar_one_or_none()
        )
        rows.append(
            StartupTrackingRow(
                symbol=candidate.symbol,
                state=state,
                state_label=signal_label,
                state_time=state_time,
                signal_type=signal_type,
                signal_label=signal_label,
                signal_date=signal_date,
                signal_score=_signal_score(candidate.tags),
                signal_reasons=_signal_reasons(candidate.tags),
                confirmation_evidence=confirmation_evidence,
                invalidation_reasons=invalidation_reasons,
                next_conditions=next_conditions,
                plan_available=plan_available,
                realised_return=realised_return,
                horizons=horizons,
            )
        )
    return rows


def build_startup_historical_evidence(payload: dict) -> HistoricalEvidence:
    evidence: HistoricalEvidence = {}
    scopes = payload.get("scopes") if isinstance(payload.get("scopes"), dict) else {}
    for signal_type in (
        "startup_preheat",
        "startup_probing",
        "startup_confirmed",
        "startup_invalidated",
    ):
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
