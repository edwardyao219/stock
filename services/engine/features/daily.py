from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.engine.signals.route import build_signal_route


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
    return sum(values[-window:]) / window


def _rolling_high(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return max(values[-window:])


def _rolling_low(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return min(values[-window:])


def _max_drawdown(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    peak = values[-window]
    max_drawdown = 0.0
    for value in values[-window:]:
        peak = max(peak, value)
        if peak:
            max_drawdown = min(max_drawdown, value / peak - 1)
    return max_drawdown


def _ma_slope(values: list[float], window: int, lookback: int) -> float | None:
    if len(values) < window + lookback:
        return None
    current = sum(values[-window:]) / window
    previous = sum(values[-window - lookback : -lookback]) / window
    if previous == 0:
        return None
    return current / previous - 1


def _component_score(components: list[bool | None]) -> float:
    clean_components = [component for component in components if component is not None]
    if not clean_components:
        return 50.0
    return sum(1 for component in clean_components if component) / len(clean_components) * 100


def _swing_low(lows: list[float], lookback: int = 10) -> float | None:
    if len(lows) < lookback:
        return None
    return min(lows[-lookback:])


def _swing_high(highs: list[float], lookback: int = 10) -> float | None:
    if len(highs) < lookback:
        return None
    return max(highs[-lookback:])


def _percentile_rank(values: list[float | None], current: float | None) -> float | None:
    clean_values = [value for value in values if value is not None]
    if current is None or not clean_values:
        return None
    lower_or_equal = sum(1 for value in clean_values if value <= current)
    return lower_or_equal / len(clean_values) * 100


def _average(values: list[float | None]) -> float | None:
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return None
    return sum(clean_values) / len(clean_values)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _estimate_amount(
    *,
    close: float,
    amount: float | None,
    volume: float | None,
    seen_amount_multipliers: list[float],
    seen_amount_volumes: list[float],
) -> float | None:
    if amount is not None and amount > 0:
        return amount
    if volume is None or volume <= 0 or close <= 0:
        return None

    known_multiplier = _median(seen_amount_multipliers)
    known_volume = _median(seen_amount_volumes)
    if known_multiplier is not None:
        if known_multiplier >= 50.0 and known_volume and volume >= known_volume * 20.0:
            return volume * close
        return volume * close * known_multiplier

    if volume * close >= 100_000_000.0:
        return volume * close
    return volume * close * 100.0


def _rebase_estimated_amount_history(
    *,
    amounts: list[float | None],
    closes: list[float],
    volumes: list[float | None],
    amount_was_estimated: list[bool],
    known_multiplier: float,
    known_volume: float,
) -> None:
    if known_multiplier < 50.0 or known_volume <= 0:
        return
    for index, was_estimated in enumerate(amount_was_estimated):
        if not was_estimated:
            continue
        volume = volumes[index]
        close = closes[index]
        if volume is None or volume <= 0 or close <= 0:
            continue
        if volume >= known_volume * 20.0:
            amounts[index] = volume * close
        else:
            amounts[index] = volume * close * known_multiplier


def _ema(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    multiplier = 2 / (window + 1)
    ema = sum(values[:window]) / window
    for value in values[window:]:
        ema = (value - ema) * multiplier + ema
    return ema


def _rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-window - 1 : -1], values[-window:], strict=False):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(values) < 35:
        return None, None, None
    dif_values: list[float] = []
    for index in range(26, len(values) + 1):
        partial = values[:index]
        ema12 = _ema(partial, 12)
        ema26 = _ema(partial, 26)
        if ema12 is not None and ema26 is not None:
            dif_values.append(ema12 - ema26)
    if len(dif_values) < 9:
        return None, None, None
    dif = dif_values[-1]
    dea = _ema(dif_values, 9)
    hist = dif - dea if dea is not None else None
    return dif, dea, hist


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


def _score_peak(value: float | None, ideal: float, tolerance: float) -> float:
    if value is None:
        return 50.0
    if tolerance <= 0:
        return 50.0
    distance = abs(value - ideal) / tolerance
    return max(0.0, min(100.0, (1 - distance) * 100))


def _route_context(
    *,
    trend_score: float,
    relative_strength_score: float,
    sector_strength_score: float,
    volume_confirmation_score: float,
    risk_score: float,
    overheat_score: float,
    volume_trap_risk_score: float,
    trend_quality_score: float,
    ma_alignment_score: float,
    amount_percentile_60d: float | None,
    amount_ratio_5d: float | None,
    recent_amount_ratio_20d: float | None,
    close_position_in_range: float,
    distance_to_ma20: float | None,
    return_1d: float | None,
    return_5d: float | None,
    return_20d: float | None,
    atr_pct: float | None,
) -> dict[str, Any]:
    route_context = {
        "trend_score": trend_score,
        "relative_strength_score": relative_strength_score,
        "sector_strength_score": sector_strength_score,
        "volume_confirmation_score": volume_confirmation_score,
        "risk_score": risk_score,
        "overheat_score": overheat_score,
        "volume_trap_risk_score": volume_trap_risk_score,
        "trend_quality_score": trend_quality_score,
        "ma_alignment_score": ma_alignment_score,
        "amount_percentile_60d": amount_percentile_60d,
        "amount_ratio_5d": amount_ratio_5d,
        "recent_amount_ratio_20d": recent_amount_ratio_20d,
        "close_position_in_range": close_position_in_range,
        "distance_to_ma20": distance_to_ma20,
        "return_1d": return_1d,
        "return_5d": return_5d,
        "return_20d": return_20d,
        "atr_pct": atr_pct,
    }
    route = build_signal_route(route_context)
    route_context.update(
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
    return route_context


def compute_stock_daily_features(bars: list[BarInput]) -> list[StockFeatureRow]:
    ordered = sorted(bars, key=lambda item: item.trade_date)
    rows: list[StockFeatureRow] = []

    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    amounts: list[float | None] = []
    volumes: list[float | None] = []
    amount_was_estimated: list[bool] = []
    true_ranges: list[float] = []
    ema12: float | None = None
    ema26: float | None = None
    macd_dea: float | None = None
    macd_dif_values: list[float] = []
    seen_amount_multipliers: list[float] = []
    seen_amount_volumes: list[float] = []

    for bar in ordered:
        estimated_amount = _estimate_amount(
            close=bar.close,
            amount=bar.amount,
            volume=bar.volume,
            seen_amount_multipliers=seen_amount_multipliers,
            seen_amount_volumes=seen_amount_volumes,
        )
        if (
            bar.amount is not None
            and bar.amount > 0
            and bar.volume is not None
            and bar.volume > 0
            and bar.close > 0
        ):
            multiplier = bar.amount / (bar.volume * bar.close)
            if multiplier > 0:
                _rebase_estimated_amount_history(
                    amounts=amounts,
                    closes=closes,
                    volumes=volumes,
                    amount_was_estimated=amount_was_estimated,
                    known_multiplier=multiplier,
                    known_volume=bar.volume,
                )
                seen_amount_multipliers.append(multiplier)
                seen_amount_volumes.append(bar.volume)
        closes.append(bar.close)
        highs.append(bar.high)
        lows.append(bar.low)
        amounts.append(estimated_amount)
        volumes.append(bar.volume)
        amount_was_estimated.append(not (bar.amount is not None and bar.amount > 0))
        true_ranges.append(_true_range(bar))

        ma5 = _ma(closes, 5)
        ma10 = _ma(closes, 10)
        ma20 = _ma(closes, 20)
        ma60 = _ma(closes, 60)
        ma20_slope_20d = _ma_slope(closes, 20, 20)
        ma60_slope_20d = _ma_slope(closes, 60, 20)
        high_20d = _rolling_high(highs, 20)
        low_20d = _rolling_low(lows, 20)
        high_60d = _rolling_high(highs, 60)
        low_60d = _rolling_low(lows, 60)
        swing_high_10d = _swing_high(highs, 10)
        swing_low_10d = _swing_low(lows, 10)
        atr_14 = _ma(true_ranges, 14)
        atr_pct = (atr_14 / bar.close) if atr_14 and bar.close else None
        max_drawdown_20d = _max_drawdown(closes, 20)
        rsi_14 = _rsi(closes, 14)
        if len(closes) == 12:
            ema12 = sum(closes[-12:]) / 12
        elif len(closes) > 12 and ema12 is not None:
            ema12 = (bar.close - ema12) * (2 / 13) + ema12
        if len(closes) == 26:
            ema26 = sum(closes[-26:]) / 26
        elif len(closes) > 26 and ema26 is not None:
            ema26 = (bar.close - ema26) * (2 / 27) + ema26
        macd_dif = ema12 - ema26 if ema12 is not None and ema26 is not None else None
        if macd_dif is not None:
            macd_dif_values.append(macd_dif)
            if len(macd_dif_values) == 9:
                macd_dea = sum(macd_dif_values[-9:]) / 9
            elif len(macd_dif_values) > 9 and macd_dea is not None:
                macd_dea = (macd_dif - macd_dea) * (2 / 10) + macd_dea
        macd_hist = macd_dif - macd_dea if macd_dif is not None and macd_dea is not None else None

        close_1d_ago = closes[-2] if len(closes) >= 2 else None
        close_3d_ago = closes[-4] if len(closes) >= 4 else None
        close_5d_ago = closes[-6] if len(closes) >= 6 else None
        close_20d_ago = closes[-21] if len(closes) >= 21 else None

        return_1d = _return_pct(bar.close, close_1d_ago)
        return_3d = _return_pct(bar.close, close_3d_ago)
        return_5d = _return_pct(bar.close, close_5d_ago)
        return_20d = _return_pct(bar.close, close_20d_ago)
        range_pct = (bar.high - bar.low) / bar.close if bar.close else None
        body_pct = abs(bar.close - bar.open) / bar.close if bar.close else None
        close_position_in_range = 0.5
        if bar.high > bar.low:
            close_position_in_range = (bar.close - bar.low) / (bar.high - bar.low)
        upper_shadow_pct = (bar.high - max(bar.open, bar.close)) / bar.close if bar.close else None
        lower_shadow_pct = (min(bar.open, bar.close) - bar.low) / bar.close if bar.close else None

        distance_to_ma5 = _return_pct(bar.close, ma5)
        distance_to_ma10 = _return_pct(bar.close, ma10)
        distance_to_ma20 = _return_pct(bar.close, ma20)
        distance_to_ma60 = _return_pct(bar.close, ma60)
        distance_to_20d_high = None
        if high_20d and high_20d != 0:
            distance_to_20d_high = bar.close / high_20d - 1
        distance_to_20d_low = None
        if low_20d and low_20d != 0:
            distance_to_20d_low = bar.close / low_20d - 1

        amount_percentile_60d = _percentile_rank(amounts[-60:], estimated_amount)
        previous_amount_ma5 = _average(amounts[-6:-1])
        previous_amount_ma20 = _average(amounts[-21:-1])
        recent_amount_ma3 = _average(amounts[-3:])
        fallback_amount = _average(amounts[-20:])
        amount_ratio_5d = (
            estimated_amount / previous_amount_ma5
            if estimated_amount is not None and previous_amount_ma5
            else None
        )
        amount_ratio_20d = (
            estimated_amount / previous_amount_ma20
            if estimated_amount is not None and previous_amount_ma20
            else None
        )
        recent_amount_ratio_20d = (
            recent_amount_ma3 / previous_amount_ma20
            if recent_amount_ma3 is not None and previous_amount_ma20
            else None
        )
        if amount_ratio_5d is None and estimated_amount is not None and fallback_amount:
            amount_ratio_5d = estimated_amount / fallback_amount
        if amount_ratio_20d is None and estimated_amount is not None and fallback_amount:
            amount_ratio_20d = estimated_amount / fallback_amount
        if recent_amount_ratio_20d is None and recent_amount_ma3 is not None and fallback_amount:
            recent_amount_ratio_20d = recent_amount_ma3 / fallback_amount
        atr_pct_percentile_60d = _percentile_rank(
            [
                (value / close) if close else None
                for value, close in zip(true_ranges[-60:], closes[-60:], strict=False)
            ],
            atr_pct,
        )
        turnover_percentile_60d = None
        pullback_to_ma20_pct = abs(distance_to_ma20) if distance_to_ma20 is not None else None
        pullback_volume_ratio = amount_ratio_5d

        ma_alignment_score = _component_score(
            [
                bar.close >= ma5 if ma5 else None,
                ma5 >= ma10 if ma5 and ma10 else None,
                ma10 >= ma20 if ma10 and ma20 else None,
                ma20 >= ma60 if ma20 and ma60 else None,
            ]
        )
        trend_slope_score = (
            _score_between(ma20_slope_20d, -0.02, 0.12) * 0.65
            + _score_between(ma60_slope_20d, -0.01, 0.10) * 0.35
        )
        drawdown_control_score = _score_between(max_drawdown_20d, -0.18, -0.03)
        ma20_distance_control_score = 100.0 - _score_between(
            abs(distance_to_ma20 or 0.0),
            0.04,
            0.20,
        )
        trend_quality_score = max(
            0.0,
            min(
                100.0,
                ma_alignment_score * 0.35
                + trend_slope_score * 0.25
                + drawdown_control_score * 0.15
                + ma20_distance_control_score * 0.15
                + _score_between(return_20d, -0.05, 0.30) * 0.10,
            ),
        )
        volume_confirmation_score = max(
            0.0,
            min(
                100.0,
                _score_peak(amount_ratio_5d, 1.15, 0.55) * 0.45
                + _score_between(amount_percentile_60d, 45.0, 85.0) * 0.35
                + _score_between(close_position_in_range, 0.35, 0.85) * 0.20,
            ),
        )
        macd_trend_score = max(
            0.0,
            min(
                100.0,
                _score_between(macd_dif, -0.10, 0.60) * 0.45
                + _score_between(macd_hist, -0.05, 0.20) * 0.35
                + _score_between(ma20_slope_20d, -0.02, 0.10) * 0.20,
            ),
        )
        overheat_score = max(
            0.0,
            min(
                100.0,
                _score_between(return_20d, 0.12, 0.35) * 0.35
                + _score_between(distance_to_ma20, 0.08, 0.24) * 0.35
                + _score_between(amount_ratio_5d, 1.35, 2.50) * 0.20
                + _score_between(upper_shadow_pct, 0.02, 0.10) * 0.10,
            ),
        )

        trend_components = [
            1 if ma5 and bar.close >= ma5 else 0,
            1 if ma10 and bar.close >= ma10 else 0,
            1 if ma20 and bar.close >= ma20 else 0,
            1 if ma60 and bar.close >= ma60 else 0,
        ]
        trend_score = sum(trend_components) / len(trend_components) * 100
        volume_score = amount_percentile_60d or 50.0
        position_score = 100.0 - _score_between(abs(distance_to_20d_high or 0), 0.0, 0.15)
        volatility_score = _score_between(atr_pct, 0.01, 0.08)
        relative_strength_score = _score_between(return_20d, -0.20, 0.30)
        risk_score = max(0.0, 100.0 - trend_score)
        volume_trap_risk_score = max(
            0.0,
            min(
                100.0,
                (amount_percentile_60d or 50.0) * 0.30
                + (100.0 - close_position_in_range * 100.0) * 0.30
                + _score_between(upper_shadow_pct, 0.0, 0.10) * 0.25
                + _score_between(return_5d, 0.0, 0.20) * 0.15,
            ),
        )
        rsi_health_score = _score_peak(rsi_14, 62.0, 22.0)
        price_volume_trend_score = max(
            0.0,
            min(
                100.0,
                macd_trend_score * 0.22
                + trend_quality_score * 0.18
                + volume_confirmation_score * 0.30
                + rsi_health_score * 0.15
                + (100.0 - volume_trap_risk_score) * 0.15,
            ),
        )
        route_context = _route_context(
            trend_score=trend_score,
            relative_strength_score=relative_strength_score,
            sector_strength_score=50.0,
            volume_confirmation_score=volume_confirmation_score,
            risk_score=risk_score,
            overheat_score=overheat_score,
            volume_trap_risk_score=volume_trap_risk_score,
            trend_quality_score=trend_quality_score,
            ma_alignment_score=ma_alignment_score,
            amount_percentile_60d=amount_percentile_60d,
            amount_ratio_5d=amount_ratio_5d,
            recent_amount_ratio_20d=recent_amount_ratio_20d,
            close_position_in_range=close_position_in_range,
            distance_to_ma20=distance_to_ma20,
            return_1d=return_1d,
            return_5d=return_5d,
            return_20d=return_20d,
            atr_pct=atr_pct,
        )

        rows.append(
            StockFeatureRow(
                symbol=bar.symbol,
                trade_date=bar.trade_date,
                features={
                    "return_1d": return_1d,
                    "return_3d": return_3d,
                    "return_5d": return_5d,
                    "return_20d": return_20d,
                    "range_pct": range_pct,
                    "body_pct": body_pct,
                    "close_position_in_range": close_position_in_range,
                    "upper_shadow_pct": upper_shadow_pct,
                    "lower_shadow_pct": lower_shadow_pct,
                    "ma5": ma5,
                    "ma10": ma10,
                    "ma20": ma20,
                    "ma60": ma60,
                    "ma20_slope_20d": ma20_slope_20d,
                    "ma60_slope_20d": ma60_slope_20d,
                    "atr_14": atr_14,
                    "atr_pct": atr_pct,
                    "atr_pct_percentile_60d": atr_pct_percentile_60d,
                    "rsi_14": rsi_14,
                    "macd_dif": macd_dif,
                    "macd_dea": macd_dea,
                    "macd_hist": macd_hist,
                    "macd_trend_score": macd_trend_score,
                    "price_volume_trend_score": price_volume_trend_score,
                    "recent_high_20d": high_20d,
                    "recent_low_20d": low_20d,
                    "recent_high_60d": high_60d,
                    "recent_low_60d": low_60d,
                    "swing_high_10d": swing_high_10d,
                    "swing_low_10d": swing_low_10d,
                    "support_level": swing_low_10d or low_20d,
                    "resistance_level": swing_high_10d or high_20d,
                    "breakout_level": high_20d,
                    "max_drawdown_20d": max_drawdown_20d,
                    "distance_to_ma5": distance_to_ma5,
                    "distance_to_ma10": distance_to_ma10,
                    "distance_to_ma20": distance_to_ma20,
                    "distance_to_ma60": distance_to_ma60,
                    "distance_to_20d_high": distance_to_20d_high,
                    "distance_to_20d_low": distance_to_20d_low,
                    "amount_percentile_60d": amount_percentile_60d,
                    "amount_ratio_5d": amount_ratio_5d,
                    "amount_ratio_20d": amount_ratio_20d,
                    "recent_amount_ratio_20d": recent_amount_ratio_20d,
                    "pullback_to_ma20_pct": pullback_to_ma20_pct,
                    "pullback_volume_ratio": pullback_volume_ratio,
                    "turnover_percentile_60d": turnover_percentile_60d,
                    "ma_alignment_score": ma_alignment_score,
                    "trend_quality_score": trend_quality_score,
                    "volume_confirmation_score": volume_confirmation_score,
                    "overheat_score": overheat_score,
                    "trend_score": trend_score,
                    "volume_score": volume_score,
                    "route_score": route_context["route_score"],
                    "route_label": route_context["route_label"],
                    "route_reason": route_context["route_reason"],
                    "route_trend_score": route_context["route_trend_score"],
                    "route_participation_score": route_context["route_participation_score"],
                    "route_risk_score": route_context["route_risk_score"],
                    "route_momentum_score": route_context["route_momentum_score"],
                    "route_components": route_context["route_components"],
                    "position_score": position_score,
                    "volatility_score": volatility_score,
                    "relative_strength_score": relative_strength_score,
                    "volume_trap_risk_score": volume_trap_risk_score,
                    "sector_strength_score": 75.0,
                    "risk_score": risk_score,
                    "is_st": False,
                    "is_suspended": False,
                },
            )
        )

    return rows
