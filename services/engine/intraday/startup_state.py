from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time


STARTUP_LABELS = {
    "preheat": "启动预热",
    "probing": "启动试探",
    "confirmed": "启动确认",
    "invalidated": "启动失效",
}


@dataclass(frozen=True)
class StartupEvidence:
    trade_date: date
    as_of: datetime
    individual_supportive: bool
    volume_confirmed: bool
    sector_sustained: bool
    sector_strength_holding: bool
    formal_eligible: bool
    market_risk_off: bool
    hard_risk_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class StartupDecision:
    state: str
    label: str
    confirmation_evidence: tuple[str, ...]
    invalidation_reasons: tuple[str, ...]
    next_conditions: tuple[str, ...]
    transitioned: bool


def resolve_startup_state(
    prior_state: str | None,
    evidence: StartupEvidence,
) -> StartupDecision:
    prior = prior_state if prior_state in STARTUP_LABELS else "preheat"
    invalidation_reasons: tuple[str, ...] = ()

    if prior == "invalidated":
        state = "invalidated"
        invalidation_reasons = evidence.hard_risk_reasons
    elif evidence.market_risk_off or evidence.hard_risk_reasons:
        state = "invalidated"
        invalidation_reasons = evidence.hard_risk_reasons or ("市场风险阀门关闭",)
    elif prior == "confirmed":
        state = "confirmed"
    elif (
        evidence.as_of.time() >= time(10, 30)
        and evidence.sector_sustained
        and evidence.individual_supportive
        and (evidence.volume_confirmed or evidence.sector_strength_holding)
        and evidence.formal_eligible
    ):
        state = "confirmed"
    else:
        state = "probing" if prior == "probing" or evidence.individual_supportive else "preheat"

    confirmation_evidence = (
        ("板块持续扩散", "个股量价承接", "市场风险阀门允许")
        if state == "confirmed"
        else ()
    )
    next_conditions: list[str] = []
    if state not in {"confirmed", "invalidated"}:
        if evidence.as_of.time() < time(10, 30):
            next_conditions.append("等待10:30板块持续扩散确认")
        elif not evidence.sector_sustained:
            next_conditions.append("等待板块持续扩散")
        if not evidence.individual_supportive:
            next_conditions.append("等待个股价格承接")
        if not (evidence.volume_confirmed or evidence.sector_strength_holding):
            next_conditions.append("等待量能或板块强度确认")
        if not evidence.formal_eligible:
            next_conditions.append("等待盘中风险条件解除")

    return StartupDecision(
        state=state,
        label=STARTUP_LABELS[state],
        confirmation_evidence=confirmation_evidence,
        invalidation_reasons=invalidation_reasons,
        next_conditions=tuple(next_conditions),
        transitioned=state != prior,
    )

