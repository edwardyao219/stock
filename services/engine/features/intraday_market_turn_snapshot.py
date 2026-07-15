from __future__ import annotations

from collections import defaultdict
from typing import Any

from services.engine.features.intraday_market_turn import classify_intraday_market_turn

INTRADAY_MARKET_MIN_COVERAGE_RATIO = 0.98
INTRADAY_SECTOR_MIN_SYMBOLS = 5
INTRADAY_SECTOR_MAX_UP_RATIO_DECAY = 0.05
INTRADAY_SECTOR_MAX_AVG_CHANGE_DECAY = 0.005


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sustained_expanding_sectors(
    expanding_sectors: list[dict[str, object]],
    prior_snapshots: list[Any],
) -> list[dict[str, object]]:
    if not prior_snapshots:
        return []
    prior_state = getattr(prior_snapshots[-1], "state_json", None) or {}
    prior_by_sector = {
        str(item.get("sector") or ""): item
        for item in prior_state.get("expanding_sectors") or []
        if isinstance(item, dict) and str(item.get("sector") or "")
    }
    sustained: list[dict[str, object]] = []
    for item in expanding_sectors:
        sector = str(item["sector"])
        prior = prior_by_sector.get(sector)
        if prior is None:
            continue
        up_ratio = float(item["up_ratio"])
        avg_change_pct = float(item["avg_change_pct"])
        prior_up_ratio = _float(prior.get("up_ratio"))
        prior_avg_change_pct = _float(prior.get("avg_change_pct"))
        if (
            prior_up_ratio is None
            or prior_avg_change_pct is None
            or up_ratio < prior_up_ratio - INTRADAY_SECTOR_MAX_UP_RATIO_DECAY
            or avg_change_pct < prior_avg_change_pct - INTRADAY_SECTOR_MAX_AVG_CHANGE_DECAY
        ):
            continue
        sustained.append(
            {
                **item,
                "prior_up_ratio": round(prior_up_ratio, 6),
                "prior_avg_change_pct": round(prior_avg_change_pct, 6),
                "consecutive_snapshots": 2,
            }
        )
    return sustained


def build_intraday_market_turn_snapshot(
    *,
    quotes: list[Any],
    active_security_count: int,
    active_symbols: set[str] | None = None,
    sector_by_symbol: dict[str, str | None],
    index_change_pct: float | None,
    prior_snapshots: list[Any],
) -> dict[str, object]:
    valid_quotes = []
    for quote in quotes:
        symbol = str(getattr(quote, "symbol", ""))
        if active_symbols is not None and symbol not in active_symbols:
            continue
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
    total_amount = sum(
        _float(getattr(quote, "amount", None)) or 0.0 for quote, _change_pct in valid_quotes
    )
    sector_changes: dict[str, list[float]] = defaultdict(list)
    for quote, change_pct in valid_quotes:
        sector = sector_by_symbol.get(str(getattr(quote, "symbol", "")))
        if sector:
            sector_changes[sector].append(change_pct)
    expanding_sectors = []
    for sector, changes in sector_changes.items():
        symbol_count = len(changes)
        up_count = sum(1 for value in changes if value > 0)
        up_ratio = up_count / symbol_count if symbol_count else 0.0
        if symbol_count < INTRADAY_SECTOR_MIN_SYMBOLS or up_ratio < 0.55:
            continue
        expanding_sectors.append(
            {
                "sector": sector,
                "symbol_count": symbol_count,
                "up_count": up_count,
                "up_ratio": round(up_ratio, 6),
                "avg_change_pct": round(sum(changes) / symbol_count, 6),
            }
        )
    expanding_sectors.sort(
        key=lambda item: (
            -float(item["avg_change_pct"]),
            -float(item["up_ratio"]),
            -int(item["symbol_count"]),
            str(item["sector"]),
        )
    )
    sector_expansion_count = len(expanding_sectors)
    sustained_expanding_sectors = _sustained_expanding_sectors(
        expanding_sectors,
        prior_snapshots,
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
            "expanding_sectors": expanding_sectors,
            "sustained_sector_count": len(sustained_expanding_sectors),
            "sustained_expanding_sectors": sustained_expanding_sectors,
        }
    )
    return snapshot
