from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from datetime import time as time_of_day
from decimal import Decimal
from time import sleep

from sqlalchemy import func, select

from services.collector.akshare_client import RealtimeQuoteRow, fetch_sina_realtime_quotes
from services.collector.repository import load_recent_realtime_quotes, upsert_realtime_quotes
from services.engine.paper.entry_quality import (
    HIGH_QUALITY_CONFIDENCE_MIN,
    HIGH_QUALITY_RANK_MAX,
    HIGH_QUALITY_RELATIVE_MIN,
    HIGH_QUALITY_RISK_MAX,
    HIGH_QUALITY_SECTOR_MIN,
    HIGH_QUALITY_TREND_MIN,
    evaluate_plan_entry_quality,
    price_action_rejection_reason,
)
from services.engine.paper.position_sizing import adjusted_position_size_pct
from services.engine.paper.repository import (
    create_trade,
    get_or_create_account,
    has_open_position,
    load_open_positions,
    load_trade_plans_for_trade_date,
)
from services.engine.paper.review import upsert_paper_trade_review_for_position
from services.engine.research_pool.repository import filter_latest_candidate_batch_items
from services.notifications.dispatcher import dispatch_paper_alerts
from services.shared.database import SessionLocal
from services.shared.models import (
    PaperAlert,
    PaperOrder,
    PaperPosition,
    ResearchPoolItem,
    TradePlan,
)
from services.shared.time import now_local
from services.shared.upsert import upsert_rows

INTRADAY_ENTRY_CUTOFF = time_of_day(14, 15)
INTRADAY_DAILY_ENTRY_CAP = 2
INTRADAY_HIGH_QUALITY_RANK_MAX = HIGH_QUALITY_RANK_MAX
INTRADAY_HIGH_QUALITY_CONFIDENCE_MIN = HIGH_QUALITY_CONFIDENCE_MIN
INTRADAY_HIGH_QUALITY_TREND_MIN = HIGH_QUALITY_TREND_MIN
INTRADAY_HIGH_QUALITY_RELATIVE_MIN = HIGH_QUALITY_RELATIVE_MIN
INTRADAY_HIGH_QUALITY_SECTOR_MIN = HIGH_QUALITY_SECTOR_MIN
INTRADAY_HIGH_QUALITY_RISK_MAX = HIGH_QUALITY_RISK_MAX
BLACK_SWAN_UP_RATIO_MAX = 0.42
BLACK_SWAN_AVG_CHANGE_MAX = 0.0
BLACK_SWAN_CANDIDATE_RED_RATE_MIN = 0.55
BLACK_SWAN_CANDIDATE_FAILED_SPIKE_RATE_MIN = 0.25
BLACK_SWAN_FAILED_SPIKE_INTRADAY_GAIN_MIN = Decimal("0.06")
BLACK_SWAN_NEAR_LIMIT_INTRADAY_GAIN_MIN = Decimal("0.085")
TRAILING_DRAWDOWN_BY_STRATEGY = {
    "short_term": Decimal("0.06"),
    "swing": Decimal("0.08"),
    "long_term": Decimal("0.10"),
}
STOP_CONFIRMATION_BUFFER_BY_STRATEGY = {
    "short_term": Decimal("1.000"),
    "swing": Decimal("0.998"),
    "long_term": Decimal("0.993"),
}
T_RHYTHM_STRATEGIES = {"long_term", "swing"}
T_REDUCE_GAIN_MIN_BY_STRATEGY = {
    "swing": Decimal("0.100"),
    "long_term": Decimal("0.120"),
}
T_REDUCE_PULLBACK_FROM_HIGH_MIN = Decimal("0.025")
T_ADD_PULLBACK_MIN_BY_STRATEGY = {
    "swing": Decimal("0.050"),
    "long_term": Decimal("0.060"),
}
T_ADD_PULLBACK_MAX = Decimal("0.140")
T_ADD_MIN_PROFIT_BUFFER = Decimal("0.015")


@dataclass(frozen=True)
class RealtimePaperAlert:
    account_id: int
    position_id: int | None
    symbol: str
    alert_type: str
    severity: str
    message: str
    alert_time: str
    price: float | None
    current_stop: float | None
    pnl_pct: float | None
    rule_id: str | None = None
    strategy_type: str | None = None
    candidate_rank: int | None = None
    candidate_score: float | None = None
    intraday_snapshot: dict | None = None
    reasons: list[str] = field(default_factory=list)
    support_flags: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RealtimePaperMonitorResult:
    status: str
    message: str
    quote_time: str
    target_symbols: int
    quotes: int
    updated_positions: int
    executed_entries: int
    executed_exits: int
    alerts: list[RealtimePaperAlert]
    notifications: list[dict[str, str]]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["alerts"] = [item.to_dict() for item in self.alerts]
        return data


INTRADAY_STATE_LABELS = {
    "fresh": "首笔快照",
    "strong_continuation": "强势延续",
    "gap_down_repair": "低开修复",
    "pullback_repair": "回调修复",
    "balanced": "盘中整理",
    "fading": "转弱回落",
    "distribution": "放量分歧",
    "downside": "下压走弱",
}


@dataclass(frozen=True)
class IntradayQuoteSnapshot:
    symbol: str
    trade_date: str
    quote_time: str
    state: str
    label: str
    summary: str
    price_change_from_prev_pct: float | None = None
    session_change_pct: float | None = None
    open_gap_pct: float | None = None
    change_from_open_pct: float | None = None
    intraday_high_gain_pct: float | None = None
    pullback_from_high_pct: float | None = None
    near_limit_up: bool = False
    failed_near_limit_up: bool = False
    spike_reversed_to_red: bool = False
    range_position: float | None = None
    current_interval_volume: float | None = None
    volume_pressure_ratio: float | None = None
    support_flags: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IntradayMarketRiskSnapshot:
    mode: str
    label: str
    summary: str
    up_ratio: float | None
    avg_change_pct: float | None
    candidate_count: int
    candidate_red_rate: float
    failed_spike_rate: float
    near_limit_failed_rate: float
    risk_flags: list[str]

    def blocks_new_entries(self) -> bool:
        return self.mode in {"black_swan_retreat", "candidate_retreat"}

    def to_dict(self) -> dict:
        return asdict(self)


def _decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _pnl_pct(position: PaperPosition, price: Decimal | None) -> float | None:
    if price is None or position.entry_price == 0:
        return None
    return float((price / position.entry_price - Decimal("1")).quantize(Decimal("0.000001")))


def _entry_quantity(cash: Decimal, price: Decimal, position_pct: Decimal) -> int:
    budget = cash * position_pct
    raw_quantity = int(budget / price)
    return raw_quantity - raw_quantity % 100


def _limit_ratio(symbol: str) -> Decimal:
    if symbol.startswith(("4", "8")):
        return Decimal("1.30")
    if symbol.startswith(("3", "688", "689")):
        return Decimal("1.20")
    return Decimal("1.10")


def _trailing_drawdown_ratio(strategy_type: str | None) -> Decimal:
    return TRAILING_DRAWDOWN_BY_STRATEGY.get(str(strategy_type or ""), Decimal("0.06"))


def _stop_confirmation_buffer(strategy_type: str | None) -> Decimal:
    return STOP_CONFIRMATION_BUFFER_BY_STRATEGY.get(str(strategy_type or ""), Decimal("1.000"))


def _pct_change(current: Decimal | None, previous: Decimal | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return float((current / previous - Decimal("1")).quantize(Decimal("0.000001")))


def _pct_decimal(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current / previous - Decimal("1")).quantize(Decimal("0.000001"))


def _pct_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _range_position(
    price: Decimal | None,
    high: Decimal | None,
    low: Decimal | None,
) -> float | None:
    if price is None or high is None or low is None or high <= low:
        return None
    position = (price - low) / (high - low)
    return float(max(Decimal("0"), min(Decimal("1"), position)).quantize(Decimal("0.000001")))


def _range_position_decimal(
    price: Decimal | None,
    high: Decimal | None,
    low: Decimal | None,
) -> Decimal | None:
    if price is None or high is None or low is None or high <= low:
        return None
    position = (price - low) / (high - low)
    return max(Decimal("0"), min(Decimal("1"), position)).quantize(Decimal("0.000001"))


def _quote_pct_change(quote: RealtimeQuoteRow) -> Decimal | None:
    price = _decimal(quote.price)
    pre_close = _decimal(quote.pre_close)
    if price is None or pre_close is None or pre_close <= 0:
        return None
    return price / pre_close - Decimal("1")


def _quote_intraday_gain(quote: RealtimeQuoteRow) -> Decimal | None:
    high = _decimal(quote.high)
    pre_close = _decimal(quote.pre_close)
    if high is None or pre_close is None or pre_close <= 0:
        return None
    return high / pre_close - Decimal("1")


def _build_intraday_market_risk_snapshot(
    *,
    quotes: list[RealtimeQuoteRow],
    candidate_symbols: set[str],
    market_overview: dict[str, float] | None = None,
) -> IntradayMarketRiskSnapshot:
    candidate_quotes = [quote for quote in quotes if quote.symbol in candidate_symbols]
    pct_changes = [
        value for quote in candidate_quotes if (value := _quote_pct_change(quote)) is not None
    ]
    failed_spikes = [
        quote
        for quote in candidate_quotes
        if (gain := _quote_intraday_gain(quote)) is not None
        and gain >= BLACK_SWAN_FAILED_SPIKE_INTRADAY_GAIN_MIN
        and (change := _quote_pct_change(quote)) is not None
        and change <= Decimal("0")
    ]
    near_limit_failed = [
        quote
        for quote in candidate_quotes
        if (gain := _quote_intraday_gain(quote)) is not None
        and gain >= BLACK_SWAN_NEAR_LIMIT_INTRADAY_GAIN_MIN
        and (change := _quote_pct_change(quote)) is not None
        and change < gain * Decimal("0.35")
    ]

    candidate_count = len(pct_changes)
    red_count = sum(1 for value in pct_changes if value < 0)
    candidate_red_rate = red_count / candidate_count if candidate_count else 0.0
    failed_spike_rate = len(failed_spikes) / candidate_count if candidate_count else 0.0
    near_limit_failed_rate = len(near_limit_failed) / candidate_count if candidate_count else 0.0
    up_ratio = market_overview.get("up_ratio") if market_overview else None
    avg_change_pct = market_overview.get("avg_change_pct") if market_overview else None

    risk_flags: list[str] = []
    if up_ratio is not None and up_ratio <= BLACK_SWAN_UP_RATIO_MAX:
        risk_flags.append("market_breadth_weak")
    if avg_change_pct is not None and avg_change_pct <= BLACK_SWAN_AVG_CHANGE_MAX:
        risk_flags.append("market_avg_return_negative")
    if candidate_red_rate >= BLACK_SWAN_CANDIDATE_RED_RATE_MIN:
        risk_flags.append("candidate_pool_broadly_red")
    if failed_spike_rate >= BLACK_SWAN_CANDIDATE_FAILED_SPIKE_RATE_MIN:
        risk_flags.append("candidate_spike_failed")
    if near_limit_failed_rate >= 0.15:
        risk_flags.append("near_limit_failure_cluster")

    market_weak = (
        up_ratio is not None
        and up_ratio <= BLACK_SWAN_UP_RATIO_MAX
        and avg_change_pct is not None
        and avg_change_pct <= BLACK_SWAN_AVG_CHANGE_MAX
    )
    candidate_retreat = (
        candidate_count >= 5
        and (
            candidate_red_rate >= BLACK_SWAN_CANDIDATE_RED_RATE_MIN
            or failed_spike_rate >= BLACK_SWAN_CANDIDATE_FAILED_SPIKE_RATE_MIN
            or near_limit_failed_rate >= 0.15
        )
    )
    if market_weak and candidate_retreat:
        mode = "black_swan_retreat"
        label = "黑天鹅退潮"
    elif candidate_retreat:
        mode = "candidate_retreat"
        label = "候选池退潮"
    elif market_weak:
        mode = "market_weak"
        label = "市场宽度偏弱"
    else:
        mode = "normal"
        label = "盘中正常"

    summary = (
        f"{label}：候选{candidate_count}只，翻绿{candidate_red_rate:.0%}，"
        f"冲高回落{failed_spike_rate:.0%}，近涨停未封{near_limit_failed_rate:.0%}"
    )
    if up_ratio is not None:
        summary += f"，全市场上涨占比{up_ratio:.0%}"
    if avg_change_pct is not None:
        summary += f"，平均涨跌{avg_change_pct:+.2%}"

    return IntradayMarketRiskSnapshot(
        mode=mode,
        label=label,
        summary=summary,
        up_ratio=up_ratio,
        avg_change_pct=avg_change_pct,
        candidate_count=candidate_count,
        candidate_red_rate=round(candidate_red_rate, 6),
        failed_spike_rate=round(failed_spike_rate, 6),
        near_limit_failed_rate=round(near_limit_failed_rate, 6),
        risk_flags=risk_flags,
    )


def _build_intraday_quote_snapshot(
    db,
    quote: RealtimeQuoteRow,
) -> IntradayQuoteSnapshot | None:
    trade_date = date.fromisoformat(quote.trade_date)
    history = load_recent_realtime_quotes(
        db,
        quote.symbol,
        trade_date=trade_date,
        before=quote.quote_time,
        limit=3,
    )
    current_price = _decimal(quote.price)
    current_open = _decimal(quote.open)
    current_high = _decimal(quote.high)
    current_low = _decimal(quote.low)
    current_pre_close = _decimal(quote.pre_close)
    previous = history[0] if history else None
    older = history[1] if len(history) > 1 else None
    previous_price = _decimal(previous.price) if previous is not None else None
    previous_volume = _decimal(previous.volume) if previous is not None else None
    older_volume = _decimal(older.volume) if older is not None else None

    price_change_from_prev_pct = _pct_change(current_price, previous_price)
    session_change_pct = _pct_change(current_price, current_pre_close)
    open_gap_pct_decimal = _pct_decimal(current_open, current_pre_close)
    change_from_open_pct_decimal = _pct_decimal(current_price, current_open)
    intraday_high_gain_pct_decimal = _pct_decimal(current_high, current_pre_close)
    pullback_from_high_pct_decimal = _pct_decimal(current_high, current_price)
    range_position = _range_position(current_price, current_high, current_low)
    limit_ratio = _limit_ratio(quote.symbol)
    near_limit_up = (
        current_pre_close is not None
        and current_high is not None
        and current_high >= (current_pre_close * limit_ratio) * Decimal("0.985")
    )
    failed_near_limit_up = bool(
        near_limit_up
        and current_pre_close is not None
        and current_price is not None
        and current_price < (current_pre_close * limit_ratio) * Decimal("0.985")
    )
    spike_reversed_to_red = bool(
        intraday_high_gain_pct_decimal is not None
        and intraday_high_gain_pct_decimal >= BLACK_SWAN_FAILED_SPIKE_INTRADAY_GAIN_MIN
        and session_change_pct is not None
        and session_change_pct <= 0
    )
    gap_down_repair = bool(
        open_gap_pct_decimal is not None
        and open_gap_pct_decimal <= Decimal("-0.015")
        and change_from_open_pct_decimal is not None
        and change_from_open_pct_decimal >= Decimal("0.018")
        and session_change_pct is not None
        and session_change_pct >= Decimal("-0.003")
        and range_position is not None
        and range_position >= 0.65
    )

    current_interval_volume: Decimal | None = None
    volume_pressure_ratio: float | None = None
    if previous_volume is not None and quote.volume is not None:
        current_volume = _decimal(quote.volume)
        if current_volume is not None and current_volume >= previous_volume:
            current_interval_volume = current_volume - previous_volume
            if older_volume is not None and previous_volume > older_volume:
                previous_interval_volume = previous_volume - older_volume
                if previous_interval_volume > 0:
                    volume_pressure_ratio = float(
                        (current_interval_volume / previous_interval_volume).quantize(
                            Decimal("0.000001")
                        )
                    )

    state = "balanced"
    if spike_reversed_to_red:
        state = "distribution"
    elif failed_near_limit_up:
        state = "distribution"
    elif previous is None:
        state = "fresh"
    elif session_change_pct is not None and session_change_pct <= -0.015:
        state = "downside"
    elif (
        price_change_from_prev_pct is not None
        and price_change_from_prev_pct < 0
        and volume_pressure_ratio is not None
        and volume_pressure_ratio >= 1.2
    ):
        state = "distribution"
    elif (
        price_change_from_prev_pct is not None
        and price_change_from_prev_pct < 0
        and range_position is not None
        and range_position <= 0.35
    ):
        state = "fading"
    elif gap_down_repair:
        state = "gap_down_repair"
    elif (
        price_change_from_prev_pct is not None
        and price_change_from_prev_pct >= 0
        and range_position is not None
        and range_position >= 0.65
    ):
        state = "strong_continuation"
    elif (
        price_change_from_prev_pct is not None
        and price_change_from_prev_pct >= 0
        and range_position is not None
        and range_position <= 0.45
    ):
        state = "pullback_repair"

    support_flags: list[str] = []
    risk_flags: list[str] = []
    if state == "strong_continuation":
        support_flags.append("intraday_strength_continuation")
        if volume_pressure_ratio is not None and volume_pressure_ratio >= 1.0:
            support_flags.append("intraday_volume_confirmed")
    elif state == "gap_down_repair":
        support_flags.append("intraday_gap_down_repair")
        if volume_pressure_ratio is not None and volume_pressure_ratio >= 1.0:
            support_flags.append("intraday_volume_confirmed")
    elif state == "pullback_repair":
        support_flags.append("intraday_pullback_repair")
    elif state == "distribution":
        risk_flags.append("intraday_distribution")
    elif state == "fading":
        risk_flags.append("intraday_strength_fading")
    elif state == "downside":
        risk_flags.append("intraday_downside_pressure")
    if open_gap_pct_decimal is not None and open_gap_pct_decimal >= Decimal("0.04"):
        if change_from_open_pct_decimal is not None and change_from_open_pct_decimal < 0:
            risk_flags.append("gap_up_faded")
        else:
            support_flags.append("gap_up_holding")
    if failed_near_limit_up:
        risk_flags.append("near_limit_up_failed")
    if spike_reversed_to_red:
        risk_flags.append("spike_reversed_to_red")

    detail_parts: list[str] = []
    if price_change_from_prev_pct is not None:
        detail_parts.append(f"较上一笔{price_change_from_prev_pct:+.2%}")
    if session_change_pct is not None:
        detail_parts.append(f"相对昨收{session_change_pct:+.2%}")
    if open_gap_pct_decimal is not None:
        detail_parts.append(f"开盘缺口{open_gap_pct_decimal:+.2%}")
    if change_from_open_pct_decimal is not None:
        detail_parts.append(f"较开盘{change_from_open_pct_decimal:+.2%}")
    if intraday_high_gain_pct_decimal is not None:
        detail_parts.append(f"最高涨幅{intraday_high_gain_pct_decimal:+.2%}")
    if pullback_from_high_pct_decimal is not None:
        detail_parts.append(f"高点回撤{pullback_from_high_pct_decimal:+.2%}")
    if range_position is not None:
        detail_parts.append(f"日内位置{range_position:.0%}")
    if current_interval_volume is not None:
        detail_parts.append(f"本轮增量成交{float(current_interval_volume):.0f}")
    elif quote.volume is not None:
        detail_parts.append(f"累计成交{float(quote.volume):.0f}")
    if volume_pressure_ratio is not None:
        detail_parts.append(f"量能压力{volume_pressure_ratio:.1f}x")

    summary = "盘中快照："
    if state == "gap_down_repair":
        summary += "低开修复，"
    if detail_parts:
        summary += "，".join(detail_parts)
    else:
        summary += "暂无足够前序快照"

    return IntradayQuoteSnapshot(
        symbol=quote.symbol,
        trade_date=quote.trade_date,
        quote_time=quote.quote_time.isoformat(timespec="seconds"),
        state=state,
        label=INTRADAY_STATE_LABELS.get(state, "盘中快照"),
        summary=summary,
        price_change_from_prev_pct=price_change_from_prev_pct,
        session_change_pct=session_change_pct,
        open_gap_pct=_pct_float(open_gap_pct_decimal),
        change_from_open_pct=_pct_float(change_from_open_pct_decimal),
        intraday_high_gain_pct=_pct_float(intraday_high_gain_pct_decimal),
        pullback_from_high_pct=_pct_float(pullback_from_high_pct_decimal),
        near_limit_up=near_limit_up,
        failed_near_limit_up=failed_near_limit_up,
        spike_reversed_to_red=spike_reversed_to_red,
        range_position=range_position,
        current_interval_volume=(
            float(current_interval_volume) if current_interval_volume is not None else None
        ),
        volume_pressure_ratio=volume_pressure_ratio,
        support_flags=support_flags,
        risk_flags=risk_flags,
    )


def _intraday_entry_rejection_reason(
    plan: TradePlan,
    quality,
    snapshot: IntradayQuoteSnapshot | None,
) -> str | None:
    if snapshot is None:
        return None

    if snapshot.state == "downside":
        return f"{snapshot.label}，先不追：{snapshot.summary}"

    if snapshot.state == "distribution":
        if (
            plan.strategy_type == "long_term"
            and quality.candidate_rank is not None
            and quality.candidate_rank <= 3
        ):
            return None
        if quality.confidence_score is not None and quality.confidence_score >= 88 and (
            quality.candidate_rank is not None and quality.candidate_rank <= 5
        ):
            return None
        return f"{snapshot.label}，先等修复：{snapshot.summary}"

    if snapshot.state == "fading":
        if plan.strategy_type == "long_term":
            return None
        if quality.candidate_rank is not None and quality.candidate_rank <= 3 and (
            quality.confidence_score is not None and quality.confidence_score >= 85
        ):
            return None
        return f"{snapshot.label}，先等修复：{snapshot.summary}"

    return None


def _intraday_position_snapshot_alert(
    *,
    position: PaperPosition,
    quote: RealtimeQuoteRow,
    snapshot: IntradayQuoteSnapshot | None,
) -> RealtimePaperAlert | None:
    if snapshot is None:
        return None
    if snapshot.state in {
        "fresh",
        "balanced",
        "strong_continuation",
        "gap_down_repair",
        "pullback_repair",
    }:
        return None

    severity = "low" if position.strategy_type == "long_term" else "medium"
    if snapshot.state == "downside":
        message = f"{position.symbol} 盘中快照转弱，{snapshot.summary}，先看是否继续失守。"
    elif snapshot.state == "distribution":
        message = f"{position.symbol} 盘中放量分歧，{snapshot.summary}，先观察承接。"
    else:
        if position.strategy_type == "long_term":
            message = (
                f"{position.symbol} 长期仓位出现正常回调，"
                f"{snapshot.summary}，先观察是否修复。"
            )
        else:
            message = f"{position.symbol} 盘中快照转弱，{snapshot.summary}，注意是否继续回落。"

    return _alert(
        position=position,
        quote=quote,
        alert_type="intraday_snapshot_watch",
        severity=severity,
        message=message,
        price=_decimal(quote.price),
        reasons=[snapshot.summary],
        support_flags=snapshot.support_flags,
        risk_flags=snapshot.risk_flags,
        intraday_snapshot=snapshot.to_dict(),
    )


def _position_t_rhythm_alert(
    *,
    position: PaperPosition,
    quote: RealtimeQuoteRow,
    snapshot: IntradayQuoteSnapshot | None = None,
) -> RealtimePaperAlert | None:
    if str(position.strategy_type or "") not in T_RHYTHM_STRATEGIES:
        return None
    price = _decimal(quote.price)
    high = _decimal(quote.high) or price
    low = _decimal(quote.low) or price
    if price is None or high is None or low is None or position.entry_price <= 0:
        return None

    pnl = price / position.entry_price - Decimal("1")
    runup = high / position.entry_price - Decimal("1")
    pullback_from_high = high / price - Decimal("1") if price > 0 else Decimal("0")
    range_position = _range_position_decimal(price, high, low)
    strategy = str(position.strategy_type or "")
    reduce_gain_min = T_REDUCE_GAIN_MIN_BY_STRATEGY.get(strategy, Decimal("0.100"))
    add_pullback_min = T_ADD_PULLBACK_MIN_BY_STRATEGY.get(strategy, Decimal("0.055"))

    if (
        pnl >= T_ADD_MIN_PROFIT_BUFFER
        and add_pullback_min <= pullback_from_high <= T_ADD_PULLBACK_MAX
        and range_position is not None
        and range_position >= Decimal("0.35")
        and snapshot is not None
        and snapshot.state in {
            "pullback_repair",
            "gap_down_repair",
            "balanced",
            "strong_continuation",
        }
    ):
        message = (
            f"{position.symbol} 中长期仓位进入做T接回观察区：浮盈{pnl:.2%}，"
            f"高点回撤{pullback_from_high:.2%}，盘中承接未破坏。只考虑接回机动仓，"
            "不要把底仓节奏做乱。"
        )
        return _alert(
            position=position,
            quote=quote,
            alert_type="t_rhythm_add_watch",
            severity="low",
            message=message,
            price=price,
            reasons=[
                f"pnl={pnl:.2%}",
                f"pullback_from_high={pullback_from_high:.2%}",
                f"snapshot={snapshot.state}",
            ],
            support_flags=[*snapshot.support_flags, "t_add_zone"],
            risk_flags=snapshot.risk_flags,
            intraday_snapshot=snapshot.to_dict(),
        )

    if (
        runup >= reduce_gain_min
        and pullback_from_high >= T_REDUCE_PULLBACK_FROM_HIGH_MIN
        and range_position is not None
        and range_position <= Decimal("0.55")
        and (snapshot is None or snapshot.state in {"distribution", "fading", "downside"})
    ):
        message = (
            f"{position.symbol} 中长期仓位进入做T减仓区：浮盈{pnl:.2%}，"
            f"高点回撤{pullback_from_high:.2%}。底仓不急着丢，机动仓可考虑减一档，"
            "等回踩承接再接回。"
        )
        return _alert(
            position=position,
            quote=quote,
            alert_type="t_rhythm_reduce_watch",
            severity="medium",
            message=message,
            price=price,
            reasons=[
                f"runup={runup:.2%}",
                f"pullback_from_high={pullback_from_high:.2%}",
                f"range_position={range_position:.0%}",
            ],
            support_flags=snapshot.support_flags if snapshot is not None else [],
            risk_flags=[*(snapshot.risk_flags if snapshot is not None else []), "t_reduce_zone"],
            intraday_snapshot=snapshot.to_dict() if snapshot is not None else None,
        )

    return None


def _alert(
    *,
    position: PaperPosition,
    quote: RealtimeQuoteRow,
    alert_type: str,
    severity: str,
    message: str,
    price: Decimal | None,
    reasons: list[str] | None = None,
    support_flags: list[str] | None = None,
    risk_flags: list[str] | None = None,
    intraday_snapshot: dict | None = None,
) -> RealtimePaperAlert:
    return RealtimePaperAlert(
        account_id=position.account_id,
        position_id=position.id,
        symbol=position.symbol,
        alert_type=alert_type,
        severity=severity,
        message=message,
        alert_time=quote.quote_time.isoformat(timespec="seconds"),
        price=_float(price),
        current_stop=_float(position.current_stop),
        pnl_pct=_pnl_pct(position, price),
        rule_id=position.rule_id,
        strategy_type=position.strategy_type,
        intraday_snapshot=intraday_snapshot,
        reasons=reasons or [],
        support_flags=support_flags or [],
        risk_flags=risk_flags or [],
    )


def _plan_alert(
    *,
    account_id: int,
    plan: TradePlan,
    quote: RealtimeQuoteRow,
    alert_type: str,
    severity: str,
    message: str,
    price: Decimal | None,
    extra_reasons: list[str] | None = None,
    extra_support_flags: list[str] | None = None,
    extra_risk_flags: list[str] | None = None,
    intraday_snapshot: dict | None = None,
) -> RealtimePaperAlert:
    evidence = (
        plan.entry_condition_json.get("evidence")
        if isinstance(plan.entry_condition_json, dict)
        else {}
    )
    support_flags = evidence.get("support_flags") if isinstance(evidence, dict) else []
    risk_flags = evidence.get("risk_flags") if isinstance(evidence, dict) else []
    reasons = []
    if isinstance(support_flags, list):
        reasons.extend(str(item) for item in support_flags[:3])
    if isinstance(risk_flags, list):
        reasons.extend(str(item) for item in risk_flags[:3])
    if extra_reasons:
        reasons.extend(str(item) for item in extra_reasons if item)
    if extra_support_flags:
        if isinstance(support_flags, list):
            support_flags = [*support_flags, *[item for item in extra_support_flags if item]]
        else:
            support_flags = [item for item in extra_support_flags if item]
    if extra_risk_flags:
        if isinstance(risk_flags, list):
            risk_flags = [*risk_flags, *[item for item in extra_risk_flags if item]]
        else:
            risk_flags = [item for item in extra_risk_flags if item]
    return RealtimePaperAlert(
        account_id=account_id,
        position_id=None,
        symbol=plan.symbol,
        alert_type=alert_type,
        severity=severity,
        message=message,
        alert_time=quote.quote_time.isoformat(timespec="seconds"),
        price=_float(price),
        current_stop=_float(plan.initial_stop),
        pnl_pct=None,
        rule_id=plan.rule_id,
        strategy_type=plan.strategy_type,
        candidate_score=_float(plan.confidence_score),
        intraday_snapshot=intraday_snapshot,
        reasons=reasons,
        support_flags=(
            [str(item) for item in support_flags[:3]] if isinstance(support_flags, list) else []
        ),
        risk_flags=[str(item) for item in risk_flags[:3]] if isinstance(risk_flags, list) else [],
    )


def _target_symbols(db, account_id: int, trade_date: date) -> set[str]:
    symbols = {position.symbol for position in load_open_positions(db, account_id)}
    symbols.update(plan.symbol for plan in load_trade_plans_for_trade_date(db, trade_date))
    return symbols


def _active_candidate_symbols(db) -> set[str]:
    stmt = (
        select(ResearchPoolItem)
        .where(ResearchPoolItem.pool_name.in_(("experiment", "experiment_star")))
        .where(ResearchPoolItem.status == "active")
    )
    symbols: set[str] = set()
    for item in filter_latest_candidate_batch_items(list(db.execute(stmt).scalars())):
        tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
        if "after_close_candidate" in tags or "next_session" in tags:
            symbols.add(item.symbol)
    return symbols


def _daily_entry_count(db, account_id: int, trade_date: date) -> int:
    stmt = (
        select(func.count(PaperOrder.id))
        .where(PaperOrder.account_id == account_id)
        .where(PaperOrder.side == "buy")
        .where(PaperOrder.order_date == trade_date)
        .where(PaperOrder.status == "filled")
    )
    return int(db.execute(stmt).scalar_one())


def _quote_map(quotes: list[RealtimeQuoteRow]) -> dict[str, RealtimeQuoteRow]:
    return {quote.symbol: quote for quote in quotes}


def _update_position_from_quote(
    position: PaperPosition,
    quote: RealtimeQuoteRow,
) -> tuple[bool, list[RealtimePaperAlert]]:
    price = _decimal(quote.price)
    high = _decimal(quote.high) or price
    low = _decimal(quote.low) or price
    if position.entry_date.isoformat() == quote.trade_date:
        high = price
        low = price
    changed = False
    alerts: list[RealtimePaperAlert] = []

    if high is not None and high > position.highest_price:
        position.highest_price = high
        changed = True
    if low is not None and low < position.lowest_price:
        position.lowest_price = low
        changed = True

    take_profit_touched = False
    if position.take_profit_1 is not None and high is not None and high >= position.take_profit_1:
        take_profit_touched = True
        trailing_stop = (
            position.highest_price
            * (Decimal("1") - _trailing_drawdown_ratio(position.strategy_type))
        ).quantize(Decimal("0.0001"))
        if position.current_stop is None or trailing_stop > position.current_stop:
            position.current_stop = trailing_stop
            changed = True
        alerts.append(
            _alert(
                position=position,
                quote=quote,
                alert_type="take_profit_touched",
                severity="medium",
                message=f"{position.symbol} 触及第一止盈，已抬高纸面跟踪止损。",
                price=price,
            )
        )

    if (
        not take_profit_touched
        and position.current_stop is not None
        and low is not None
        and low <= position.current_stop
    ):
        alerts.append(
            _alert(
                position=position,
                quote=quote,
                alert_type="stop_loss_touched",
                severity="high",
                message=f"{position.symbol} 盘中触及纸面止损/跟踪止损。",
                price=price,
            )
        )

    if quote.pre_close is not None:
        limit_ratio = _limit_ratio(position.symbol)
        limit_up = (_decimal(quote.pre_close) * limit_ratio).quantize(Decimal("0.0001"))
        limit_down = (_decimal(quote.pre_close) * (Decimal("2") - limit_ratio)).quantize(
            Decimal("0.0001")
        )
        if high is not None and high >= limit_up:
            alerts.append(
                _alert(
                    position=position,
                    quote=quote,
                    alert_type="limit_up_touched",
                    severity="medium",
                    message=f"{position.symbol} 盘中触及或接近涨停价。",
                    price=price,
                )
            )
        if low is not None and low <= limit_down:
            alerts.append(
                _alert(
                    position=position,
                    quote=quote,
                    alert_type="limit_down_touched",
                    severity="high",
                    message=f"{position.symbol} 盘中触及或接近跌停价。",
                    price=price,
                )
            )

    return changed, alerts


def _persist_alerts(db, alerts: list[RealtimePaperAlert]) -> int:
    if not alerts:
        return 0
    rows = [
        {
            "account_id": alert.account_id,
            "position_id": alert.position_id,
            "symbol": alert.symbol,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "alert_time": datetime.fromisoformat(alert.alert_time),
            "price": Decimal(str(alert.price)) if alert.price is not None else None,
            "current_stop": (
                Decimal(str(alert.current_stop)) if alert.current_stop is not None else None
            ),
            "pnl_pct": Decimal(str(alert.pnl_pct)) if alert.pnl_pct is not None else None,
            "message": alert.message,
            "status": "open",
        }
        for alert in alerts
    ]
    return upsert_rows(
        db,
        PaperAlert,
        rows,
        update_columns=["severity", "price", "current_stop", "pnl_pct", "message"],
        constraint="uq_paper_alert_event",
    )


def _realtime_exit_signal(
    position: PaperPosition,
    quote: RealtimeQuoteRow,
) -> tuple[bool, Decimal | None, str]:
    low = _decimal(quote.price) if position.entry_date.isoformat() == quote.trade_date else (
        _decimal(quote.low) or _decimal(quote.price)
    )
    if position.current_stop is None or low is None:
        return False, None, ""
    stop_floor = position.current_stop * _stop_confirmation_buffer(position.strategy_type)
    if low > stop_floor:
        return False, None, ""
    if position.take_profit_1 is not None and position.highest_price >= position.take_profit_1:
        return True, position.current_stop, "trailing_take_profit"
    return True, position.current_stop, "stop_loss"


def _entry_quality_rejection_reason(
    plan: TradePlan,
    quote: RealtimeQuoteRow,
    trigger_price: Decimal,
) -> str | None:
    return price_action_rejection_reason(
        plan,
        price=quote.price,
        open_price=quote.open,
        high=quote.high,
        low=quote.low,
        pre_close=quote.pre_close,
        trigger_price=trigger_price,
    )


def _execute_realtime_exit(
    db,
    account,
    position: PaperPosition,
    exit_price: Decimal,
    reason: str,
    trade_date: date,
) -> None:
    order = PaperOrder(
        account_id=account.id,
        trade_plan_id=position.trade_plan_id,
        symbol=position.symbol,
        side="sell",
        order_date=trade_date,
        planned_price=exit_price,
        quantity=position.quantity,
        status="filled",
        reason=reason,
    )
    db.add(order)
    db.flush()
    trade = create_trade(
        db,
        account_id=account.id,
        order_id=order.id,
        position_id=position.id,
        symbol=position.symbol,
        side="sell",
        trade_date=trade_date,
        price=exit_price,
        quantity=position.quantity,
        reason=f"realtime:{reason}",
    )
    account.cash += trade.amount - trade.fee
    position.status = "closed"
    position.exit_date = trade_date
    position.exit_price = exit_price
    position.exit_reason = reason
    position.pnl = (exit_price - position.entry_price) * Decimal(position.quantity) - trade.fee
    position.pnl_pct = (exit_price / position.entry_price - Decimal("1")).quantize(
        Decimal("0.000001")
    )


def _execute_realtime_entry(
    db,
    account,
    plan: TradePlan,
    quote: RealtimeQuoteRow,
    trade_date: date,
    current_time: datetime,
    *,
    entry_cap_reached: bool = False,
    snapshot: IntradayQuoteSnapshot | None = None,
    market_risk: IntradayMarketRiskSnapshot | None = None,
    open_positions_count: int = 0,
) -> tuple[bool, RealtimePaperAlert | None]:
    if has_open_position(db, account.id, plan.symbol):
        return False, None

    price = _decimal(quote.price)
    open_price = _decimal(quote.open)
    pre_close = _decimal(quote.pre_close)
    if price is None:
        return False, None

    if current_time.time() >= INTRADAY_ENTRY_CUTOFF:
        plan.status = "cancelled"
        return False, _plan_alert(
            account_id=account.id,
            plan=plan,
            quote=quote,
            alert_type="paper_entry_deferred",
            severity="low",
            message=f"{plan.symbol} 临近收盘，不再新开仓。",
            price=price,
        )
    if entry_cap_reached:
        return False, _plan_alert(
            account_id=account.id,
            plan=plan,
            quote=quote,
            alert_type="paper_entry_deferred",
            severity="low",
            message="今日纸面买入笔数已达上限，先不继续开仓。",
            price=price,
        )
    if market_risk is not None and market_risk.blocks_new_entries():
        return False, _plan_alert(
            account_id=account.id,
            plan=plan,
            quote=quote,
            alert_type="paper_entry_deferred",
            severity="high",
            message=f"{plan.symbol} 遇到{market_risk.label}，暂停新开仓：{market_risk.summary}。",
            price=price,
            extra_reasons=[market_risk.summary],
            extra_risk_flags=market_risk.risk_flags,
            intraday_snapshot={"market_risk": market_risk.to_dict()},
        )
    quality = evaluate_plan_entry_quality(db, plan)
    if not quality.accepted:
        quality_detail = quality.detail_text()
        reason_detail = "，".join(quality.reasons[:2])
        return False, _plan_alert(
            account_id=account.id,
            plan=plan,
            quote=quote,
            alert_type="paper_entry_deferred",
            severity="medium",
            message=(
                f"{plan.symbol} 不是足够高质量的盘中计划，先不买"
                f"{('（' + quality_detail + '）') if quality_detail else ''}"
                f"{('：' + reason_detail) if reason_detail else ''}。"
            ),
            price=price,
        )

    trigger_price = (
        _decimal(plan.entry_trigger_price) if plan.entry_trigger_price is not None else price
    )
    max_gap_up_pct = (
        Decimal(str(plan.max_gap_up_pct)) if plan.max_gap_up_pct is not None else Decimal("0.06")
    )
    if open_price is not None and pre_close is not None and pre_close > 0:
        gap_up_pct = open_price / pre_close - Decimal("1")
        if gap_up_pct > max_gap_up_pct:
            plan.status = "cancelled"
            return False, None

    if price < trigger_price:
        return False, None

    rejection_reason = _entry_quality_rejection_reason(plan, quote, trigger_price)
    if rejection_reason:
        return False, _plan_alert(
            account_id=account.id,
            plan=plan,
            quote=quote,
            alert_type="paper_entry_deferred",
            severity="medium",
            message=(
                f"{plan.symbol} 到达计划触发区，但盘中入场质量不足，"
                f"暂缓买入：{rejection_reason}。"
            ),
            price=price,
        )

    snapshot = snapshot or _build_intraday_quote_snapshot(db, quote)
    snapshot_rejection_reason = _intraday_entry_rejection_reason(plan, quality, snapshot)
    if snapshot_rejection_reason:
        return False, _plan_alert(
            account_id=account.id,
            plan=plan,
            quote=quote,
            alert_type="paper_entry_deferred",
            severity="medium",
            message=(
                f"{plan.symbol} 到达计划触发区，但盘中快照偏弱，"
                f"暂缓买入：{snapshot_rejection_reason}。"
            ),
            price=price,
            extra_reasons=[snapshot.summary] if snapshot is not None else None,
            extra_support_flags=snapshot.support_flags if snapshot is not None else None,
            extra_risk_flags=snapshot.risk_flags if snapshot is not None else None,
            intraday_snapshot=snapshot.to_dict() if snapshot is not None else None,
        )

    initial_stop = _decimal(plan.initial_stop)
    if initial_stop is not None and initial_stop >= price:
        plan.status = "cancelled"
        return False, None

    effective_position_size = adjusted_position_size_pct(
        plan.position_size,
        open_positions_count,
        plan.strategy_type,
    )
    quantity = _entry_quantity(account.cash, price, effective_position_size)
    if quantity <= 0:
        return False, None

    order = PaperOrder(
        account_id=account.id,
        trade_plan_id=plan.id,
        symbol=plan.symbol,
        side="buy",
        order_date=trade_date,
        planned_price=price,
        quantity=quantity,
        status="filled",
        reason=f"realtime_entry:{plan.rule_id}",
    )
    db.add(order)
    db.flush()

    trade = create_trade(
        db,
        account_id=account.id,
        order_id=order.id,
        position_id=None,
        symbol=plan.symbol,
        side="buy",
        trade_date=trade_date,
        price=price,
        quantity=quantity,
        reason=f"realtime_open_by_plan:{plan.rule_id}",
    )
    cost = trade.amount + trade.fee
    if cost > account.cash:
        order.status = "rejected"
        return False, None

    account.cash -= cost
    position = PaperPosition(
        account_id=account.id,
        trade_plan_id=plan.id,
        symbol=plan.symbol,
        rule_id=plan.rule_id,
        strategy_type=plan.strategy_type,
        entry_date=trade_date,
        entry_price=price,
        quantity=quantity,
        initial_stop=plan.initial_stop,
        current_stop=plan.initial_stop,
        take_profit_1=plan.take_profit_1,
        take_profit_2=plan.take_profit_2,
        highest_price=price,
        lowest_price=price,
        max_holding_days=plan.max_holding_days,
        status="open",
    )
    db.add(position)
    db.flush()
    trade.position_id = position.id
    plan.status = "executed"

    concentration_note = ""
    if effective_position_size < Decimal(str(plan.position_size)):
        concentration_note = (
            f" 当前持仓 {open_positions_count} 只，单票仓位已调到 "
            f"{effective_position_size:.2%}。"
        )

    return True, _alert(
        position=position,
        quote=quote,
        alert_type="paper_entry_filled",
        severity="medium",
        message=(
            f"{plan.symbol} 纸面买入已触发，价格 {price}，数量 {quantity}。"
            f"{concentration_note}"
            f"{(' ' + snapshot.summary) if snapshot is not None else ''}"
        ),
        price=price,
        reasons=[snapshot.summary] if snapshot is not None else [],
        support_flags=snapshot.support_flags if snapshot is not None else [],
        risk_flags=snapshot.risk_flags if snapshot is not None else [],
        intraday_snapshot=snapshot.to_dict() if snapshot is not None else None,
    )


def monitor_paper_positions_realtime(
    trade_date: str | None = None,
    account_name: str = "default",
    quotes: list[RealtimeQuoteRow] | None = None,
    quote_time: datetime | None = None,
    snapshot_stage: str | None = None,
    execute_entries: bool = True,
    execute_exits: bool = False,
    market_overview: dict[str, float] | None = None,
) -> RealtimePaperMonitorResult:
    current_time = (quote_time or now_local()).replace(tzinfo=None)
    current_date = date.fromisoformat(trade_date) if trade_date else current_time.date()

    with SessionLocal() as db:
        account = get_or_create_account(db, name=account_name)
        target_symbols = _target_symbols(db, account.id, current_date)
        quote_rows = quotes
        if quote_rows is None and target_symbols:
            try:
                quote_rows = fetch_sina_realtime_quotes(
                    symbols=target_symbols,
                    quote_time=current_time,
                )
            except Exception as exc:
                db.rollback()
                return RealtimePaperMonitorResult(
                    status="failed",
                    message=f"{type(exc).__name__}: {exc}",
                    quote_time=current_time.isoformat(timespec="seconds"),
                    target_symbols=len(target_symbols),
                    quotes=0,
                    updated_positions=0,
                    executed_entries=0,
                    executed_exits=0,
                    alerts=[],
                    notifications=[],
                )
        quote_rows = quote_rows or []
        if quote_rows:
            upsert_realtime_quotes(db, quote_rows)

        by_symbol = _quote_map(quote_rows)
        intraday_snapshots = {
            symbol: _build_intraday_quote_snapshot(db, quote)
            for symbol, quote in by_symbol.items()
        }
        candidate_symbols = _active_candidate_symbols(db)
        market_risk = _build_intraday_market_risk_snapshot(
            quotes=quote_rows,
            candidate_symbols=candidate_symbols,
            market_overview=market_overview,
        )
        updated_positions = 0
        executed_entries = 0
        executed_exits = 0
        alerts: list[RealtimePaperAlert] = []
        daily_entry_cap = INTRADAY_DAILY_ENTRY_CAP
        existing_daily_entries = _daily_entry_count(db, account.id, current_date)
        open_positions_count = len(load_open_positions(db, account.id))
        if execute_entries:
            for plan in load_trade_plans_for_trade_date(db, current_date):
                quote = by_symbol.get(plan.symbol)
                if quote is None:
                    continue
                remaining_slots = daily_entry_cap - existing_daily_entries - executed_entries
                opened, entry_alert = _execute_realtime_entry(
                    db,
                    account,
                    plan,
                    quote,
                    current_date,
                    current_time,
                    entry_cap_reached=remaining_slots <= 0,
                    snapshot=intraday_snapshots.get(plan.symbol),
                    market_risk=market_risk,
                    open_positions_count=open_positions_count,
                )
                if opened:
                    executed_entries += 1
                    open_positions_count += 1
                if entry_alert is not None:
                    alerts.append(entry_alert)

        for position in load_open_positions(db, account.id):
            quote = by_symbol.get(position.symbol)
            if quote is None:
                continue
            if execute_exits:
                should_exit, exit_price, reason = _realtime_exit_signal(position, quote)
                if should_exit and exit_price is not None:
                    _execute_realtime_exit(db, account, position, exit_price, reason, current_date)
                    upsert_paper_trade_review_for_position(db, position)
                    executed_exits += 1
                    continue
            changed, position_alerts = _update_position_from_quote(position, quote)
            if changed:
                updated_positions += 1
            alerts.extend(position_alerts)
            snapshot_alert = _intraday_position_snapshot_alert(
                position=position,
                quote=quote,
                snapshot=intraday_snapshots.get(position.symbol),
            )
            if snapshot_alert is not None:
                alerts.append(snapshot_alert)
            rhythm_alert = _position_t_rhythm_alert(
                position=position,
                quote=quote,
                snapshot=intraday_snapshots.get(position.symbol),
            )
            if rhythm_alert is not None:
                alerts.append(rhythm_alert)

        _persist_alerts(db, alerts)
        db.commit()

    notifications = dispatch_paper_alerts([alert.to_dict() for alert in alerts])

    return RealtimePaperMonitorResult(
        status="ok",
        message="realtime paper monitor completed",
        quote_time=current_time.isoformat(timespec="seconds"),
        target_symbols=len(target_symbols),
        quotes=len(quote_rows),
        updated_positions=updated_positions,
        executed_entries=executed_entries,
        executed_exits=executed_exits,
        alerts=alerts,
        notifications=[item.to_dict() for item in notifications],
    )


def run_realtime_monitor_loop(
    *,
    interval_seconds: float = 30.0,
    max_ticks: int | None = None,
    trade_date: str | None = None,
    account_name: str = "default",
    execute_entries: bool = True,
    execute_exits: bool = False,
) -> list[RealtimePaperMonitorResult]:
    results: list[RealtimePaperMonitorResult] = []
    tick = 0
    while max_ticks is None or tick < max_ticks:
        results.append(
            monitor_paper_positions_realtime(
                trade_date=trade_date,
                account_name=account_name,
                execute_entries=execute_entries,
                execute_exits=execute_exits,
            )
        )
        tick += 1
        if max_ticks is not None and tick >= max_ticks:
            break
        sleep(max(1.0, interval_seconds))
    return results
