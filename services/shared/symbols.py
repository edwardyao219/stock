from __future__ import annotations


def is_growth_board_symbol(symbol: str | None) -> bool:
    value = str(symbol or "").strip()
    if not value:
        return False
    base = value.split(".", 1)[0]
    return base.startswith(("300", "301", "688"))


def is_star_market_symbol(symbol: str | None) -> bool:
    value = str(symbol or "").strip()
    if not value:
        return False
    base = value.split(".", 1)[0]
    return base.startswith("688")
