from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from services.engine.risk.profiles import DEFAULT_RISK_PROFILE, RiskProfile
from services.engine.rules.models import StrategyRule


@dataclass(frozen=True)
class TradeParameters:
    entry_reference_price: float
    entry_trigger_price: float
    max_gap_up_pct: float
    initial_stop: float
    risk_per_share: float
    take_profit_1: float
    take_profit_2: float
    trailing_drawdown_pct: float
    position_size_pct: float
    max_holding_days: int
    invalid_conditions: list[str]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _float(context: dict[str, Any], key: str, default: float | None = None) -> float | None:
    value = context.get(key)
    if value is None:
        return default
    return float(value)


def _round_price(value: float) -> float:
    return round(value, 4)


def _bounded_stop(entry_price: float, raw_stop: float, profile: RiskProfile) -> float:
    min_stop = entry_price * (1 - profile.min_stop_loss_pct)
    max_stop = entry_price * (1 - profile.max_stop_loss_pct)
    return min(min_stop, max(max_stop, raw_stop))


def _position_size_pct(entry_price: float, stop: float, profile: RiskProfile) -> float:
    risk_per_share = max(entry_price - stop, 0.01)
    risk_budget = profile.account_equity * profile.risk_per_trade_pct
    shares = int(risk_budget / risk_per_share)
    shares = shares - shares % profile.lot_size
    if shares <= 0:
        return 0.0
    position_value = shares * entry_price
    pct = position_value / profile.account_equity
    return round(max(profile.min_position_pct, min(profile.max_position_pct, pct)), 4)


def build_trade_parameters(
    rule: StrategyRule,
    context: dict[str, Any],
    profile: RiskProfile = DEFAULT_RISK_PROFILE,
) -> TradeParameters:
    close = _float(context, "close")
    if close is None or close <= 0:
        raise ValueError("close is required to build trade parameters")

    atr = _float(context, "atr_14", 0.0) or 0.0
    support = _float(context, "support_level")
    breakout = _float(context, "breakout_level") or _float(context, "recent_high_20d") or close

    if rule.id == "R001":
        entry_reference_price = breakout
        entry_reason = "breakout_level"
    elif rule.id == "R005":
        signal_high = _float(context, "high", close) or close
        entry_reference_price = max(close, signal_high)
        entry_reason = "signal_day_high_confirmation"
    elif rule.id == "R002":
        ma5 = _float(context, "ma5", close) or close
        entry_reference_price = max(close, ma5)
        entry_reason = "pullback_confirm_reference"
    elif rule.id == "R006":
        ma10 = _float(context, "ma10", close) or close
        entry_reference_price = max(close, ma10)
        entry_reason = "trend_continuation_reference"
    elif rule.id == "R004":
        ma20 = _float(context, "ma20", close) or close
        entry_reference_price = min(close, ma20 * 1.02)
        entry_reason = "compound_trend_reference"
    else:
        entry_reference_price = close
        entry_reason = "close_reference"
    entry_trigger_price = entry_reference_price * (1 + profile.breakout_buffer_pct)

    atr_stop = (
        entry_trigger_price - atr * profile.atr_stop_multiple
        if atr
        else entry_trigger_price * 0.95
    )
    structure_stop = None
    if support:
        structure_stop = support * (1 - profile.structure_stop_buffer_pct)

    raw_stop = max(value for value in [atr_stop, structure_stop] if value is not None)
    initial_stop = _bounded_stop(entry_trigger_price, raw_stop, profile)
    risk_per_share = max(entry_trigger_price - initial_stop, 0.01)

    take_profit_1 = entry_trigger_price + risk_per_share * profile.take_profit_1_r
    take_profit_2 = entry_trigger_price + risk_per_share * profile.take_profit_2_r
    position_size_pct = _position_size_pct(entry_trigger_price, initial_stop, profile)

    invalid_conditions = [
        f"gap_up_pct > {profile.max_gap_up_pct:.2%}",
        "price does not touch entry_trigger_price on trade date",
    ]
    if support:
        invalid_conditions.append(f"close below support_level {support:.4f}")

    evidence = {
        "profile": profile.to_dict(),
        "entry_reason": entry_reason,
        "entry_reference_price": entry_reference_price,
        "atr_stop": atr_stop,
        "structure_stop": structure_stop,
        "raw_stop": raw_stop,
        "bounded_stop": initial_stop,
        "risk_per_share": risk_per_share,
        "position_model": "risk_budget / risk_per_share, capped by max_position_pct",
        "context_keys": {
            "atr_14": atr,
            "support_level": support,
            "breakout_level": breakout,
            "atr_pct": context.get("atr_pct"),
            "max_drawdown_20d": context.get("max_drawdown_20d"),
            "analysis_framework": context.get("analysis_framework"),
            "fundamental_score": context.get("fundamental_score"),
            "fundamental_verdict": context.get("fundamental_verdict"),
            "fundamental_reasons": context.get("fundamental_reasons"),
            "sector_strength_score": context.get("sector_strength_score"),
            "sector_sample_confidence": context.get("sector_sample_confidence"),
            "sector_stock_count": context.get("sector_stock_count"),
        },
    }

    return TradeParameters(
        entry_reference_price=_round_price(entry_reference_price),
        entry_trigger_price=_round_price(entry_trigger_price),
        max_gap_up_pct=profile.max_gap_up_pct,
        initial_stop=_round_price(initial_stop),
        risk_per_share=_round_price(risk_per_share),
        take_profit_1=_round_price(take_profit_1),
        take_profit_2=_round_price(take_profit_2),
        trailing_drawdown_pct=profile.trailing_drawdown_pct,
        position_size_pct=position_size_pct,
        max_holding_days=rule.time_exit.max_holding_days or profile.default_max_holding_days,
        invalid_conditions=invalid_conditions,
        evidence=evidence,
    )
