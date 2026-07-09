import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.engine.paper.learning_repository import (
    latest_review_date,
    load_learning_insights,
    load_recent_trade_reviews,
)
from services.engine.review.monthly_summary import generate_monthly_trade_summary
from services.engine.review.repository import load_latest_review_report
from services.shared.database import get_db
from services.shared.models import PaperTradeReview

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
_MARKET_SUMMARY_RE = re.compile(
    r"数据日期 (?P<trade_date>\d{4}-\d{2}-\d{2}).*?"
    r"上涨 (?P<up_count>\d+) / 下跌 (?P<down_count>\d+) / 平盘 (?P<flat_count>\d+)，"
    r"上涨占比 (?P<up_ratio>-?\d+(?:\.\d+)?)%，"
    r"平均涨跌 (?P<avg_change_pct>-?\d+(?:\.\d+)?)%，"
    r"成交额 (?P<total_amount>-?\d+(?:\.\d+)?)亿",
    re.S,
)
_AMOUNT_CHANGE_RE = re.compile(r"较前日成交额 (?P<amount_change_pct>-?\d+(?:\.\d+)?)%")


class LearningInsightResponse(BaseModel):
    scope_type: str
    scope_value: str
    sample_count: int
    avg_return: float
    avg_giveback: float
    verdict_counts: dict[str, int]
    summary: str
    suggestions: list[dict[str, Any]]


class TradeReviewResponse(BaseModel):
    id: int
    position_id: int
    symbol: str
    rule_id: str
    sector_code: str | None
    strategy_type: str
    entry_date: date
    exit_date: date
    holding_days: int
    pnl_pct: float
    mfe_pct: float
    mae_pct: float
    giveback_pct: float
    exit_reason: str
    signal_tags: list[str]
    alert_summary: dict[str, Any]
    verdict: str
    summary: str


class PaperLearningOverviewResponse(BaseModel):
    latest_review_date: str | None
    insights: list[LearningInsightResponse]
    recent_reviews: list[TradeReviewResponse]


class MechanicalReviewResponse(BaseModel):
    report_date: str | None
    report_type: str
    title: str
    content_md: str
    metrics: dict[str, Any]
    found: bool


class MonthlySummaryResponse(BaseModel):
    month: str
    paper_review_count: int
    backtest_trade_count: int
    winning_reviews: int
    losing_reviews: int
    total_pnl: float
    avg_review_return: float | None
    avg_backtest_return: float | None
    top_symbols: list[dict[str, Any]]
    top_rules: list[dict[str, Any]]
    factor_insights: list[dict[str, Any]]
    sector_opportunities: list[dict[str, Any]]
    excluded_symbols: list[str]
    content_md: str


def _review_to_response(item: PaperTradeReview) -> TradeReviewResponse:
    return TradeReviewResponse(
        id=item.id,
        position_id=item.position_id,
        symbol=item.symbol,
        rule_id=item.rule_id,
        sector_code=item.sector_code,
        strategy_type=item.strategy_type,
        entry_date=item.entry_date,
        exit_date=item.exit_date,
        holding_days=item.holding_days,
        pnl_pct=float(item.pnl_pct),
        mfe_pct=float(item.mfe_pct),
        mae_pct=float(item.mae_pct),
        giveback_pct=float(item.giveback_pct),
        exit_reason=item.exit_reason,
        signal_tags=(item.signal_tags_json or {}).get("items", []),
        alert_summary=item.alert_summary_json or {},
        verdict=item.verdict,
        summary=item.summary,
    )


def _pct_to_decimal(value: str) -> float:
    return float(Decimal(value) / Decimal("100"))


def _amount_yi_to_yuan(value: str) -> float:
    return float(Decimal(value) * Decimal("100000000"))


def _review_metrics_with_legacy_market_summary(
    metrics: dict[str, Any],
    content_md: str,
) -> dict[str, Any]:
    if metrics.get("market_summary"):
        return metrics
    market_match = _MARKET_SUMMARY_RE.search(content_md)
    if not market_match:
        return metrics

    enriched = dict(metrics)
    summary: dict[str, Any] = {
        "trade_date": market_match.group("trade_date"),
        "up_count": int(market_match.group("up_count")),
        "down_count": int(market_match.group("down_count")),
        "flat_count": int(market_match.group("flat_count")),
        "up_ratio": _pct_to_decimal(market_match.group("up_ratio")),
        "avg_change_pct": _pct_to_decimal(market_match.group("avg_change_pct")),
        "total_amount": _amount_yi_to_yuan(market_match.group("total_amount")),
    }
    amount_change_match = _AMOUNT_CHANGE_RE.search(content_md)
    if amount_change_match:
        summary["amount_change_pct"] = _pct_to_decimal(
            amount_change_match.group("amount_change_pct")
        )
    enriched["market_summary"] = summary
    return enriched


@router.get("/overview", response_model=PaperLearningOverviewResponse)
def get_learning_overview(
    db: DbSession,
    report_date: str | None = None,
    scope_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> PaperLearningOverviewResponse:
    effective_date = report_date or latest_review_date(db)
    insights = (
        load_learning_insights(db, report_date=effective_date, scope_type=scope_type)
        if effective_date
        else []
    )
    reviews = load_recent_trade_reviews(db, limit=limit)
    return PaperLearningOverviewResponse(
        latest_review_date=effective_date,
        insights=[LearningInsightResponse(**item) for item in insights],
        recent_reviews=[_review_to_response(item) for item in reviews],
    )


@router.get("/reviews", response_model=list[TradeReviewResponse])
def list_trade_reviews(
    db: DbSession,
    symbol: str | None = None,
    rule_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TradeReviewResponse]:
    return [
        _review_to_response(item)
        for item in load_recent_trade_reviews(
            db,
            symbol=symbol,
            rule_id=rule_id,
            limit=limit,
            offset=offset,
        )
    ]


@router.get("/mechanical-review", response_model=MechanicalReviewResponse)
def get_mechanical_review(
    db: DbSession,
    before_report_date: str | None = None,
) -> MechanicalReviewResponse:
    report = load_latest_review_report(
        db,
        "daily_mechanical",
        before_report_date=before_report_date,
    )
    if report is None:
        return MechanicalReviewResponse(
            report_date=None,
            report_type="daily_mechanical",
            title="暂无盘后复盘",
            content_md="",
            metrics={},
            found=False,
        )
    return MechanicalReviewResponse(
        report_date=report.report_date.isoformat(),
        report_type=report.report_type,
        title=f"{report.report_date.isoformat()} 收盘总体复盘",
        content_md=report.content_md,
        metrics=_review_metrics_with_legacy_market_summary(
            report.metrics_json or {},
            report.content_md,
        ),
        found=True,
    )


@router.get("/monthly-summary", response_model=MonthlySummaryResponse)
def get_monthly_summary(month: str) -> MonthlySummaryResponse:
    summary = generate_monthly_trade_summary(month)
    return MonthlySummaryResponse(
        month=summary.month,
        paper_review_count=summary.paper_review_count,
        backtest_trade_count=summary.backtest_trade_count,
        winning_reviews=summary.winning_reviews,
        losing_reviews=summary.losing_reviews,
        total_pnl=summary.total_pnl,
        avg_review_return=summary.avg_review_return,
        avg_backtest_return=summary.avg_backtest_return,
        top_symbols=summary.top_symbols,
        top_rules=summary.top_rules,
        factor_insights=summary.factor_insights,
        sector_opportunities=summary.sector_opportunities,
        excluded_symbols=summary.excluded_symbols,
        content_md=summary.content_md,
    )
