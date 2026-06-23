from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.engine.fundamental.repository import load_fundamental_context
from services.engine.fundamental.scoring import assess_fundamentals
from services.shared.models import DailyBar, SectorFeatureDaily, Security, StockFeatureDaily


def load_sector_feature_map(db: Session, trade_date: date) -> dict[str, dict[str, Any]]:
    return {
        row.sector_code: row.features or {}
        for row in db.execute(
            select(SectorFeatureDaily).where(SectorFeatureDaily.trade_date == trade_date)
        ).scalars()
    }


def build_strategy_context(
    db: Session,
    feature_row: StockFeatureDaily,
    security: Security,
    bar: DailyBar,
    sector_feature_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = dict(feature_row.features or {})
    sector_features = dict((sector_feature_map or {}).get(security.industry, {}))
    fundamental_context = load_fundamental_context(db, feature_row.symbol, feature_row.trade_date)
    context.update(
        {
            "symbol": feature_row.symbol,
            "trade_date": feature_row.trade_date.isoformat(),
            "name": security.name,
            "sector_code": security.industry,
            "industry": security.industry,
            "style": security.sector_style,
            "sector_style": security.sector_style,
            "analysis_framework": security.analysis_framework,
            "holding_style": security.holding_style,
            "is_st": security.is_st,
            "is_suspended": bar.is_suspended,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "amount": float(bar.amount) if bar.amount is not None else None,
            "volume": float(bar.volume) if bar.volume is not None else None,
            "turnover_rate": float(bar.turnover_rate) if bar.turnover_rate is not None else None,
            **sector_features,
            **fundamental_context,
        }
    )
    assessment = assess_fundamentals(context)
    context.update(
        {
            "fundamental_score": assessment.score,
            "fundamental_verdict": assessment.verdict,
            "fundamental_reasons": assessment.reasons,
        }
    )
    return context
