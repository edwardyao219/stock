from __future__ import annotations

from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True)
class BarInput:
    symbol: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    pre_close: float | None
    amount: float | None
    volume: float | None = None
    turnover_rate: float | None = None


@dataclass(frozen=True)
class StockFeatureRow:
    symbol: str
    trade_date: str
    features: dict[str, float | bool | None]


def _return_pct(current: float, previous: float | None) -> float | None:
    if previous is None or previous == 0:
        return None
    return current / previous - 1


def _ma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return mean(values[-window:])


def _rolling_high(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return max(values[-window:])


def _percentile_rank(values: list[float | None], current: float | None) -> float | None:
    clean_values = [value for value in values if value is not None]
    if current is None or not clean_values:
        return None
    lower_or_equal = sum(1 for value in clean_values if value <= current)
    return lower_or_equal / len(clean_values) * 100


def _true_range(bar: BarInput) -> float:
    if bar.pre_close is None:
        return bar.high - bar.low
    return max(
        bar.high - bar.low,
        abs(bar.high - bar.pre_close),
        abs(bar.low - bar.pre_close),
    )


def _score_between(value: float | None, low: float, high: float) -> float:
    if value is None:
        return 50.0
    if high == low:
        return 50.0
    score = (value - low) / (high - low) * 100
    return max(0.0, min(100.0, score))


def compute_stock_daily_features(bars: list[BarInput]) -> list[StockFeatureRow]:
    ordered = sorted(bars, key=lambda item: item.trade_date)
    rows: list[StockFeatureRow] = []

    closes: list[float] = []
    highs: list[float] = []
    amounts: list[float | None] = []
    true_ranges: list[float] = []

    for bar in ordered:
        closes.append(bar.close)
        highs.append(bar.high)
        amounts.append(bar.amount)
        true_ranges.append(_true_range(bar))

        ma5 = _ma(closes, 5)
        ma10 = _ma(closes, 10)
        ma20 = _ma(closes, 20)
        ma60 = _ma(closes, 60)
        high_20d = _rolling_high(highs, 20)
        atr_14 = _ma(true_ranges, 14)

        close_1d_ago = closes[-2] if len(closes) >= 2 else None
        close_3d_ago = closes[-4] if len(closes) >= 4 else None
        close_5d_ago = closes[-6] if len(closes) >= 6 else None
        close_20d_ago = closes[-21] if len(closes) >= 21 else None

        return_1d = _return_pct(bar.close, close_1d_ago)
        return_3d = _return_pct(bar.close, close_3d_ago)
        return_5d = _return_pct(bar.close, close_5d_ago)
        return_20d = _return_pct(bar.close, close_20d_ago)

        distance_to_ma5 = _return_pct(bar.close, ma5)
        distance_to_ma10 = _return_pct(bar.close, ma10)
        distance_to_ma20 = _return_pct(bar.close, ma20)
        distance_to_ma60 = _return_pct(bar.close, ma60)
        distance_to_20d_high = None
        if high_20d and high_20d != 0:
            distance_to_20d_high = bar.close / high_20d - 1

        amount_percentile_60d = _percentile_rank(amounts[-60:], bar.amount)
        turnover_percentile_60d = None

        trend_components = [
            1 if ma5 and bar.close >= ma5 else 0,
            1 if ma10 and bar.close >= ma10 else 0,
            1 if ma20 and bar.close >= ma20 else 0,
            1 if ma60 and bar.close >= ma60 else 0,
        ]
        trend_score = sum(trend_components) / len(trend_components) * 100
        volume_score = amount_percentile_60d or 50.0
        position_score = 100.0 - _score_between(abs(distance_to_20d_high or 0), 0.0, 0.15)
        volatility_score = _score_between((atr_14 / bar.close) if atr_14 and bar.close else None, 0.01, 0.08)
        relative_strength_score = _score_between(return_20d, -0.20, 0.30)
        risk_score = max(0.0, 100.0 - trend_score)

        rows.append(
            StockFeatureRow(
                symbol=bar.symbol,
                trade_date=bar.trade_date,
                features={
                    "return_1d": return_1d,
                    "return_3d": return_3d,
                    "return_5d": return_5d,
                    "return_20d": return_20d,
                    "ma5": ma5,
                    "ma10": ma10,
                    "ma20": ma20,
                    "ma60": ma60,
                    "atr_14": atr_14,
                    "distance_to_ma5": distance_to_ma5,
                    "distance_to_ma10": distance_to_ma10,
                    "distance_to_ma20": distance_to_ma20,
                    "distance_to_ma60": distance_to_ma60,
                    "distance_to_20d_high": distance_to_20d_high,
                    "amount_percentile_60d": amount_percentile_60d,
                    "turnover_percentile_60d": turnover_percentile_60d,
                    "trend_score": trend_score,
                    "volume_score": volume_score,
                    "position_score": position_score,
                    "volatility_score": volatility_score,
                    "relative_strength_score": relative_strength_score,
                    "risk_score": risk_score,
                    "is_st": False,
                    "is_suspended": False,
                },
            )
        )

    return rows
