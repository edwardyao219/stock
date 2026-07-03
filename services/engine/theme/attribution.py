from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.shared.models import TushareMoneyflowIndDc

THEME_TAG_PREFIXES = ("theme:", "主题:", "concept:", "概念:")
THEME_MONEYFLOW_RATE_MIN = 5.0
THEME_PCT_CHANGE_MIN = 3.0
GENERIC_THEME_TERMS = {"概念", "板块", "行业", "风格"}


@dataclass(frozen=True)
class ThemeMoneyflowSignal:
    score_delta: float = 0.0
    theme_name: str | None = None
    pct_change: float | None = None
    net_amount_rate: float | None = None
    support_flags: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    caution_reasons: list[str] = field(default_factory=list)


def _theme_tags(tags: list[str]) -> list[str]:
    themes: list[str] = []
    for tag in tags:
        for prefix in THEME_TAG_PREFIXES:
            if not tag.startswith(prefix):
                continue
            theme = tag.removeprefix(prefix).strip()
            if theme and theme not in themes:
                themes.append(theme)
    return themes


def _normalize_theme_text(value: str) -> str:
    return value.replace(" ", "").replace("　", "").lower()


def _is_informative_theme_term(term: str) -> bool:
    if term in GENERIC_THEME_TERMS:
        return False
    if any(char.isdigit() for char in term):
        return False
    return True


def _theme_name_terms(name: str) -> list[str]:
    normalized = _normalize_theme_text(name)
    if not normalized:
        return []
    terms: list[str] = []
    for length in range(3, min(6, len(normalized)) + 1):
        for start in range(0, len(normalized) - length + 1):
            term = normalized[start : start + length]
            if not _is_informative_theme_term(term) or term in terms:
                continue
            terms.append(term)
    if (
        len(normalized) >= 2
        and normalized.isascii()
        and _is_informative_theme_term(normalized)
        and normalized not in terms
    ):
        terms.append(normalized)
    return terms


def _percent_like(value: Decimal | None) -> float:
    if value is None:
        return 0.0
    number = float(value)
    if -1.0 <= number <= 1.0:
        return number * 100.0
    return number


def load_latest_theme_moneyflow_rows(
    db: Session,
    *,
    trade_date: date,
) -> list[TushareMoneyflowIndDc]:
    latest_date = db.execute(
        select(func.max(TushareMoneyflowIndDc.trade_date))
        .where(TushareMoneyflowIndDc.trade_date <= trade_date)
        .where(TushareMoneyflowIndDc.content_type.in_(("概念", "行业")))
    ).scalar_one_or_none()
    if latest_date is None:
        return []
    return list(
        db.execute(
            select(TushareMoneyflowIndDc)
            .where(TushareMoneyflowIndDc.trade_date == latest_date)
            .where(TushareMoneyflowIndDc.content_type.in_(("概念", "行业")))
        ).scalars()
    )


def build_theme_moneyflow_signal(
    *,
    tags: list[str],
    note: str | None,
    rows: list[TushareMoneyflowIndDc],
) -> ThemeMoneyflowSignal:
    themes = _theme_tags(tags)
    note_key = _normalize_theme_text(note or "")
    if not rows or (not themes and not note_key):
        return ThemeMoneyflowSignal()

    best_row: TushareMoneyflowIndDc | None = None
    best_score = -999.0
    for theme in themes or [""]:
        theme_key = _normalize_theme_text(theme)
        for row in rows:
            name = str(row.name or "").strip()
            name_key = _normalize_theme_text(name)
            if not name_key:
                continue
            explicit_match = bool(theme_key) and (
                theme_key in name_key or name_key in theme_key
            )
            note_match = bool(note_key) and any(
                term in note_key for term in _theme_name_terms(name)
            )
            if not explicit_match and not note_match:
                continue
            pct_change = _percent_like(row.pct_change)
            flow_rate = _percent_like(row.net_amount_rate)
            score = pct_change * 0.45 + flow_rate * 0.55
            if score > best_score:
                best_score = score
                best_row = row

    if best_row is None:
        return ThemeMoneyflowSignal()

    pct_change = _percent_like(best_row.pct_change)
    flow_rate = _percent_like(best_row.net_amount_rate)
    if pct_change < THEME_PCT_CHANGE_MIN and flow_rate < THEME_MONEYFLOW_RATE_MIN:
        return ThemeMoneyflowSignal()

    theme_name = str(best_row.name or "").strip()
    pct_change = round(pct_change, 4)
    flow_rate = round(flow_rate, 4)
    return ThemeMoneyflowSignal(
        score_delta=2.0,
        theme_name=theme_name,
        pct_change=pct_change,
        net_amount_rate=flow_rate,
        support_flags=["theme_moneyflow_supported", f"theme:{theme_name}"],
        caution_reasons=["主题资金有支撑，但只修正粗行业标签，不单独触发买入"],
    )
