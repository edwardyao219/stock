from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from math import ceil
from threading import Lock
from time import monotonic
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.collector.akshare_client import (
    RealtimeQuoteRow,
    fetch_realtime_quotes,
    fetch_sina_realtime_quotes,
)
from services.engine.features.health import (
    DAILY_CANDIDATE_MIN_COVERAGE_RATIO,
    inspect_daily_data_health,
)
from services.engine.news.catalysts import (
    build_sector_catalyst_report,
    fetch_market_hot_messages,
)
from services.engine.news.repository import (
    load_recent_message_snapshot,
    snapshot_to_report,
    store_message_snapshot,
)
from services.engine.review.sector_replay import replay_sector_month
from services.engine.sector.names import canonical_sector_name as _canonical_sector_name
from services.engine.tracking.mainline import list_confirmed_mainline_outcomes
from services.shared.database import get_db
from services.shared.models import (
    DailyBar,
    IntradayMarketTurnSnapshot,
    RealtimeQuote,
    SectorDaily,
    SectorFeatureDaily,
    Security,
    TushareMoneyflowIndDc,
)
from services.shared.time import now_local

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
LIVE_MARKET_CACHE_SECONDS = 15.0
LIVE_MARKET_TIMEOUT_SECONDS = 1.0
LIVE_MARKET_SYMBOL_BATCH_SIZE = 500
_LIVE_MARKET_CACHE: tuple[float, "MarketOverviewResponse"] | None = None
_LIVE_MARKET_LOCK = Lock()
_LIVE_MARKET_FUTURE: Future | None = None
_LIVE_MARKET_FUTURE_LOCK = Lock()
_LIVE_MARKET_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-live")
SECTOR_CATALYST_CACHE_SECONDS = 300.0
_SECTOR_CATALYST_CACHE: tuple[float, int, "SectorCatalystResponse"] | None = None
_SECTOR_CATALYST_LOCK = Lock()
SECTOR_OVERVIEW_CACHE_SECONDS = 15.0
_SECTOR_OVERVIEW_CACHE: tuple[float, int | None, "SectorOverviewResponse"] | None = None
_SECTOR_OVERVIEW_LOCK = Lock()
SECTOR_FEATURE_MIN_COVERAGE_RATIO = 0.80
MARKET_DAILY_MIN_COVERAGE_RATIO = DAILY_CANDIDATE_MIN_COVERAGE_RATIO
TARGET_INDEXES = (
    ("sh000001", "上证", ("sh000001", "000001")),
    ("sz399001", "深成", ("sz399001", "399001")),
    ("sz399006", "创业板", ("sz399006", "399006")),
)
TARGET_INDEX_BY_SOURCE_CODE = {
    source_code: (canonical_code, name)
    for canonical_code, name, source_codes in TARGET_INDEXES
    for source_code in source_codes
}


class CandleResponse(BaseModel):
    time: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    amount: float | None
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None


class MarketIndexResponse(BaseModel):
    code: str
    name: str
    quote_date: date | None
    price: float | None
    change_pct: float | None
    amount: float | None
    source: str


class MarketOverviewResponse(BaseModel):
    trade_date: date | None
    stock_count: int
    up_count: int
    down_count: int
    flat_count: int
    up_ratio: float | None
    avg_change_pct: float | None
    total_amount: float | None
    amount_change_pct: float | None
    active_security_count: int
    coverage_ratio: float | None
    is_full_market: bool
    message: str
    is_live_snapshot: bool = False
    is_current_snapshot: bool = False
    snapshot_scope_label: str = "最近交易日"
    stress_status: str = "neutral"
    stress_label: str = "中性"
    stress_score: float = 0.0
    stress_reasons: list[str] = Field(default_factory=list)
    stress_scope_label: str = "最近交易日压力"
    risk_action_label: str = "按原计划精选"
    indexes: list[MarketIndexResponse] = Field(default_factory=list)


class CrossDayMainlineSectorResponse(BaseModel):
    sector: str
    status: str
    reason: str
    baseline_up_ratio: float | None = None
    baseline_avg_change_pct: float | None = None
    baseline_leader_change_pct: float | None = None
    current_up_ratio: float | None = None
    current_avg_change_pct: float | None = None
    current_leader_change_pct: float | None = None


class CrossDayMainlineResponse(BaseModel):
    status: str
    summary: str
    baseline_trade_date: str | None = None
    checkpoint: str
    confirmed_sectors: list[str] = Field(default_factory=list)
    sectors: list[CrossDayMainlineSectorResponse] = Field(default_factory=list)


class MainlineOutcomeHorizonResponse(BaseModel):
    horizon: int
    status: str
    return_pct: float | None


class ConfirmedMainlineOutcomeResponse(BaseModel):
    signal_date: str
    sector: str
    leader_symbol: str
    horizons: list[MainlineOutcomeHorizonResponse] = Field(default_factory=list)


class IntradayMarketTurnResponse(BaseModel):
    trade_date: date | None
    snapshot_time: datetime | None
    key: str
    label: str
    summary: str
    data_ready: bool
    startup_watch_allowed: bool
    core_action_allowed: bool
    coverage_ratio: float | None
    breadth_ratio: float | None
    index_change_pct: float | None
    sector_expansion_count: int | None
    confirmed_signals: list[str] = Field(default_factory=list)
    pending_signals: list[str] = Field(default_factory=list)
    expanding_sectors: list["IntradayExpandingSectorResponse"] = Field(default_factory=list)
    sustained_expanding_sectors: list["IntradaySustainedExpandingSectorResponse"] = Field(
        default_factory=list
    )
    leading_sustained_sectors: list["IntradayLeadingSectorResponse"] = Field(
        default_factory=list
    )
    cross_day_mainline: CrossDayMainlineResponse | None = None


class IntradayExpandingSectorResponse(BaseModel):
    sector: str
    symbol_count: int
    up_count: int
    up_ratio: float
    avg_change_pct: float
    total_amount: float | None = None
    leader_symbol: str | None = None
    leader_change_pct: float | None = None


class IntradaySustainedExpandingSectorResponse(IntradayExpandingSectorResponse):
    prior_up_ratio: float
    prior_avg_change_pct: float
    consecutive_snapshots: int


class IntradayLeadingSectorResponse(IntradaySustainedExpandingSectorResponse):
    total_amount: float
    leader_symbol: str
    leader_change_pct: float


class DataHealthIssueResponse(BaseModel):
    code: str
    severity: str
    message: str
    metric: str
    value: float | int | None
    threshold: float | int | None


def _market_stress_policy(
    *,
    up_ratio: float | None,
    avg_change_pct: float | None,
    amount_change_pct: float | None,
) -> dict[str, object]:
    score = 0.0
    reasons: list[str] = []

    if up_ratio is not None:
        if up_ratio <= 0.25:
            score += 45.0
            reasons.append(f"上涨占比仅{up_ratio:.0%}，市场宽度明显不足")
        elif up_ratio <= 0.35:
            score += 30.0
            reasons.append(f"上涨占比{up_ratio:.0%}，弱势面较宽")
        elif up_ratio <= 0.45:
            score += 15.0
            reasons.append(f"上涨占比{up_ratio:.0%}，赚钱效应偏弱")

    if avg_change_pct is not None:
        if avg_change_pct <= -0.02:
            score += 35.0
            reasons.append(f"平均涨跌{avg_change_pct:+.2%}，全市场跌幅较深")
        elif avg_change_pct <= -0.01:
            score += 20.0
            reasons.append(f"平均涨跌{avg_change_pct:+.2%}，市场明显回落")
        elif avg_change_pct < 0:
            score += 8.0
            reasons.append(f"平均涨跌{avg_change_pct:+.2%}，市场小幅偏弱")

    if amount_change_pct is not None and avg_change_pct is not None:
        if amount_change_pct >= 0.30 and avg_change_pct < 0:
            score += 15.0
            reasons.append("放量下跌，先降低交易频率")
        elif amount_change_pct <= -0.20 and (up_ratio or 0.5) <= 0.45:
            score += 8.0
            reasons.append("缩量弱势，反弹确认度不足")

    if score >= 70.0:
        status = "risk_off"
        label = "压力大"
        action = "停止扩散，只做观察和风控"
    elif score >= 40.0:
        status = "caution"
        label = "谨慎"
        action = "降低频率，等盘中确认"
    elif (
        up_ratio is not None
        and avg_change_pct is not None
        and up_ratio >= 0.55
        and avg_change_pct >= 0.005
    ):
        status = "supportive"
        label = "偏暖"
        action = "允许顺势，但不追高"
    else:
        status = "neutral"
        label = "中性"
        action = "按原计划精选"

    return {
        "stress_status": status,
        "stress_label": label,
        "stress_score": round(score, 2),
        "stress_reasons": reasons or ["没有明显全市场压力信号"],
        "risk_action_label": action,
    }


def _market_snapshot_scope(
    *,
    trade_date: date | None,
    is_live: bool,
    today: date | None = None,
) -> dict[str, object]:
    current_date = today or now_local().date()
    is_current = bool(is_live and trade_date == current_date)

    if trade_date is None:
        snapshot_scope_label = "暂无行情"
        stress_scope_label = "盘面压力"
    elif is_current:
        snapshot_scope_label = "盘中实时"
        stress_scope_label = "今日压力"
    elif is_live:
        snapshot_scope_label = "实时源非今日"
        stress_scope_label = "最近交易日压力"
    else:
        snapshot_scope_label = "最近交易日"
        stress_scope_label = "最近交易日压力"

    return {
        "is_live_snapshot": is_live,
        "is_current_snapshot": is_current,
        "snapshot_scope_label": snapshot_scope_label,
        "stress_scope_label": stress_scope_label,
    }


class DataHealthResponse(BaseModel):
    trade_date: date | None
    status: str
    daily_bar_count: int
    feature_count: int
    previous_daily_bar_count: int
    amount_missing_ratio: float | None
    previous_amount_missing_ratio: float | None
    amount_ratio_5d_median: float | None
    amount_ratio_5d_p10: float | None
    volume_confirmation_median: float | None
    amount_volume_multiplier_median: float | None
    previous_amount_volume_multiplier_median: float | None
    expected_security_count: int
    eligible_daily_bar_count: int
    daily_coverage_ratio: float
    candidate_generation_allowed: bool
    candidate_block_reasons: list[str] = Field(default_factory=list)
    issues: list[DataHealthIssueResponse] = Field(default_factory=list)


class SectorOverviewItem(BaseModel):
    sector_code: str
    sector_name: str
    canonical_sector_name: str | None = None
    trade_date: date | None
    month_start_date: date | None
    month_rank: int | None
    monthly_return_pct: float | None
    day_change_pct: float | None
    amount: float | None
    fund_flow_net_amount: float | None
    fund_flow_rate: float | None
    sector_strength_score: float | None
    sector_breadth_score: float | None
    sector_momentum_score: float | None
    sector_stock_count: int | None
    sector_up_count: int | None
    sector_gate_score: float | None = None
    sector_gate_label: str | None = None
    sector_gate_reasons: list[str] = Field(default_factory=list)


class SectorGateSummaryResponse(BaseModel):
    main_allowed_count: int = 0
    observe_count: int = 0
    cooldown_count: int = 0
    unknown_count: int = 0


class SectorOverviewResponse(BaseModel):
    trade_date: date | None
    month_start_date: date | None
    feature_trade_date: date | None = None
    moneyflow_trade_date: date | None = None
    feature_sector_count: int = 0
    overview_sector_count: int = 0
    feature_coverage_ratio: float | None = None
    moneyflow_sector_count: int = 0
    moneyflow_missing_count: int = 0
    moneyflow_coverage_ratio: float | None = None
    moneyflow_reliability_label: str = "资金流缺失"
    sector_gate_summary: SectorGateSummaryResponse = Field(
        default_factory=SectorGateSummaryResponse
    )
    sectors: list[SectorOverviewItem] = Field(default_factory=list)
    monthly_rank: list[SectorOverviewItem] = Field(default_factory=list)
    activity_rank: list[SectorOverviewItem] = Field(default_factory=list)
    continuity_rank: list[SectorOverviewItem] = Field(default_factory=list)


class SectorCatalystItemResponse(BaseModel):
    sector_name: str
    catalyst_score: float
    catalyst_label: str
    keywords: list[str] = Field(default_factory=list)
    related_sectors: list[str] = Field(default_factory=list)
    source_titles: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class SectorCatalystResponse(BaseModel):
    as_of: datetime
    source_count: int
    catalysts: list[SectorCatalystItemResponse] = Field(default_factory=list)
    message: str
    snapshot_id: int | None = None
    snapshot_trade_date: str | None = None
    stored: bool = False


class SectorReplayEventResponse(BaseModel):
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


class SectorReplayResponse(BaseModel):
    month: str
    sector: str
    events: list[SectorReplayEventResponse] = Field(default_factory=list)


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _moving_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    running_sum = 0.0
    for index, value in enumerate(values):
        running_sum += value
        if index >= window:
            running_sum -= values[index - window]
        if index + 1 < window:
            result.append(None)
        else:
            result.append(running_sum / window)
    return result


def _change_pct(item: DailyBar) -> float | None:
    if item.pre_close is None or float(item.pre_close) <= 0:
        return None
    return float(item.close) / float(item.pre_close) - 1


def _quote_change_pct(item: RealtimeQuoteRow) -> float | None:
    if item.price is None or item.pre_close is None or item.pre_close <= 0:
        return None
    return float(item.price / item.pre_close - Decimal("1"))


def _symbol_batches(symbols: list[str], batch_size: int) -> list[list[str]]:
    return [symbols[index : index + batch_size] for index in range(0, len(symbols), batch_size)]


def _active_live_symbols(db: Session) -> list[str]:
    return list(
        db.execute(
            select(Security.symbol)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
            .order_by(Security.symbol)
        ).scalars()
    )


def _sum_amount(items: list[DailyBar]) -> float:
    return sum(float(item.amount or 0) for item in items)


def _to_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_index_rows_from_spot(
    df: pd.DataFrame,
    *,
    source: str,
) -> list[MarketIndexResponse]:
    rows_by_code: dict[str, MarketIndexResponse] = {}
    quote_date = now_local().date()
    for raw in df.to_dict("records"):
        source_code = str(raw.get("代码") or "").strip()
        target = TARGET_INDEX_BY_SOURCE_CODE.get(source_code)
        if target is None:
            continue
        canonical_code, name = target
        change_pct = _to_float(raw.get("涨跌幅"))
        rows_by_code[canonical_code] = MarketIndexResponse(
            code=canonical_code,
            name=name,
            quote_date=quote_date,
            price=_to_float(raw.get("最新价")),
            change_pct=change_pct / 100 if change_pct is not None else None,
            amount=_to_float(raw.get("成交额")),
            source=source,
        )
    return [
        rows_by_code[canonical_code]
        for canonical_code, _, _ in TARGET_INDEXES
        if canonical_code in rows_by_code
    ]


def _sina_quote_date(parts: list[str]) -> date | None:
    for value in parts:
        text = value.strip()
        if len(text) != 10 or text[4] != "-" or text[7] != "-":
            continue
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    return None


def _live_market_indexes() -> list[MarketIndexResponse]:
    import akshare as ak

    df = ak.stock_zh_index_spot_sina()
    return _market_index_rows_from_spot(df, source="akshare.stock_zh_index_spot_sina")


def _eastmoney_live_market_indexes() -> list[MarketIndexResponse]:
    import akshare as ak

    df = ak.stock_zh_index_spot_em()
    return _market_index_rows_from_spot(df, source="akshare.stock_zh_index_spot_em")


def _sina_direct_live_market_indexes() -> list[MarketIndexResponse]:
    import requests

    source_codes = ",".join(canonical_code for canonical_code, _, _ in TARGET_INDEXES)
    response = requests.get(
        f"https://hq.sinajs.cn/list={source_codes}",
        headers={
            "Referer": "https://finance.sina.com.cn/",
            "User-Agent": "Mozilla/5.0",
        },
        timeout=8,
    )
    response.raise_for_status()
    rows_by_code: dict[str, MarketIndexResponse] = {}
    for line in response.content.decode("gbk", errors="replace").splitlines():
        assignment, _, value = line.partition("=")
        source_code = assignment.rsplit("_", maxsplit=1)[-1].strip()
        target = TARGET_INDEX_BY_SOURCE_CODE.get(source_code)
        if target is None:
            continue
        payload = value.strip().rstrip(";").strip()
        if payload.startswith('"') and payload.endswith('"'):
            payload = payload[1:-1]
        parts = payload.split(",")
        if len(parts) < 10:
            continue
        canonical_code, name = target
        pre_close = _to_float(parts[2])
        price = _to_float(parts[3])
        change_pct = (
            round(price / pre_close - 1, 6)
            if price is not None and pre_close is not None and pre_close > 0
            else None
        )
        rows_by_code[canonical_code] = MarketIndexResponse(
            code=canonical_code,
            name=name,
            quote_date=_sina_quote_date(parts) or now_local().date(),
            price=price,
            change_pct=change_pct,
            amount=_to_float(parts[9]),
            source="sina.hq.sinajs.cn",
        )
    return [
        rows_by_code[canonical_code]
        for canonical_code, _, _ in TARGET_INDEXES
        if canonical_code in rows_by_code
    ]


def _safe_live_market_indexes() -> list[MarketIndexResponse]:
    for loader in (
        _live_market_indexes,
        _sina_direct_live_market_indexes,
        _eastmoney_live_market_indexes,
    ):
        try:
            rows = loader()
        except Exception:
            continue
        if rows:
            return rows
    return []


def _eastmoney_a_share_overview() -> MarketOverviewResponse:
    quotes = fetch_realtime_quotes()
    changes = [value for item in quotes if (value := _quote_change_pct(item)) is not None]
    if not changes:
        raise ValueError("No live A-share quote changes available")

    up_count = sum(1 for value in changes if value > 0)
    down_count = sum(1 for value in changes if value < 0)
    flat_count = len(changes) - up_count - down_count
    total_amount = sum(float(item.amount or 0) for item in quotes)
    stock_count = len(changes)
    up_ratio = up_count / stock_count if stock_count else None
    avg_change_pct = round(sum(changes) / stock_count, 6) if stock_count else None
    trade_date = max((item.trade_date for item in quotes), default=None)
    parsed_trade_date = date.fromisoformat(trade_date) if trade_date else None
    return MarketOverviewResponse(
        trade_date=parsed_trade_date,
        stock_count=stock_count,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        up_ratio=up_ratio,
        avg_change_pct=avg_change_pct,
        total_amount=total_amount,
        amount_change_pct=None,
        active_security_count=len(quotes),
        coverage_ratio=1.0,
        is_full_market=True,
        message=(
            f"A股实时全市场快照：上涨 {up_count}，下跌 {down_count}，"
            f"平盘 {flat_count}；统计样本 {stock_count}/{len(quotes)}。"
        ),
        **_market_stress_policy(
            up_ratio=up_ratio,
            avg_change_pct=avg_change_pct,
            amount_change_pct=None,
        ),
        **_market_snapshot_scope(trade_date=parsed_trade_date, is_live=True),
        indexes=_safe_live_market_indexes(),
    )


def _sina_a_share_overview() -> MarketOverviewResponse:
    import akshare as ak

    df = ak.stock_zh_a_spot()
    changes = pd.to_numeric(df.get("涨跌幅"), errors="coerce").dropna() / 100
    if changes.empty:
        raise ValueError("No Sina A-share quote changes available")
    amount = pd.to_numeric(df.get("成交额"), errors="coerce").fillna(0)
    up_count = int((changes > 0).sum())
    down_count = int((changes < 0).sum())
    flat_count = int((changes == 0).sum())
    stock_count = int(changes.count())
    up_ratio = up_count / stock_count if stock_count else None
    avg_change_pct = round(float(changes.mean()), 6) if stock_count else None
    total_rows = int(len(df))
    trade_date = now_local().date()
    return MarketOverviewResponse(
        trade_date=trade_date,
        stock_count=stock_count,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        up_ratio=up_ratio,
        avg_change_pct=avg_change_pct,
        total_amount=float(amount.sum()),
        amount_change_pct=None,
        active_security_count=total_rows,
        coverage_ratio=1.0,
        is_full_market=True,
        message=(
            f"A股实时全市场快照：上涨 {up_count}，下跌 {down_count}，"
            f"平盘 {flat_count}；统计样本 {stock_count}/{total_rows}。"
        ),
        **_market_stress_policy(
            up_ratio=up_ratio,
            avg_change_pct=avg_change_pct,
            amount_change_pct=None,
        ),
        **_market_snapshot_scope(trade_date=trade_date, is_live=True),
        indexes=_safe_live_market_indexes(),
    )


def _sina_symbol_live_a_share_overview(db: Session) -> MarketOverviewResponse:
    symbols = _active_live_symbols(db)
    if not symbols:
        raise ValueError("No active A-share symbols available for Sina live snapshot")

    quotes: list[RealtimeQuoteRow] = []
    failed_batches = 0
    for batch in _symbol_batches(symbols, LIVE_MARKET_SYMBOL_BATCH_SIZE):
        try:
            quotes.extend(fetch_sina_realtime_quotes(set(batch)))
        except Exception:
            failed_batches += 1

    latest_trade_date_text = max(
        (item.trade_date for item in quotes if item.trade_date),
        default=None,
    )
    if not latest_trade_date_text:
        raise ValueError("No Sina live quote dates available")

    latest_quotes = [item for item in quotes if item.trade_date == latest_trade_date_text]
    changes = [value for item in latest_quotes if (value := _quote_change_pct(item)) is not None]
    if not changes:
        raise ValueError("No Sina live quote changes available")

    up_count = sum(1 for value in changes if value > 0)
    down_count = sum(1 for value in changes if value < 0)
    flat_count = len(changes) - up_count - down_count
    stock_count = len(changes)
    active_security_count = len(symbols)
    coverage_ratio = (
        round(stock_count / active_security_count, 6) if active_security_count else None
    )
    up_ratio = up_count / stock_count if stock_count else None
    avg_change_pct = round(sum(changes) / stock_count, 6) if stock_count else None
    total_amount = sum(float(item.amount or 0) for item in latest_quotes)
    parsed_trade_date = date.fromisoformat(latest_trade_date_text)
    stale_quote_count = len(quotes) - len(latest_quotes)
    is_full_market = bool(
        coverage_ratio is not None and coverage_ratio >= MARKET_DAILY_MIN_COVERAGE_RATIO
    )
    quality_notes = [f"统计样本 {stock_count}/{active_security_count}"]
    if stale_quote_count:
        quality_notes.append(f"旧日期 {stale_quote_count}")
    if failed_batches:
        quality_notes.append(f"失败批次 {failed_batches}")

    return MarketOverviewResponse(
        trade_date=parsed_trade_date,
        stock_count=stock_count,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        up_ratio=up_ratio,
        avg_change_pct=avg_change_pct,
        total_amount=total_amount,
        amount_change_pct=None,
        active_security_count=active_security_count,
        coverage_ratio=coverage_ratio,
        is_full_market=is_full_market,
        message=(
            f"A股新浪分批实时快照：上涨 {up_count}，下跌 {down_count}，"
            f"平盘 {flat_count}；{'；'.join(quality_notes)}。"
        ),
        **_market_stress_policy(
            up_ratio=up_ratio,
            avg_change_pct=avg_change_pct,
            amount_change_pct=None,
        ),
        **_market_snapshot_scope(trade_date=parsed_trade_date, is_live=True),
        indexes=_safe_live_market_indexes(),
    )


def _try_sina_symbol_live_a_share_overview(db: Session) -> MarketOverviewResponse | None:
    try:
        return _sina_symbol_live_a_share_overview(db)
    except Exception:
        return None


def _store_live_market_cache(overview: MarketOverviewResponse) -> None:
    global _LIVE_MARKET_CACHE
    with _LIVE_MARKET_LOCK:
        _LIVE_MARKET_CACHE = (monotonic(), overview)


def _live_a_share_overview() -> MarketOverviewResponse:
    try:
        return _eastmoney_a_share_overview()
    except Exception:
        return _sina_a_share_overview()


def _cached_live_a_share_overview() -> MarketOverviewResponse:
    global _LIVE_MARKET_CACHE
    current = monotonic()
    if (
        _LIVE_MARKET_CACHE is not None
        and current - _LIVE_MARKET_CACHE[0] <= LIVE_MARKET_CACHE_SECONDS
    ):
        return _LIVE_MARKET_CACHE[1]
    with _LIVE_MARKET_LOCK:
        current = monotonic()
        if (
            _LIVE_MARKET_CACHE is not None
            and current - _LIVE_MARKET_CACHE[0] <= LIVE_MARKET_CACHE_SECONDS
        ):
            return _LIVE_MARKET_CACHE[1]
        overview = _live_a_share_overview()
        _LIVE_MARKET_CACHE = (monotonic(), overview)
        return overview


def _try_cached_live_a_share_overview(timeout_seconds: float) -> MarketOverviewResponse | None:
    global _LIVE_MARKET_FUTURE
    current = monotonic()
    if (
        _LIVE_MARKET_CACHE is not None
        and current - _LIVE_MARKET_CACHE[0] <= LIVE_MARKET_CACHE_SECONDS
    ):
        return _LIVE_MARKET_CACHE[1]

    with _LIVE_MARKET_FUTURE_LOCK:
        if _LIVE_MARKET_FUTURE is None or _LIVE_MARKET_FUTURE.done():
            _LIVE_MARKET_FUTURE = _LIVE_MARKET_EXECUTOR.submit(_cached_live_a_share_overview)
        future = _LIVE_MARKET_FUTURE

    try:
        overview = future.result(timeout=timeout_seconds)
    except TimeoutError:
        return None
    except Exception:
        with _LIVE_MARKET_FUTURE_LOCK:
            if _LIVE_MARKET_FUTURE is future:
                _LIVE_MARKET_FUTURE = None
        return None

    with _LIVE_MARKET_FUTURE_LOCK:
        if _LIVE_MARKET_FUTURE is future:
            _LIVE_MARKET_FUTURE = None
    return overview


def _stored_market_overview(db: Session) -> MarketOverviewResponse:
    latest_date = _latest_well_covered_daily_bar_date(db)
    if latest_date is None:
        return MarketOverviewResponse(
            trade_date=None,
            stock_count=0,
            up_count=0,
            down_count=0,
            flat_count=0,
            up_ratio=None,
            avg_change_pct=None,
            total_amount=None,
            amount_change_pct=None,
            active_security_count=0,
            coverage_ratio=None,
            is_full_market=False,
            message="暂无行情数据。",
            **_market_stress_policy(
                up_ratio=None,
                avg_change_pct=None,
                amount_change_pct=None,
            ),
            **_market_snapshot_scope(trade_date=None, is_live=False),
            indexes=_safe_live_market_indexes(),
        )

    bars = list(
        db.execute(select(DailyBar).where(DailyBar.trade_date == latest_date)).scalars()
    )
    changes = [value for item in bars if (value := _change_pct(item)) is not None]
    up_count = sum(1 for value in changes if value > 0)
    down_count = sum(1 for value in changes if value < 0)
    flat_count = len(changes) - up_count - down_count
    total_amount = _sum_amount(bars)

    previous_date = db.execute(
        select(func.max(DailyBar.trade_date)).where(DailyBar.trade_date < latest_date)
    ).scalar_one_or_none()
    previous_amount = 0.0
    if previous_date is not None:
        previous_bars = list(
            db.execute(select(DailyBar).where(DailyBar.trade_date == previous_date)).scalars()
        )
        previous_amount = _sum_amount(previous_bars)

    amount_change_pct = (
        round(total_amount / previous_amount - 1, 6) if previous_amount > 0 else None
    )
    stock_count = len(changes)
    up_ratio = up_count / stock_count if stock_count else None
    avg_change_pct = round(sum(changes) / stock_count, 6) if stock_count else None
    active_security_count = int(
        db.execute(
            select(func.count())
            .select_from(Security)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).scalar_one()
    )
    coverage_ratio = (
        round(stock_count / active_security_count, 6) if active_security_count else None
    )
    is_full_market = bool(coverage_ratio is not None and coverage_ratio >= 0.80)

    return MarketOverviewResponse(
        trade_date=latest_date,
        stock_count=stock_count,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        up_ratio=up_ratio,
        avg_change_pct=avg_change_pct,
        total_amount=total_amount,
        amount_change_pct=amount_change_pct,
        active_security_count=active_security_count,
        coverage_ratio=coverage_ratio,
        is_full_market=is_full_market,
        message=(
            f"{latest_date.isoformat()} 上涨 {up_count}，下跌 {down_count}，"
            f"平盘 {flat_count}；统计样本 {stock_count}/{active_security_count}。"
        ),
        **_market_stress_policy(
            up_ratio=up_ratio,
            avg_change_pct=avg_change_pct,
            amount_change_pct=amount_change_pct,
        ),
        **_market_snapshot_scope(trade_date=latest_date, is_live=False),
        indexes=_safe_live_market_indexes(),
    )


def _stored_full_market_realtime_overview(db: Session) -> MarketOverviewResponse | None:
    current_trade_date = now_local().date()
    active_security_count = int(
        db.execute(
            select(func.count())
            .select_from(Security)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).scalar_one()
    )
    minimum_count = max(1, ceil(active_security_count * MARKET_DAILY_MIN_COVERAGE_RATIO))
    snapshots = db.execute(
        select(
            RealtimeQuote.trade_date,
            RealtimeQuote.quote_time,
            func.count().label("quote_count"),
        )
        .join(Security, Security.symbol == RealtimeQuote.symbol)
        .where(Security.is_active.is_(True))
        .where(Security.is_st.is_(False))
        .where(RealtimeQuote.trade_date == current_trade_date)
        .where(RealtimeQuote.price.is_not(None))
        .where(RealtimeQuote.pre_close.is_not(None))
        .where(RealtimeQuote.pre_close > 0)
        .group_by(RealtimeQuote.trade_date, RealtimeQuote.quote_time)
        .order_by(RealtimeQuote.quote_time.desc())
    ).all()
    snapshot = next((item for item in snapshots if int(item.quote_count) >= minimum_count), None)
    if snapshot is None:
        return None

    rows = list(
        db.execute(
            select(RealtimeQuote)
            .join(Security, Security.symbol == RealtimeQuote.symbol)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
            .where(RealtimeQuote.trade_date == snapshot.trade_date)
            .where(RealtimeQuote.quote_time == snapshot.quote_time)
        ).scalars()
    )
    changes = [
        float(item.price / item.pre_close - Decimal("1"))
        for item in rows
        if item.price is not None and item.pre_close is not None and item.pre_close > 0
    ]
    if not changes:
        return None

    up_count = sum(1 for value in changes if value > 0)
    down_count = sum(1 for value in changes if value < 0)
    flat_count = len(changes) - up_count - down_count
    stock_count = len(changes)
    coverage_ratio = (
        round(stock_count / active_security_count, 6) if active_security_count else None
    )
    trade_date = snapshot.trade_date
    scope = _market_snapshot_scope(trade_date=trade_date, is_live=True)
    if scope["is_current_snapshot"]:
        scope["snapshot_scope_label"] = "当日全市场归档"
        scope["stress_scope_label"] = "今日归档压力"
    return MarketOverviewResponse(
        trade_date=trade_date,
        stock_count=stock_count,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        up_ratio=up_count / stock_count if stock_count else None,
        avg_change_pct=round(sum(changes) / stock_count, 6) if stock_count else None,
        total_amount=sum(float(item.amount or 0) for item in rows),
        amount_change_pct=None,
        active_security_count=active_security_count,
        coverage_ratio=coverage_ratio,
        is_full_market=True,
        message=(
            f"A股全市场归档快照：上涨 {up_count}，下跌 {down_count}，"
            f"平盘 {flat_count}；统计样本 {stock_count}/{active_security_count}。"
        ),
        **_market_stress_policy(
            up_ratio=up_count / stock_count if stock_count else None,
            avg_change_pct=round(sum(changes) / stock_count, 6) if stock_count else None,
            amount_change_pct=None,
        ),
        **scope,
        indexes=_safe_live_market_indexes(),
    )


def _latest_well_covered_daily_bar_date(db: Session) -> date | None:
    rows = list(
        db.execute(
            select(DailyBar.trade_date, func.count().label("bar_count"))
            .group_by(DailyBar.trade_date)
            .order_by(DailyBar.trade_date.desc())
        ).all()
    )
    if not rows:
        return None

    max_count = max(int(row.bar_count) for row in rows)
    min_count = max(1, ceil(max_count * MARKET_DAILY_MIN_COVERAGE_RATIO))
    for row in rows:
        if int(row.bar_count) >= min_count:
            return row.trade_date
    return rows[0].trade_date


def _month_start(trade_date: date) -> date:
    return date(trade_date.year, trade_date.month, 1)


def _sector_features_by_name(db: Session, trade_date: date) -> dict[str, dict]:
    rows = db.execute(
        select(SectorFeatureDaily).where(SectorFeatureDaily.trade_date == trade_date)
    ).scalars()
    return {str(row.sector_code): dict(row.features or {}) for row in rows}


def _latest_well_covered_sector_feature_date(
    db: Session,
    reference_date: date | None,
) -> date | None:
    stmt = (
        select(SectorFeatureDaily.trade_date, func.count().label("feature_count"))
        .group_by(SectorFeatureDaily.trade_date)
        .order_by(SectorFeatureDaily.trade_date.desc())
    )
    if reference_date is not None:
        stmt = stmt.where(SectorFeatureDaily.trade_date <= reference_date)

    rows = list(db.execute(stmt).all())
    if not rows:
        return None

    max_count = max(int(row.feature_count) for row in rows)
    min_count = max(1, ceil(max_count * SECTOR_FEATURE_MIN_COVERAGE_RATIO))
    for row in rows:
        if int(row.feature_count) >= min_count:
            return row.trade_date
    return rows[0].trade_date


def _sector_monthly_returns_from_moneyflow(
    db: Session,
    latest_date: date,
) -> dict[str, dict[str, float | date | None]]:
    month_start = _month_start(latest_date)
    rows = list(
        db.execute(
            select(TushareMoneyflowIndDc)
            .where(TushareMoneyflowIndDc.trade_date >= month_start)
            .where(TushareMoneyflowIndDc.trade_date <= latest_date)
            .where(TushareMoneyflowIndDc.content_type == "行业")
            .order_by(TushareMoneyflowIndDc.name, TushareMoneyflowIndDc.trade_date)
        ).scalars()
    )
    by_name: dict[str, list[TushareMoneyflowIndDc]] = {}
    for row in rows:
        if row.name:
            by_name.setdefault(str(row.name), []).append(row)

    result: dict[str, dict[str, float | date | None]] = {}
    for sector_name, items in by_name.items():
        start_row = next((item for item in items if item.close is not None), None)
        end_row = next((item for item in reversed(items) if item.close is not None), None)
        monthly_return_pct = None
        if start_row and end_row and start_row.close and end_row.close and start_row.close > 0:
            monthly_return_pct = float(end_row.close / start_row.close - Decimal("1"))
        result[sector_name] = {
            "month_start_date": start_row.trade_date if start_row else None,
            "monthly_return_pct": monthly_return_pct,
        }
    return result


def _sector_monthly_returns(
    db: Session,
    latest_date: date,
) -> dict[str, dict[str, float | date | None]]:
    month_start = _month_start(latest_date)
    rows = list(
        db.execute(
            select(SectorDaily)
            .where(SectorDaily.trade_date >= month_start)
            .where(SectorDaily.trade_date <= latest_date)
            .order_by(SectorDaily.sector_name, SectorDaily.trade_date)
        ).scalars()
    )
    by_name: dict[str, list[SectorDaily]] = {}
    for row in rows:
        by_name.setdefault(row.sector_name, []).append(row)

    result: dict[str, dict[str, float | date | None]] = {}
    for sector_name, items in by_name.items():
        start_row = next((item for item in items if item.close is not None), None)
        end_row = next((item for item in reversed(items) if item.close is not None), None)
        monthly_return_pct = None
        if start_row and end_row and start_row.close and end_row.close and start_row.close > 0:
            monthly_return_pct = float(end_row.close / start_row.close - Decimal("1"))
        result[sector_name] = {
            "month_start_date": start_row.trade_date if start_row else None,
            "monthly_return_pct": monthly_return_pct,
        }
    moneyflow_fallback = _sector_monthly_returns_from_moneyflow(db, latest_date)
    for sector_name, item in moneyflow_fallback.items():
        result.setdefault(sector_name, item)
    return result


def _sector_moneyflow_by_name(db: Session, trade_date: date) -> dict[str, TushareMoneyflowIndDc]:
    rows = db.execute(
        select(TushareMoneyflowIndDc)
        .where(TushareMoneyflowIndDc.trade_date == trade_date)
        .where(TushareMoneyflowIndDc.content_type == "行业")
    ).scalars()
    return {str(row.name): row for row in rows if row.name}


def _sector_activity_score(item: SectorOverviewItem) -> float:
    amount_score = (item.amount or 0.0) / 100000000
    flow_score = (item.fund_flow_net_amount or 0.0) / 100000000
    flow_rate_score = (item.fund_flow_rate or 0.0) * 100
    return amount_score + flow_score + flow_rate_score


def _sector_continuity_score(item: SectorOverviewItem) -> float:
    strength = item.sector_strength_score or 0.0
    momentum = item.sector_momentum_score or 0.0
    breadth = item.sector_breadth_score or 0.0
    return strength * 0.45 + momentum * 0.35 + breadth * 0.20


def _sector_month_trend_score(item: SectorOverviewItem) -> float:
    monthly_return = item.monthly_return_pct
    if monthly_return is None:
        return 45.0
    if monthly_return >= 0.12:
        return 90.0
    if monthly_return >= 0.08:
        return 75.0
    if monthly_return >= 0.04:
        return 60.0
    if monthly_return > 0:
        return 50.0
    if monthly_return >= -0.03:
        return 35.0
    return 20.0


def _sector_fund_flow_score(item: SectorOverviewItem) -> float:
    net_amount = item.fund_flow_net_amount
    rate = item.fund_flow_rate
    if net_amount is None and rate is None:
        return 45.0
    if (net_amount or 0.0) > 0 and (rate or 0.0) >= 0.05:
        return 80.0
    if (net_amount or 0.0) > 0 and (rate or 0.0) > 0:
        return 60.0
    if (net_amount or 0.0) < 0 or (rate or 0.0) < 0:
        return 25.0
    return 40.0


def _sector_gate(item: SectorOverviewItem) -> tuple[float, str, list[str]]:
    month_score = _sector_month_trend_score(item)
    strength = item.sector_strength_score if item.sector_strength_score is not None else 45.0
    breadth = item.sector_breadth_score if item.sector_breadth_score is not None else 45.0
    momentum = item.sector_momentum_score if item.sector_momentum_score is not None else 45.0
    fund_flow = _sector_fund_flow_score(item)
    score = round(
        month_score * 0.35
        + strength * 0.25
        + breadth * 0.15
        + momentum * 0.15
        + fund_flow * 0.10,
        2,
    )
    if score >= 70:
        label = "主线允许"
    elif score >= 50:
        label = "观察确认"
    else:
        label = "降温等待"

    reasons: list[str] = []
    monthly_return = item.monthly_return_pct
    if monthly_return is not None and monthly_return >= 0.06 and (item.month_rank or 99) <= 5:
        reasons.append("月度排名靠前")
    elif monthly_return is not None and monthly_return > 0:
        reasons.append("月度趋势转正")
    elif monthly_return is not None:
        reasons.append("月度趋势不足")

    if item.sector_strength_score is not None and item.sector_strength_score >= 70:
        reasons.append("板块强度较好")
    elif item.sector_strength_score is not None and item.sector_strength_score <= 50:
        reasons.append("板块强度不足")

    if item.sector_breadth_score is not None and item.sector_breadth_score >= 65:
        reasons.append("扩散较好")
    elif item.sector_breadth_score is not None and item.sector_breadth_score < 55:
        reasons.append("扩散不足，先观察")

    if item.sector_momentum_score is not None and item.sector_momentum_score >= 70:
        reasons.append("动量延续")
    if (item.fund_flow_net_amount or 0.0) > 0 and (item.fund_flow_rate or 0.0) > 0:
        reasons.append("资金流入确认")
    elif (item.fund_flow_net_amount or 0.0) < 0 or (item.fund_flow_rate or 0.0) < 0:
        reasons.append("资金未确认")

    if not reasons:
        reasons.append("数据不足，先观察")
    return score, label, reasons[:4]


def _moneyflow_reliability_label(coverage_ratio: float | None) -> str:
    if coverage_ratio is None or coverage_ratio <= 0:
        return "资金流缺失"
    if coverage_ratio >= 0.8:
        return "资金覆盖正常"
    return "资金覆盖不足"


def _sector_gate_summary(items: list[SectorOverviewItem]) -> SectorGateSummaryResponse:
    return SectorGateSummaryResponse(
        main_allowed_count=sum(1 for item in items if item.sector_gate_label == "主线允许"),
        observe_count=sum(1 for item in items if item.sector_gate_label == "观察确认"),
        cooldown_count=sum(1 for item in items if item.sector_gate_label == "降温等待"),
        unknown_count=sum(1 for item in items if not item.sector_gate_label),
    )


def _sector_overview_cache_key(db: Session) -> int | None:
    try:
        return id(db.get_bind())
    except Exception:
        return None


def _cached_stored_sector_overview(db: Session) -> SectorOverviewResponse:
    global _SECTOR_OVERVIEW_CACHE
    current = monotonic()
    cache_key = _sector_overview_cache_key(db)
    if (
        _SECTOR_OVERVIEW_CACHE is not None
        and _SECTOR_OVERVIEW_CACHE[1] == cache_key
        and current - _SECTOR_OVERVIEW_CACHE[0] <= SECTOR_OVERVIEW_CACHE_SECONDS
    ):
        return _SECTOR_OVERVIEW_CACHE[2]

    with _SECTOR_OVERVIEW_LOCK:
        current = monotonic()
        if (
            _SECTOR_OVERVIEW_CACHE is not None
            and _SECTOR_OVERVIEW_CACHE[1] == cache_key
            and current - _SECTOR_OVERVIEW_CACHE[0] <= SECTOR_OVERVIEW_CACHE_SECONDS
        ):
            return _SECTOR_OVERVIEW_CACHE[2]
        overview = _stored_sector_overview(db)
        _SECTOR_OVERVIEW_CACHE = (monotonic(), cache_key, overview)
        return overview


def _stored_sector_overview(db: Session) -> SectorOverviewResponse:
    latest_sector_daily_date = db.execute(
        select(func.max(SectorDaily.trade_date))
    ).scalar_one_or_none()
    latest_moneyflow_date = db.execute(
        select(func.max(TushareMoneyflowIndDc.trade_date)).where(
            TushareMoneyflowIndDc.content_type == "行业"
        )
    ).scalar_one_or_none()
    latest_market_date = max(
        (item for item in (latest_sector_daily_date, latest_moneyflow_date) if item is not None),
        default=None,
    )
    latest_feature_date = _latest_well_covered_sector_feature_date(
        db,
        reference_date=latest_market_date,
    )
    latest_date = latest_market_date or latest_feature_date
    if latest_date is None:
        return SectorOverviewResponse(
            trade_date=None,
            month_start_date=None,
            feature_trade_date=None,
            moneyflow_trade_date=None,
            sectors=[],
        )

    sector_rows = (
        list(
            db.execute(
                select(SectorDaily)
                .where(SectorDaily.trade_date == latest_sector_daily_date)
                .order_by(SectorDaily.sector_name)
            ).scalars()
        )
        if latest_sector_daily_date is not None
        else []
    )
    features_by_name = (
        _sector_features_by_name(db, latest_feature_date) if latest_feature_date else {}
    )
    moneyflow_by_name = (
        _sector_moneyflow_by_name(db, latest_moneyflow_date)
        if latest_moneyflow_date
        else {}
    )
    monthly_reference_date = latest_market_date or latest_feature_date
    monthly_by_name = (
        _sector_monthly_returns(db, monthly_reference_date) if monthly_reference_date else {}
    )

    sector_rows_by_name = {row.sector_name: row for row in sector_rows}
    sector_names = sorted(
        set(sector_rows_by_name)
        | set(features_by_name)
        | set(moneyflow_by_name)
        | set(monthly_by_name)
    )

    items: list[SectorOverviewItem] = []
    for sector_name in sector_names:
        row = sector_rows_by_name.get(sector_name)
        canonical_sector_name = _canonical_sector_name(sector_name)
        feature_values = (
            features_by_name.get(sector_name)
            or features_by_name.get(canonical_sector_name)
            or (features_by_name.get(row.sector_code) if row is not None else None)
            or {}
        )
        month_values = monthly_by_name.get(sector_name, {})
        moneyflow = moneyflow_by_name.get(sector_name)
        items.append(
            SectorOverviewItem(
                sector_code=row.sector_code if row is not None else sector_name,
                sector_name=sector_name,
                canonical_sector_name=(
                    canonical_sector_name if canonical_sector_name != sector_name else None
                ),
                trade_date=(
                    row.trade_date
                    if row is not None
                    else (latest_moneyflow_date or latest_feature_date or latest_date)
                ),
                month_start_date=month_values.get("month_start_date"),
                month_rank=None,
                monthly_return_pct=month_values.get("monthly_return_pct"),
                day_change_pct=(
                    _float(row.pct_change)
                    if row is not None
                    else (_float(moneyflow.pct_change) if moneyflow else None)
                ),
                amount=_float(row.amount) if row is not None else None,
                fund_flow_net_amount=_float(moneyflow.net_amount) if moneyflow else None,
                fund_flow_rate=_float(moneyflow.net_amount_rate) if moneyflow else None,
                sector_strength_score=float(feature_values["sector_strength_score"])
                if feature_values.get("sector_strength_score") is not None
                else None,
                sector_breadth_score=float(feature_values["sector_breadth_score"])
                if feature_values.get("sector_breadth_score") is not None
                else None,
                sector_momentum_score=float(feature_values["sector_momentum_score"])
                if feature_values.get("sector_momentum_score") is not None
                else None,
                sector_stock_count=int(feature_values["sector_stock_count"])
                if feature_values.get("sector_stock_count") is not None
                else None,
                sector_up_count=int(feature_values["sector_up_count"])
                if feature_values.get("sector_up_count") is not None
                else None,
            )
        )

    ranked_items = sorted(
        items,
        key=lambda item: (
            item.monthly_return_pct is None,
            -(item.monthly_return_pct or -999.0),
            -(item.fund_flow_rate or -999.0),
            -(item.sector_strength_score or -999.0),
        ),
    )
    for index, item in enumerate(ranked_items, start=1):
        item.month_rank = index
    for item in ranked_items:
        gate_score, gate_label, gate_reasons = _sector_gate(item)
        item.sector_gate_score = gate_score
        item.sector_gate_label = gate_label
        item.sector_gate_reasons = gate_reasons

    overview_sector_count = len(ranked_items)
    feature_sector_count = len(features_by_name)
    matched_feature_count = sum(
        1 for item in ranked_items if item.sector_strength_score is not None
    )
    moneyflow_sector_count = sum(
        1
        for item in ranked_items
        if item.fund_flow_net_amount is not None or item.fund_flow_rate is not None
    )
    feature_coverage_ratio = (
        round(matched_feature_count / overview_sector_count, 6)
        if overview_sector_count
        else None
    )
    moneyflow_coverage_ratio = (
        round(moneyflow_sector_count / overview_sector_count, 6)
        if overview_sector_count
        else None
    )

    return SectorOverviewResponse(
        trade_date=latest_date,
        month_start_date=_month_start(monthly_reference_date) if monthly_reference_date else None,
        feature_trade_date=latest_feature_date,
        moneyflow_trade_date=latest_moneyflow_date,
        feature_sector_count=feature_sector_count,
        overview_sector_count=overview_sector_count,
        feature_coverage_ratio=feature_coverage_ratio,
        moneyflow_sector_count=moneyflow_sector_count,
        moneyflow_missing_count=max(0, overview_sector_count - moneyflow_sector_count),
        moneyflow_coverage_ratio=moneyflow_coverage_ratio,
        moneyflow_reliability_label=_moneyflow_reliability_label(moneyflow_coverage_ratio),
        sector_gate_summary=_sector_gate_summary(ranked_items),
        sectors=ranked_items,
        monthly_rank=ranked_items[:10],
        activity_rank=sorted(
            ranked_items,
            key=lambda item: (
                _sector_activity_score(item),
                item.monthly_return_pct or -999.0,
                item.sector_strength_score or -999.0,
            ),
            reverse=True,
        )[:10],
        continuity_rank=sorted(
            ranked_items,
            key=lambda item: (
                _sector_continuity_score(item),
                item.monthly_return_pct or -999.0,
                item.fund_flow_rate or -999.0,
            ),
            reverse=True,
        )[:10],
    )


@router.get("/intraday-turn", response_model=IntradayMarketTurnResponse)
def get_intraday_market_turn(db: DbSession) -> IntradayMarketTurnResponse:
    row = db.execute(
        select(IntradayMarketTurnSnapshot)
        .order_by(IntradayMarketTurnSnapshot.snapshot_time.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return IntradayMarketTurnResponse(
            trade_date=None,
            snapshot_time=None,
            key="watch_repair",
            label="待采集",
            summary="尚未采集盘中全市场快照，启动观察保持关闭。",
            data_ready=False,
            startup_watch_allowed=False,
            core_action_allowed=False,
            coverage_ratio=None,
            breadth_ratio=None,
            index_change_pct=None,
            sector_expansion_count=None,
            expanding_sectors=[],
            sustained_expanding_sectors=[],
            leading_sustained_sectors=[],
            cross_day_mainline=None,
        )
    state = row.state_json or {}
    return IntradayMarketTurnResponse(
        trade_date=row.trade_date,
        snapshot_time=row.snapshot_time,
        key=str(state.get("key") or "watch_repair"),
        label=str(state.get("label") or "观察修复"),
        summary=str(state.get("summary") or "盘中信号不足，先观察。"),
        data_ready=bool(state.get("data_ready")),
        startup_watch_allowed=bool(state.get("startup_watch_allowed")),
        core_action_allowed=bool(state.get("core_action_allowed")),
        coverage_ratio=row.coverage_ratio,
        breadth_ratio=row.breadth_ratio,
        index_change_pct=row.index_change_pct,
        sector_expansion_count=row.sector_expansion_count,
        confirmed_signals=list(state.get("confirmed_signals") or []),
        pending_signals=list(state.get("pending_signals") or []),
        expanding_sectors=list(state.get("expanding_sectors") or []),
        sustained_expanding_sectors=list(state.get("sustained_expanding_sectors") or []),
        leading_sustained_sectors=list(state.get("leading_sustained_sectors") or []),
        cross_day_mainline=(
            state.get("cross_day_mainline")
            if isinstance(state.get("cross_day_mainline"), dict)
            else None
        ),
    )


@router.get("/mainline-outcomes", response_model=list[ConfirmedMainlineOutcomeResponse])
def get_confirmed_mainline_outcomes(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=120)] = 60,
) -> list[ConfirmedMainlineOutcomeResponse]:
    return [
        ConfirmedMainlineOutcomeResponse(
            signal_date=item.signal_date,
            sector=item.sector,
            leader_symbol=item.leader_symbol,
            horizons=[
                MainlineOutcomeHorizonResponse(
                    horizon=horizon.horizon,
                    status=horizon.status,
                    return_pct=horizon.return_pct,
                )
                for horizon in item.horizons.values()
            ],
        )
        for item in list_confirmed_mainline_outcomes(db, limit=limit)
    ]


@router.get("/overview", response_model=MarketOverviewResponse)
def get_market_overview(db: DbSession, live: bool = False) -> MarketOverviewResponse:
    if live:
        overview = _try_cached_live_a_share_overview(LIVE_MARKET_TIMEOUT_SECONDS)
        if overview is not None:
            return overview
        archived = _stored_full_market_realtime_overview(db)
        if archived is not None:
            return archived

    return _stored_market_overview(db)


@router.get("/sectors/overview", response_model=SectorOverviewResponse)
def get_sector_overview(db: DbSession) -> SectorOverviewResponse:
    return _cached_stored_sector_overview(db)


@router.get("/sectors/catalysts", response_model=SectorCatalystResponse)
def get_sector_catalysts(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> SectorCatalystResponse:
    global _SECTOR_CATALYST_CACHE
    as_of = now_local()
    current = monotonic()
    if (
        _SECTOR_CATALYST_CACHE is not None
        and _SECTOR_CATALYST_CACHE[1] == limit
        and current - _SECTOR_CATALYST_CACHE[0] <= SECTOR_CATALYST_CACHE_SECONDS
    ):
        return _SECTOR_CATALYST_CACHE[2]

    with _SECTOR_CATALYST_LOCK:
        current = monotonic()
        if (
            _SECTOR_CATALYST_CACHE is not None
            and _SECTOR_CATALYST_CACHE[1] == limit
            and current - _SECTOR_CATALYST_CACHE[0] <= SECTOR_CATALYST_CACHE_SECONDS
        ):
            return _SECTOR_CATALYST_CACHE[2]
        snapshot = load_recent_message_snapshot(
            db,
            as_of=as_of,
            max_age_seconds=SECTOR_CATALYST_CACHE_SECONDS,
        )
        if snapshot is not None:
            response = SectorCatalystResponse(**snapshot_to_report(snapshot, limit=limit).to_dict())
            _SECTOR_CATALYST_CACHE = (monotonic(), limit, response)
            return response

        raw_messages = fetch_market_hot_messages()
        report = build_sector_catalyst_report(
            raw_messages,
            as_of=as_of,
            limit=limit,
        )
        snapshot = store_message_snapshot(db, report=report, raw_messages=raw_messages)
        report = snapshot_to_report(snapshot, limit=limit)
        response = SectorCatalystResponse(**report.to_dict())
        _SECTOR_CATALYST_CACHE = (monotonic(), limit, response)
        return response


@router.get("/data-health", response_model=DataHealthResponse)
def get_data_health(
    db: DbSession,
    trade_date: str | None = None,
) -> DataHealthResponse:
    parsed_trade_date = date.fromisoformat(trade_date) if trade_date else None
    report = inspect_daily_data_health(db, trade_date=parsed_trade_date)
    return DataHealthResponse(**asdict(report))


@router.get("/sectors/replay", response_model=SectorReplayResponse)
def get_sector_replay(
    month: str,
    sector: str,
) -> SectorReplayResponse:
    result = replay_sector_month(month, sector=sector, horizons=(5, 10, 20))
    return SectorReplayResponse(**result.to_dict())


@router.get("/candles/{symbol}", response_model=list[CandleResponse])
def get_symbol_candles(
    symbol: str,
    db: DbSession,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: Annotated[int, Query(ge=30, le=1000)] = 240,
) -> list[CandleResponse]:
    stmt = select(DailyBar).where(DailyBar.symbol == symbol)
    if start_date:
        stmt = stmt.where(DailyBar.trade_date >= date.fromisoformat(start_date))
    if end_date:
        stmt = stmt.where(DailyBar.trade_date <= date.fromisoformat(end_date))
    if not start_date:
        stmt = stmt.order_by(DailyBar.trade_date.desc()).limit(limit)
        bars = list(reversed(db.execute(stmt).scalars().all()))
    else:
        stmt = stmt.order_by(DailyBar.trade_date).limit(limit)
        bars = list(db.execute(stmt).scalars().all())

    closes = [float(item.close) for item in bars]
    ma5 = _moving_average(closes, 5)
    ma10 = _moving_average(closes, 10)
    ma20 = _moving_average(closes, 20)
    ma60 = _moving_average(closes, 60)

    return [
        CandleResponse(
            time=item.trade_date,
            open=float(item.open),
            high=float(item.high),
            low=float(item.low),
            close=float(item.close),
            volume=_float(item.volume),
            amount=_float(item.amount),
            ma5=ma5[index],
            ma10=ma10[index],
            ma20=ma20[index],
            ma60=ma60[index],
        )
        for index, item in enumerate(bars)
    ]
