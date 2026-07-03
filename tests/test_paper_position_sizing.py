from decimal import Decimal

from services.engine.paper.position_sizing import (
    adjusted_position_size_pct,
    position_concentration_multiplier,
)


def test_position_concentration_multiplier_softens_after_two_positions() -> None:
    assert position_concentration_multiplier(0, "swing") == Decimal("1.0000")
    assert position_concentration_multiplier(2, "swing") == Decimal("1.0000")
    assert position_concentration_multiplier(3, "swing") < Decimal("1.0000")
    assert position_concentration_multiplier(5, "swing") < position_concentration_multiplier(3, "swing")


def test_position_concentration_is_gentler_for_long_term() -> None:
    long_term = adjusted_position_size_pct(Decimal("0.10"), 4, "long_term")
    short_term = adjusted_position_size_pct(Decimal("0.10"), 4, "short_term")

    assert long_term > short_term
