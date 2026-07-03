from __future__ import annotations

from decimal import Decimal

BASE_FREE_POSITIONS = 2
POSITION_CONCENTRATION_STEPS = {
    "long_term": Decimal("0.025"),
    "swing": Decimal("0.045"),
    "short_term": Decimal("0.055"),
}
POSITION_CONCENTRATION_FLOORS = {
    "long_term": Decimal("0.85"),
    "swing": Decimal("0.75"),
    "short_term": Decimal("0.70"),
}


def position_concentration_multiplier(
    open_positions_count: int,
    strategy_type: str | None = None,
) -> Decimal:
    count = max(0, int(open_positions_count))
    if count <= BASE_FREE_POSITIONS:
        return Decimal("1.0000")

    step = POSITION_CONCENTRATION_STEPS.get(str(strategy_type or ""), Decimal("0.050"))
    floor = POSITION_CONCENTRATION_FLOORS.get(str(strategy_type or ""), Decimal("0.72"))
    excess = Decimal(count - BASE_FREE_POSITIONS)
    multiplier = Decimal("1.0000") - step * excess
    return max(floor, multiplier).quantize(Decimal("0.0001"))


def adjusted_position_size_pct(
    position_size_pct: float | Decimal,
    open_positions_count: int,
    strategy_type: str | None = None,
) -> Decimal:
    base = Decimal(str(position_size_pct))
    multiplier = position_concentration_multiplier(open_positions_count, strategy_type)
    adjusted = base * multiplier
    return max(Decimal("0.0050"), adjusted).quantize(Decimal("0.0001"))
