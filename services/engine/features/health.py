from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.engine.features.late_market_turn_health import late_market_turn_history_health
from services.shared.models import (
    DailyBar,
    MarketRegimeDaily,
    Security,
    StockFeatureDaily,
    TushareCyqPerf,
    TushareLimitListD,
    TushareMoneyflow,
    TushareMoneyflowDc,
)

MIN_DISTRIBUTION_SAMPLE_SIZE = 3
DAILY_CANDIDATE_MIN_COVERAGE_RATIO = 0.98
DAILY_CANDIDATE_MAX_AMOUNT_MISSING_RATIO = 0.01


@dataclass(frozen=True)
class DataHealthIssue:
    code: str
    severity: str
    message: str
    metric: str
    value: float | int | None
    threshold: float | int | None


@dataclass(frozen=True)
class DailyDataHealthReport:
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
    market_regime: str | None
    market_regime_updated_at: datetime | None
    candidate_block_reasons: list[str] = field(default_factory=list)
    late_market_turn_20d: dict[str, int] = field(default_factory=dict)
    issues: list[DataHealthIssue] = field(default_factory=list)


def _float(value: Decimal | float | int | None) -> float | None:
    return float(value) if value is not None else None


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int((len(ordered) - 1) * percentile)
    return ordered[index]


def _feature_float(features: dict[str, Any], key: str) -> float | None:
    value = features.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _amount_missing_ratio(rows: list[DailyBar]) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if row.amount is None) / len(rows)


def _amount_volume_multipliers(rows: list[DailyBar]) -> list[float]:
    multipliers: list[float] = []
    for row in rows:
        amount = _float(row.amount)
        volume = _float(row.volume)
        close = _float(row.close)
        if amount is None or volume is None or close is None:
            continue
        if amount <= 0 or volume <= 0 or close <= 0:
            continue
        multipliers.append(amount / (volume * close))
    return multipliers


def _volumes(rows: list[DailyBar], *, amount_missing: bool | None = None) -> list[float]:
    values: list[float] = []
    for row in rows:
        if amount_missing is not None and (row.amount is None) is not amount_missing:
            continue
        value = _float(row.volume)
        if value is not None and value > 0:
            values.append(value)
    return values


def _latest_trade_date(db: Session) -> date | None:
    return db.execute(select(func.max(DailyBar.trade_date))).scalar_one_or_none()


def _previous_trade_date(db: Session, trade_date: date) -> date | None:
    return db.execute(
        select(func.max(DailyBar.trade_date)).where(DailyBar.trade_date < trade_date)
    ).scalar_one_or_none()


def _daily_bars(db: Session, trade_date: date | None) -> list[DailyBar]:
    if trade_date is None:
        return []
    return list(db.execute(select(DailyBar).where(DailyBar.trade_date == trade_date)).scalars())


def inspect_tushare_evidence_health(
    db: Session,
    trade_date: date,
    sync_statuses: dict[str, str] | None = None,
) -> dict[str, Any]:
    eligible_rows = list(
        db.execute(
            select(DailyBar.symbol, Security.exchange)
            .join(Security, Security.symbol == DailyBar.symbol)
            .where(DailyBar.trade_date == trade_date)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).all()
    )
    eligible_symbols = {str(symbol) for symbol, _ in eligible_rows}

    def full_market_dataset(
        name: str,
        model: type,
        supported_exchanges: set[str] | None = None,
    ) -> dict[str, Any]:
        supported_symbols = {
            str(symbol)
            for symbol, exchange in eligible_rows
            if supported_exchanges is None or str(exchange) in supported_exchanges
        }
        ts_codes = list(
            db.execute(select(model.ts_code).where(model.trade_date == trade_date)).scalars()
        )
        matched_rows = sum(
            1 for ts_code in ts_codes if str(ts_code).split(".", 1)[0] in supported_symbols
        )
        coverage_ratio = matched_rows / len(supported_symbols) if supported_symbols else None
        if not ts_codes:
            status = "missing"
        elif coverage_ratio is not None and coverage_ratio >= 0.98:
            status = "ok"
        else:
            status = "partial"
        return {
            "name": name,
            "rows": len(ts_codes),
            "matched_rows": matched_rows,
            "coverage_ratio": coverage_ratio,
            "status": status,
        }

    limit_codes = list(
        db.execute(
            select(TushareLimitListD.ts_code).where(TushareLimitListD.trade_date == trade_date)
        ).scalars()
    )
    limit_matched_rows = sum(
        1 for ts_code in limit_codes if str(ts_code).split(".", 1)[0] in eligible_symbols
    )
    limit_status = (
        "ok"
        if limit_codes or (sync_statuses or {}).get("limit_list_d") in {"ok", "skipped"}
        else "missing"
    )
    return {
        "trade_date": trade_date.isoformat(),
        "daily_symbol_count": len(eligible_symbols),
        "datasets": [
            full_market_dataset("moneyflow", TushareMoneyflow, {"SH", "SZ"}),
            full_market_dataset("moneyflow_dc", TushareMoneyflowDc, {"SH", "SZ"}),
            full_market_dataset("cyq_perf", TushareCyqPerf),
            {
                "name": "limit_list_d",
                "rows": len(limit_codes),
                "matched_rows": limit_matched_rows,
                "coverage_ratio": None,
                "status": limit_status,
            },
        ],
    }


def _features(db: Session, trade_date: date | None) -> list[StockFeatureDaily]:
    if trade_date is None:
        return []
    return list(
        db.execute(select(StockFeatureDaily).where(StockFeatureDaily.trade_date == trade_date))
        .scalars()
        .all()
    )


def _issue(
    code: str,
    severity: str,
    message: str,
    metric: str,
    value: float | int | None,
    threshold: float | int | None,
) -> DataHealthIssue:
    return DataHealthIssue(
        code=code,
        severity=severity,
        message=message,
        metric=metric,
        value=_round(value) if isinstance(value, float) else value,
        threshold=threshold,
    )


def _status(issues: list[DataHealthIssue]) -> str:
    if any(issue.severity == "critical" for issue in issues):
        return "critical"
    if issues:
        return "warning"
    return "ok"


def inspect_daily_data_health(
    db: Session,
    trade_date: date | None = None,
) -> DailyDataHealthReport:
    target_date = trade_date or _latest_trade_date(db)
    previous_date = _previous_trade_date(db, target_date) if target_date is not None else None

    bars = _daily_bars(db, target_date)
    previous_bars = _daily_bars(db, previous_date)
    feature_rows = _features(db, target_date)
    market_regime_row = db.get(MarketRegimeDaily, target_date) if target_date else None
    eligible_symbols = set(
        db.execute(
            select(Security.symbol)
            .where(Security.is_active.is_(True))
            .where(Security.is_st.is_(False))
        ).scalars()
    )
    eligible_bars = [row for row in bars if row.symbol in eligible_symbols]

    amount_missing_ratio = _amount_missing_ratio(bars)
    previous_amount_missing_ratio = _amount_missing_ratio(previous_bars)
    multipliers = _amount_volume_multipliers(bars)
    previous_multipliers = _amount_volume_multipliers(previous_bars)
    missing_volume_median = _median(_volumes(bars, amount_missing=True))
    previous_known_volume_median = _median(_volumes(previous_bars, amount_missing=False))
    amount_ratio_5d_values = [
        value
        for row in feature_rows
        if (value := _feature_float(row.features or {}, "amount_ratio_5d")) is not None
    ]
    volume_confirmation_values = [
        value
        for row in feature_rows
        if (value := _feature_float(row.features or {}, "volume_confirmation_score")) is not None
    ]

    amount_ratio_5d_median = _median(amount_ratio_5d_values)
    amount_ratio_5d_p10 = _percentile(amount_ratio_5d_values, 0.10)
    volume_confirmation_median = _median(volume_confirmation_values)
    multiplier_median = _median(multipliers)
    previous_multiplier_median = _median(previous_multipliers)
    expected_security_count = len(eligible_symbols)
    eligible_daily_bar_count = len(eligible_bars)
    daily_coverage_ratio = (
        eligible_daily_bar_count / expected_security_count if expected_security_count else 0.0
    )
    eligible_amount_missing_ratio = _amount_missing_ratio(eligible_bars)
    candidate_block_reasons: list[str] = []
    if expected_security_count == 0:
        candidate_block_reasons.append("有效非ST证券宇宙为空，不能生成候选。")
    elif not eligible_bars:
        candidate_block_reasons.append("目标交易日没有有效非ST日线，不能生成候选。")
    elif daily_coverage_ratio < DAILY_CANDIDATE_MIN_COVERAGE_RATIO:
        candidate_block_reasons.append(
            f"日线覆盖 {daily_coverage_ratio:.1%}，低于 98% 门槛。"
        )
    if (
        eligible_amount_missing_ratio is not None
        and eligible_amount_missing_ratio >= DAILY_CANDIDATE_MAX_AMOUNT_MISSING_RATIO
    ):
        candidate_block_reasons.append(
            f"有效样本成交额缺失 {eligible_amount_missing_ratio:.1%}，达到 1% 门槛。"
        )
    issues: list[DataHealthIssue] = []
    if target_date is None:
        issues.append(
            _issue(
                "daily_bar_missing",
                "warning",
                "暂无日线数据，无法判断特征健康度。",
                "daily_bar_count",
                0,
                1,
            )
        )
    if bars and not feature_rows:
        issues.append(
            _issue(
                "feature_missing",
                "warning",
                "已有日线但缺少当日特征，候选池可能仍在使用旧批次。",
                "feature_count",
                0,
                1,
            )
        )
    if feature_rows and market_regime_row is None:
        issues.append(
            _issue(
                "market_regime_missing",
                "warning",
                "市场阶段缺口：当日特征已完成，但阶段记录尚未生成。",
                "market_regime_daily",
                None,
                None,
            )
        )
    recent_feature_dates = list(
        db.execute(
            select(StockFeatureDaily.trade_date)
            .where(StockFeatureDaily.trade_date <= target_date)
            .group_by(StockFeatureDaily.trade_date)
            .order_by(StockFeatureDaily.trade_date.desc())
            .limit(2)
        ).scalars()
    ) if target_date else []
    if len(recent_feature_dates) == 2 and all(
        db.get(MarketRegimeDaily, trade_date) is None for trade_date in recent_feature_dates
    ):
        issues.append(
            _issue(
                "market_regime_consecutive_missing",
                "warning",
                "市场阶段连续缺口：最近两个特征日均未生成阶段记录。",
                "market_regime_daily",
                2,
                0,
            )
        )
    has_distribution_sample = len(bars) >= MIN_DISTRIBUTION_SAMPLE_SIZE
    has_feature_distribution_sample = len(feature_rows) >= MIN_DISTRIBUTION_SAMPLE_SIZE

    if (
        has_distribution_sample
        and amount_missing_ratio is not None
        and amount_missing_ratio >= 0.5
    ):
        issues.append(
            _issue(
                "daily_amount_missing_high",
                "warning",
                "当日大量日线缺少成交额，量能因子需要依赖估算，需关注单位一致性。",
                "amount_missing_ratio",
                amount_missing_ratio,
                0.5,
            )
        )
    if (
        has_distribution_sample
        and amount_missing_ratio is not None
        and previous_amount_missing_ratio is not None
        and amount_missing_ratio - previous_amount_missing_ratio >= 0.35
    ):
        issues.append(
            _issue(
                "daily_amount_coverage_drop",
                "warning",
                "成交额覆盖率相对上一交易日明显下降，可能是数据源字段缺失或同步不完整。",
                "amount_missing_ratio_delta",
                amount_missing_ratio - previous_amount_missing_ratio,
                0.35,
            )
        )
    if (
        has_feature_distribution_sample
        and amount_ratio_5d_median is not None
        and amount_ratio_5d_median < 0.2
    ):
        issues.append(
            _issue(
                "amount_ratio_5d_too_low",
                "warning",
                "当日 amount_ratio_5d 中位数异常偏低，可能存在历史成交额单位噪音。",
                "amount_ratio_5d_median",
                amount_ratio_5d_median,
                0.2,
            )
        )
    if (
        has_feature_distribution_sample
        and amount_ratio_5d_p10 is not None
        and amount_ratio_5d_p10 < 0.05
    ):
        issues.append(
            _issue(
                "amount_ratio_5d_tail_too_low",
                "warning",
                "部分股票 amount_ratio_5d 极低，需检查是否被历史量额单位污染。",
                "amount_ratio_5d_p10",
                amount_ratio_5d_p10,
                0.05,
            )
        )
    if (
        has_distribution_sample
        and multiplier_median is not None
        and previous_multiplier_median is not None
        and previous_multiplier_median > 0
        and (
            multiplier_median / previous_multiplier_median >= 20
            or previous_multiplier_median / multiplier_median >= 20
        )
    ):
        issues.append(
            _issue(
                "amount_volume_multiplier_mixed",
                "warning",
                "成交额/成交量/价格的隐含倍率相邻交易日差异过大，需警惕股数与手数混用。",
                "amount_volume_multiplier_ratio",
                max(
                    multiplier_median / previous_multiplier_median,
                    previous_multiplier_median / multiplier_median,
                ),
                20,
            )
        )
    elif (
        has_distribution_sample
        and missing_volume_median is not None
        and previous_known_volume_median is not None
        and previous_known_volume_median > 0
        and (
            missing_volume_median / previous_known_volume_median >= 20
            or previous_known_volume_median / missing_volume_median >= 20
        )
    ):
        issues.append(
            _issue(
                "amount_volume_multiplier_mixed",
                "warning",
                "缺少成交额的行与上一交易日有成交额样本的成交量尺度差异过大，需警惕股数与手数混用。",
                "amount_missing_volume_scale_ratio",
                max(
                    missing_volume_median / previous_known_volume_median,
                    previous_known_volume_median / missing_volume_median,
                ),
                20,
            )
        )

    late_market_turn_20d = late_market_turn_history_health(db)

    return DailyDataHealthReport(
        trade_date=target_date,
        status=_status(issues),
        daily_bar_count=len(bars),
        feature_count=len(feature_rows),
        previous_daily_bar_count=len(previous_bars),
        amount_missing_ratio=amount_missing_ratio,
        previous_amount_missing_ratio=previous_amount_missing_ratio,
        amount_ratio_5d_median=amount_ratio_5d_median,
        amount_ratio_5d_p10=amount_ratio_5d_p10,
        volume_confirmation_median=volume_confirmation_median,
        amount_volume_multiplier_median=multiplier_median,
        previous_amount_volume_multiplier_median=previous_multiplier_median,
        expected_security_count=expected_security_count,
        eligible_daily_bar_count=eligible_daily_bar_count,
        daily_coverage_ratio=round(daily_coverage_ratio, 6),
        candidate_generation_allowed=not candidate_block_reasons,
        late_market_turn_20d=late_market_turn_20d,
        market_regime=market_regime_row.regime if market_regime_row else None,
        market_regime_updated_at=market_regime_row.updated_at if market_regime_row else None,
        candidate_block_reasons=candidate_block_reasons,
        issues=issues,
    )
