from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.engine.fundamental.repository import load_fundamental_context
from services.engine.fundamental.scoring import assess_fundamentals
from services.engine.sector.repository import load_sector_profile
from services.engine.signals.route import build_signal_route
from services.shared.models import (
    DailyBar,
    SectorFeatureDaily,
    SectorProfile,
    Security,
    StockFeatureDaily,
    TushareDailyBasic,
    TushareMoneyflow,
    TushareMoneyflowIndDc,
)


def load_sector_feature_map(db: Session, trade_date: date) -> dict[str, dict[str, Any]]:
    return {
        row.sector_code: row.features or {}
        for row in db.execute(
            select(SectorFeatureDaily).where(SectorFeatureDaily.trade_date == trade_date)
        ).scalars()
    }


def _ts_code_for_symbol(security: Security) -> str:
    exchange = (security.exchange or "").upper()
    suffix = "SH" if exchange == "SH" else "BJ" if exchange == "BJ" else "SZ"
    return f"{security.symbol}.{suffix}"


def _daily_basic_context(row: TushareDailyBasic) -> dict[str, Any]:
    return {
        "turnover_rate": float(row.turnover_rate) if row.turnover_rate is not None else None,
        "volume_ratio": float(row.volume_ratio) if row.volume_ratio is not None else None,
        "pe_ttm": float(row.pe_ttm) if row.pe_ttm is not None else None,
        "pb": float(row.pb) if row.pb is not None else None,
        "total_mv": float(row.total_mv) if row.total_mv is not None else None,
        "circ_mv": float(row.circ_mv) if row.circ_mv is not None else None,
    }


def load_tushare_daily_basic_map(
    db: Session,
    ts_codes: Sequence[str],
    trade_date: date,
) -> dict[str, dict[str, Any]]:
    unique_ts_codes = sorted({code for code in ts_codes if code})
    if not unique_ts_codes:
        return {}
    rows = db.execute(
        select(TushareDailyBasic).where(
            TushareDailyBasic.ts_code.in_(unique_ts_codes),
            TushareDailyBasic.trade_date == trade_date,
        )
    ).scalars()
    return {row.ts_code: _daily_basic_context(row) for row in rows}


def _load_tushare_daily_basic(db: Session, ts_code: str, trade_date: date) -> dict[str, Any]:
    row = db.execute(
        select(TushareDailyBasic).where(
            TushareDailyBasic.ts_code == ts_code,
            TushareDailyBasic.trade_date == trade_date,
        )
    ).scalar_one_or_none()
    if row is None:
        return {}
    return _daily_basic_context(row)


def _load_tushare_moneyflow(db: Session, ts_code: str, trade_date: date) -> dict[str, Any]:
    row = db.execute(
        select(TushareMoneyflow).where(
            TushareMoneyflow.ts_code == ts_code,
            TushareMoneyflow.trade_date == trade_date,
        )
    ).scalar_one_or_none()
    if row is None:
        return {}
    return _moneyflow_context(row)


def _moneyflow_context(row: TushareMoneyflow) -> dict[str, Any]:
    gross_buy = sum(
        value or 0
        for value in [
            row.buy_sm_amount,
            row.buy_md_amount,
            row.buy_lg_amount,
            row.buy_elg_amount,
        ]
    )
    return {
        "net_mf_amount": float(row.net_mf_amount) if row.net_mf_amount is not None else None,
        "moneyflow_buy_amount": float(gross_buy) if gross_buy is not None else None,
        "moneyflow_support_score": max(
            0.0,
            min(
                100.0,
                50.0 + float(row.net_mf_amount or 0) / 20000000.0,
            ),
        ),
    }


def load_tushare_moneyflow_map(
    db: Session,
    ts_codes: Sequence[str],
    trade_date: date,
) -> dict[str, dict[str, Any]]:
    unique_ts_codes = sorted({code for code in ts_codes if code})
    if not unique_ts_codes:
        return {}
    rows = db.execute(
        select(TushareMoneyflow).where(
            TushareMoneyflow.ts_code.in_(unique_ts_codes),
            TushareMoneyflow.trade_date == trade_date,
        )
    ).scalars()
    return {row.ts_code: _moneyflow_context(row) for row in rows}


def _load_tushare_industry_moneyflow(
    db: Session,
    sector_code: str | None,
    trade_date: date,
) -> dict[str, Any]:
    if not sector_code:
        return {}
    row = db.execute(
        select(TushareMoneyflowIndDc).where(
            TushareMoneyflowIndDc.trade_date == trade_date,
            TushareMoneyflowIndDc.content_type == "行业",
            TushareMoneyflowIndDc.name == sector_code,
        )
        .order_by(*_industry_moneyflow_priority_order())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return {}
    return _industry_moneyflow_context(row)


def _industry_moneyflow_priority_order() -> tuple[Any, ...]:
    return (
        func.coalesce(TushareMoneyflowIndDc.net_amount_rate, -999999999).desc(),
        func.coalesce(TushareMoneyflowIndDc.net_amount, -999999999).desc(),
        TushareMoneyflowIndDc.id.desc(),
    )


def _industry_moneyflow_context(row: TushareMoneyflowIndDc) -> dict[str, Any]:
    return {
        "sector_fund_flow_net_amount": (
            float(row.net_amount) if row.net_amount is not None else None
        ),
        "sector_fund_flow_rate": (
            float(row.net_amount_rate) if row.net_amount_rate is not None else None
        ),
        "sector_fund_flow_score": max(
            0.0,
            min(100.0, 50.0 + float(row.net_amount_rate or 0) * 5.0),
        ),
    }


def load_tushare_industry_moneyflow_map(
    db: Session,
    sector_codes: Sequence[str | None],
    trade_date: date,
) -> dict[str, dict[str, Any]]:
    unique_sector_codes = sorted({code for code in sector_codes if code})
    if not unique_sector_codes:
        return {}
    rows = db.execute(
        select(TushareMoneyflowIndDc).where(
            TushareMoneyflowIndDc.trade_date == trade_date,
            TushareMoneyflowIndDc.content_type == "行业",
            TushareMoneyflowIndDc.name.in_(unique_sector_codes),
        )
        .order_by(TushareMoneyflowIndDc.name.asc(), *_industry_moneyflow_priority_order())
    ).scalars()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.name and row.name not in result:
            result[str(row.name)] = _industry_moneyflow_context(row)
    return result


def _sector_leadership_metrics(context: dict[str, Any]) -> dict[str, Any]:
    strength = float(context.get("sector_strength_score") or 50.0)
    breadth = float(context.get("sector_breadth_score") or 50.0)
    momentum = float(context.get("sector_momentum_score") or 50.0)
    fund_flow = float(context.get("sector_fund_flow_score") or 50.0)
    continuity = float(context.get("sector_trend_continuity_score") or 50.0)
    resilience = float(context.get("sector_trend_resilience_score") or 50.0)
    confidence = float(context.get("sector_sample_confidence") or 0.0)
    stock_count = float(context.get("sector_stock_count") or 0.0)

    leadership_score = (
        strength * 0.26
        + breadth * 0.15
        + momentum * 0.16
        + fund_flow * 0.15
        + continuity * 0.15
        + resilience * 0.13
    )
    if confidence < 0.15 or stock_count <= 2:
        leadership_score = leadership_score * 0.65 + 17.5
    leadership_score = max(0.0, min(100.0, leadership_score))

    if leadership_score >= 75:
        tier = "core_leader"
    elif leadership_score >= 63:
        tier = "followable"
    elif leadership_score >= 52:
        tier = "neutral"
    else:
        tier = "weak"

    return {
        "sector_leadership_score": round(leadership_score, 4),
        "sector_leadership_tier": tier,
    }


def build_strategy_context(
    db: Session,
    feature_row: StockFeatureDaily,
    security: Security,
    bar: DailyBar,
    sector_feature_map: dict[str, dict[str, Any]] | None = None,
    tushare_daily_basic_map: Mapping[str, dict[str, Any]] | None = None,
    tushare_moneyflow_map: Mapping[str, dict[str, Any]] | None = None,
    industry_moneyflow_map: Mapping[str, dict[str, Any]] | None = None,
    fundamental_context_map: Mapping[str, dict[str, Any]] | None = None,
    sector_profile_map: Mapping[str, SectorProfile] | None = None,
) -> dict[str, Any]:
    context = dict(feature_row.features or {})
    sector_features = dict((sector_feature_map or {}).get(security.industry, {}))
    ts_code = _ts_code_for_symbol(security)
    if tushare_daily_basic_map is None:
        tushare_daily_basic = _load_tushare_daily_basic(db, ts_code, feature_row.trade_date)
    else:
        tushare_daily_basic = dict(tushare_daily_basic_map.get(ts_code, {}))
    if tushare_moneyflow_map is None:
        tushare_moneyflow = _load_tushare_moneyflow(db, ts_code, feature_row.trade_date)
    else:
        tushare_moneyflow = dict(tushare_moneyflow_map.get(ts_code, {}))
    if industry_moneyflow_map is None:
        industry_moneyflow = _load_tushare_industry_moneyflow(
            db,
            security.industry,
            feature_row.trade_date,
        )
    else:
        industry_moneyflow = dict(industry_moneyflow_map.get(security.industry or "", {}))
    if fundamental_context_map is None:
        fundamental_context = load_fundamental_context(
            db,
            feature_row.symbol,
            feature_row.trade_date,
        )
    else:
        fundamental_context = dict(fundamental_context_map.get(feature_row.symbol, {}))
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
            **tushare_daily_basic,
            **tushare_moneyflow,
            **industry_moneyflow,
            **fundamental_context,
        }
    )
    context.update(_sector_leadership_metrics(context))
    if sector_profile_map is None:
        sector_profile = load_sector_profile(db, security.industry)
    else:
        sector_profile = sector_profile_map.get(security.industry or "")
    if sector_profile is not None:
        context.setdefault("sector_style", sector_profile.sector_style)
        context.setdefault("analysis_framework", sector_profile.analysis_framework)
        context.setdefault("holding_style", sector_profile.preferred_holding_style)
        context.setdefault(
            "sector_key_drivers",
            (sector_profile.key_drivers_json or {}).get("drivers", []),
        )
    assessment = assess_fundamentals(context)
    context.update(
        {
            "fundamental_score": assessment.score,
            "fundamental_verdict": assessment.verdict,
            "fundamental_reasons": assessment.reasons,
        }
    )
    route = build_signal_route(context)
    context.update(
        {
            "route_score": route.route_score,
            "route_label": route.route_label,
            "route_reason": route.route_reason,
            "route_trend_score": route.trend_score,
            "route_participation_score": route.participation_score,
            "route_risk_score": route.risk_score,
            "route_momentum_score": route.momentum_score,
            "route_components": route.route_components,
        }
    )
    return context
