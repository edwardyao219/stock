from __future__ import annotations

from collections import defaultdict
from typing import Any

from services.engine.features.intraday_market_turn import classify_intraday_market_turn

INTRADAY_MARKET_MIN_COVERAGE_RATIO = 0.98
INTRADAY_SECTOR_MIN_SYMBOLS = 5


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_intraday_market_turn_snapshot(
    *,
    quotes: list[Any],
    active_security_count: int,
    sector_by_symbol: dict[str, str | None],
    index_change_pct: float | None,
    prior_snapshots: list[Any],
) -> dict[str, object]:
    valid_quotes = []
    for quote in quotes:
        price = _float(getattr(quote, "price", None))
        pre_close = _float(getattr(quote, "pre_close", None))
        if price is not None and pre_close is not None and pre_close > 0:
            valid_quotes.append((quote, price / pre_close - 1))

    coverage_ratio = len(valid_quotes) / active_security_count if active_security_count else 0.0
    breadth_ratio = (
        sum(1 for _, change_pct in valid_quotes if change_pct > 0) / len(valid_quotes)
        if valid_quotes
        else 0.0
    )
    total_amount = sum(_float(getattr(quote, "amount", None)) or 0.0 for quote in quotes)
    sector_changes: dict[str, list[float]] = defaultdict(list)
    for quote, change_pct in valid_quotes:
        sector = sector_by_symbol.get(str(getattr(quote, "symbol", "")))
        if sector:
            sector_changes[sector].append(change_pct)
    sector_expansion_count = sum(
        1
        for changes in sector_changes.values()
        if len(changes) >= INTRADAY_SECTOR_MIN_SYMBOLS
        and sum(1 for value in changes if value > 0) / len(changes) >= 0.55
    )
    prior_index_values = [
        _float(getattr(item, "index_change_pct", None))
        for item in prior_snapshots
    ]
    prior_index_low_pct = min(
        (value for value in prior_index_values if value is not None),
        default=None,
    )
    prior_amount = (
        _float(getattr(prior_snapshots[-1], "total_amount", None))
        if prior_snapshots
        else None
    )
    amount_supported = prior_amount is not None and total_amount > prior_amount
    data_ready = bool(
        coverage_ratio >= INTRADAY_MARKET_MIN_COVERAGE_RATIO and index_change_pct is not None
    )
    state = classify_intraday_market_turn(
        breadth_ratio=breadth_ratio,
        index_change_pct=index_change_pct,
        prior_index_low_pct=prior_index_low_pct,
        amount_supported=amount_supported,
        sector_expansion_count=sector_expansion_count,
        data_ready=data_ready,
        prior_snapshot_count=len(prior_snapshots),
    )
    snapshot = state.to_dict()
    snapshot.update(
        {
            "data_ready": data_ready,
            "coverage_ratio": round(coverage_ratio, 6),
            "breadth_ratio": round(breadth_ratio, 6),
            "total_amount": round(total_amount, 2),
            "index_change_pct": (
                round(index_change_pct, 6) if index_change_pct is not None else None
            ),
            "prior_index_low_pct": round(prior_index_low_pct, 6)
            if prior_index_low_pct is not None
            else None,
            "amount_supported": amount_supported,
            "sector_expansion_count": sector_expansion_count,
        }
    )
    return snapshot
