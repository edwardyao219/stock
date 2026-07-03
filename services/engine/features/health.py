from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.shared.models import DailyBar, StockFeatureDaily

MIN_DISTRIBUTION_SAMPLE_SIZE = 3


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
        issues=issues,
    )
