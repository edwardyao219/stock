from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.shared.models import ExternalMarketSignal


def load_external_market_signals(
    db: Session,
    *,
    signal_date: date,
) -> list[dict[str, object]]:
    start = datetime.combine(signal_date, time.min)
    end = start + timedelta(days=1)
    rows = list(
        db.execute(
            select(ExternalMarketSignal)
            .where(ExternalMarketSignal.observed_at >= start)
            .where(ExternalMarketSignal.observed_at < end)
            .order_by(ExternalMarketSignal.observed_at.desc(), ExternalMarketSignal.id.desc())
        ).scalars()
    )
    return [
        {
            "source": row.source,
            "title": row.title,
            "change_pct": row.change_pct,
            "a_share_sectors": list(row.a_share_sectors_json or []),
            "source_url": row.source_url,
            "observed_at": row.observed_at.isoformat(),
        }
        for row in rows
    ]


def build_external_challengers(
    *,
    signals: list[dict[str, Any]],
    sector_focus: list[dict[str, Any]],
    market_turn: dict[str, Any] | None = None,
) -> list[dict[str, object]]:
    focus_scores = {
        str(item.get("sector") or "").strip(): float(item.get("focus_score") or 0.0)
        for item in sector_focus
        if str(item.get("sector") or "").strip()
    }
    challengers: list[dict[str, object]] = []
    market_turn = market_turn or {}
    startup_candidates_allowed = bool(market_turn.get("startup_candidates_allowed"))
    market_turn_key = str(market_turn.get("key") or "").strip()
    for signal in signals:
        sectors = [
            str(value).strip()
            for value in signal.get("a_share_sectors") or []
            if str(value).strip()
        ]
        if not sectors:
            continue
        matched_focus_scores = {
            sector: round(focus_scores[sector], 4)
            for sector in sectors
            if sector in focus_scores
        }
        if not startup_candidates_allowed:
            a_share_confirmation = "市场防守，A股未确认"
        elif not matched_focus_scores:
            a_share_confirmation = "市场修复中，映射板块未确认"
        else:
            a_share_confirmation = "仅板块有响应，仍待量能和龙头承接确认"
        challengers.append(
            {
                "source": str(signal.get("source") or "external"),
                "title": str(signal.get("title") or "外盘信号"),
                "change_pct": signal.get("change_pct"),
                "a_share_sectors": sectors,
                "mapped_focus_scores": matched_focus_scores,
                "label": "外盘映射待确认",
                "startup_watch_allowed": False,
                "market_confirmed": False,
                "a_share_confirmation": a_share_confirmation,
                "summary": (
                    "外盘异动仅列入观察，"
                    f"{a_share_confirmation}。"
                    "不单独升级候选，需等待A股板块扩散、量能和龙头承接确认。"
                ),
                "market_turn_key": market_turn_key,
            }
        )
    return challengers
